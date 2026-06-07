#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import textwrap


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def default_root() -> Path:
    cwd = Path.cwd()
    if (cwd / "package.json").exists() or (cwd / ".git").exists():
        return cwd / ".agents" / "agents"
    return Path.home() / ".agents" / "agents"


def write_text(path: Path, content: str, force: bool = False) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def write_json(path: Path, payload: object, force: bool = False) -> bool:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return write_text(path, text, force=force)


SERVER_MJS = r'''
import http from 'node:http';
import fs from 'node:fs/promises';
import fssync from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const ROOT = process.env.AGENT_HUB_ROOT || path.dirname(__filename);
const HOST = process.env.HOST || '127.0.0.1';
const PORT = Number(process.env.PORT || 17771);
const registryPath = path.join(ROOT, 'registry', 'agents.json');
const runs = new Map();
const subscribers = new Map();

function now() {
  return new Date().toISOString();
}

async function readJson(filePath, fallback) {
  try {
    return JSON.parse(await fs.readFile(filePath, 'utf8'));
  } catch {
    return fallback;
  }
}

async function writeJson(filePath, value) {
  const tmp = `${filePath}.tmp`;
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(tmp, JSON.stringify(value, null, 2) + '\n', 'utf8');
  await fs.rename(tmp, filePath);
}

async function registry() {
  const data = await readJson(registryPath, { version: 1, agents: [] });
  if (!Array.isArray(data.agents)) data.agents = [];
  return data;
}

async function findAgent(id) {
  const data = await registry();
  return data.agents.find((agent) => agent.id === id) || null;
}

function sendJson(res, status, payload) {
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
  });
  res.end(JSON.stringify(payload, null, 2));
}

function sendText(res, status, text) {
  res.writeHead(status, {
    'Content-Type': 'text/plain; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
  });
  res.end(text);
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString('utf8');
  if (!raw.trim()) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return { raw };
  }
}

function nextSequence(run) {
  run.sequence += 1;
  return run.sequence;
}

function envelope(run, type, data = {}, options = {}) {
  return {
    specversion: '1.0',
    id: options.id || `evt_${randomUUID()}`,
    type,
    source: `agenthub://local/${run.agent_id}`,
    subject: options.subject || `${run.id}/${type}`,
    time: now(),
    datacontenttype: 'application/json',
    dataschema: 'agent-event.v1',
    sequence: nextSequence(run),
    run_id: run.id,
    conversation_id: run.conversation_id || run.id,
    task_id: run.task_id || run.id,
    parent_id: options.parent_id || null,
    trace: options.trace || {},
    producer: {
      agent_id: run.agent_id,
      agent_name: run.agent?.name || run.agent_id,
      framework: run.agent?.frameworks?.[0] || run.agent?.framework || 'unknown',
      provider: options.provider || null,
      model: options.model || null,
    },
    visibility: options.visibility || 'user',
    data,
  };
}

function writeSse(res, event) {
  res.write(`event: ${event.type}\n`);
  res.write(`id: ${event.id}\n`);
  res.write(`data: ${JSON.stringify(event)}\n\n`);
}

function appendEvent(run, event) {
  run.events.push(event);
  if (event.type === 'agent.run.completed' || event.type === 'agent.run.cancelled' || event.type === 'agent.error') {
    run.status = event.type === 'agent.error' ? 'failed' : 'completed';
  }
  const clients = subscribers.get(run.id) || new Set();
  for (const res of clients) {
    writeSse(res, event);
    if (run.status === 'completed' || run.status === 'failed') {
      res.write('event: done\nid: done\ndata: [DONE]\n\n');
      res.end();
      clients.delete(res);
    }
  }
}

async function loadAdapter(agent) {
  const adapterPath = path.join(ROOT, 'adapters', agent.id, 'adapter.mjs');
  if (fssync.existsSync(adapterPath)) {
    const moduleUrl = `${pathToFileURL(adapterPath).href}?t=${Date.now()}`;
    return import(moduleUrl);
  }
  return builtinAdapter;
}

const builtinAdapter = {
  async run({ agent, input, emit }) {
    emit('agent.run.in_progress', { status: 'running', adapter: 'builtin' });
    const text = `Agent ${agent.id} is registered but has no generated adapter yet. Generate one with scripts/generate_adapter.py or add agenthub.manifest.json.`;
    emit('agent.text.delta', { item_id: 'msg_1', content_index: 0, delta: text, role: 'assistant', modality: 'text' });
    emit('agent.text.done', { item_id: 'msg_1', text, role: 'assistant', finish_reason: 'adapter_missing' });
    emit('agent.final', { output: text, messages: [], artifacts: [], finish_reason: 'adapter_missing', input });
    emit('agent.usage', { input_tokens: null, output_tokens: null, reasoning_output_tokens: null, cached_input_tokens: null, cost: null, model: null, provider: null });
  },
};

async function startRun(agent, input = {}, options = {}) {
  const run = {
    id: `run_${randomUUID()}`,
    agent_id: agent.id,
    agent,
    input,
    events: [],
    sequence: 0,
    status: 'queued',
    conversation_id: options.conversation_id || null,
    task_id: options.task_id || null,
    cancelled: false,
  };
  runs.set(run.id, run);
  appendEvent(run, envelope(run, 'agent.run.created', { status: 'created', input }));
  queueMicrotask(async () => {
    try {
      run.status = 'running';
      const adapter = await loadAdapter(agent);
      const emit = (type, data = {}, eventOptions = {}) => appendEvent(run, envelope(run, type, data, eventOptions));
      await adapter.run({ root: ROOT, agent, input, emit, run, spawn });
      if (!run.cancelled && run.status !== 'failed') {
        appendEvent(run, envelope(run, 'agent.run.completed', { status: 'completed' }));
      }
    } catch (error) {
      appendEvent(run, envelope(run, 'agent.error', {
        code: 'adapter_error',
        message: error?.message || String(error),
        type: 'runtime',
        retryable: false,
        details: {},
        http_status: 500,
        jsonrpc_error: null,
        tool_call_id: null,
      }));
    }
  });
  return run;
}

function openApiDocument() {
  return {
    openapi: '3.1.0',
    info: { title: 'NeuroDock API', version: '1.0.0' },
    paths: {
      '/health': { get: { responses: { 200: { description: 'Hub health' } } } },
      '/agents': { get: { responses: { 200: { description: 'Registered agents' } } } },
      '/agents/{id}': { get: { responses: { 200: { description: 'Agent metadata' }, 404: { description: 'Missing agent' } } } },
      '/agents/{id}/runs': { post: { responses: { 202: { description: 'Created run' } } } },
      '/runs/{run_id}/events': { get: { responses: { 200: { description: 'SSE stream of universal agent events' } } } },
      '/mcp': { get: { responses: { 200: { description: 'MCP Streamable HTTP event stream' } } }, post: { responses: { 200: { description: 'MCP JSON-RPC response' } } } },
      '/message/send': { post: { responses: { 200: { description: 'A2A-style message send' } } } },
      '/message/stream': { post: { responses: { 200: { description: 'A2A-style SSE message stream' } } } },
    },
  };
}

async function handleMcp(body) {
  const calls = Array.isArray(body) ? body : [body];
  const responses = [];
  const data = await registry();
  for (const call of calls) {
    const id = call?.id ?? null;
    const method = call?.method;
    if (method === 'initialize') {
      responses.push({ jsonrpc: '2.0', id, result: { protocolVersion: '2025-06-18', serverInfo: { name: 'NeuroDock', version: '1.0.0' }, capabilities: { tools: {}, resources: {}, prompts: {} } } });
    } else if (method === 'tools/list') {
      responses.push({ jsonrpc: '2.0', id, result: { tools: data.agents.map((agent) => ({ name: `agent:${agent.id}`, description: agent.description || `Run ${agent.name || agent.id}`, inputSchema: { type: 'object', properties: { input: { type: 'object' } } } })) } });
    } else if (method === 'resources/list' || method === 'prompts/list') {
      const key = method.startsWith('resources') ? 'resources' : 'prompts';
      responses.push({ jsonrpc: '2.0', id, result: { [key]: [] } });
    } else if (method === 'tools/call') {
      const name = call?.params?.name || '';
      const agentId = name.startsWith('agent:') ? name.slice(6) : call?.params?.arguments?.agent_id;
      const agent = data.agents.find((candidate) => candidate.id === agentId);
      if (!agent) {
        responses.push({ jsonrpc: '2.0', id, error: { code: -32602, message: `Unknown agent ${agentId || name}` } });
      } else {
        const run = await startRun(agent, call?.params?.arguments || {});
        responses.push({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: `Started run ${run.id}` }], structuredContent: { run_id: run.id, events_url: `/runs/${run.id}/events` } } });
      }
    } else {
      responses.push({ jsonrpc: '2.0', id, error: { code: -32601, message: `Method not found: ${method}` } });
    }
  }
  return Array.isArray(body) ? responses : responses[0];
}

async function route(req, res) {
  if (req.method === 'OPTIONS') {
    res.writeHead(204, { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type,Authorization' });
    res.end();
    return;
  }
  const url = new URL(req.url, `http://${req.headers.host || `${HOST}:${PORT}`}`);
  const parts = url.pathname.split('/').filter(Boolean);

  if (req.method === 'GET' && url.pathname === '/health') {
    sendJson(res, 200, { ok: true, root: ROOT, time: now() });
    return;
  }

  if (req.method === 'GET' && url.pathname === '/openapi.json') {
    sendJson(res, 200, openApiDocument());
    return;
  }

  if (req.method === 'GET' && url.pathname === '/agents') {
    sendJson(res, 200, await registry());
    return;
  }

  if (req.method === 'GET' && parts[0] === 'agents' && parts.length === 2) {
    const agent = await findAgent(parts[1]);
    sendJson(res, agent ? 200 : 404, agent || { error: 'agent_not_found' });
    return;
  }

  if (req.method === 'GET' && parts[0] === 'agents' && parts[2] === 'tools') {
    const agent = await findAgent(parts[1]);
    sendJson(res, agent ? 200 : 404, { tools: agent?.tools || [], error: agent ? undefined : 'agent_not_found' });
    return;
  }

  if (req.method === 'POST' && parts[0] === 'agents' && parts[2] === 'setup') {
    const agent = await findAgent(parts[1]);
    if (!agent) return sendJson(res, 404, { error: 'agent_not_found' });
    const required = agent.required_env || [];
    const missing = required.filter((name) => !process.env[name]);
    sendJson(res, 200, { agent_id: agent.id, required_env: required, missing_env: missing, setup_required: missing.length > 0 });
    return;
  }

  if (req.method === 'POST' && parts[0] === 'agents' && parts[2] === 'runs') {
    const agent = await findAgent(parts[1]);
    if (!agent) return sendJson(res, 404, { error: 'agent_not_found' });
    const body = await readBody(req);
    const run = await startRun(agent, body);
    sendJson(res, 202, { run_id: run.id, status: run.status, events_url: `/runs/${run.id}/events` });
    return;
  }

  if (req.method === 'GET' && parts[0] === 'runs' && parts[2] === 'events') {
    const run = runs.get(parts[1]);
    if (!run) return sendJson(res, 404, { error: 'run_not_found' });
    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'Access-Control-Allow-Origin': '*',
    });
    for (const event of run.events) writeSse(res, event);
    if (run.status === 'completed' || run.status === 'failed') {
      res.write('event: done\nid: done\ndata: [DONE]\n\n');
      res.end();
      return;
    }
    const set = subscribers.get(run.id) || new Set();
    set.add(res);
    subscribers.set(run.id, set);
    req.on('close', () => set.delete(res));
    return;
  }

  if (req.method === 'POST' && parts[0] === 'runs' && ['cancel', 'input', 'approve'].includes(parts[2])) {
    const run = runs.get(parts[1]);
    if (!run) return sendJson(res, 404, { error: 'run_not_found' });
    const body = await readBody(req);
    if (parts[2] === 'cancel') {
      run.cancelled = true;
      appendEvent(run, envelope(run, 'agent.run.cancelled', { reason: body.reason || 'client_request' }));
    } else {
      appendEvent(run, envelope(run, 'agent.log', { level: 'info', category: parts[2], message: `${parts[2]} received`, attributes: body }));
    }
    sendJson(res, 200, { ok: true, run_id: run.id });
    return;
  }

  if (req.method === 'POST' && url.pathname === '/agents/download') {
    sendJson(res, 202, { status: 'external_download_helper_required', command: 'Use the NeuroDock scripts/download_agent.py helper so repo writes and registry updates stay explicit.' });
    return;
  }

  if (url.pathname === '/mcp' && req.method === 'GET') {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'Access-Control-Allow-Origin': '*',
    });
    writeSse(res, { id: `evt_${randomUUID()}`, type: 'mcp.ready', time: now(), data: { endpoint: '/mcp' } });
    res.end();
    return;
  }

  if (url.pathname === '/mcp' && req.method === 'POST') {
    sendJson(res, 200, await handleMcp(await readBody(req)));
    return;
  }

  if (req.method === 'GET' && url.pathname === '/.well-known/agent-card.json') {
    const data = await registry();
    sendJson(res, 200, {
      name: 'NeuroDock',
      description: 'Local hub exposing downloaded agents through API, MCP, and A2A-style streams.',
      url: `http://${HOST}:${PORT}`,
      version: '1.0.0',
      capabilities: { streaming: true, pushNotifications: false },
      skills: data.agents.map((agent) => ({ id: agent.id, name: agent.name || agent.id, description: agent.description || '' })),
      endpoints: { message_send: '/message/send', message_stream: '/message/stream' },
    });
    return;
  }

  if (req.method === 'POST' && (url.pathname === '/message/send' || url.pathname === '/message/stream')) {
    const body = await readBody(req);
    const data = await registry();
    const agent = data.agents.find((candidate) => candidate.id === body.agent_id) || data.agents[0];
    if (!agent) return sendJson(res, 404, { error: 'no_agents_registered' });
    const run = await startRun(agent, body);
    if (url.pathname.endsWith('/stream')) {
      res.writeHead(200, {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'Access-Control-Allow-Origin': '*',
      });
      for (const event of run.events) writeSse(res, event);
      const set = subscribers.get(run.id) || new Set();
      set.add(res);
      subscribers.set(run.id, set);
      req.on('close', () => set.delete(res));
      return;
    }
    sendJson(res, 200, { task: { id: run.id, status: 'submitted', events_url: `/runs/${run.id}/events` } });
    return;
  }

  sendJson(res, 404, { error: 'not_found', path: url.pathname });
}

const server = http.createServer((req, res) => {
  route(req, res).catch((error) => sendJson(res, 500, { error: 'server_error', message: error?.message || String(error) }));
});

server.listen(PORT, HOST, () => {
  console.log(`NeuroDock listening on http://${HOST}:${PORT}`);
  console.log(`Root: ${ROOT}`);
});
'''


