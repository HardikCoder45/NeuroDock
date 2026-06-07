# Agent Framework Adapter Reference

Use this reference when inspecting an agent repository and choosing an adapter. Prefer direct evidence from package manifests, imports, config files, and documented entrypoints. If multiple frameworks are detected, choose the framework that owns the runnable entrypoint; record the rest as capabilities.

## Adapter Priority

1. Native framework adapter with first-class streaming/events.
2. Protocol adapter for MCP, A2A, AG-UI, OpenAPI/REST, JSON-RPC, or an existing SSE/WebSocket stream.
3. Generic adapter for CLI commands, Python callables, JavaScript exports, or HTTP endpoints.
4. Manual `agenthub.manifest.json` when detection is incomplete.

## Python Frameworks

| Framework | Detection Signals | Streaming/Event Surface | Adapter Notes |
| --- | --- | --- | --- |
| LangGraph / LangChain | `langgraph`, `langchain`, `langchain-core`, imports from `langgraph.graph`, `langchain_core`, `create_react_agent`, `StateGraph`, `langgraph.json` | `stream()`, `astream()`, `stream_events(version="v3")`; modes include `messages`, `tools`, `updates`, `values`, `custom`, `tasks`, `debug`; event streaming exposes messages, reasoning, tool calls, subgraphs, interrupts, usage metadata | Prefer `stream_events(version="v3")`. Use raw event order when text, reasoning summaries, and tool argument chunks must preserve arrival order. |
| CrewAI | `crewai`, imports `crewai`, `crewai.flow`, `crewai.events`; `crew.py`, `agents.yaml`, `tasks.yaml` | Event bus with `BaseEventListener`; crew, flow, agent, task, tool, MCP, LLM stream chunk, reasoning/thinking chunk events | Register a listener near the crew/flow entrypoint. Ensure listener instance remains alive. Treat AMP/cloud tracing as optional, not required. |
| AutoGen / AG2 | `autogen-agentchat`, `autogen-core`, `autogen-ext`, `ag2`; imports `autogen_agentchat`, `autogen_ext`, `autogen` | `run_stream()`, `on_messages_stream()`, model token stream via `model_client_stream=True`; events include tool request/execution, memory, thought, user input, streaming chunks, task result | New Microsoft work may use Microsoft Agent Framework. Adapter should gate by installed package and import path. |
| OpenAI Agents SDK | `openai-agents`, import `agents`, `Agent`, `Runner`, `function_tool` | `Runner.run_streamed()` and `result.stream_events()`; raw Responses events, run item events, agent updates, handoffs, tool calls/results, MCP approvals, reasoning items | Drain streams fully before finalizing. Resume approval interruptions from run state, not a fresh user turn. |
| LlamaIndex Agents / Workflows | `llama-index`, `llama-index-core`, `llama_index.core.agent.workflow`, `FunctionAgent`, `AgentWorkflow`, `Workflow` | Agent handler `stream_events()`; event classes include `AgentStream`, `AgentInput`, `AgentOutput`, `ToolCall`, `ToolCallResult` | Prefer newer workflow agents over legacy query pipelines. Preserve workflow context where possible. |
| Pydantic AI | `pydantic-ai`, import `pydantic_ai`, `Agent(...)` | `run_stream()`, `stream_text()`, `stream_output()`, `run_stream_events()`, `iter()`; events include model parts, tool execution, final result, usage | Use `run_stream_events()` or `iter()` for complete tool/event visibility. `run_stream()` can end at first matching output. |
| Semantic Kernel / Microsoft Agent Framework | `semantic-kernel`, imports `semantic_kernel`; .NET packages `Microsoft.SemanticKernel*`; Java build files | Python `invoke_stream()`, .NET `InvokeStreamingAsync`; streaming agent response content and thread messages | Version/migration ambiguity is common. Detect language and package generation before generating adapter. |
| Haystack | `haystack-ai`, import `haystack`; `haystack.components.agents.Agent`; YAML pipelines | `streaming_callback`; built-in streaming chunk helpers emit text, tool calls, and tool results | Agent is often one pipeline component. Preserve pipeline state and entrypoint rather than isolating the agent class only. |
| Agno | `agno`, imports `agno.agent`, `agno.models`, `agno.tools` | `Agent.run(..., stream=True)`; `stream_events=True` for full events including tools, reasoning, memory | Default stream can be content-only. Set all-event streaming for observability. |
| Google ADK | `google-adk`, imports `google.adk`; files exposing `root_agent`; CLI `adk run`, `adk web` | `Runner.run_live()` async events, Live/Gemini streaming, streaming tools via async generators | Version-gate event/session behavior. Some streaming docs focus on Gemini Live; generic text agents may need fallback CLI/API adapter. |

## JavaScript and TypeScript Frameworks

