import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { prepareChatRequest } from '../src/publicChatRequest.ts';
import { captureRequestReceipt, receiptChunks, receiptText } from '../src/requestReceipt.ts';
import { archiveToBlob, receiptArchiveEntries, writeZip64 } from '../src/exportPipeline.ts';
import { exportTemplates } from '../src/playgroundExport.ts';

const run = promisify(execFile);
const media = 'data:image/png;base64,' + 'aGVsbG8='.repeat(130_000);
const user = { role: 'user', content: [{ type: 'image_url', image_url: { url: media } }, { type: 'text', text: '설명하세요' }] };

function getPrepared(n = 3) {
  const body = { model: 'local-main', messages: Array.from({ length: n }, () => user), stream: true,
    response_format: { type: 'json_object' }, top_k: 32 };
  return prepareChatRequest(body, [{ data: media }]);
}

test('repeated media is held by reference, never copied into per-turn text fragments', () => {
  const request = getPrepared(4);
  assert.equal(receiptText(request.receipt), request.json);
  assert.equal(request.receipt.byteLength, new TextEncoder().encode(request.json).byteLength);
  assert.equal(request.receipt.parts.filter((part) => part.kind === 'media').length, 4);
  assert.equal(request.receipt.parts.filter((part) => part.kind === 'media').every((part) => part.value === media), true);
  const inlineBytes = request.receipt.parts.filter((part) => part.kind === 'text').reduce((sum, part) => sum + part.value.length, 0);
  assert.ok(inlineBytes < 2_000, 'inline segments must not retain the full old wire JSON');
});

test('plain requests and values requiring JSON escaping remain lossless', () => {
  const plain = { model: 'local-main', messages: [{ role: 'user', content: '한글\\n"quoted"' }], stream: false };
  const expected = JSON.stringify(plain);
  const receipt = captureRequestReceipt(plain, []);
  assert.equal(receiptText(receipt), expected);
  const unsafeMedia = { data: '"\\n' };
  const fallback = captureRequestReceipt({ ...plain, messages: [{ role: 'user', content: unsafeMedia.data }] },
    [unsafeMedia]);
  assert.equal(receiptText(fallback), JSON.stringify({ ...plain, messages: [{ role: 'user', content: unsafeMedia.data }] }));
});

test('receipt can be streamed into byte-identical UTF-8 chunks', async () => {
  const prepared = getPrepared(2);
  const chunks = [];
  for await (const chunk of receiptChunks(prepared.receipt)) chunks.push(chunk);
  assert.equal(Buffer.concat(chunks).toString('utf8'), prepared.json);
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(async () => {
    for await (const chunk of receiptChunks(prepared.receipt, controller.signal)) void chunk;
  }, { name: 'AbortError' });
});

test('ZIP64 archive uses backpressure and contains original multimodal request and SDK recipes', async (t) => {
  const prepared = getPrepared(3);
  const entries = receiptArchiveEntries(prepared.receipt);
  assert.ok(entries.some((entry) => entry.name === 'client_openai.py'));
  assert.ok(entries.some((entry) => entry.name === 'client_openai.mjs'));
  let updates = 0;
  const blob = await archiveToBlob(entries, { onProgress(done, total) {
    assert.ok(done <= total);
    updates += 1;
  } });
  assert.ok(updates > 10, 'large input must be processed in chunks');
  const dir = await mkdtemp(join(tmpdir(), 'receipt-zip64-'));
  t.after(() => rm(dir, { force: true, recursive: true }));
  const filename = join(dir, 'export.zip');
  await writeFile(filename, new Uint8Array(await blob.arrayBuffer()));
  const script = [
    'import sys,zipfile',
    'z=zipfile.ZipFile(sys.argv[1])',
    'assert z.testzip() is None',
    'assert set(z.namelist()) == {"request.json", "client.py", "client.mjs", "client.sh", "client_openai.py", "client_openai.mjs", "README.md"}',
    'assert z.read("request.json").decode("utf8") == sys.argv[2]',
    'print("ZIP64_OK")',
  ].join('\n');
  // Pass a short expected SHA rather than a 3MB argument to avoid OS argv limits.
  const hashScript = script.replace(
    'z.read("request.json").decode("utf8") == sys.argv[2]',
    'len(z.read("request.json")) == int(sys.argv[2])',
  );
  const { stdout } = await run('python3', ['-c', hashScript, filename, String(new TextEncoder().encode(prepared.json).length)]);
  assert.match(stdout, /ZIP64_OK/);
});

test('archive respects cancellation and aborts the sink instead of saving partial output', async () => {
  const prepared = getPrepared(5);
  const controller = new AbortController();
  let aborted = false;
  let closed = false;
  const sink = {
    async write() {},
    async close() { closed = true; },
    async abort() { aborted = true; },
  };
  await assert.rejects(writeZip64(receiptArchiveEntries(prepared.receipt), sink, {
    signal: controller.signal,
    onProgress(done) { if (done >= 32768) controller.abort(); },
  }), { name: 'AbortError' });
  assert.equal(aborted, true);
  assert.equal(closed, false);
});

test('application code is independently syntax-checkable and shows explicit SDK/HTTP boundary', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'integration-code-'));
  t.after(() => rm(dir, { force: true, recursive: true }));
  const files = exportTemplates(true);
  await writeFile(join(dir, 'client_openai.py'), files['client_openai.py']);
  await writeFile(join(dir, 'client_openai.mjs'), files['client_openai.mjs']);
  await run('python3', ['-c', 'import ast,sys; ast.parse(open(sys.argv[1]).read())', join(dir, 'client_openai.py')]);
  await run(process.execPath, ['--check', join(dir, 'client_openai.mjs')]);
  assert.match(files.README_MD ?? files['README.md'], /SDK/);
});

