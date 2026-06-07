#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import json
import os
from pathlib import Path
import re
from typing import Any


SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".turbo", ".cache"}
TEXT_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".toml", ".yaml", ".yml", ".md", ".txt", ".env", ".example"}


FRAMEWORK_RULES = [
    ("langgraph", ["langgraph", "@langchain/langgraph", "langgraph.graph", "StateGraph", "stream_events"]),
    ("langchain", ["langchain", "@langchain/core", "langchain_core", "createAgent", "create_react_agent"]),
    ("crewai", ["crewai", "Crew(", "BaseEventListener", "agents.yaml", "tasks.yaml"]),
    ("autogen-ag2", ["autogen_agentchat", "autogen-core", "autogen-ext", "ag2", "ConversableAgent"]),
    ("openai-agents", ["openai-agents", "@openai/agents", "from agents import", "Runner.run_streamed", "new Agent("]),
    ("llamaindex", ["llama-index", "llama_index", "llamaindex", "@llamaindex/workflow", "AgentWorkflow"]),
    ("pydantic-ai", ["pydantic-ai", "pydantic_ai", "Agent(", "run_stream_events"]),
    ("semantic-kernel", ["semantic-kernel", "semantic_kernel", "Microsoft.SemanticKernel"]),
    ("haystack", ["haystack-ai", "haystack.components.agents", "Pipeline("]),
    ("agno", ["agno", "agno.agent", "stream_events=True"]),
    ("google-adk", ["google-adk", "google.adk", "root_agent", "adk run"]),
    ("vercel-ai-sdk", ['"ai"', "'ai'", "@ai-sdk/", "streamText", "generateText", "stepCountIs"]),
    ("mastra", ["@mastra/core", "@mastra/mcp", "from '@mastra/core/agent'", "createTool"]),
    ("genkit", ["genkit", "@genkit-ai/", "defineFlow", "defineTool", "generateStream"]),
    ("dify", ["DIFY_API_KEY", "response_mode", "/chat-messages", "/workflows/run"]),
    ("flowise", ["flowise", "flowise-sdk", "/api/v1/predictions", "usedTools"]),
    ("n8n", ["n8n-nodes-langchain.agent", "n8n", "Chat Trigger", "Tools Agent"]),
    ("botpress", ["@botpress/client", "botpress", "actions", "channels"]),
    ("rasa", ["domain.yml", "config.yml", "data/flows", "rasa"]),
]


PROTOCOL_RULES = [
    ("mcp", ["mcp.json", "@modelcontextprotocol/sdk", "Model Context Protocol", "tools/list", "tools/call"]),
    ("a2a", ["agent-card", ".well-known/agent-card", "message/stream", "message/send", "TaskArtifact"]),
    ("ag-ui", ["@ag-ui/core", "AG-UI", "TEXT_MESSAGE_CONTENT", "ToolCallStart"]),
    ("openapi", ["openapi.json", "openapi.yaml", "swagger.json", "Swagger"]),
    ("json-rpc", ['"jsonrpc"', "'jsonrpc'", "JSON-RPC"]),
    ("rest", ["FastAPI(", "express()", "@app.get", "router.post", "fetch("]),
]


ENV_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")
SECRET_VALUE_RE = re.compile(r"(?i)(api[_-]?key|secret|token|password|bearer)\s*[:=]\s*['\"]?([^'\"\s]+)")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()[:80] or "agent"


def iter_files(root: Path):
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            path = Path(current) / name
            if path.suffix.lower() in TEXT_SUFFIXES or name in {"package.json", "pyproject.toml", "requirements.txt", "requirements-dev.txt", ".env.example", "mcp.json"}:
                yield path


def read_small(path: Path, limit: int = 200_000) -> str:
    try:
        if path.stat().st_size > limit:
            return ""
        text = path.read_text(encoding="utf-8", errors="ignore")
        return SECRET_VALUE_RE.sub(lambda m: f"{m.group(1)}=<redacted>", text)
    except OSError:
        return ""


def package_dependencies(package_json: Path) -> list[str]:
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except Exception:
        return []
    deps = []
    for key in ["dependencies", "devDependencies", "peerDependencies", "optionalDependencies"]:
        deps.extend((data.get(key) or {}).keys())
    return sorted(set(deps))


def pyproject_dependencies(pyproject: Path) -> list[str]:
    text = read_small(pyproject)
    try:
        import tomllib
        data = tomllib.loads(text)
    except Exception:
        return []
    deps: list[str] = []
    project = data.get("project") if isinstance(data, dict) else {}
    for dep in (project or {}).get("dependencies") or []:
        if isinstance(dep, str):
            deps.append(re.split(r"[<>=~!; ]", dep)[0])
    optional = (project or {}).get("optional-dependencies") or {}
    if isinstance(optional, dict):
        for group in optional.values():
            for dep in group or []:
                if isinstance(dep, str):
                    deps.append(re.split(r"[<>=~!; ]", dep)[0])
    poetry = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies") if isinstance(data, dict) else {}
    if isinstance(poetry, dict):
        deps.extend(name for name in poetry.keys() if name.lower() != "python")
    return sorted(set(filter(None, deps)))


