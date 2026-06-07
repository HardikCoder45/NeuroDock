#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.parse import urlparse


REQUIRED_PATHS = [
    "apps",
    "adapters",
    "registry/agents.json",
    "schemas/agent-event.schema.json",
    "server.mjs",
    "package.json",
]


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    return int(port)


def request_json(base: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    parsed = urlparse(base)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    conn.request(method, path, body=payload, headers=headers)
    res = conn.getresponse()
    text = res.read().decode("utf-8", errors="replace")
    conn.close()
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        data = {"raw": text}
    return res.status, data


def request_sse_until_done(base: str, path: str) -> list[str]:
    parsed = urlparse(base)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
    conn.request("GET", path, headers={"Accept": "text/event-stream"})
    res = conn.getresponse()
    if res.status != 200:
        raise RuntimeError(f"SSE endpoint returned {res.status}")
    events: list[str] = []
    start = time.time()
    while time.time() - start < 8:
        line = res.readline().decode("utf-8", errors="replace")
        if not line:
            break
        if line.startswith("event:"):
            events.append(line.split(":", 1)[1].strip())
        if "done" in events or "agent.run.completed" in events or "agent.error" in events:
            break
    conn.close()
    return events


def static_checks(hub: Path) -> list[str]:
    errors: list[str] = []
    for rel in REQUIRED_PATHS:
        if not (hub / rel).exists():
            errors.append(f"Missing {rel}")
    for rel in ["registry/agents.json", "schemas/agent-event.schema.json", "package.json"]:
        path = hub / rel
        if path.exists():
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"Invalid JSON {rel}: {exc}")
    server = hub / "server.mjs"
    if server.exists():
        text = server.read_text(encoding="utf-8")
        for needle in ["/health", "/agents", "/openapi.json", "/mcp", "/message/send", "/message/stream"]:
            if needle not in text:
                errors.append(f"server.mjs missing route marker {needle}")
    return errors


def node_check(hub: Path) -> list[str]:
    node = subprocess.run(["node", "--check", str(hub / "server.mjs")], text=True, capture_output=True, check=False)
    if node.returncode != 0:
        return [node.stderr.strip() or node.stdout.strip() or "node --check failed"]
    return []


def with_temp_agent(hub: Path) -> dict:
    registry_path = hub / "registry" / "agents.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    original = json.dumps(registry, indent=2, sort_keys=True) + "\n"
    registry["agents"] = [agent for agent in registry.get("agents", []) if agent.get("id") != "smoke-test-agent"]
    registry["agents"].append({
        "id": "smoke-test-agent",
        "name": "Smoke Test Agent",
        "description": "Temporary agent inserted by smoke_test_hub.py",
        "app_path": str(hub / "apps" / "smoke-test-agent"),
        "frameworks": [],
        "languages": [],
        "required_env": [],
        "tools": [],
        "protocols": [],
        "streaming": {"supported": True, "modes": ["builtin"]},
        "adapter": {"kind": "builtin", "path": None},
    })
    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"registry_path": registry_path, "original": original}


def restore_temp_agent(snapshot: dict) -> None:
    snapshot["registry_path"].write_text(snapshot["original"], encoding="utf-8")


def server_checks(hub: Path) -> list[str]:
    errors: list[str] = []
    port = free_port()
    env = os.environ.copy()
    env["HOST"] = "127.0.0.1"
    env["PORT"] = str(port)
    env["AGENT_HUB_ROOT"] = str(hub)
    snapshot = with_temp_agent(hub)
    proc = subprocess.Popen(["node", str(hub / "server.mjs")], cwd=str(hub), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                status, health = request_json(base, "GET", "/health")
                if status == 200 and health.get("ok"):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            errors.append("server did not start")
            return errors

        checks = [
            ("GET", "/agents", None, 200),
            ("GET", "/openapi.json", None, 200),
            ("GET", "/.well-known/agent-card.json", None, 200),
            ("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, 200),
        ]
        for method, route, body, expected in checks:
            status, payload = request_json(base, method, route, body)
            if status != expected:
                errors.append(f"{method} {route} returned {status}: {payload}")

        status, run = request_json(base, "POST", "/agents/smoke-test-agent/runs", {"input": {"message": "hello"}})
        if status != 202:
            errors.append(f"run creation returned {status}: {run}")
        else:
            events = request_sse_until_done(base, run["events_url"])
            for required in ["agent.run.created", "agent.text.delta", "agent.final", "agent.run.completed"]:
                if required not in events:
                    errors.append(f"SSE stream missing {required}; saw {events}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        restore_temp_agent(snapshot)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a NeuroDock scaffold.")
    parser.add_argument("--hub", type=Path, required=True, help="Hub root.")
    parser.add_argument("--start-server", action="store_true", help="Start the Node server and verify live endpoints/SSE.")
    args = parser.parse_args()
    hub = args.hub.expanduser().resolve()

    errors = static_checks(hub)
    if (hub / "server.mjs").exists():
        try:
            errors.extend(node_check(hub))
        except FileNotFoundError:
            errors.append("node is not available for syntax check")
    if args.start_server:
        errors.extend(server_checks(hub))

    if errors:
        print(json.dumps({"ok": False, "hub": str(hub), "errors": errors}, indent=2))
        return 1
    print(json.dumps({"ok": True, "hub": str(hub), "checks": "passed"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
