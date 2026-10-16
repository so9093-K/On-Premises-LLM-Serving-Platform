import assert from 'node:assert/strict';
import test from 'node:test';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { exportTemplates } from '../src/playgroundExport.ts';

const run = promisify(execFile);
const body = {
  model: 'local-main',
  messages: [{ role: 'user', content: 'JSON 응답' }],
  stream: false,
  response_format: { type: 'json_object' },
  reasoning: true,
  top_k: 7,
};

test('Python SDK integration keeps standard fields and forwards provider extensions via extra_body', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'sdk-python-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const files = exportTemplates(false);
  await writeFile(join(dir, 'client_openai.py'), files['client_openai.py']);
  await writeFile(join(dir, 'request.json'), JSON.stringify(body));
  await writeFile(join(dir, 'openai.py'), [
    'import json, os, types',
    'class APIError(Exception): pass',
    'class OpenAI:',
    '    def __init__(self, **options):',
    '        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))',
    '    def create(self, **kwargs):',
    '        with open(os.environ["CAPTURE_FILE"], "w") as fd: json.dump(kwargs, fd)',
    '        message = types.SimpleNamespace(content="{\\\"ok\\\":true}", tool_calls=None)',
    '        class Result:',
    '            def model_dump_json(self, indent=2): return "{\\\"choices\\\":[]}"',
    '        result = Result()',
    '        result.choices = [types.SimpleNamespace(message=message)]',
    '        return result',
  ].join('\n'));
  await run('python3', ['client_openai.py'], {
    cwd: dir, env: { ...process.env, CAPTURE_FILE: join(dir, 'captured.json') },
  });
  const captured = JSON.parse(await readFile(join(dir, 'captured.json'), 'utf8'));
  assert.equal(captured.model, 'local-main');
  assert.deepEqual(captured.messages, body.messages);
  assert.deepEqual(captured.response_format, body.response_format);
  assert.deepEqual(captured.extra_body, { reasoning: true, top_k: 7 });
});

test('Node.js SDK integration receives model parameters and structured JSON without losing extensions', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'sdk-node-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const files = exportTemplates(false);
  await writeFile(join(dir, 'client_openai.mjs'), files['client_openai.mjs']);
  await writeFile(join(dir, 'request.json'), JSON.stringify(body));
  const sdk = join(dir, 'node_modules', 'openai');
  await mkdir(sdk, { recursive: true });
  await writeFile(join(sdk, 'package.json'), JSON.stringify({ name: 'openai', type: 'module', exports: './index.mjs' }));
  await writeFile(join(sdk, 'index.mjs'), [
    "import { writeFileSync } from 'node:fs';",
    'export default class OpenAI {',
    '  constructor() { this.chat = { completions: { create: async (body) => {',
    "    writeFileSync(process.env.CAPTURE_FILE, JSON.stringify(body));",
    '    return { choices: [{ message: { content: JSON.stringify({ok:true}), tool_calls: [] } }] };',
    '  } } }; }',
    '}',
  ].join('\n'));
  await run(process.execPath, ['client_openai.mjs'], {
    cwd: dir, env: { ...process.env, CAPTURE_FILE: join(dir, 'captured.json') },
  });
  assert.deepEqual(JSON.parse(await readFile(join(dir, 'captured.json'), 'utf8')), body);
});
