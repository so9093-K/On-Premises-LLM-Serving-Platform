import type { MainModelSwitchRequest } from './api';

export type ExecutionPolicy = NonNullable<MainModelSwitchRequest['execution_policy']>;

export const executionPolicyPresentation: Record<ExecutionPolicy, { label: string; description: string }> = {
  fallback: {
    label: 'GPU 우선 · CPU 복구',
    description: 'GPU를 사용할 수 없으면 CPU로 복구합니다. GPU 복귀는 직접 선택합니다.',
  },
  automatic: {
    label: '자동 전환',
    description: 'GPU 여유와 상태에 따라 CPU 복구와 GPU 복귀를 자동으로 수행합니다.',
  },
  cpu: {
    label: 'CPU 고정',
    description: 'CPU 모델을 유지하며 GPU로 자동 전환하지 않습니다.',
  },
  gpu: {
    label: 'GPU 고정',
    description: '선택한 GPU 모델을 유지합니다. GPU 실패 시 CPU로 자동 전환하지 않습니다.',
  },
};

export function isRecoveringPolicy(mode: ExecutionPolicy | undefined): boolean {
  return mode === 'fallback' || mode === 'automatic';
}
