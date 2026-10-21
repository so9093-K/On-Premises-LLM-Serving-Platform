import riskExamples from './playgroundRiskExamples.json' with { type: 'json' };

// Risk 작업 화면의 순수 로직. 탐지기는 위험 신호만 제공하며 허용·차단을 결정하지 않는다
// (ADR-0002). 화면은 응답의 완료 여부와 신호를 구분해 보여 주고 최종 판정을 만들지 않는다.
export type RiskCheckId = 'pii' | 'secret' | 'prompt' | 'assessment';

export type RiskCheck = {
  id: RiskCheckId;
  path: string;
  label: string;
  description: string;
  // 이 검사를 공개하는 deployment feature다. Prompt 검사는 모델 Runtime이 필요하다.
  feature: 'risk' | 'prompt_detection';
};

// Prompt 검사기는 모델 Runtime이다. Target feature는 선언일 뿐이고, 자원 정책으로 비활성인
// 구성에서는 Gateway가 이 capability의 공개 모델을 /v1/models에서 제외한다.
export const PROMPT_DETECTOR_CAPABILITY = 'risk.prompt_attack_signal';

type CapabilityModel = { capabilities: readonly string[] };

export const RISK_CHECKS: readonly RiskCheck[] = [
  {
    id: 'pii',
    path: '/v1/risk/detectors/pii/assessments',
    label: 'PII 탐지',
    description: '이메일·전화번호·한국형 식별자·IP 주소',
    feature: 'risk',
  },
  {
    id: 'secret',
    path: '/v1/risk/detectors/secret/assessments',
    label: 'Secret 탐지',
    description: 'API Key·자격 증명·DB 접속 정보',
    feature: 'risk',
  },
  {
    id: 'prompt',
    path: '/v1/risk/detectors/prompt/assessments',
    label: 'Prompt Injection 탐지',
    description: '지시 무시·시스템 프롬프트 유출 시도',
    feature: 'prompt_detection',
  },
  {
    id: 'assessment',
    path: '/v1/risk/assessments',
    label: '통합 Risk 평가',
    description: '활성 검사기를 순서대로 실행',
    feature: 'risk',
  },
];

export type RiskExample = {
  id: string;
  title: string;
  description: string;
  check: RiskCheckId;
  prompt: string;
  expected_codes: string[];
};

// 실제 개인정보·운영 Secret 대신 합성 값만 쓴다. 로컬 검출기가 기대 신호를 실제로
// 반환하는지는 Python 테스트가 같은 파일로 검증한다.
export const RISK_EXAMPLES: readonly RiskExample[] = riskExamples as RiskExample[];

const DETECTOR_CHECK_LABELS: Record<RiskCheckId, string> = {
  pii: 'PII',
  secret: 'Secret',
  prompt: 'Prompt Injection',
  assessment: '통합',
};

function promptDetectorPublished(models: readonly CapabilityModel[]): boolean {
  return models.some((model) => model.capabilities.includes(PROMPT_DETECTOR_CAPABILITY));
}

export function availableRiskChecks(features: readonly string[], models: readonly CapabilityModel[]): RiskCheck[] {
  return RISK_CHECKS.filter((check) => features.includes(check.feature)
    && (check.id !== 'prompt' || promptDetectorPublished(models)));
}

// Target은 Prompt 검사를 선언했지만 현재 구성에서 공개하지 않는 경우다.
export function promptDetectorInactive(features: readonly string[], models: readonly CapabilityModel[]): boolean {
  return features.includes('prompt_detection') && !promptDetectorPublished(models);
}

// 통합 평가 설명은 이 화면이 실행 가능하다고 판단한 검사기만 나열한다.
export function riskCheckDescription(check: RiskCheck, checks: readonly RiskCheck[]): string {
  if (check.id !== 'assessment') return check.description;
  const order = checks.filter((item) => item.id !== 'assessment').map((item) => DETECTOR_CHECK_LABELS[item.id]);
  return `활성 검사기를 ${order.join(' → ')} 순서로 실행`;
}

export function availableRiskExamples(checks: readonly RiskCheck[]): RiskExample[] {
  const ids = new Set(checks.map((check) => check.id));
  return RISK_EXAMPLES.filter((example) => ids.has(example.check));
}

// Gateway는 Python 문자열 길이(code point)로 제한한다.
export const MAX_RISK_PROMPT_CHARACTERS = 20_000;

export function riskPromptLength(prompt: string): number {
  return [...prompt].length;
}

export function buildRiskRequest(prompt: string): { body: { prompt: string }; error: null } | { body: null; error: string } {
  if (!prompt.trim()) return { body: null, error: '검사할 텍스트를 입력하세요.' };
  const length = riskPromptLength(prompt);
  if (length > MAX_RISK_PROMPT_CHARACTERS) {
    return { body: null, error: `입력은 ${MAX_RISK_PROMPT_CHARACTERS.toLocaleString()}자 이하여야 합니다. 현재 ${length.toLocaleString()}자입니다.` };
  }
  return { body: { prompt }, error: null };
}

