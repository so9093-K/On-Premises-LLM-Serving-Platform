import assert from 'node:assert/strict';
import test from 'node:test';

import {
  availableRiskChecks,
  availableRiskExamples,
  buildRiskRequest,
  interpretRiskAssessment,
  MAX_RISK_PROMPT_CHARACTERS,
  promptDetectorInactive,
  RISK_EXAMPLES,
  riskCheckDescription,
} from '../src/riskPlayground.ts';

const PROMPT_MODEL = { id: 'risk-prompt', capabilities: ['risk.prompt_attack_signal'] };
const CHAT_MODEL = { id: 'local-main', capabilities: ['chat.completions'] };
const DYNAMIC_FEATURES = ['chat', 'embeddings', 'risk', 'prompt_detection'];

function assessment(overrides = {}) {
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
    categories: [],
    system_signals: [],
    ...overrides,
  };
}

test('Core offers PII·Secret checks without the model-backed prompt detector', () => {
  const core = availableRiskChecks(['risk'], []);
  assert.deepEqual(core.map((check) => check.id), ['pii', 'secret', 'assessment']);
  assert.equal(availableRiskExamples(core).some((example) => example.check === 'prompt'), false);
  assert.equal(promptDetectorInactive(['risk'], []), false);
  assert.deepEqual(availableRiskChecks(['chat'], [PROMPT_MODEL]), []);
});

test('the prompt detector is offered only when /v1/models publishes it, not because the target declares it', () => {
  // rtx4090-24gb처럼 자원 정책으로 detector가 빠진 구성: feature는 있지만 공개 모델은 없다.
  const inactive = availableRiskChecks(DYNAMIC_FEATURES, [CHAT_MODEL]);
  assert.deepEqual(inactive.map((check) => check.id), ['pii', 'secret', 'assessment']);
  assert.equal(promptDetectorInactive(DYNAMIC_FEATURES, [CHAT_MODEL]), true);
  assert.equal(availableRiskExamples(inactive).some((example) => example.check === 'prompt'), false);
  const assessment = inactive.find((check) => check.id === 'assessment');
  assert.equal(riskCheckDescription(assessment, inactive), '활성 검사기를 PII → Secret 순서로 실행');

  const active = availableRiskChecks(DYNAMIC_FEATURES, [CHAT_MODEL, PROMPT_MODEL]);
  assert.deepEqual(active.map((check) => check.id), ['pii', 'secret', 'prompt', 'assessment']);
  assert.equal(promptDetectorInactive(DYNAMIC_FEATURES, [PROMPT_MODEL]), false);
  assert.equal(riskCheckDescription(assessment, active), '활성 검사기를 PII → Secret → Prompt Injection 순서로 실행');
});

test('every example targets a known check and uses synthetic data', () => {
  const checks = new Set(availableRiskChecks(['risk', 'prompt_detection'], [PROMPT_MODEL]).map((check) => check.id));
  for (const example of RISK_EXAMPLES) {
    assert.ok(checks.has(example.check), example.id);
    for (const email of example.prompt.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+/g) ?? []) {
      assert.match(email, /@(?:[a-z0-9-]+\.)*example\.(?:com|org|net|internal)$/, example.id);
    }
  }
});

test('request validation uses the Gateway code point limit', () => {
  assert.deepEqual(buildRiskRequest('메일 hong@example.com').body, { prompt: '메일 hong@example.com' });
  assert.match(buildRiskRequest('   ').error, /입력/);
  // UTF-16 길이로 세면 이모지 입력을 실제 한도보다 일찍 거부한다.
  assert.equal(buildRiskRequest('😀'.repeat(MAX_RISK_PROMPT_CHARACTERS)).error, null);
  assert.match(buildRiskRequest('a'.repeat(MAX_RISK_PROMPT_CHARACTERS + 1)).error, /20,000/);
});

test('HTTP 200 is a non-detection only when the assessment completed without system signals', () => {
  assert.equal(interpretRiskAssessment(assessment()).result.verdict, 'no_signal');
  for (const incomplete of [
    { status: 'partial', assessment_complete: false },
    { status: 'failed', assessment_complete: false, message: 'Detector inference failed.' },
    {
      system_signal_detected: true,
      attention_required: true,
      strongest_code: 'TRUNCATED_INPUT',
      system_signals: [{ code: 'TRUNCATED_INPUT', detected: true, retryable: false }],
    },
  ]) {
    const { result } = interpretRiskAssessment(assessment(incomplete));
    assert.equal(result.verdict, 'incomplete');
  }
});

test('detected signals are reported with completeness instead of a policy decision', () => {
  const { result } = interpretRiskAssessment(assessment({
    status: 'partial',
    assessment_complete: false,
    risk_detected: true,
    model_risk_detected: true,
    attention_required: true,
    strongest_code: 'D2',
    categories: [
      { code: 'D2', family: 'data_exposure', detected: true, confidence: null, label: 'EMAIL_ADDRESS', span_count: 1, source_model: 'pii-protection' },
      { code: null, family: 'prompt_attack', detected: false, confidence: null, label: '<SAFE>', source_model: 'risk-prompt' },
    ],
    system_signals: [{ code: 'INFERENCE_TIMEOUT', detected: true, retryable: true }],
  }));
  assert.equal(result.verdict, 'signal_detected');
  assert.equal(result.complete, false);
  assert.deepEqual(result.signals, [
    { code: 'D2', family: 'data_exposure', label: 'EMAIL_ADDRESS', spanCount: 1, source: 'pii-protection' },
  ]);
  assert.deepEqual(result.systemSignals, [{ code: 'INFERENCE_TIMEOUT', retryable: true }]);
  assert.equal('decision' in result || 'allow' in result, false);
});

test('the executed detector scope comes from the response, including failed detectors', () => {
  // 실제 rtx4090-24gb 구성의 통합 평가 응답: Prompt 검사기 없이 completed다.
  const localOnly = interpretRiskAssessment(assessment({
    categories: [
      { code: null, family: 'data_exposure', detected: false, confidence: null, source_model: 'pii-protection', label: null, span_count: 0 },
      { code: null, family: 'data_exposure', detected: false, confidence: null, source_model: 'secret-scanner', label: null, span_count: 0 },
    ],
  })).result;
  assert.equal(localOnly.verdict, 'no_signal');
  assert.deepEqual(localOnly.detectors.map((detector) => detector.label), ['PII', 'Secret']);

  const promptFailed = interpretRiskAssessment(assessment({
    status: 'partial',
    assessment_complete: false,
    system_signal_detected: true,
    attention_required: true,
    strongest_code: 'INFERENCE_TIMEOUT',
    categories: [{ code: null, family: 'data_exposure', detected: false, confidence: null, source_model: 'pii-protection', label: null, span_count: 0 }],
    system_signals: [{ code: 'INFERENCE_TIMEOUT', detected: true, retryable: true, message: 'timeout', source: 'risk-prompt' }],
  })).result;
  assert.deepEqual(promptFailed.detectors, [
    { source: 'pii-protection', label: 'PII', failed: false },
    { source: 'risk-prompt', label: 'Prompt Injection', failed: true },
  ]);
});

test('responses outside the signal contract are reported as invalid', () => {
  assert.match(interpretRiskAssessment({ status: 'completed' }).error, /형식/);
  assert.match(interpretRiskAssessment(null).error, /형식/);
});
