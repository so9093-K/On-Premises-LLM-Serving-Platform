import assert from 'node:assert/strict';
import test from 'node:test';
import { writeZip64, receiptArchiveEntries } from '../src/exportPipeline.ts';
import { prepareChatRequest } from '../src/publicChatRequest.ts';

test('ZIP writer preserves originating error when aborting the file sink also fails', async () => {
  const original = new Error('ORIGINATING_WRITE_FAILURE');
  let abortCalled = false;
  const sink = {
    async write() { throw original; },
    async close() { assert.fail('close must never be called after a failed write'); },
    async abort() { abortCalled = true; throw new Error('SECONDARY_ABORT_FAILURE'); },
  };
  const entries = [{
    name: 'request.json',
    byteLength: 2,
    async *chunks() { yield new TextEncoder().encode('{}'); },
  }];
  await assert.rejects(writeZip64(entries, sink), (error) => {
    assert.equal(error, original);
    return true;
  });
  assert.equal(abortCalled, true);
});

test('archive detects misreported original byte length and aborts incomplete output', async () => {
  let aborted = false;
  let closed = false;
  const chunks = [];
  const sink = {
    async write(bytes) { chunks.push(bytes); },
    async close() { closed = true; },
    async abort() { aborted = true; },
  };
  const entries = [{
    name: 'request.json', byteLength: 100,
    async *chunks() { yield new TextEncoder().encode('{}'); },
  }];
  await assert.rejects(writeZip64(entries, sink), /원본 길이/);
  assert.equal(aborted, true);
  assert.equal(closed, false);
});

test('chunked ZIP writer yields to the event loop while preserving bounded progress', async () => {
  const request = prepareChatRequest({
    model: 'local-main',
    messages: [{ role: 'user', content: '길게 반복된 요청 '.repeat(140000) }],
  });
  let timerRan = false;
  let bytesWritten = 0;
  let lastProgress = 0;
  let progressReports = 0;
  const timer = setTimeout(() => { timerRan = true; }, 0);
  try {
    await writeZip64(receiptArchiveEntries(request.receipt), {
      async write(bytes) { bytesWritten += bytes.length; },
      async close() {},
      async abort(reason) { throw new Error('unexpected archive abort: ' + String(reason)); },
    }, {
      onProgress(done, total) {
        assert.ok(done >= lastProgress && done <= total);
        lastProgress = done;
        progressReports += 1;
      },
    });
  } finally { clearTimeout(timer); }
  assert.ok(timerRan, 'large export must give the browser event loop an opportunity to run');
  assert.ok(progressReports > 20, 'large export must be divided into chunks');
  assert.ok(bytesWritten > request.receipt.byteLength);
});