const RISK_CODE_LABELS: Record<string, string> = {
  A1: 'Prompt Injection',
  A2: 'Prompt Leaking',
  D1: '한국형 식별자',
  D2: '이메일·전화번호',
  D4: 'API Key·자격 증명',
  D5: 'IP 주소·인프라 정보',
};

const SYSTEM_SIGNAL_LABELS: Record<string, string> = {
  INFERENCE_TIMEOUT: '검사 시간 초과',
  INFERENCE_QUEUE_TIMEOUT: '검사 대기 시간 초과',
  INFERENCE_ERROR: '검사 실행 오류',
  PARSE_ERROR: '검사 결과 해석 실패',
  TRUNCATED_INPUT: '입력 일부만 검사',
};

const DETECTOR_SOURCE_LABELS: Record<string, string> = {
  'pii-protection': 'PII',
  'secret-scanner': 'Secret',
  'risk-prompt': 'Prompt Injection',
};

export const PROMPT_DETECTOR_SOURCE = 'risk-prompt';

export function riskCodeLabel(code: string): string {
  return RISK_CODE_LABELS[code] ?? code;
}

export function systemSignalLabel(code: string): string {
  return SYSTEM_SIGNAL_LABELS[code] ?? code;
}

export type RiskVerdict = 'signal_detected' | 'no_signal' | 'incomplete';

export type RiskSignal = {
  code: string;
  family: string;
  label: string | null;
  spanCount: number | null;
  source: string | null;
};

export type RiskDetectorRun = {
  source: string;
  label: string;
  // 실행했지만 시스템 신호를 남긴 검사기다. 완료된 검사로 세지 않는다.
  failed: boolean;
};

export type RiskInterpretation = {
  verdict: RiskVerdict;
  status: string;
  // status=completed와 assessment_complete=true가 모두 참일 때만 완료다.
  complete: boolean;
  strongestCode: string | null;
  message: string;
  signals: RiskSignal[];
  systemSignals: { code: string; retryable: boolean }[];
  // 응답의 source_model·source에서 확인한 실제 실행 검사기다. 화면의 가용성 판단이
  // 실제 구성과 달라도 결과의 검사 범위는 응답이 근거가 된다.
  detectors: RiskDetectorRun[];
};

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : {};
}

export function interpretRiskAssessment(
  payload: unknown,
): { result: RiskInterpretation; error: null } | { result: null; error: string } {
  const body = record(payload);
  const status = body.status;
  if (typeof status !== 'string' || !Array.isArray(body.categories) || !Array.isArray(body.system_signals)
    || typeof body.assessment_complete !== 'boolean' || typeof body.risk_detected !== 'boolean'
    || typeof body.system_signal_detected !== 'boolean') {
    return { result: null, error: 'Risk 응답 형식이 올바르지 않습니다.' };
  }
  const complete = status === 'completed' && body.assessment_complete === true;
  const signals = body.categories
    .map(record)
    .filter((category) => category.detected === true && typeof category.code === 'string')
    .map((category) => ({
      code: category.code as string,
      family: typeof category.family === 'string' ? category.family : '',
      label: typeof category.label === 'string' ? category.label : null,
      spanCount: Number.isInteger(category.span_count) ? category.span_count as number : null,
      source: typeof category.source_model === 'string' ? category.source_model : null,
    }));
  const detectedSystemSignals = body.system_signals
    .map(record)
    .filter((signal) => signal.detected === true && typeof signal.code === 'string');
  const systemSignals = detectedSystemSignals
    .map((signal) => ({ code: signal.code as string, retryable: signal.retryable === true }));
  const failedSources = new Set(detectedSystemSignals.map((signal) => signal.source));
  const sources: string[] = [];
  for (const source of [
    ...body.categories.map((category) => record(category).source_model),
    ...body.system_signals.map((signal) => record(signal).source),
  ]) {
    if (typeof source === 'string' && source && !sources.includes(source)) sources.push(source);
  }
  // API Reference 6.6: 완료됐고 시스템 신호와 위험 신호가 모두 없을 때만 미탐지다.
  // HTTP 200이나 risk_detected=false 하나만으로 미탐지로 해석하지 않는다.
  const verdict: RiskVerdict = body.risk_detected
    ? 'signal_detected'
    : complete && !body.system_signal_detected ? 'no_signal' : 'incomplete';
  return {
    result: {
      verdict,
      status,
      complete,
      strongestCode: typeof body.strongest_code === 'string' ? body.strongest_code : null,
      message: typeof body.message === 'string' ? body.message : '',
      signals,
      systemSignals,
      detectors: sources.map((source) => ({
        source,
        label: DETECTOR_SOURCE_LABELS[source] ?? source,
        failed: failedSources.has(source),
      })),
    },
    error: null,
  };
}
