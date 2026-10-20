import type {
  MainModelOperationResponse,
  MainModelProfile,
  MainModelSwitchRequest,
} from './api';

type MainModelOperationProgressState = 'complete' | 'current' | 'pending' | 'failed';

export const MAIN_MODEL_TERMINAL_QUERY_KEYS = [
  ['main-model', 'status'],
  ['main-model', 'profiles'],
  ['public-models'],
] as const;

export type MainModelOperationProgressStep = {
  stage: string;
  label: string;
  description: string;
  state: MainModelOperationProgressState;
};

const MAIN_MODEL_SWITCH_FLOW = [
  {
    stage: 'pending',
    label: '요청 접수',
    description: '전환 요청이 접수되어 실행 순서를 기다리고 있습니다.',
  },
  {
    stage: 'preparing',
    label: '대상 모델 준비',
    description: '고정된 모델/revision snapshot과 실행 준비 상태를 확인합니다.',
  },
  {
    stage: 'draining',
    label: '기존 요청 정리',
    description: '새 요청 gate를 닫고 진행 중인 요청이 안전하게 끝나도록 기다립니다.',
  },
  {
    stage: 'stopping',
    label: '현재 런타임 전환 준비',
    description: '현재 런타임을 교체하기 위한 경계에 진입합니다.',
  },
  {
    stage: 'starting',
    label: '대상 런타임 시작',
    description: '선택한 프로필의 이미지와 리소스 정책으로 런타임을 시작합니다.',
  },
  {
    stage: 'validating',
    label: '런타임 검증',
    description: '상태, 모델 identity와 프로필 기능 canary를 확인합니다.',
  },
] as const;

const SPECIAL_STAGE_PRESENTATION: Record<string, { label: string; description: string }> = {
  rolling_back: {
    label: '이전 프로필 복구',
    description: '대상 런타임 전환이 실패해 마지막 정상 프로필을 복구하고 검증하고 있습니다.',
  },
  completed: {
    label: '전환 완료',
    description: '대상 프로필 검증을 통과했고 새 상태가 마지막 정상 상태로 기록되었습니다.',
  },
  failed: {
    label: '전환 실패',
    description: '전환이 완료되지 않았습니다. 오류와 현재 제어 상태를 확인하세요.',
  },
  rollback_failed: {
    label: '복구 실패',
    description: '대상 전환과 이전 프로필 복구가 모두 완료되지 않아 gate가 닫힌 상태일 수 있습니다.',
  },
};

export function mainModelOperationStagePresentation(stage: string): {
  label: string;
  description: string;
} {
  const flow = MAIN_MODEL_SWITCH_FLOW.find((item) => item.stage === stage);
  if (flow) return { label: flow.label, description: flow.description };
  return SPECIAL_STAGE_PRESENTATION[stage] ?? {
    label: stage,
    description: 'Controller가 보고한 현재 작업 단계입니다.',
  };
}

export function mainModelOperationProgress(
  operation: Pick<MainModelOperationResponse, 'stage' | 'status'>,
): MainModelOperationProgressStep[] {
  if (operation.status === 'completed') {
    return MAIN_MODEL_SWITCH_FLOW.map((item) => ({ ...item, state: 'complete' as const }));
  }
  if (operation.stage === 'rolling_back' || operation.status === 'rollback_failed') {
    const presentation = mainModelOperationStagePresentation(
      operation.status === 'rollback_failed' ? 'rollback_failed' : 'rolling_back',
    );
    return [{
      stage: operation.stage,
      ...presentation,
      state: operation.status === 'rollback_failed' ? 'failed' : 'current',
    }];
  }
  const currentIndex = MAIN_MODEL_SWITCH_FLOW.findIndex((item) => item.stage === operation.stage);
  if (operation.status === 'failed') {
    if (currentIndex < 0) {
      const presentation = mainModelOperationStagePresentation(operation.stage);
      return [{ stage: operation.stage, ...presentation, state: 'failed' }];
    }
    return MAIN_MODEL_SWITCH_FLOW.map((item, index) => ({
      ...item,
      state: index < currentIndex ? 'complete' : index === currentIndex ? 'failed' : 'pending',
    }));
  }

  if (currentIndex < 0) {
    const presentation = mainModelOperationStagePresentation(operation.stage);
    return [{ stage: operation.stage, ...presentation, state: 'current' }];
  }
  return MAIN_MODEL_SWITCH_FLOW.map((item, index) => ({
    ...item,
    state: index < currentIndex ? 'complete' : index === currentIndex ? 'current' : 'pending',
  }));
}

export function mainModelResourcePolicyLabel(
  profile: { resource_variant?: string | null },
): string {
  return profile.resource_variant
    ? `GPU 정책 override · ${profile.resource_variant}`
    : '기준 리소스 정책';
}

type MainModelComparableProfile = {
  compatibility: { status: string };
  qualification: { status: string };
  capabilities: { deployed_input: readonly string[] };
  resource_variant?: string | null;
  vram_fraction: number;
};

export type MainModelTokenLimits = {
  contextTokens: number | null;
  maxOutputTokens: number | null;
};

function positiveInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : null;
}