| Framework | Detection Signals | Streaming/Event Surface | Adapter Notes |
| --- | --- | --- | --- |
| Vercel AI SDK | `ai`, `@ai-sdk/*`; imports `generateText`, `streamText`, `tool`, `stepCountIs` | `streamText()`, `textStream`, `fullStream`; parts include text, reasoning, source, file, tool-call, tool-call-delta, tool-result; `usage`, `totalUsage`, `onStepFinish` | Strong default for TS agents, but it is an SDK not a durable runtime. Multi-step behavior depends on `stopWhen`. |
| Mastra | `@mastra/core`, `@mastra/mcp`; imports `Agent`, `createTool`; `mastra` config | Agent `.stream()`, nested streaming, background tools with `.streamUntilIdle()`, AI SDK-compatible streams | Good for production TS agents. Separate core code from Studio/Cloud features. |
| LangChain JS / LangGraph JS | `langchain`, `@langchain/core`, `@langchain/langgraph`; imports `createAgent`, `StateGraph`, `MemorySaver` | Agent/graph `stream`, `streamEvents`; channels include messages, tools, lifecycle; LangSmith tracing | Detect high-level agents versus custom graphs. Use graph stream events when available. |
| OpenAI Agents SDK JS | `@openai/agents`, `@openai/agents-core`, `@openai/agents-realtime`; imports `Agent`, `run`, `tool` | `run(agent, input, { stream: true })`; async iterable; raw model stream, run item stream, `toTextStream()`, `toStream()`, `completed` | Strong official adapter when OpenAI provider assumptions fit. Preserve raw events as metadata only. |
| LlamaIndex.TS | `llamaindex`, `@llamaindex/workflow`, `@llamaindex/openai`; imports `agent`, `tool`, `createWorkflow`, `workflowEvent` | Agent workflows emit stream events such as agent stream and tool call events | Prefer `@llamaindex/workflow` over deprecated agent classes. |
| Genkit | `genkit`, `genkit-cli`, `@genkit-ai/*`; imports `genkit`, `defineFlow`, `defineTool` | `generateStream()`, flow `.stream()`, SSE deployments with `Accept: text/event-stream`, Dev UI traces | Treat flows as runnable agents when the user asks to expose them. Dynamic tools may need manual metadata. |

## Platform and Low-Code Agents

| Platform | Detection Signals | Streaming/Event Surface | Adapter Notes |
| --- | --- | --- | --- |
| Dify | Dify app exports/configs, API base URL, API key names, `response_mode: "streaming"` | `/chat-messages` and `/workflows/run` can stream SSE; workflow logs expose steps/tokens | Use API adapter. Keep hosted/self-hosted base URL and app IDs in manifest/env, not code. |
| Flowise | `flowise`, `flowise-sdk`, flow IDs, `/api/v1/predictions/{flow-id}` | Data-only SSE events include start, token, metadata, sourceDocuments, usedTools, error, end | Use API/flow-ID adapter. Treat custom nodes and MCP as untrusted code. |
| n8n AI Agent | n8n workflow JSON; `n8n-nodes-langchain.agent`, Chat Trigger, Webhook streaming | Chat Trigger/Webhook can stream; Tools Agent can return intermediate steps | Treat as workflow automation. Preserve workflow IDs and credentials externally. |
| Botpress | `@botpress/client`, Botpress integration SDK files, actions/events/channels | Runtime API messages, events, actions, webhooks | Good for conversational bots; weaker for token-level tracing. Use official client/API. |
| Rasa CALM | `domain.yml`, `config.yml`, `data/flows`, custom actions | Dialogue commands/flows/actions, not typical token streaming | Include for enterprise chatbots. Use REST/webhook adapter unless a custom action stream exists. |

## Protocol and Generic Signals

- MCP: `mcp.json`, `server.py`/`server.ts` with MCP SDK imports, `@modelcontextprotocol/sdk`, JSON-RPC methods, stdio server commands.
- A2A: Agent Card, `/.well-known/agent-card.json`, `message/send`, `message/stream`, task/artifact types.
- AG-UI: `@ag-ui/core`, `ag-ui`, event types for text messages, tool calls, lifecycle, state.
- OpenAPI/REST: `openapi.json`, `openapi.yaml`, Swagger files, route definitions, FastAPI/Express servers.
- JSON-RPC: `jsonrpc`, `method`, `params`, `id`, `result`, `error` message shapes.
- CLI: executable scripts, package scripts, `if __name__ == "__main__"`, Typer/Click/argparse, Node bin entries.
- Module callable: exported `agent`, `run`, `invoke`, `stream`, `handler`, `root_agent`, or Python functions/classes with agent framework types.

## Research Anchors

- LangGraph: https://docs.langchain.com/oss/python/langgraph/event-streaming
- CrewAI: https://docs.crewai.com/en/concepts/event-listener
- OpenAI Agents SDK Python: https://openai.github.io/openai-agents-python/streaming/
- Vercel AI SDK: https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol
- Pydantic AI: https://pydantic.dev/docs/ai/integrations/ui/overview/
- Semantic Kernel: https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-streaming
- Haystack: https://docs.haystack.deepset.ai/docs/agent
- AG-UI: https://docs.ag-ui.com/