GENERIC_ADAPTER_MJS = r'''
export async function run({ agent, input, emit, spawn }) {
  const runtime = agent.runtime || {};
  const command = runtime.command;
  if (!command) {
    const text = `No runtime command configured for ${agent.id}. Add one to agenthub.manifest.json or regenerate a framework adapter.`;
    emit('agent.run.in_progress', { status: 'running', adapter: 'generic' });
    emit('agent.text.delta', { item_id: 'msg_1', content_index: 0, delta: text, role: 'assistant', modality: 'text' });
    emit('agent.text.done', { item_id: 'msg_1', text, role: 'assistant', finish_reason: 'missing_runtime_command' });
    emit('agent.final', { output: text, messages: [], artifacts: [], finish_reason: 'missing_runtime_command' });
    return;
  }

  emit('agent.run.in_progress', { status: 'running', adapter: 'generic-cli', command });
  const child = spawn(command[0], command.slice(1), {
    cwd: agent.app_path,
    env: { ...process.env, ...(runtime.env || {}) },
  });

  let output = '';
  child.stdout.setEncoding('utf8');
  child.stderr.setEncoding('utf8');
  child.stdout.on('data', (chunk) => {
    output += chunk;
    emit('agent.text.delta', { item_id: 'stdout', content_index: 0, delta: chunk, role: 'assistant', modality: 'text' });
  });
  child.stderr.on('data', (chunk) => {
    emit('agent.log', { level: 'warn', category: 'stderr', message: chunk, attributes: {} });
  });

  const exitCode = await new Promise((resolve) => child.on('close', resolve));
  emit('agent.text.done', { item_id: 'stdout', text: output, role: 'assistant', finish_reason: exitCode === 0 ? 'stop' : 'error' });
  emit('agent.final', { output, messages: [], artifacts: [], finish_reason: exitCode === 0 ? 'stop' : 'error' });
  emit('agent.usage', { input_tokens: null, output_tokens: null, reasoning_output_tokens: null, cached_input_tokens: null, cost: null, model: null, provider: null });
}
'''


