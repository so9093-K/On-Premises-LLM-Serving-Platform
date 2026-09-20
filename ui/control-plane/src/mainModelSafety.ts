import type {
  MainModelOperationResponse,
  MainModelProfile,
  MainModelSwitchRequest,
} from './api';

type MainModelOperationProgressState = 'complete' | 'current' | 'pending' | 'failed';

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
    description: '고정된 model/revision snapshot과 실행 준비 상태를 확인합니다.',
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
    description: '선택한 profile의 image와 resource policy로 런타임을 시작합니다.',
  },
  {
    stage: 'validating',
    label: '런타임 검증',
    description: 'health, model identity와 profile capability canary를 확인합니다.',
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
    description: '전환이 완료되지 않았습니다. 오류와 현재 control state를 확인하세요.',
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
    description: 'Controller가 보고한 현재 operation stage입니다.',
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
    ? `Override · ${profile.resource_variant}`
    : 'Reference policy';
}

export function mainModelProfileRequiresConfirmation(profile: MainModelProfile): boolean {
  return profile.qualification.status !== 'verified';
}

export function mainModelProfileSwitchable(profile: MainModelProfile): boolean {
  return profile.active !== true && profile.compatibility.status !== 'incompatible';
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
