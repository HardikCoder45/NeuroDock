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
