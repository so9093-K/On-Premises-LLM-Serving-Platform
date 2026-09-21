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

export function mainModelOverviewSignals(
  mainModel: MainModelSnapshot | null | undefined,
): OverviewSignal[] {
  if (!mainModel) return [];

  const signals: OverviewSignal[] = [];
  if (mainModel.state_recovery_error) {
    signals.push({
      key: 'main-model-state-recovery',
      tone: 'danger',
      title: 'Main Model state recovery 확인 필요',
      detail: mainModel.state_recovery_error,
    });
  }

  if (mainModel.runtime_state === 'stopped') {
    signals.push({
      key: 'main-model-stopped',
      tone: 'info',
      title: 'Main Model이 stopped 상태입니다.',
      detail: '의도적인 stop일 수 있으므로 장애로 판정하지 않습니다. 필요하면 Main Model 화면에서 현재 state와 최근 operation을 확인하세요.',
    });
    return signals;
  }

  if (mainModel.gate !== 'open') {
    signals.push({
      key: 'main-model-gate',
      tone: 'warning',
      title: 'Main Model gate가 닫혀 있습니다.',
      detail: 'runtime_state는 active이지만 새 inference 요청을 받는 gate가 open이 아닙니다.',
    });
  }

  const observed = mainModel.observed_runtime;
  if (!observed) {
    signals.push({
      key: 'main-model-observation',
      tone: 'warning',
      title: 'Main Model runtime 관측값이 없습니다.',
      detail: '저장된 control state만으로 실제 serving readiness를 가정하지 않습니다.',
    });
    return signals;
  }

  if (observed.status !== 'ready' || observed.health !== 'healthy') {
    const error = observed.error ? ` · ${observed.error}` : '';
    signals.push({
      key: 'main-model-observed-state',
      tone: 'warning',
      title: 'Main Model runtime 관측 상태를 확인하세요.',
      detail: `status=${observed.status}, health=${observed.health ?? 'unknown'}${error}`,
    });
  }

  return signals;
}