def requirements_dependencies(path: Path) -> list[str]:
    deps = []
    for line in read_small(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        deps.append(re.split(r"[<>=~!; ]", line)[0])
    return sorted(set(filter(None, deps)))


def detect(app: Path) -> dict[str, Any]:
    app = app.expanduser().resolve()
    texts: list[str] = []
    filenames: list[str] = []
    deps: list[str] = []
    entrypoints: list[dict[str, Any]] = []
    required_env: set[str] = set()

    package_json = app / "package.json"
    if package_json.exists():
        deps.extend(package_dependencies(package_json))
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
            for name, command in (data.get("scripts") or {}).items():
                if name in {"start", "dev", "serve", "agent", "chat"} or "agent" in name:
                    entrypoints.append({"type": "npm_script", "name": name, "command": ["npm", "run", name]})
        except Exception:
            pass

    pyproject = app / "pyproject.toml"
    if pyproject.exists():
        deps.extend(pyproject_dependencies(pyproject))

    for req_name in ["requirements.txt", "requirements-dev.txt"]:
        req = app / req_name
        if req.exists():
            deps.extend(requirements_dependencies(req))

    for file_path in iter_files(app):
        rel = str(file_path.relative_to(app))
        filenames.append(rel)
        text = read_small(file_path)
        if text:
            texts.append(text[:40_000])
            if file_path.name.startswith(".env") or file_path.name.endswith(".env.example") or "README" in file_path.name.upper():
                for env_name in ENV_RE.findall(text):
                    if any(token in env_name for token in ["KEY", "TOKEN", "SECRET", "MODEL", "BASE_URL", "URL"]):
                        required_env.add(env_name)

    haystack = "\n".join(deps + filenames + texts)
    frameworks = []
    for name, needles in FRAMEWORK_RULES:
        if any(needle in haystack for needle in needles):
            frameworks.append(name)

    protocols = []
    for name, needles in PROTOCOL_RULES:
        if any(needle in haystack for needle in needles):
            protocols.append(name)

    languages = []
    suffixes = {Path(name).suffix for name in filenames}
    if ".py" in suffixes or pyproject.exists() or any(name.startswith("requirements") for name in filenames):
        languages.append("python")
    if any(suffix in suffixes for suffix in [".js", ".jsx", ".ts", ".tsx"]) or package_json.exists():
        languages.append("javascript-typescript")
    if ".go" in suffixes:
        languages.append("go")
    if ".java" in suffixes:
        languages.append("java")
    if ".csproj" in suffixes:
        languages.append("dotnet")

    for common in ["main.py", "app.py", "server.py", "agent.py", "crew.py"]:
        if (app / common).exists():
            entrypoints.append({"type": "python_file", "path": common, "command": ["python", common]})

    manifest = app / "agenthub.manifest.json"
    manual_manifest = None
    if manifest.exists():
        try:
            manual_manifest = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception as exc:
            manual_manifest = {"error": str(exc)}

    streaming = {
        "supported": bool(frameworks or any(protocol in protocols for protocol in ["mcp", "a2a", "ag-ui", "openapi"])),
        "modes": sorted(set(frameworks + protocols)),
    }

    return {
        "id": slug(app.name),
        "name": app.name,
        "description": "",
        "source": {"type": "local", "url": None, "ref": None, "commit": None},
        "app_path": str(app),
        "frameworks": sorted(set(frameworks)),
        "languages": sorted(set(languages)),
        "dependencies": sorted(set(deps)),
        "entrypoints": entrypoints,
        "required_env": sorted(required_env),
        "tools": [],
        "protocols": sorted(set(protocols)),
        "streaming": streaming,
        "manual_manifest": manual_manifest,
        "adapter": {"kind": "unassigned", "path": None},
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }


def load_registry(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "updated_at": utc_now(), "agents": []}
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
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = utc_now()
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect an agent folder and optionally update the hub registry.")
    parser.add_argument("--app", type=Path, required=True, help="Agent app folder.")
    parser.add_argument("--registry", type=Path, help="Registry JSON to update.")
    parser.add_argument("--id", dest="agent_id", help="Override detected agent id.")
    args = parser.parse_args()

    report = detect(args.app)
    if args.agent_id:
        report["id"] = slug(args.agent_id)
    if args.registry:
        with registry_lock(args.registry):
            registry = load_registry(args.registry)
            existing = next((agent for agent in registry["agents"] if agent.get("id") == report["id"]), None)
            if existing:
                report["created_at"] = existing.get("created_at") or report["created_at"]
                if existing.get("source"):
                    report["source"] = existing["source"]
            registry["agents"] = [agent for agent in registry["agents"] if agent.get("id") != report["id"]]
            registry["agents"].append(report)
            save_registry(args.registry, registry)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
