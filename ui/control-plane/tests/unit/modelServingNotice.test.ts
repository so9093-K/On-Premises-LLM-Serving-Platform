import { describe, expect, it } from 'vitest';
import { modelRuntimeLabel, modelServingNotice } from '../../src/uiText';

describe('공개 모델 변경과 제어 상태의 사용자 계약', () => {
  it('계약이 활성 상태이거나 외부 Runtime에 정책 정보가 없을 때 요청을 제한하지 않는다', () => {
    expect(modelServingNotice('active')).toBeNull();
    expect(modelServingNotice(undefined)).toBeNull();
  });

  it('Controller 장애·요청 Gate 차단·미검증을 정상 상태로 표시하지 않는다', () => {
    for (const status of ['controller_unavailable', 'gate_closed', 'unverified', 'future_state']) {
      const notice = modelServingNotice(status);
      expect(notice).not.toBeNull();
    }
    expect(modelRuntimeLabel('unknown')).toBe('실행 엔진 확인 불가');
  });
});
