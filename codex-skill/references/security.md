# Security and Operations Reference

Use this reference before downloading, installing, running, or patching any external agent project.

## Download Safety

- Download into `apps/<agent-id>` only.
- Do not overwrite existing folders unless the user explicitly requests replacement.
- Prefer shallow clones for first inspection.
- Inspect files before installing dependencies or running code.
- Treat generated code, custom nodes, MCP servers, browser tools, shell tools, and workflow automation as untrusted until reviewed.
- Record source URL, commit/ref, download time, detected framework, and adapter type in the registry.

## Secrets

- Never write real API keys into registry files, manifests, adapters, logs, or generated source.
- Extract required env var names from `.env.example`, docs, manifests, and code patterns.
- Write `.env.example` with variable names only.
- Put local `.env`, `.env.*`, secrets, logs, artifacts, venvs, and node_modules in `.gitignore`.
- Redact values matching common key patterns before writing reports.

Common secret variable names:

```text
OPENAI_API_KEY
ANTHROPIC_API_KEY
GOOGLE_API_KEY
GEMINI_API_KEY
OPENROUTER_API_KEY
MISTRAL_API_KEY
COHERE_API_KEY
AZURE_OPENAI_API_KEY
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
SUPABASE_SERVICE_ROLE_KEY
LANGSMITH_API_KEY
DIFY_API_KEY
FLOWISE_API_KEY
N8N_API_KEY
BOT_TOKEN
```

## Execution

- Ask for approval before network installs, dependency downloads, or running untrusted code when the environment requires it.
- Prefer local-only server binding: `127.0.0.1`.
- Run Python agents through per-agent virtual environments when possible.
- Run Node agents through per-agent package installs when possible.
- Keep hub adapters outside downloaded repos by default.
- Use timeouts and cancellation for long-running commands.
- Capture stdout/stderr as `agent.log` events; do not mix logs with MCP stdout.

## Repo Mutation

Default: do not edit downloaded repos.

Allowed only when necessary:

- `agenthub.manifest.json`
- `omni-agent-adapter.py`
- `omni-agent-adapter.mjs`

If patching is needed, keep it small, reversible, and documented in the registry. Never rewrite user project architecture just to fit the hub.

## Reasoning Policy

Do not expose hidden chain-of-thought. Normalize only:

- final answers
- text deltas
- tool calls and results
- logs/progress
- artifacts
- usage
- provider/framework reasoning summaries that are explicitly returned as visible summaries

If a framework exposes `ThoughtEvent`, `reasoning`, or `thinking`, inspect whether it is intended for user display. If uncertain, downgrade to `agent.log` with a generic progress label or omit it.

## Tool and MCP Safety

- Keep destructive tools behind approval gates.
- Surface tool name, arguments, approval requirement, result, error, and duration.
- Validate MCP origins and bind local servers to localhost.
- Do not auto-connect remote MCP servers without user approval.
- Do not forward arbitrary client-supplied tool calls to downloaded agents unless the agent manifest allows it.

## Registry Integrity

Every registered agent should include:

- `id`
- `name`
- `source`
- `app_path`
- `frameworks`
- `languages`
- `adapter.kind`
- `required_env`
- `tools`
- `protocols`
- `streaming`
- `created_at`
- `updated_at`

Keep registry writes atomic: write to a temporary file, then replace.

## Acceptance Checks

Before saying the hub is ready:

- The hub root exists with `apps`, `adapters`, `registry`, `schemas`, `logs`, and `artifacts`.
- `registry/agents.json` parses.
- `server.mjs` passes Node syntax check if Node is available.
- `schemas/agent-event.schema.json` parses.
- `/health`, `/agents`, `/openapi.json`, MCP, and A2A routes are present.
- At least one inspected agent has an adapter or a clear manual-manifest next step.
