#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import json
import os
from pathlib import Path
import re


PY_NATIVE = {
    "langgraph",
    "langchain",
    "crewai",
    "autogen-ag2",
    "openai-agents",
    "llamaindex",
    "pydantic-ai",
    "semantic-kernel",
    "haystack",
    "agno",
    "google-adk",
}

JS_NATIVE = {
    "vercel-ai-sdk",
    "mastra",
    "langgraph",
    "langchain",
    "openai-agents",
    "llamaindex",
    "genkit",
}

PROTOCOLS = {"mcp", "a2a", "ag-ui", "openapi", "json-rpc", "rest"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()[:80] or "agent"


def load_registry(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("agents"), list):
        data["agents"] = []
    return data


@contextmanager
def registry_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        except ImportError:
            pass
        try:
            yield
        finally:
            try:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_UN)
            except ImportError:
                pass


def save_registry(path: Path, data: dict) -> None:
    data["updated_at"] = utc_now()
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def choose_kind(agent: dict) -> str:
    manual = agent.get("manual_manifest") if isinstance(agent.get("manual_manifest"), dict) else {}
    if manual.get("runtime"):
        return "manual-manifest"
    frameworks = set(agent.get("frameworks") or [])
    protocols = set(agent.get("protocols") or [])
    languages = set(agent.get("languages") or [])
    if frameworks & PY_NATIVE and "python" in languages:
        return "native-python"
    if frameworks & JS_NATIVE and "javascript-typescript" in languages:
        return "native-javascript"
    if protocols & PROTOCOLS:
        return "protocol"
    if agent.get("entrypoints"):
        return "generic-cli"
    return "manual-required"


def runtime_command(agent: dict) -> list[str] | None:
    manual = agent.get("manual_manifest") if isinstance(agent.get("manual_manifest"), dict) else {}
    runtime = manual.get("runtime") if isinstance(manual.get("runtime"), dict) else {}
    command = runtime.get("command")
    if isinstance(command, list) and command and all(isinstance(part, str) for part in command):
        return command
    for entrypoint in agent.get("entrypoints") or []:
        command = entrypoint.get("command")
        if isinstance(command, list) and command:
            return command
    return None


def adapter_js(agent: dict, kind: str) -> str:
    command = runtime_command(agent)
    agent_id = agent["id"]
    frameworks = ", ".join(agent.get("frameworks") or ["unknown"])
    protocols = ", ".join(agent.get("protocols") or [])
    command_json = json.dumps(command)
    required_env_json = json.dumps(agent.get("required_env") or [])
    return f'''const ADAPTER_KIND = {json.dumps(kind)};
const DETECTED_FRAMEWORKS = {json.dumps(agent.get("frameworks") or [])};
const DETECTED_PROTOCOLS = {json.dumps(agent.get("protocols") or [])};
const RUNTIME_COMMAND = {command_json};
const REQUIRED_ENV = {required_env_json};

function missingEnv() {{
  return REQUIRED_ENV.filter((name) => !process.env[name]);
}}

async function runCommand({{ agent, input, emit, spawn }}) {{
  emit('agent.run.in_progress', {{ status: 'running', adapter: ADAPTER_KIND, command: RUNTIME_COMMAND }});
  const child = spawn(RUNTIME_COMMAND[0], RUNTIME_COMMAND.slice(1), {{
    cwd: agent.app_path,
    env: {{ ...process.env, AGENTHUB_INPUT: JSON.stringify(input || {{}}) }},
  }});
  let output = '';
  child.stdout.setEncoding('utf8');
  child.stderr.setEncoding('utf8');
  child.stdout.on('data', (chunk) => {{
    output += chunk;
    emit('agent.text.delta', {{ item_id: 'stdout', content_index: 0, delta: chunk, role: 'assistant', modality: 'text' }});
  }});
  child.stderr.on('data', (chunk) => {{
    emit('agent.log', {{ level: 'warn', category: 'stderr', message: chunk, attributes: {{}} }});
  }});
  const exitCode = await new Promise((resolve) => child.on('close', resolve));
  emit('agent.text.done', {{ item_id: 'stdout', text: output, role: 'assistant', finish_reason: exitCode === 0 ? 'stop' : 'error' }});
  emit('agent.final', {{ output, messages: [], artifacts: [], finish_reason: exitCode === 0 ? 'stop' : 'error' }});
}}

export async function run(ctx) {{
  const {{ agent, input, emit }} = ctx;
  const missing = missingEnv();
  if (missing.length) {{
    emit('agent.log', {{ level: 'warn', category: 'setup', message: 'Required environment variables are missing.', attributes: {{ missing_env: missing }} }});
  }}

  if (RUNTIME_COMMAND) {{
    await runCommand(ctx);
    emit('agent.usage', {{ input_tokens: null, output_tokens: null, reasoning_output_tokens: null, cached_input_tokens: null, cost: null, model: null, provider: null }});
    return;
  }}

  const summary = 'Adapter generated for {agent_id} using kind {kind}. Detected frameworks: {frameworks}. Detected protocols: {protocols}. Configure agenthub.manifest.json with a runtime.command, HTTP endpoint, or framework entrypoint to execute the agent.';
  emit('agent.run.in_progress', {{ status: 'running', adapter: ADAPTER_KIND }});
  emit('agent.reasoning_summary.delta', {{ item_id: 'setup', summary_index: 0, delta: 'Detected adapter kind {kind}; no runnable entrypoint is configured yet.', policy: 'summary_only' }});
  emit('agent.reasoning_summary.done', {{ item_id: 'setup', summary_index: 0, text: 'Adapter requires a runtime entrypoint before live execution.', policy: 'summary_only' }});
  emit('agent.text.delta', {{ item_id: 'msg_1', content_index: 0, delta: summary, role: 'assistant', modality: 'text' }});
  emit('agent.text.done', {{ item_id: 'msg_1', text: summary, role: 'assistant', finish_reason: 'manual_runtime_required' }});
  emit('agent.final', {{ output: summary, messages: [], artifacts: [], finish_reason: 'manual_runtime_required', input }});
  emit('agent.usage', {{ input_tokens: null, output_tokens: null, reasoning_output_tokens: null, cached_input_tokens: null, cost: null, model: null, provider: null }});
}}
'''


