import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'node:http';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { PUBLIC_EXPORT_LANGUAGES, publicExportSource } from '../src/publicRequestExport.ts';

const run = promisify(execFile);
// 따옴표·백슬래시·줄바꿈·한글·이모지가 셸·Python·JavaScript literal을 거쳐도 같은 바이트여야 한다.
const TRICKY = "it's \"quoted\" \\ back\nslash · 한글 😀 $HOME `cmd`";
const EMBEDDING = { kind: 'embeddings', path: '/v1/embeddings', requestJson: JSON.stringify({ model: 'local-embed-ko', input: [TRICKY, '두 번째'] }) };
const RISK = { kind: 'risk', path: '/v1/risk/assessments', requestJson: JSON.stringify({ prompt: TRICKY }) };

const EMBEDDING_RESPONSE = {
  object: 'list',
  model: 'local-embed-ko',
  data: [
    { object: 'embedding', index: 0, embedding: [0.1, 0.2, 0.3, 0.4, 0.5] },
    { object: 'embedding', index: 1, embedding: [0.5, 0.4, 0.3, 0.2, 0.1] },
  ],
  usage: { prompt_tokens: 9, total_tokens: 9 },
};

function riskResponse(overrides = {}) {
  return {
    assessment_id: 'risk_1',
    status: 'completed',
    risk_detected: false,
    attention_required: false,
    model_risk_detected: false,
    system_signal_detected: false,
    assessment_complete: true,
    strongest_code: null,
    message: 'No model risk signal detected.',
    categories: [
      { code: null, family: 'data_exposure', detected: false, confidence: null, source_model: 'pii-protection', label: null, span_count: 0 },
      { code: null, family: 'data_exposure', detected: false, confidence: null, source_model: 'secret-scanner', label: null, span_count: 0 },
    ],
    system_signals: [],
    ...overrides,
  };
}

async function fakeGateway(t, responseBody, status = 200) {
  const received = [];
  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    received.push({ path: req.url, method: req.method, headers: req.headers, body: Buffer.concat(chunks).toString('utf8') });
    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(responseBody));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  return { received, url: `http://127.0.0.1:${server.address().port}` };
}

const RUNNERS = {
  curl: { file: 'client.sh', binary: 'bash' },
  python: { file: 'client.py', binary: process.env.PYTHON_BIN || 'python3' },
  javascript: { file: 'client.mjs', binary: process.execPath },
};

