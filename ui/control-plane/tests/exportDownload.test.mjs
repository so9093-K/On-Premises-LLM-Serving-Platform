import assert from 'node:assert/strict';
import test from 'node:test';
import { canStreamDirectToFile, saveRequestZip, MAX_BUFFERED_DOWNLOAD_BYTES } from '../src/exportDownload.ts';

test('large export fails closed when direct file streaming is unsupported', async (t) => {
  const oldWindow = globalThis.window;
  globalThis.window = {};
  t.after(() => { if (oldWindow === undefined) delete globalThis.window; else globalThis.window = oldWindow; });
  const receipt = {
    parts: [{ kind: 'text', value: '{}' }],
    byteLength: MAX_BUFFERED_DOWNLOAD_BYTES + 100,
    streaming: false,
  };
  await assert.rejects(saveRequestZip(receipt, new AbortController().signal, () => {}),
    /직접 저장을 지원하지 않습니다/);
});

test('large export opens a user-owned file stream and aborts it on cancel', async (t) => {
  const oldWindow = globalThis.window;
  const controller = new AbortController();
  let writes = 0;
  let aborted = false;
  let closed = false;
  globalThis.window = {
    async showSaveFilePicker() {
      return {
        async createWritable() {
          return {
            async write(chunk) { writes += chunk.length; if (writes >= 128 * 1024) controller.abort(); },
            async close() { closed = true; },
            async abort() { aborted = true; },
          };
        },
      };
    },
  };
  t.after(() => { if (oldWindow === undefined) delete globalThis.window; else globalThis.window = oldWindow; });
  const receipt = {
    parts: [{ kind: 'media', value: 'A'.repeat(MAX_BUFFERED_DOWNLOAD_BYTES + 1) }],
    byteLength: MAX_BUFFERED_DOWNLOAD_BYTES + 1,
    streaming: false,
  };
  await assert.rejects(saveRequestZip(receipt, controller.signal, () => {}), { name: 'AbortError' });
  assert.ok(writes >= 128 * 1024);
  assert.equal(aborted, true);
  assert.equal(closed, false);
});

test('direct streaming support is detectable without opening the picker', (t) => {
  const prior = globalThis.window;
  t.after(() => {
    if (prior === undefined) delete globalThis.window;
    else globalThis.window = prior;
  });
  delete globalThis.window;
  assert.equal(canStreamDirectToFile(), false);
  globalThis.window = {};
  assert.equal(canStreamDirectToFile(), false);
  globalThis.window = { showSaveFilePicker: async () => {
    throw new Error('picker must not be opened by capability detection');
  } };
  assert.equal(canStreamDirectToFile(), true);
});
