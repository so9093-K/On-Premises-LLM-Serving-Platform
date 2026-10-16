import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'node:http';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { buildExportFiles, createExportZip, requestPreview } from '../src/playgroundExport.ts';

const run = promisify(execFile);
const request = JSON.stringify({
  model: 'local-main',
  messages: [
    { role: 'system', content: '응답 형식을 유지하세요.' },
    { role: 'user', content: [
      { type: 'text', text: '오디오를 분석하세요.' },
      { type: 'input_audio', input_audio: { data: 'UklGRgAAAAA=', format: 'wav' } },
      { type: 'image_url', image_url: { url: 'data:image/png;base64,aGVsbG8=' } },
    ] },
    { role: 'assistant', content: null, tool_calls: [{
      id: 'call_1', type: 'function', function: { name: 'lookup', arguments: '{"key":"x"}' },
    }] },
    { role: 'tool', tool_call_id: 'call_1', content: '{"ok":true}' },
  ],
  stream: true,
  stream_options: { include_usage: true },
  max_tokens: 128,
  reasoning: true,
  top_k: 7,
  response_format: { type: 'json_object' },
});

test('export preserves the original HTTP JSON rather than rebuilding or redacting its fields', () => {
  const files = buildExportFiles(request);
  assert.equal(files['request.json'], request);
  assert.deepEqual(JSON.parse(files['request.json']).messages, JSON.parse(request).messages);
  assert.match(files['client.py'], /request.json/);
  assert.match(files['client.mjs'], /request.json/);
  assert.match(files['client.sh'], /request.json/);
  assert.doesNotMatch(JSON.stringify(files), /Bearer only-in-env/);
  assert.match(requestPreview(request), /"reasoning": true/);
  assert.equal(requestPreview(request, 8), null);
  assert.throws(() => buildExportFiles('[]'), /JSON 객체/);
  assert.throws(() => buildExportFiles('{"model":"m"}'), /Chat Completions/);
});

test('ZIP archive contains all five UTF-8 files with valid CRC and lossless media payload', async (t) => {
  const files = buildExportFiles(request);
  const zip = createExportZip(files);
  const dir = await mkdtemp(join(tmpdir(), 'playground-zip-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const path = join(dir, 'bundle.zip');
  await writeFile(path, new Uint8Array(await zip.arrayBuffer()));
  const script = [
    'import sys,zipfile',
    'z=zipfile.ZipFile(sys.argv[1])',
    'assert z.testzip() is None',
    'assert z.namelist()==["request.json","client.py","client.mjs","client.sh","README.md"]',
    'assert z.read("request.json").decode("utf-8")==sys.argv[2]',
    'print("ZIP_OK")',
  ].join('\n');
  const { stdout } = await run('python3', ['-c', script, path, request]);
  assert.match(stdout, /ZIP_OK/);
});

async function createFakeGateway(t, { status = 200, responseBody = 'data: [DONE]\n\n', contentType = 'text/event-stream' } = {}) {
  const received = [];
  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    received.push({ path: req.url, method: req.method, headers: req.headers, body: Buffer.concat(chunks).toString('utf8') });
    res.writeHead(status, { 'Content-Type': contentType });
    res.end(responseBody);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const address = server.address();
  assert.ok(address && typeof address !== 'string');
  return { received, url: 'http://127.0.0.1:' + address.port };
}


const LANGUAGE_CLIENTS = [
  ['Python', 'python3', ['client.py']],
  ['Node.js', process.execPath, ['client.mjs']],
  ['cURL', 'bash', ['client.sh']],
];

for (const [name, binary, args] of LANGUAGE_CLIENTS) {
  for (const [scenario, responseBody, expected] of [
    ['truncated SSE response', 'data: {"choices":[{"delta":{"content":"partial"}}]}\\n\\n', 'STREAM_INCOMPLETE'],
    ['Gateway SSE error', 'event: error\\ndata: {"error":{"code":"UPSTREAM_TIMEOUT","message":"timeout"}}\\n\\n', 'Gateway SSE error'],
    ['HTTP 503', '{"error":{"code":"MAIN_MODEL_SWITCH_IN_PROGRESS"}}', 'MAIN_MODEL_SWITCH_IN_PROGRESS'],
  ]) {
    test(name + ' exits with error on ' + scenario, async (t) => {
      const { received, url } = await createFakeGateway(t, {
        status: scenario === 'HTTP 503' ? 503 : 200,
        contentType: scenario === 'HTTP 503' ? 'application/json' : 'text/event-stream',
        responseBody: responseBody.replaceAll('\\n', '\n'),
      });
      const dir = await mkdtemp(join(tmpdir(), 'playground-error-'));
      t.after(() => rm(dir, { recursive: true, force: true }));
      for (const [filename, content] of Object.entries(buildExportFiles(request))) {
        await writeFile(join(dir, filename), content);
      }
      await assert.rejects(
        run(binary, args, { cwd: dir, env: { ...process.env, GATEWAY_URL: url } }),
        (error) => {
          assert.match(String(error.stderr) + String(error.stdout), new RegExp(expected));
          return true;
        },
      );
      assert.equal(received.length, 1);
      assert.equal(received[0].body, request);
      assert.equal(received[0].headers.authorization, undefined);
    });
  }
}

for (const [name, binary, args] of [
  ['Python', 'python3', ['client.py']],
  ['Node.js', process.execPath, ['client.mjs']],
  ['cURL', 'bash', ['client.sh']],
]) {
  test(name + ' client replays the exact request body, media, extensions and authorization boundary', async (t) => {
    const { received, url } = await createFakeGateway(t);
    const files = buildExportFiles(request);
    const dir = await mkdtemp(join(tmpdir(), 'playground-client-'));
    t.after(() => rm(dir, { recursive: true, force: true }));
    for (const [filename, content] of Object.entries(files)) {
      await writeFile(join(dir, filename), content);
    }
    const result = await run(binary, args, {
      cwd: dir,
      env: { ...process.env, GATEWAY_URL: url, API_KEY: 'only-in-env' },
    });
    assert.match(result.stdout, /data: \[DONE\]/);
    assert.equal(received.length, 1);
    const call = received[0];
    assert.equal(call.path, '/v1/chat/completions');
    assert.equal(call.method, 'POST');
    assert.equal(call.headers.authorization, 'Bearer only-in-env');
    assert.equal(call.body, request);
    assert.equal(call.headers.accept, 'text/event-stream');
  });
}

test('non-streaming export requests JSON and retains stream=false', () => {
  const json = JSON.stringify({ model: 'local-main', messages: [{ role: 'user', content: 'hi' }], stream: false });
  const files = buildExportFiles(json);
  assert.match(files['client.sh'], /Accept: application\/json/);
  assert.equal(files['request.json'], json);
});