test('large Unicode text is chunked on code point boundaries', async () => {
  const text = 'x'.repeat(32750) + '🤖' + '한글'.repeat(50000);
  const prepared = prepareChatRequest({ model: 'local-main', messages: [{ role: 'user', content: text }] });
  const chunks = [];
  for await (const part of receiptChunks(prepared.receipt)) {
    assert.ok(part.byteLength <= 32 * 1024 * 4);
    chunks.push(part);
  }
  assert.equal(Buffer.concat(chunks).toString('utf8'), prepared.json);
});

test('repeated long system prompts and previous turns reuse immutable value segments', async () => {
  const system = '시스템 역할: ' + '규칙과 긴 문맥을 유지합니다. '.repeat(300);
  const prior = '질문: ' + '장기 대화 텍스트의 요청 중복 저장을 피합니다. '.repeat(170);
  const body = {
    model: 'local-main', stream: true, messages: [
      { role: 'system', content: system },
      { role: 'user', content: prior },
      { role: 'assistant', content: '확인' },
      { role: 'user', content: prior },
    ],
  };
  const request = prepareChatRequest(body);
  assert.equal(request.json, JSON.stringify(body));
  const shared = request.receipt.parts.filter((part) => part.kind === 'shared');
  assert.equal(shared.length, 3);
  assert.equal(shared.filter((part) => part.value === prior).length, 2);
  assert.ok(request.receipt.parts.filter((part) => part.kind === 'text')
    .reduce((total, part) => total + part.value.length, 0) < 900);
  const chunks = [];
  for await (const bytes of receiptChunks(request.receipt)) chunks.push(bytes);
  assert.equal(Buffer.concat(chunks).toString('utf8'), request.json);
});

test('escaped strings and invalid Unicode do not corrupt byte-exact export', () => {
  const escaped = 'x'.repeat(1000) + '"\\\\\n\t' + 'x'.repeat(1000);
  const loneSurrogate = 'x'.repeat(1100) + '\uD800';
  const validUnicode = '한글 🧪'.repeat(300);
  const body = { model: 'local-main', messages: [
    { role: 'system', content: escaped },
    { role: 'user', content: loneSurrogate },
    { role: 'user', content: validUnicode },
  ] };
  const prepared = prepareChatRequest(body);
  assert.equal(prepared.json, JSON.stringify(body));
  const shared = prepared.receipt.parts.filter((part) => part.kind === 'shared');
  assert.deepEqual(shared.map((part) => part.value), [escaped, loneSurrogate, validUnicode]);
  assert.equal(prepared.receipt.byteLength, Buffer.byteLength(prepared.json));
});

test('mixed reusable media and long text preserves byte equality and avoids duplicate content', () => {
  const system = 'The assistant should preserve policy contracts. '.repeat(80);
  const body = { model: 'local-main', messages: [
    { role: 'system', content: system },
    { role: 'user', content: [{ type: 'image_url', image_url: { url: media } }] },
    { role: 'user', content: [{ type: 'image_url', image_url: { url: media } }] },
  ] };
  const request = prepareChatRequest(body, [{ data: media }]);
  assert.equal(request.json, JSON.stringify(body));
  assert.equal(request.receipt.parts.filter((part) => part.kind === 'media').length, 2);
  assert.equal(request.receipt.parts.filter((part) => part.kind === 'shared').length, 1);
});

test('escaped long content roundtrips JSON-special characters and surrogate boundaries', async () => {
  const examples = [
    '\u0000'.repeat(520), '\\'.repeat(513), '"'.repeat(650),
    'hello\nworld\t'.repeat(90),
    '🥽'.repeat(17000), 'x'.repeat(32767) + '🧪' + 'y'.repeat(600),
    '\uD800'.repeat(540),
    '한글 줄바꿈\r\n \\ " emoji 🙂'.repeat(110),
  ];
  for (const [index, content] of examples.entries()) {
    const body = { model: 'local-main', messages: [{ role: 'user', content }],
      metadata: { sample: index } };
    const prepared = prepareChatRequest(body);
    assert.equal(prepared.json, JSON.stringify(body), 'serialized value ' + index);
    assert.ok(prepared.receipt.parts.some((part) => part.kind === 'shared'), 'shared receipt ' + index);
    const chunks = [];
    for await (const chunk of receiptChunks(prepared.receipt)) chunks.push(chunk);
    const bytes = Buffer.concat(chunks);
    assert.equal(bytes.toString('utf8'), prepared.json, 'export chunks ' + index);
    assert.equal(bytes.length, prepared.receipt.byteLength, 'reported byte length ' + index);
  }
});

test('recorded request segments and receipt metadata are runtime immutable', () => {
  const prepared = prepareChatRequest({
    model: 'local-main',
    messages: [{ role: 'user', content: 'immutable prompt '.repeat(100) }],
  });
  const receipt = prepared.receipt;
  assert.equal(Object.isFrozen(receipt), true);
  assert.equal(Object.isFrozen(receipt.parts), true);
  assert.ok(receipt.parts.every((part) => Object.isFrozen(part)));
  assert.throws(() => { receipt.parts[0].value = 'corrupted'; }, TypeError);
  assert.throws(() => { receipt.byteLength = -1; }, TypeError);
  assert.equal(receiptText(receipt), prepared.json);
});
