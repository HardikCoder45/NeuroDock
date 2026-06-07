---
name: neurodock
description: Create and operate NeuroDock, a universal local agent hub that downloads agent repositories, inspects Python/JavaScript/TypeScript/low-code/protocol agent frameworks, generates adapters, and exposes all agents through one streaming API, MCP server, and A2A-compatible interface. Use when Codex is asked to set up `.agents/agents`, download GitHub agents into `.agents/agents/apps`, unify LangGraph/LangChain, CrewAI, AutoGen/AG2, OpenAI Agents SDK, LlamaIndex, Pydantic AI, Semantic Kernel, Haystack, Agno, Google ADK, Vercel AI SDK, Mastra, Genkit, Dify, Flowise, n8n, Botpress, Rasa, MCP, A2A, OpenAPI/REST, JSON-RPC, CLI, or module-based agents behind a single controllable API with streaming text, tool, reasoning-summary, artifact, usage, and final-output events.
---

# NeuroDock

## Core Workflow

Use this skill to build NeuroDock: a local hub that keeps downloaded agent projects in isolated folders and exposes them through one API/protocol surface. Default runtime root:

```text
<workspace>/.agents/agents
```

If no workspace is clear, use:

```text
$HOME/.agents/agents
```

Always keep downloaded repositories under `apps/<agent-id>`. Put generated hub code, adapters, manifests, logs, artifacts, schemas, and registry state outside the downloaded repo unless the user explicitly requests a repo-local shim.

1. Scaffold the hub with `scripts/scaffold_hub.py --root <hub-root>`.
2. Download or register agents with `scripts/download_agent.py` or by manually placing folders under `apps/`.
3. Inspect every agent folder with `scripts/inspect_agent.py --app <agent-folder> --registry <hub-root>/registry/agents.json`.
4. Generate adapters with `scripts/generate_adapter.py --hub <hub-root> --agent <agent-id>`.
5. Run `scripts/smoke_test_hub.py --hub <hub-root>` before claiming the hub is ready.

## Reference Loading

Load only the reference needed for the current decision:

- `references/frameworks.md`: framework detection signals, native stream APIs, adapter priorities, and risks.
- `references/protocols.md`: universal event envelope, SSE, MCP, A2A, AG-UI, OpenAPI, JSON-RPC, WebSocket, and OpenTelemetry mapping.
- `references/security.md`: safe downloads, secrets, sandboxing, patching, approvals, and reasoning-summary rules.

## Hub Contract

The generated hub exposes:

- `GET /health`
- `GET /agents`
- `GET /agents/:id`
- `POST /agents/download`
- `POST /agents/:id/setup`
- `POST /agents/:id/runs`
- `GET /runs/:run_id/events` as Server-Sent Events
- `POST /runs/:run_id/cancel`
- `POST /runs/:run_id/input`
- `POST /runs/:run_id/approve`
- `GET /agents/:id/tools`
- `POST /agents/:id/tools/:tool_name`
- `GET /openapi.json`
- `GET|POST /mcp` for MCP Streamable HTTP style JSON-RPC
- `GET /.well-known/agent-card.json`, `POST /message/send`, and `POST /message/stream` for A2A-style access
- Optional `WS /control` only when live bidirectional control is needed

Normalize all streams into CloudEvents-like envelopes. Use event types such as `agent.run.created`, `agent.text.delta`, `agent.reasoning_summary.delta`, `agent.tool.call.created`, `agent.tool.result`, `agent.artifact.created`, `agent.usage`, `agent.final`, `agent.error`, and `agent.run.completed`.

## Adapter Rules

Prefer adapters in this order:

1. Native framework adapter when the repo clearly uses a supported SDK.
2. Protocol adapter for MCP, A2A, OpenAPI/REST, JSON-RPC, AG-UI, or existing SSE/WebSocket streams.
3. Generic runtime adapter for CLI commands, Python callables, JavaScript module exports, or HTTP endpoints.
4. Manual manifest adapter when detection is incomplete.

For Python agents, generate hub-owned Python bridge files under `adapters/<agent-id>/`. For JavaScript/TypeScript agents, generate hub-owned ESM adapters under `adapters/<agent-id>/`. Do not install dependencies or run untrusted code without the user approving network and execution.

## Safety Rules

Do not expose raw hidden chain-of-thought. Stream only normal output, tool activity, logs, artifacts, usage, and reasoning summaries explicitly returned by the model/framework.

Do not write secrets into manifests. Record required environment variable names and write `.env.example`, but keep real values in the user's environment or an ignored local `.env`.

Do not overwrite existing agent folders unless the user explicitly asks. Do not mutate downloaded repos unless a shim is required; if required, add only `agenthub.manifest.json` and `omni-agent-adapter.*`.