async function runExample(t, record, language, env) {
  const dir = await mkdtemp(join(tmpdir(), 'public-export-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const { file, binary } = RUNNERS[language];
  await writeFile(join(dir, file), publicExportSource(record, language));
  // 호출자가 넘긴 경우에만 API_KEY가 존재한다. 개발자 셸의 값이 결과를 바꾸지 않게 한다.
  const base = { ...process.env };
  delete base.API_KEY;
  return run(binary, [file], { cwd: dir, env: { ...base, ...env } });
}

for (const language of ['curl', 'python', 'javascript']) {
  test(`${language} Embedding example resends the exact request bytes with the key only from the environment`, async (t) => {
    const { received, url } = await fakeGateway(t, EMBEDDING_RESPONSE);
    const result = await runExample(t, EMBEDDING, language, { GATEWAY_URL: url, API_KEY: 'only-in-env' });
    assert.equal(received.length, 1);
    assert.equal(received[0].path, '/v1/embeddings');
    assert.equal(received[0].method, 'POST');
    assert.equal(received[0].body, EMBEDDING.requestJson);
    assert.equal(received[0].headers.authorization, 'Bearer only-in-env');
    if (language !== 'curl') assert.match(result.stdout, /index=1 dimensions=5/);
    assert.doesNotMatch(publicExportSource(EMBEDDING, language), /only-in-env/);
  });

  test(`${language} Risk example sends no authorization header without API_KEY`, async (t) => {
    const { received, url } = await fakeGateway(t, riskResponse());
    await runExample(t, RISK, language, { GATEWAY_URL: url });
    assert.equal(received[0].path, '/v1/risk/assessments');
    assert.equal(received[0].body, RISK.requestJson);
    assert.equal(received[0].headers.authorization, undefined);
  });

  test(`${language} example fails on an HTTP error instead of printing success`, async (t) => {
    const { url } = await fakeGateway(t, { error: { code: 'MODEL_UNAVAILABLE', message: 'embedding runtime is stopped' } }, 503);
    await assert.rejects(runExample(t, EMBEDDING, language, { GATEWAY_URL: url }), (error) => {
      assert.match(String(error.stdout) + String(error.stderr), /MODEL_UNAVAILABLE/);
      return true;
    });
  });
}

for (const language of ['python', 'javascript']) {
  test(`${language} Risk 예제는 null·누락된 검사기 출처를 제외하고 문자열 출처만 정렬한다`, async (t) => {
    for (const knownSource of [false, true]) {
      const categories = riskResponse().categories.map(({ source_model, ...category }, index) => (
        index === 0 ? { ...category, source_model: null } : category
      ));
      if (knownSource) categories.push(...riskResponse().categories);
      const { url } = await fakeGateway(t, riskResponse({ categories }));
      const result = await runExample(t, RISK, language, { GATEWAY_URL: url });
      assert.match(result.stdout, knownSource
        ? /executed detectors: pii-protection, secret-scanner/
        : /executed detectors: unknown/);
      assert.match(result.stdout, /no risk signal from the executed detectors/);
    }
  });

  test(`${language} Risk 예제는 부분 평가의 탐지 신호를 출력하고 종료 코드 2를 반환한다`, async (t) => {
    for (const knownSource of [true, false]) {
      const systemSignals = [
        { code: 'INFERENCE_TIMEOUT', detected: true, retryable: true, source: null },
        { code: 'INFERENCE_ERROR', detected: true, retryable: true },
      ];
      if (knownSource) systemSignals.push({ code: 'INFERENCE_TIMEOUT', detected: true, retryable: true, source: 'risk-prompt' });
      const { url } = await fakeGateway(t, riskResponse({
        status: 'partial',
        assessment_complete: false,
        risk_detected: true,
        model_risk_detected: true,
        attention_required: true,
        system_signal_detected: true,
        strongest_code: 'D2',
        categories: [{
          code: 'D2', family: 'data_exposure', detected: true, confidence: null, label: 'EMAIL_ADDRESS', span_count: 1,
          ...(knownSource ? { source_model: 'pii-protection' } : {}),
        }],
        system_signals: systemSignals,
      }));
      await assert.rejects(runExample(t, RISK, language, { GATEWAY_URL: url }), (error) => {
        assert.equal(error.code, 2);
        assert.match(error.stdout, /signal D2 EMAIL_ADDRESS count=1/);
        assert.match(error.stdout, knownSource ? /executed detectors: pii-protection, risk-prompt/ : /executed detectors: unknown/);
        assert.match(error.stderr, /assessment incomplete/);
        assert.doesNotMatch(error.stdout, /no risk signal/);
        return true;
      });
    }
  });

  test(`${language} Risk example reports the executed scope and never treats an incomplete 200 as no-signal`, async (t) => {
    const complete = await fakeGateway(t, riskResponse());
    const clean = await runExample(t, RISK, language, { GATEWAY_URL: complete.url });
    assert.match(clean.stdout, /executed detectors: pii-protection, secret-scanner/);
    assert.match(clean.stdout, /no risk signal from the executed detectors/);

    const partial = await fakeGateway(t, riskResponse({
      status: 'partial',
      assessment_complete: false,
      system_signal_detected: true,
      attention_required: true,
      strongest_code: 'INFERENCE_TIMEOUT',
      system_signals: [{ code: 'INFERENCE_TIMEOUT', detected: true, retryable: true, message: 'timeout', source: 'risk-prompt' }],
    }));
    await assert.rejects(runExample(t, RISK, language, { GATEWAY_URL: partial.url }), (error) => {
      assert.equal(error.code, 2);
      assert.match(error.stdout, /executed detectors: pii-protection, risk-prompt, secret-scanner/);
      assert.match(error.stderr, /assessment incomplete/);
      assert.doesNotMatch(error.stdout, /no risk signal/);
      return true;
    });

    const detected = await fakeGateway(t, riskResponse({
      risk_detected: true,
      model_risk_detected: true,
      attention_required: true,
      strongest_code: 'D2',
      categories: [{ code: 'D2', family: 'data_exposure', detected: true, confidence: null, source_model: 'pii-protection', label: 'EMAIL_ADDRESS', span_count: 1 }],
    }));
    const signal = await runExample(t, RISK, language, { GATEWAY_URL: detected.url });
    assert.match(signal.stdout, /signal D2 EMAIL_ADDRESS count=1/);
  });
}

test('Python OpenAI SDK Embedding example keeps standard fields and forwards Gateway extensions', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'public-export-sdk-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const record = { ...EMBEDDING, requestJson: JSON.stringify({ model: 'local-embed-ko', input: TRICKY, truncate_prompt_tokens: 512 }) };
  await writeFile(join(dir, 'client_openai.py'), publicExportSource(record, 'python-sdk'));
  await writeFile(join(dir, 'openai.py'), [
    'import json, os, types',
    'class OpenAI:',
    '    def __init__(self, **options):',
    '        self.embeddings = types.SimpleNamespace(create=self.create)',
    '    def create(self, **kwargs):',
    '        with open(os.environ["CAPTURE_FILE"], "w", encoding="utf-8") as fd: json.dump(kwargs, fd)',
    '        return types.SimpleNamespace(data=[types.SimpleNamespace(index=0, embedding=[0.1, 0.2])])',
  ].join('\n'));
  await run(process.env.PYTHON_BIN || 'python3', ['client_openai.py'], {
    cwd: dir, env: { ...process.env, CAPTURE_FILE: join(dir, 'captured.json') },
  });
  const captured = JSON.parse(await readFile(join(dir, 'captured.json'), 'utf8'));
  assert.equal(captured.model, 'local-embed-ko');
  assert.equal(captured.input, TRICKY);
  assert.deepEqual(captured.extra_body, { truncate_prompt_tokens: 512 });
});

test('Risk offers no SDK example and records that do not match their API are rejected', () => {
  assert.deepEqual(PUBLIC_EXPORT_LANGUAGES.risk.map((item) => item.id), ['curl', 'python', 'javascript']);
  assert.throws(() => publicExportSource(RISK, 'python-sdk'), /제공하지 않는/);
  assert.throws(() => publicExportSource({ ...RISK, path: '/v1/chat/completions' }, 'curl'), /Risk 요청/);
  assert.throws(() => publicExportSource({ ...EMBEDDING, requestJson: '{"prompt":"x"}' }, 'curl'), /Embedding 요청/);
  assert.throws(() => publicExportSource({ ...RISK, requestJson: '[]' }, 'curl'), /JSON 객체/);
});