// profile의 Gateway 정책이 공개 API에 약속하는 토큰 한도다. 전환 판단에 필요한 핵심 차이다.
export function mainModelTokenLimits(profile: { gateway_policy: object }): MainModelTokenLimits {
  const policy = profile.gateway_policy as Record<string, unknown>;
  const limits = (policy.request_limits ?? {}) as Record<string, unknown>;
  return {
    contextTokens: positiveInteger(limits.max_model_len),
    maxOutputTokens: positiveInteger(policy.max_output_tokens),
  };
}

export function formatTokenLimits(limits: MainModelTokenLimits): string {
  const format = (value: number | null) => (value === null ? '—' : value.toLocaleString('ko-KR'));
  return `${format(limits.contextTokens)} / ${format(limits.maxOutputTokens)}`;
}

export type MainModelProfileImpact = {
  addedInputs: string[];
  removedInputs: string[];
  resourcePolicyChanged: boolean;
  vramFractionDelta: number;
  compatibilityChanged: boolean;
  qualificationChanged: boolean;
};

export function mainModelProfileImpact(
  current: MainModelComparableProfile,
  target: MainModelComparableProfile,
): MainModelProfileImpact {
  const currentInputs = new Set(current.capabilities.deployed_input);
  const targetInputs = new Set(target.capabilities.deployed_input);
  return {
    addedInputs: target.capabilities.deployed_input.filter((item) => !currentInputs.has(item)),
    removedInputs: current.capabilities.deployed_input.filter((item) => !targetInputs.has(item)),
    resourcePolicyChanged:
      mainModelResourcePolicyLabel(current) !== mainModelResourcePolicyLabel(target)
      || current.vram_fraction !== target.vram_fraction,
    vramFractionDelta: target.vram_fraction - current.vram_fraction,
    compatibilityChanged: current.compatibility.status !== target.compatibility.status,
    qualificationChanged: current.qualification.status !== target.qualification.status,
  };
}

export function mainModelProfileRequiresConfirmation(profile: MainModelProfile): boolean {
  return profile.qualification.status !== 'verified';
}

export type MainModelPreflightView = {
  label: string;
  description: string;
  color: 'green' | 'orange' | 'red' | 'grey';
};

// 백엔드 GPU Admission과 정책 검사를 UI에서 다시 계산하지 않는다.
// 응답이 없거나 새 상태를 해석할 수 없다면 "가능"으로 추측하지 않는다.
export function mainModelPreflightView(profile: MainModelProfile): MainModelPreflightView {
  const preflight = profile.switch_preflight;
  if (!preflight) return {
    label: '판단 불가', description: 'GPU 예약 예산 정보를 받지 못했습니다. 새로고침 후 다시 확인하세요.', color: 'orange',
  };
  switch (preflight.status) {
    case 'current':
      return { label: '현재 사용 중', description: '현재 활성 프로필입니다.', color: 'green' };
    case 'fits':
      return { label: '예산 검사 통과', description: 'GPU 예약 정책을 통과했습니다. 실제 모델 적재와 추론 성공은 시작 후 검증합니다.', color: 'green' };
    case 'needs_stop':
      return { label: '자원 정리 필요', description: '다른 Runtime을 먼저 중지해야 합니다. 전환 검토에서 대상을 확인하세요.', color: 'orange' };
    case 'infeasible':
      return { label: 'GPU 예산 부족', description: '현재 GPU 예약 상한에서 실행에 필요한 예산을 확보할 수 없습니다.', color: 'red' };
    case 'blocked':
      if (preflight.reason_code === 'MODEL_SWITCH_IN_PROGRESS') {
        return { label: '전환 진행 중', description: '다른 모델 전환 작업이 완료된 뒤 다시 검토하세요.', color: 'orange' };
      }
      if (preflight.reason_code === 'MODEL_PROFILE_HOST_VARIANT_UNSUPPORTED') {
        return { label: '리소스 정책 불일치', description: '서버에서 명시한 리소스 정책 Override를 이 프로필이 선언하지 않습니다.', color: 'red' };
      }
      if (preflight.reason_code === 'MODEL_PROFILE_LOCKED') {
        return { label: '전환 잠김', description: '현재 배포에서는 Main Model 전환 권한을 제공하지 않습니다.', color: 'grey' };
      }
      return { label: '기술적 전환 불가', description: '현재 배포·Runtime 조합에서 이 프로필로 전환할 수 없습니다.', color: 'red' };
    default:
      return { label: '판단 불가', description: 'GPU 예약 예산 또는 Runtime 관측을 확인할 수 없습니다. 실행 가능으로 간주하지 않습니다.', color: 'orange' };
  }
}

export function mainModelProfileSwitchable(profile: MainModelProfile): boolean {
  return profile.active !== true
    && profile.compatibility.status !== 'incompatible'
    && profile.switch_preflight?.status === 'fits';
}

export function mainModelSwitchRequest(
  profile: MainModelProfile,
  confirmed: boolean,
): MainModelSwitchRequest {
  if (!mainModelProfileSwitchable(profile)) {
    throw new Error('selected profile cannot be switched');
  }
  if (mainModelProfileRequiresConfirmation(profile) && !confirmed) {
    throw new Error('selected profile requires explicit confirmation');
  }
  return {
    profile: profile.id,
    confirm_unverified: mainModelProfileRequiresConfirmation(profile),
  };
}

export function isMainModelOperationTerminal(operation: MainModelOperationResponse): boolean {
  return operation.status === 'completed'
    || operation.status === 'failed'
    || operation.status === 'rollback_failed';
}
