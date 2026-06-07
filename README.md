# NeuroDock

NeuroDock downloads, inspects, and adapts AI agent projects into one local hub. It supports major agent frameworks, MCP, A2A, REST, CLI, Python, and JavaScript agents, then exposes them through unified streaming APIs with text, tool calls, reasoning summaries, artifacts, usage, setup checks, and safe secret handling.

## What It Does

NeuroDock is a local-first agent dock for connecting many agent runtimes behind one controllable interface. It is not tied to one model provider, one framework, or one assistant product. Use it to collect agents from GitHub or local folders, inspect their runtime shape, generate adapters, and expose them through a shared API.

Supported adapter families include:

- Python frameworks: LangGraph, LangChain, CrewAI, AutoGen/AG2, OpenAI Agents SDK, LlamaIndex, Pydantic AI, Semantic Kernel, Haystack, Agno, and Google ADK
- JavaScript and TypeScript frameworks: Vercel AI SDK, Mastra, LangChain/LangGraph JS, OpenAI Agents JS, LlamaIndex.TS, and Genkit
- Platform agents: Dify, Flowise, n8n, Botpress, and Rasa
- Protocol agents: MCP, A2A, AG-UI, OpenAPI/REST, JSON-RPC, SSE, WebSocket, CLI, Python callables, and JavaScript module exports

## Repository Layout

```text
NeuroDock/
├── README.md
├── neurodock/              # Standalone local hub scaffold
│   ├── server.mjs          # Dependency-light Node API server
│   ├── adapters/           # Hub-owned adapter output
│   ├── apps/               # Downloaded agent repos live here
│   ├── bridges/            # Python bridge helpers
│   ├── registry/           # Agent registry
│   └── schemas/            # Universal event schema
└── codex-skill/            # Optional Codex skill package
    ├── SKILL.md
    ├── references/
    └── scripts/
```

## Quick Start

Run the hub:

```bash
cd neurodock
npm start
```

The default server listens on:

```text
http://127.0.0.1:17771
```

Core endpoints:

- `GET /health`
- `GET /agents`
- `POST /agents/:id/runs`
- `GET /runs/:run_id/events`
- `GET /openapi.json`
- `GET|POST /mcp`
- `GET /.well-known/agent-card.json`
- `POST /message/send`
- `POST /message/stream`

## Download And Inspect Agents

Use the helper scripts from `codex-skill/scripts`:

```bash
codex-skill/scripts/download_agent.py git@github.com:owner/agent-repo.git --hub neurodock
codex-skill/scripts/inspect_agent.py --app neurodock/apps/owner-agent-repo --registry neurodock/registry/agents.json
codex-skill/scripts/generate_adapter.py --hub neurodock --agent owner-agent-repo
codex-skill/scripts/smoke_test_hub.py --hub neurodock
```

Every downloaded repo gets its own folder:

```text
neurodock/apps/<agent-id>
```

Generated wrappers stay outside downloaded repos by default:

```text
neurodock/adapters/<agent-id>
```

## Universal Event Stream

NeuroDock streams events as Server-Sent Events by default:

```text
event: agent.text.delta
id: evt_...
data: {"type":"agent.text.delta","run_id":"run_...","data":{"delta":"hello"}}
```

Common event types:

- `agent.run.created`
- `agent.text.delta`
- `agent.reasoning_summary.delta`
- `agent.tool.call.created`
- `agent.tool.result`
- `agent.artifact.created`
- `agent.usage`
- `agent.final`
- `agent.error`
- `agent.run.completed`

NeuroDock never exposes hidden chain-of-thought. It only streams reasoning summaries that the framework or provider explicitly returns as visible summaries.

## Safety Model

- Keep downloaded repos isolated under `neurodock/apps`.
- Keep generated adapters under `neurodock/adapters`.
- Do not store real API keys in manifests, registry files, or logs.
- Use `.env.example` for variable names only.
- Bind local servers to `127.0.0.1` by default.
- Treat downloaded MCP servers, workflow nodes, shell tools, browser tools, and generated code as untrusted until reviewed.

## Codex Skill

The `codex-skill` folder is optional. It lets Codex use NeuroDock as a skill with bundled references and scripts.

To install manually:

```bash
mkdir -p ~/.codex/skills/neurodock
cp -R codex-skill/. ~/.codex/skills/neurodock/
```

Then invoke:

```text
Use $neurodock to scaffold a local agent hub, download agent repos, generate adapters, and expose streaming API/MCP/A2A access.
```

## Validation

Run:

```bash
codex-skill/scripts/smoke_test_hub.py --hub neurodock
```

For a live local API check:

```bash
codex-skill/scripts/smoke_test_hub.py --hub neurodock --start-server
```

## License

MIT
