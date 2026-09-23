export type UiLocale = 'ko-KR' | 'en-US';

export const DEFAULT_UI_LOCALE: UiLocale = 'ko-KR';

const messages = {
  'nav.overview': { 'ko-KR': '개요', 'en-US': 'Overview' },
  'nav.runtimes': { 'ko-KR': '런타임', 'en-US': 'Runtimes' },
  'nav.mainModel': { 'ko-KR': '메인 모델', 'en-US': 'Main Model' },
  'nav.configuration': { 'ko-KR': '설정', 'en-US': 'Configuration' },
  'nav.activity': { 'ko-KR': '활동', 'en-US': 'Activity' },
  'common.loading': { 'ko-KR': 'Control Plane 정보를 불러오는 중입니다.', 'en-US': 'Loading Control Plane information.' },
  'common.refresh': { 'ko-KR': '새로고침', 'en-US': 'Refresh' },
  'common.refreshing': { 'ko-KR': '새로고침 중…', 'en-US': 'Refreshing…' },
  'link.apiDocs': { 'ko-KR': 'API 문서', 'en-US': 'API Docs' },
} as const;

export type UiTextKey = keyof typeof messages;

export function t(key: UiTextKey, locale: UiLocale = DEFAULT_UI_LOCALE): string {
  return messages[key][locale] ?? messages[key]['en-US'];
}

export function deploymentTargetLabel(target: string, fallback: string): string {
  const labels: Record<string, string> = {
    'linux-nvidia-dynamic': 'Linux + NVIDIA · 플랫폼 관리형',
    'linux-nvidia-static': 'Linux + NVIDIA · 외부 메인 런타임',
    'macos-metal-static': 'macOS + Metal · 외부 메인 런타임',
  };
  return labels[target] ?? fallback;
}

export function lifecycleOwnerLabel(owner: string): string {
  if (owner === 'platform') return '플랫폼';
  if (owner === 'external') return '외부 / 네이티브';
  return owner;
}

export function controlModeLabel(mode: string): string {
  if (mode === 'runtime_controller') return '플랫폼 런타임 제어';
  if (mode === 'static') return '외부 관리';
  return mode;
}

export function implementationStatusLabel(status: string): string {
  if (status === 'implemented') return '구현됨';
  if (status === 'planned') return '계획됨';
  return status;
}

export function qualificationStatusLabel(status: string): string {
  if (status === 'verified') return '검증됨';
  if (status === 'unverified') return '미검증';
  return status;
}

export function runtimeStateLabel(state: string): string {
  const labels: Record<string, string> = {
    active: '실행 중',
    starting: '시작 중',
    stopped: '중지됨',
    ready: '준비됨',
    unavailable: '사용할 수 없음',
    created: '컨테이너 생성됨',
    running: '실행 중',
    healthy: '정상',
    open: '요청 허용',
    closed: '요청 차단',
    verified: '검증 완료',
    noop: '변경 없음',
    rejected: '거부됨',
    pending: '진행 중',
    failed: '실패',
    interrupted: '중단됨',
    recovered_after_restart: '재시작 후 복구',
  };
  return labels[state] ?? state;
}

export function accessProfileLabel(profile: string): string {
  const labels: Record<string, string> = {
    local: '로컬',
    private: '사설망',
    edge: '외부 공개',
    'legacy/custom': '사용자 지정',
  };
  return labels[profile] ?? profile;
}

export function yesNoLabel(value: boolean): string {
  return value ? '예' : '아니요';
}

export function sourceLabel(source: string): string {
  const labels: Record<string, string> = {
    repository: '저장소 기본값',
    operator: '운영자 설정',
    deployment: '배포 환경',
    runtime: '런타임',
    secret: '비밀값',
  };
  return labels[source] ?? source;
}

export function riskLabel(risk: string): string {
  const labels: Record<string, string> = {
    low: '낮음',
    medium: '보통',
    high: '높음',
    critical: '매우 높음',
  };
  return labels[risk] ?? risk;
}

export type CapabilityTone = 'green' | 'blue' | 'grey';

export type CapabilityPresentation = {
  key: string;
  label: string;
  status: string;
  detail: string;
  tone: CapabilityTone;
};

export const CAPABILITY_KEYS = [
  'chat',
  'embeddings',
  'retrieval',
  'risk',
  'gpu_admission',
  'model_switching',
  'runtime_control',
] as const;

const CAPABILITY_LABELS: Record<string, string> = {
  chat: '채팅',
  embeddings: '임베딩',
  retrieval: '검색',
  risk: '위험 신호',
  gpu_admission: 'GPU 실행 가능성',
  model_switching: '메인 모델 전환',
  runtime_control: '런타임 제어',
};

const EXTERNAL_MANAGEMENT_CAPABILITIES = new Set([
  'gpu_admission',
  'model_switching',
  'runtime_control',
]);

export function capabilityPresentation(
  feature: string,
  enabledFeatures: readonly string[],
  lifecycleOwner: string,
): CapabilityPresentation {
  const enabled = enabledFeatures.includes(feature);
  if (enabled) {
    return {
      key: feature,
      label: CAPABILITY_LABELS[feature] ?? feature,
      status: '사용 가능',
      detail: '이 실행 환경에서 Control Plane이 지원합니다.',
      tone: 'green',
    };
  }
  if (lifecycleOwner === 'external' && EXTERNAL_MANAGEMENT_CAPABILITIES.has(feature)) {
    return {
      key: feature,
      label: CAPABILITY_LABELS[feature] ?? feature,
      status: '외부 관리',
      detail: '이 실행 환경에서는 외부 또는 네이티브 런타임이 관리합니다.',
      tone: 'blue',
    };
  }
  return {
    key: feature,
    label: CAPABILITY_LABELS[feature] ?? feature,
    status: '제공하지 않음',
    detail: '현재 실행 환경의 지원 기능에 포함되지 않습니다.',
    tone: 'grey',
  };
}

export function formatFraction(value: number | null | undefined): string {
  return typeof value === 'number' ? value.toFixed(2) : '—';
}

export function formatPercent(value: number | null | undefined): string {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : '—';
}
