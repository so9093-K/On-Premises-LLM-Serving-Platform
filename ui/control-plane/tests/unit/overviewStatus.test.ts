import { describe, expect, it } from 'vitest';

import { unmanagedModelSummary } from '../../src/overviewSignals';
import { capabilityPresentation } from '../../src/uiText';

describe('전환 API가 없는 배포의 운영 개요', () => {
  it('Core는 외부 모델 관리가 아니라 모델이 없는 상태다', () => {
    expect(unmanagedModelSummary('none', 'static', 'external')).toContain('메인 모델 없음');
    expect(capabilityPresentation('model_switching', ['risk'], 'external', 'none').status).toBe('제공하지 않음');
    expect(capabilityPresentation('runtime_control', ['risk'], 'external', 'none').status).toBe('제공하지 않음');
  });

  it('실제로 외부가 관리하는 Runtime은 기존 운영 경계를 설명한다', () => {
    expect(unmanagedModelSummary('vllm-cuda', 'static', 'external')).toContain('외부');
    expect(capabilityPresentation('runtime_control', ['chat'], 'external', 'vllm-cuda').status).toBe('외부 관리');
  });
});
