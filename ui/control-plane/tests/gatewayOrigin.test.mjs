import assert from 'node:assert/strict';
import test from 'node:test';
import { exportTemplates } from '../src/playgroundExport.ts';
import { publicExportSource, PUBLIC_EXPORT_LANGUAGES } from '../src/publicRequestExport.ts';

test('내보낸 클라이언트는 접속 중인 Gateway를 사용하고 요청 바이트를 보존한다', () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'location');
  Object.defineProperty(globalThis, 'location', { configurable: true, value: { origin: 'http://192.0.2.7:9600' } });
  try {
    for (const source of Object.values(exportTemplates(true))) {
      assert.ok(source.includes('http://192.0.2.7:9600'));
    }
    const requestJson = JSON.stringify({ model: 'local-embed', input: ['http://127.0.0.1:9400'] });
    const record = { kind: 'embeddings', path: '/v1/embeddings', requestJson };
    for (const language of PUBLIC_EXPORT_LANGUAGES.embeddings) {
      const source = publicExportSource(record, language.id);
      assert.ok(source.includes('http://192.0.2.7:9600'));
      assert.ok(source.includes('http://127.0.0.1:9400'), '사용자 입력이 변경됐다');
    }
  } finally {
    if (previous) Object.defineProperty(globalThis, 'location', previous);
    else delete globalThis.location;
  }
});
