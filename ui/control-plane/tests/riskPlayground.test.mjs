import assert from 'node:assert/strict';
import test from 'node:test';

import {
  availableRiskChecks,
  availableRiskExamples,
  buildRiskRequest,
  interpretRiskAssessment,
  MAX_RISK_PROMPT_CHARACTERS,
  RISK_EXAMPLES,
} from '../src/riskPlayground.ts';

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
  const core = availableRiskChecks(['risk']);
  assert.deepEqual(core.map((check) => check.id), ['pii', 'secret', 'assessment']);
  assert.equal(availableRiskExamples(core).some((example) => example.check === 'prompt'), false);
  const dynamic = availableRiskChecks(['chat', 'risk', 'prompt_detection']);
  assert.deepEqual(dynamic.map((check) => check.id), ['pii', 'secret', 'prompt', 'assessment']);
  assert.deepEqual(availableRiskChecks(['chat']), []);
});

test('every example targets a known check and uses synthetic data', () => {
  const checks = new Set(availableRiskChecks(['risk', 'prompt_detection']).map((check) => check.id));
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

test('responses outside the signal contract are reported as invalid', () => {
  assert.match(interpretRiskAssessment({ status: 'completed' }).error, /형식/);
  assert.match(interpretRiskAssessment(null).error, /형식/);
});