PYTHON_BRIDGE = r'''
#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time


def emit(event_type: str, data: dict) -> None:
    sys.stdout.write(json.dumps({"type": event_type, "data": data}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    agent_id = payload.get("agent", {}).get("id", "python-agent")
    emit("agent.run.in_progress", {"status": "running", "adapter": "python-bridge"})
    text = f"Python bridge placeholder for {agent_id}. Replace this bridge with a framework-native adapter."
    emit("agent.text.delta", {"item_id": "msg_1", "content_index": 0, "delta": text, "role": "assistant", "modality": "text"})
    emit("agent.text.done", {"item_id": "msg_1", "text": text, "role": "assistant", "finish_reason": "bridge_placeholder"})
    emit("agent.final", {"output": text, "messages": [], "artifacts": [], "finish_reason": "bridge_placeholder"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


EVENT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "agent-event.v1",
    "title": "NeuroDock Event",
    "type": "object",
    "required": ["id", "type", "source", "time", "sequence", "run_id", "producer", "data"],
    "properties": {
        "specversion": {"type": "string"},
        "id": {"type": "string"},
        "type": {"type": "string"},
        "source": {"type": "string"},
        "subject": {"type": ["string", "null"]},
        "time": {"type": "string"},
        "datacontenttype": {"type": "string"},
        "dataschema": {"type": "string"},
        "sequence": {"type": "integer", "minimum": 1},
        "run_id": {"type": "string"},
        "conversation_id": {"type": ["string", "null"]},
        "task_id": {"type": ["string", "null"]},
        "parent_id": {"type": ["string", "null"]},
        "trace": {"type": "object"},
        "producer": {
            "type": "object",
            "required": ["agent_id"],
            "properties": {
                "agent_id": {"type": "string"},
                "agent_name": {"type": ["string", "null"]},
                "framework": {"type": ["string", "null"]},
                "provider": {"type": ["string", "null"]},
                "model": {"type": ["string", "null"]},
            },
            "additionalProperties": True,
        },
        "visibility": {"type": "string"},
        "data": {"type": "object"},
    },
    "additionalProperties": True,
}


def scaffold(root: Path, force: bool = False) -> list[str]:
    root = root.expanduser().resolve()
    created: list[str] = []
    for name in ["apps", "adapters", "registry", "schemas", "logs", "artifacts", "runtime", "bridges"]:
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        created.append(str(directory))

    if write_json(root / "registry" / "agents.json", {"version": 1, "updated_at": utc_now(), "agents": []}, force=force):
        created.append(str(root / "registry" / "agents.json"))

    if write_json(root / "schemas" / "agent-event.schema.json", EVENT_SCHEMA, force=force):
        created.append(str(root / "schemas" / "agent-event.schema.json"))

    package = {
        "name": "neurodock",
        "version": "1.0.0",
        "private": True,
        "type": "module",
        "scripts": {"start": "node server.mjs", "dev": "node server.mjs"},
        "dependencies": {},
    }
    if write_json(root / "package.json", package, force=force):
        created.append(str(root / "package.json"))

    if write_text(root / "server.mjs", textwrap.dedent(SERVER_MJS).lstrip(), force=force):
        created.append(str(root / "server.mjs"))

    if write_text(root / "adapters" / "_generic" / "adapter.mjs", textwrap.dedent(GENERIC_ADAPTER_MJS).lstrip(), force=force):
        created.append(str(root / "adapters" / "_generic" / "adapter.mjs"))

    if write_text(root / "bridges" / "python_bridge.py", textwrap.dedent(PYTHON_BRIDGE).lstrip(), force=force):
        created.append(str(root / "bridges" / "python_bridge.py"))

    gitignore = "\n".join([
        "node_modules/",
        ".env",
        ".env.*",
        "!.env.example",
        "logs/",
        "artifacts/",
        "runtime/",
        "apps/*/.venv/",
        "apps/*/venv/",
        "apps/*/node_modules/",
        "apps/*/.env",
        "apps/*/.env.*",
        "",
    ])
    if write_text(root / ".gitignore", gitignore, force=force):
        created.append(str(root / ".gitignore"))

    env_example = "\n".join([
        "HOST=127.0.0.1",
        "PORT=17771",
        "AGENT_HUB_ROOT=",
        "OPENAI_API_KEY=",
        "ANTHROPIC_API_KEY=",
        "GOOGLE_API_KEY=",
        "OPENROUTER_API_KEY=",
        "",
    ])
    if write_text(root / ".env.example", env_example, force=force):
        created.append(str(root / ".env.example"))

    return created


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold a universal local agent hub.")
    parser.add_argument("--root", type=Path, default=None, help="Hub root. Defaults to <cwd>/.agents/agents inside a repo, else ~/.agents/agents.")
    parser.add_argument("--force", action="store_true", help="Overwrite generated hub files.")
    args = parser.parse_args()
    root = args.root or default_root()
    created = scaffold(root, force=args.force)
    print(json.dumps({"root": str(root.expanduser().resolve()), "created_or_updated": created}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