def adapter_py(agent: dict, kind: str) -> str:
    return f'''#!/usr/bin/env python3
from __future__ import annotations

"""
Hub-owned Python bridge for {agent["id"]}.

Detected adapter kind: {kind}
Detected frameworks: {", ".join(agent.get("frameworks") or ["unknown"])}

Replace this file with framework-native loading when the app exposes a stable Python callable.
Keep output as newline-delimited JSON objects with fields: type, data.
"""

import json
import os
import sys


def emit(event_type: str, data: dict) -> None:
    sys.stdout.write(json.dumps({{"type": event_type, "data": data}}, ensure_ascii=False) + "\\n")
    sys.stdout.flush()


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{{}}")
    text = "Python adapter for {agent["id"]} is generated but needs a concrete callable or CLI command."
    emit("agent.run.in_progress", {{"status": "running", "adapter": "{kind}"}})
    emit("agent.text.delta", {{"item_id": "msg_1", "content_index": 0, "delta": text, "role": "assistant", "modality": "text"}})
    emit("agent.text.done", {{"item_id": "msg_1", "text": text, "role": "assistant", "finish_reason": "manual_runtime_required"}})
    emit("agent.final", {{"output": text, "messages": [], "artifacts": [], "finish_reason": "manual_runtime_required", "input": payload}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def generate(hub: Path, agent_id: str, force: bool = False) -> dict:
    registry_path = hub / "registry" / "agents.json"
    with registry_lock(registry_path):
        registry = load_registry(registry_path)
        agent = next((candidate for candidate in registry["agents"] if candidate.get("id") == agent_id), None)
        if not agent:
            raise SystemExit(f"Agent not found in registry: {agent_id}")

        kind = choose_kind(agent)
        adapter_dir = hub / "adapters" / agent_id
        adapter_dir.mkdir(parents=True, exist_ok=True)
        adapter_path = adapter_dir / "adapter.mjs"
        py_path = adapter_dir / "adapter.py"
        manifest_path = adapter_dir / "manifest.json"

        if adapter_path.exists() and not force:
            raise SystemExit(f"Refusing to overwrite existing adapter: {adapter_path}")

        adapter_path.write_text(adapter_js(agent, kind), encoding="utf-8")
        py_path.write_text(adapter_py(agent, kind), encoding="utf-8")
        manifest = {
            "agent_id": agent_id,
            "adapter_kind": kind,
            "frameworks": agent.get("frameworks") or [],
            "protocols": agent.get("protocols") or [],
            "languages": agent.get("languages") or [],
            "required_env": agent.get("required_env") or [],
            "runtime_command": runtime_command(agent),
            "generated_at": utc_now(),
            "notes": [
                "Generated adapters are hub-owned and do not mutate the downloaded app.",
                "Configure agenthub.manifest.json or registry runtime data for reliable execution when no entrypoint was detected.",
                "Expose only reasoning summaries explicitly returned by the framework/provider.",
            ],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        agent["adapter"] = {"kind": kind, "path": str(adapter_path), "manifest": str(manifest_path), "generated_at": utc_now()}
        agent["updated_at"] = utc_now()
        save_registry(registry_path, registry)
    return {"agent_id": agent_id, "kind": kind, "adapter": str(adapter_path), "manifest": str(manifest_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a hub-owned adapter for a registered agent.")
    parser.add_argument("--hub", type=Path, required=True, help="Hub root.")
    parser.add_argument("--agent", required=True, help="Agent id.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing generated adapter.")
    args = parser.parse_args()
    result = generate(args.hub.expanduser().resolve(), slug(args.agent), force=args.force)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
