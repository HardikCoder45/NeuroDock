# Protocol and Event Normalization Reference

Use this reference when mapping framework-specific events into the universal hub stream.

## Default Transport

Expose external run streams as Server-Sent Events:

```text
event: agent.text.delta
id: evt_...
data: {"specversion":"1.0","id":"evt_...","type":"agent.text.delta",...}
```

Use WebSocket only for live bidirectional controls such as cancellation, approvals, human input, cursor edits, audio, or collaborative state. Use ordinary HTTP requests for `cancel`, `input`, and `approve` unless a live control channel is explicitly needed.

## Universal Envelope

Every emitted event should be a CloudEvents-like JSON object:

```json
{
  "specversion": "1.0",
  "id": "evt_01HX",
  "type": "agent.text.delta",
  "source": "agenthub://local",
  "subject": "run_123/item_msg_1",
  "time": "2026-06-07T12:00:00.000Z",
  "datacontenttype": "application/json",
  "dataschema": "agent-event.v1",
  "sequence": 42,
  "run_id": "run_123",
  "conversation_id": "conv_123",
  "task_id": "task_123",
  "parent_id": "evt_parent",
  "trace": {
    "trace_id": "trace",
    "span_id": "span",
    "parent_span_id": "parent"
  },
  "producer": {
    "agent_id": "agent_id",
    "agent_name": "Agent",
    "framework": "langgraph",
    "provider": "openai",
    "model": "gpt-5"
  },
  "visibility": "user",
  "data": {}
}
```

Required fields: `id`, `type`, `source`, `time`, `sequence`, `run_id`, `producer.agent_id`, and `data`.

## Event Types

Use these canonical event types:

- `agent.run.created`
- `agent.run.in_progress`
- `agent.text.delta`
- `agent.text.done`
- `agent.reasoning_summary.delta`
- `agent.reasoning_summary.done`
- `agent.tool.call.created`
- `agent.tool.call.arguments.delta`
- `agent.tool.call.arguments.done`
- `agent.tool.result`
- `agent.final`
- `agent.error`
- `agent.log`
- `agent.artifact.created`
- `agent.artifact.delta`
- `agent.artifact.done`
- `agent.usage`
- `agent.run.completed`
- `agent.run.cancelled`

## Payload Shapes

`agent.text.delta`:

```json
{"item_id":"msg_1","content_index":0,"delta":"hello","role":"assistant","modality":"text","annotations":[]}
```

`agent.reasoning_summary.delta`:

```json
{"item_id":"reason_1","summary_index":0,"delta":"Checking available tools.","policy":"summary_only"}
```

`agent.tool.call.created`:

```json
{"tool_call_id":"call_1","tool_name":"search","tool_type":"function","server_id":"local","protocol":"mcp","method":"tools/call","approval_required":false}
```

`agent.tool.call.arguments.delta`:

```json
{"tool_call_id":"call_1","delta":"{\"query\":\"agent\"","arguments_format":"json"}
```

`agent.tool.call.arguments.done`:

```json
{"tool_call_id":"call_1","arguments":{"query":"agent"},"arguments_format":"json"}
```

`agent.tool.result`:

```json
{"tool_call_id":"call_1","status":"completed","result":{},"content":[],"structured_content":{},"duration_ms":120,"error":null}
```

`agent.final`:

```json
{"output":"done","messages":[],"artifacts":[],"finish_reason":"stop"}
```

`agent.error`:

```json
{"code":"adapter_error","message":"Adapter failed","type":"runtime","retryable":false,"details":{},"http_status":500,"jsonrpc_error":null,"tool_call_id":null}
```

`agent.artifact.*`:

```json
{"artifact_id":"art_1","name":"report.md","mime_type":"text/markdown","uri":"artifacts/run/report.md","bytes":1024,"sha256":"...","metadata":{},"delta":null}
```

`agent.usage`:

```json
{"input_tokens":10,"output_tokens":20,"reasoning_output_tokens":0,"cached_input_tokens":0,"cost":null,"model":"gpt-5","provider":"openai"}
```

## MCP Mapping

MCP uses JSON-RPC 2.0 over stdio or Streamable HTTP. The hub should expose an MCP-compatible endpoint for tools/resources/prompts and adapt external MCP servers into hub tools.

Minimum hub behavior:

- `initialize`: return protocol version and server capabilities.
- `tools/list`: return one tool per registered agent plus discovered agent tools.
- `tools/call`: run the requested agent/tool and return structured content.
- `resources/list` and `prompts/list`: return empty arrays unless discovered.

Preserve JSON-RPC `id`. Never write non-JSON-RPC messages to MCP stdout when bridging stdio servers.

## A2A Mapping

Expose an Agent Card and task-style messaging:

- `GET /.well-known/agent-card.json`: hub metadata, skills, streaming capability, endpoint URLs.
- `POST /message/send`: create or run a task and return a task snapshot/final response.
- `POST /message/stream`: stream task status and artifact updates over SSE.

Map hub events to A2A concepts:

- `agent.run.created` -> task submitted/working.
- `agent.text.delta` -> task status message or artifact delta.
- `agent.artifact.*` -> task artifact update.
- `agent.final` and `agent.run.completed` -> task completed.
- `agent.error` -> task failed.

## AG-UI Mapping

AG-UI is useful for frontends. If the user needs AG-UI, map:

- Run lifecycle -> lifecycle events.
- Text deltas -> text message start/content/end.
- Tool call events -> tool call start/args/end and tool result.
- State or progress -> custom or state events.

Do not expose hidden chain-of-thought. Represent thinking as visible reasoning summaries or trace-derived steps only.

## OpenAPI and REST

Generate `GET /openapi.json` for the hub endpoints. For REST-only agents, record:

- `base_url`
- auth environment variable names
- request method/path/body
- stream mode (`text/event-stream`, chunked text, WebSocket, polling, or blocking)
- response mapping into canonical events

OpenAPI 3.2 supports describing sequential streaming media types. If the local tooling only supports 3.0/3.1, keep the schema valid and document streaming in endpoint descriptions.

## OpenTelemetry

Emit or preserve trace fields when available:

- root span: `invoke_agent`
- model calls: chat/generate spans
- tools: `execute_tool`
- attributes: framework, provider, model, response ID, token usage, time-to-first-chunk

OpenTelemetry GenAI conventions are still developing. Prefer optional export rather than making tracing required.

## Source Anchors

- MCP: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- A2A: https://a2a-protocol.org/latest/specification/
- AG-UI: https://docs.ag-ui.com/
- CloudEvents: https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md
- OpenAPI: https://spec.openapis.org/oas/latest.html
- JSON-RPC: https://www.jsonrpc.org/specification
- SSE: https://html.spec.whatwg.org/multipage/server-sent-events.html
- WebSocket: https://www.rfc-editor.org/info/rfc6455/
- OpenTelemetry GenAI: https://opentelemetry.io/docs/specs/semconv/gen-ai/
