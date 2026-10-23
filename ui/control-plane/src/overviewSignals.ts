export type OverviewSignalTone = 'info' | 'warning' | 'danger';

export type OverviewSignal = {
  key: string;
  tone: OverviewSignalTone;
  title: string;
  detail: string;
};

type MainModelSnapshot = {
  gate: string;
  runtime_state: string;
  state_recovery_error?: string | null;
  observed_runtime?: {
    status: string;
    health?: string | null;
    error?: string | null;
  } | null;
};

// stateLabel은 raw 상태 값을 운영자 어휘로 바꾼다(uiText.runtimeStateLabel).
export function mainModelOverviewSignals(
  mainModel: MainModelSnapshot | null | undefined,
  stateLabel: (state: string) => string,
): OverviewSignal[] {
  if (!mainModel) return [];

  const signals: OverviewSignal[] = [];
  if (mainModel.state_recovery_error) {
    signals.push({
      key: 'main-model-state-recovery',
      tone: 'danger',
      title: '메인 모델 상태 복구 확인 필요',
      detail: mainModel.state_recovery_error,
    });
  }

  if (mainModel.runtime_state === 'stopped') {
    signals.push({
      key: 'main-model-stopped',
      tone: 'info',
      title: '메인 모델이 중지된 상태입니다.',
      detail: '의도적으로 중지한 상태일 수 있으므로 장애로 단정하지 않습니다. 필요하면 메인 모델 화면에서 현재 상태와 최근 작업을 확인하세요.',
    });
    return signals;
  }

  if (mainModel.gate !== 'open') {
    signals.push({
      key: 'main-model-gate',
      tone: 'warning',
      title: '메인 모델이 새 요청을 받지 않는 상태입니다.',
      detail: '런타임은 실행 중이지만 새 추론 요청을 허용하는 상태가 아닙니다.',
    });
  }

  const observed = mainModel.observed_runtime;
  if (!observed) {
    signals.push({
      key: 'main-model-observation',
      tone: 'warning',
      title: '메인 모델 런타임의 실제 상태를 확인할 수 없습니다.',
      detail: '저장된 제어 상태만으로 실제 서빙 준비 상태를 가정하지 않습니다.',
    });
    return signals;
  }

  if (observed.status !== 'ready' || observed.health !== 'healthy') {
    const error = observed.error ? ` · ${observed.error}` : '';
    signals.push({
      key: 'main-model-observed-state',
      tone: 'warning',
      title: '메인 모델 런타임 상태를 확인하세요.',
      detail: `실제 상태 ${stateLabel(observed.status)} · 상태 확인 ${stateLabel(observed.health ?? 'unknown')}${error}`,
    });
  }

  return signals;
}

/**
 * 전환 API의 부재는 외부 관리나 모델 준비 완료를 의미하지 않는다.
 * 실제 모델 기동/응답은 해당 Target의 기존 lifecycle에서 확인한다.
 */
export function unmanagedModelSummary(
  runtimeBackend: string,
  controlMode: string,
  lifecycleOwner: string,
): string {
  if (runtimeBackend === 'none') return '메인 모델 없음 · Risk 등 기본 서비스 운영';
  if (controlMode === 'managed_cpu') return 'CPU · 플랫폼 Compose 관리 · 준비 상태 별도 확인';
  if (lifecycleOwner === 'external') return '외부 / 네이티브 모델 관리 · 상태 별도 확인';
  return '플랫폼 관리 · 모델 전환 제어 없음 · 상태 별도 확인';
}
