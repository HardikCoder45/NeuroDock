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
