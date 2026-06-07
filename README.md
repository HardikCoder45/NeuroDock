# NeuroDock

NeuroDock is a Codex skill for creating a unified local agent hub. It helps an agent download AI-agent repositories, inspect their frameworks, generate adapters, and expose every supported agent through one streaming API, MCP-compatible interface, and A2A-compatible interface.

## Skill Contents

```text
NeuroDock/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── references/
│   ├── frameworks.md
│   ├── protocols.md
│   └── security.md
└── scripts/
    ├── scaffold_hub.py
    ├── download_agent.py
    ├── inspect_agent.py
    ├── generate_adapter.py
    └── smoke_test_hub.py
```

## What It Supports

- Python agents: LangGraph, LangChain, CrewAI, AutoGen/AG2, OpenAI Agents SDK, LlamaIndex, Pydantic AI, Semantic Kernel, Haystack, Agno, and Google ADK
- JavaScript and TypeScript agents: Vercel AI SDK, Mastra, LangChain/LangGraph JS, OpenAI Agents JS, LlamaIndex.TS, and Genkit
- Platform agents: Dify, Flowise, n8n, Botpress, and Rasa
- Protocol agents: MCP, A2A, AG-UI, OpenAPI/REST, JSON-RPC, SSE, WebSocket, CLI, Python callables, and JavaScript module exports

## Install As A Codex Skill

```bash
mkdir -p ~/.codex/skills/neurodock
cp -R . ~/.codex/skills/neurodock/
```

Then use:

```text
Use $neurodock to scaffold a local agent hub, download agent repos, generate adapters, and expose streaming API/MCP/A2A access.
```

## Default Hub Workflow

```bash
scripts/scaffold_hub.py --root .agents/agents
scripts/download_agent.py <git-url> --hub .agents/agents
scripts/inspect_agent.py --app .agents/agents/apps/<agent-id> --registry .agents/agents/registry/agents.json
scripts/generate_adapter.py --hub .agents/agents --agent <agent-id>
scripts/smoke_test_hub.py --hub .agents/agents
```

## Safety

NeuroDock keeps downloaded repositories isolated under `apps/<agent-id>`, writes generated adapters outside downloaded repos by default, records required environment variable names without storing real secrets, and never exposes hidden chain-of-thought. Only reasoning summaries explicitly returned by a framework or provider are streamed.
