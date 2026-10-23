import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, CardBody, CardTitle, Label, Spinner } from '@patternfly/react-core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import {
  fetchMainModel,
  fetchMainModelOperation,
  fetchMainModelProfiles,
  switchMainModel,
  type MainModelOperationResponse,
  type MainModelProfile,
} from './api';
import { executionPolicyPresentation, isRecoveringPolicy, type ExecutionPolicy } from './mainModelExecutionPolicy';
import { apiErrorMessage, isUnauthorized } from './apiFeedback';
import { playgroundPath } from './navigation';
import {
  formatTokenLimits,
  MAIN_MODEL_TERMINAL_QUERY_KEYS,
  mainModelTokenLimits,
  isMainModelOperationTerminal,
  mainModelOperationProgress,
  mainModelOperationStagePresentation,
  mainModelProfileImpact,
  mainModelPreflightView,
  mainModelProfileRequiresConfirmation,
  mainModelPolicySwitchable,
  mainModelResourcePolicyLabel,
  mainModelSwitchRequest,
} from './mainModelSafety';
import { formatPercent, modelRuntimeLabel, runtimeStateLabel, t } from './uiText';

type MainModelPageProps = {
  token: string | null;
  onUnauthorized: () => void;
  chatEnabled: boolean;
};

function compatibilityVariant(status: string): 'green' | 'orange' | 'red' | 'grey' {
  if (status === 'compatible') return 'green';
  if (status === 'incompatible') return 'red';
  if (status === 'unknown') return 'orange';
  return 'grey';
}

function compatibilityLabel(status: string): string {
  if (status === 'compatible') return '호환';
  if (status === 'incompatible') return '호환되지 않음';
  if (status === 'unknown') return '확인 필요';
  return status;
}

function qualificationVariant(status: string): 'green' | 'orange' | 'grey' {
  if (status === 'verified') return 'green';
  if (status === 'unverified') return 'orange';
  return 'grey';
}

function qualificationLabel(status: string): string {
  if (status === 'verified') return '검증됨';
  if (status === 'unverified') return '미검증';
  return status;
}

function inputLabel(value: string): string {
  const labels: Record<string, string> = {
    text: '텍스트',
    image: '이미지',
    audio: '오디오',
    video: '영상',
  };
  return labels[value] ?? value;
}

function inputList(values: readonly string[]): string {
  return values.map(inputLabel).join(', ');
}

function inputImpactLabel(added: string[], removed: string[]): string {
  const parts = [
    added.length ? `추가: ${added.map(inputLabel).join(', ')}` : null,
    removed.length ? `제거: ${removed.map(inputLabel).join(', ')}` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : '변경 없음';
}

function vramImpactLabel(delta: number): string {
  if (Math.abs(delta) < 0.0001) return '변경 없음';
  return `${delta > 0 ? '+' : ''}${delta.toFixed(2)}`;
}

function operationStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: '대기 중',
    running: '진행 중',
    completed: '완료',
    failed: '실패',
    rollback_failed: '복구 실패',
  };
  return labels[status] ?? status;
}

function operationVariant(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'completed') return 'success';
  if (status === 'failed') return 'warning';
  if (status === 'rollback_failed') return 'danger';
  return 'info';
}

function OperationProgress({ operation }: { operation: MainModelOperationResponse }) {
  const presentation = mainModelOperationStagePresentation(operation.stage);
  const steps = mainModelOperationProgress(operation);
  return (
    <>
      <Alert isInline variant={operationVariant(operation.status)} title={presentation.label}>
        <p>{presentation.description}</p>
        {operation.error ? <p><strong>오류:</strong> {operation.error}</p> : null}
        {operation.rollback_error ? <p><strong>복구 오류:</strong> {operation.rollback_error}</p> : null}
      </Alert>
      <ol className="operation-progress" aria-label="메인 모델 전환 진행 단계">
        {steps.map((step) => (
          <li key={step.stage} data-state={step.state}>
            <span className="operation-progress-marker" aria-hidden="true" />
            <div>
              <strong>{step.label}</strong>
              <small>{step.description}</small>
            </div>
          </li>
        ))}
      </ol>
      <dl className="facts operation-facts">
        <dt>작업 ID</dt><dd><code>{operation.id}</code></dd>
        <dt>요청 프로필</dt><dd>{operation.requested_profile}</dd>
        <dt>이전 프로필</dt><dd>{operation.previous_profile ?? '—'}</dd>
        <dt>작업 상태</dt><dd>{operationStatusLabel(operation.status)}</dd>
        <dt>현재 단계</dt><dd>{presentation.label} <code>({operation.stage})</code></dd>
      </dl>
    </>
  );
}

export function MainModelPage({ token, onUnauthorized, chatEnabled }: MainModelPageProps) {
  const queryClient = useQueryClient();
  const [reviewProfileId, setReviewProfileId] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [reviewPolicy, setReviewPolicy] = useState<ExecutionPolicy | undefined>();
  const [actionError, setActionError] = useState<string | null>(null);
  const [operationId, setOperationId] = useState<string | null>(null);
  const authClass = token === null ? 'anonymous' : 'authenticated';

  const statusQuery = useQuery({
    queryKey: ['main-model', 'status', authClass],
    queryFn: () => fetchMainModel(token),
    retry: false,
    refetchInterval: () => document.visibilityState === 'visible' ? 10_000 : false,
    refetchIntervalInBackground: false,
  });
  const profilesQuery = useQuery({
    queryKey: ['main-model', 'profiles', authClass],
    queryFn: () => fetchMainModelProfiles(token),
    retry: false,
    staleTime: 10_000,
    refetchInterval: () => document.visibilityState === 'visible' ? 10_000 : false,
    refetchIntervalInBackground: false,
  });

  useEffect(() => {
    if (isUnauthorized(statusQuery.error) || isUnauthorized(profilesQuery.error)) {
      onUnauthorized();
    }
  }, [onUnauthorized, profilesQuery.error, statusQuery.error]);

  const operationQuery = useQuery({
    queryKey: ['main-model', 'operation', operationId, authClass],
    queryFn: () => {
      if (operationId === null) throw new Error('operation id is required');
      return fetchMainModelOperation(token, operationId);
    },
    enabled: operationId !== null,
    retry: false,
    refetchInterval: (query) => {
      const operation = query.state.data;
      return operation && isMainModelOperationTerminal(operation) ? false : 2_000;
    },
    refetchIntervalInBackground: false,
  });

  useEffect(() => {
    if (isUnauthorized(operationQuery.error)) onUnauthorized();
  }, [onUnauthorized, operationQuery.error]);

  useEffect(() => {
    const operation = operationQuery.data;
    if (!operation || !isMainModelOperationTerminal(operation)) return;
    for (const queryKey of MAIN_MODEL_TERMINAL_QUERY_KEYS) {
      void queryClient.invalidateQueries({ queryKey: [...queryKey] });
    }
  }, [operationQuery.data, queryClient]);

  const profiles = profilesQuery.data?.profiles ?? [];
  const reviewProfile = useMemo(
    () => profiles.find((profile) => profile.id === reviewProfileId) ?? null,
    [profiles, reviewProfileId],
  );

  const switchMutation = useMutation({
    mutationFn: ({ profile, accepted }: { profile: MainModelProfile; accepted: boolean }) =>
      switchMainModel(token, mainModelSwitchRequest(profile, accepted, reviewPolicy)),
    retry: false,
    onMutate: () => setActionError(null),
    onSuccess: async (result) => {
      setOperationId(result.operation_id);
      setReviewProfileId(null);
      setConfirmed(false);
      await queryClient.invalidateQueries({ queryKey: ['main-model', 'status'] });
      await queryClient.invalidateQueries({ queryKey: ['main-model', 'profiles'] });
    },
    onError: (error) => {
      if (isUnauthorized(error)) {
        onUnauthorized();
        return;
      }
      setActionError(apiErrorMessage(error));
    },
  });

  if (statusQuery.isPending || profilesQuery.isPending) {
    return <div className="inline-loading"><Spinner size="lg" aria-label="메인 모델 상태 불러오는 중" /> 메인 모델 상태를 불러오는 중입니다.</div>;
  }
  if (statusQuery.isError) {
    return <Alert isInline variant="danger" title="메인 모델 상태를 불러오지 못했습니다.">{apiErrorMessage(statusQuery.error)}</Alert>;
  }
  if (profilesQuery.isError) {
    return <Alert isInline variant="danger" title="메인 모델 프로필을 불러오지 못했습니다.">{apiErrorMessage(profilesQuery.error)}</Alert>;
  }

  const status = statusQuery.data;
  const active = status.active_profile;
  const observed = status.observed_runtime;
  const locked = status.profile_locked;
  const selection = status.runtime_selection;
  const busy = status.last_operation !== null && !isMainModelOperationTerminal(status.last_operation);
  const selectionReasons: Record<string, string> = {
    CPU_FALLBACK_ACTIVE: "CPU 사용 · GPU 복귀는 수동",
    GPU_START_FAILED: "GPU 시작 또는 응답 검증 실패",
    GPU_DRIVER_INCOMPATIBLE: "GPU 이미지와 드라이버 호환 조건 미충족",
    GPU_DRIVER_COMPATIBILITY_UNKNOWN: "GPU 이미지·드라이버 호환성 확인 필요",
    OPERATOR_SELECTED: "선택한 모델 유지", GPU_BUDGET_BLOCKED: "GPU 예약 여유 대기 · CPU 사용",
    STARTING_CPU: "CPU 준비 중", CPU_BOOTSTRAP: "CPU 준비 중", CPU_RUNTIME_UNAVAILABLE: "CPU 복구 중",
    GPU_SERVING: "GPU 서빙 중", GPU_RECOVERY_PENDING: "GPU 자원 안정성 확인 중",
    GPU_MEMORY_INSUFFICIENT: "GPU 여유 메모리 부족 · CPU 사용",
    GPU_OBSERVATION_UNAVAILABLE: "GPU 자원 관측 불가", GPU_ARTIFACT_UNAVAILABLE: "GPU 이미지 준비 필요 · CPU 사용",
    GPU_FAILURE_BACKOFF: "GPU 재시도 대기 · CPU 사용", GPU_RECOVERY_VALIDATION: "GPU 적재 및 응답 검증 중",
    GPU_HEALTH_OR_MEMORY_PRESSURE: "GPU 장애 또는 메모리 부족 · CPU 복구", OPERATOR_STOPPED: "운영자가 중지함",
    RUNTIME_OBSERVATION_UNAVAILABLE: "런타임 관측 불가",
    GPU_MEMORY_PRESSURE: "GPU 메모리 압력 · 새 요청 차단",
    GPU_RUNTIME_UNHEALTHY: "GPU 런타임 장애 · 새 요청 차단",
    CPU_FALLBACK_PREPARATION_FAILED: "CPU 복구 준비 실패 · 새 요청 차단",
    CPU_FALLBACK_FAILED: "CPU 복구 실패 · 새 요청 차단",
    GPU_REVALIDATION_PENDING: "GPU 안정성 확인 중 · 새 요청 차단",
    GPU_REVALIDATION_FAILED: "GPU 응답 재검증 미완료 · 새 요청 차단",
    GPU_IDENTITY_UNAVAILABLE: "GPU 장치 식별 불가 · CPU 사용",
    GPU_COMPATIBILITY_UNKNOWN: "GPU Compute Capability 확인 필요 · CPU 사용",
    GPU_COMPATIBILITY_UNSUPPORTED: "GPU Compute Capability 조건 미충족 · CPU 사용",
    GPU_RESOURCE_POLICY_UNAVAILABLE: "GPU 리소스 정책 확인 필요 · CPU 사용",
  };
  const gpuPolicy = active?.runtime_backend === "vllm-cuda"
    ? selection?.gpu_assignment : selection?.gpu_candidate;
  const gpuCandidateProfile = profiles.find(profile => profile.id === selection?.gpu_profile);
  const requiresConfirmation = reviewProfile ? mainModelProfileRequiresConfirmation(reviewProfile)
    || (isRecoveringPolicy(reviewPolicy) && gpuCandidateProfile?.qualification.status !== 'verified') : false;
  const switchImpact = reviewProfile && active
    ? mainModelProfileImpact(active, reviewProfile)
    : null;

  const policyAction = (mode: ExecutionPolicy) => {
    if (!selection) return null;
    const retry = mode === 'fallback' && selection.mode === 'fallback' && active?.runtime_backend === 'llama-cpp';
    const target = profiles.find(profile => mode === 'gpu'
      ? profile.id === (active?.runtime_backend === 'vllm-cuda' ? active.id : selection.gpu_profile)
      : profile.id === (selection.cpu_profile ?? 'cpu-gguf-text'));
    return <Button key={mode} variant="secondary"
      isDisabled={switchMutation.isPending || busy || !target || (selection.mode === mode && !retry)}
      onClick={() => {
        if (target) { setReviewPolicy(mode); setReviewProfileId(target.id); setConfirmed(false); setActionError(null); }
      }}>
      {retry ? 'GPU 다시 확인' : executionPolicyPresentation[mode].label}
    </Button>;
  };

  return (
    <section className="runtime-page">
      <div className="page-heading">
        <div>
          <h1>메인 모델</h1>
          <p>현재 모델 · 전환 후보 · 진행 상태</p>
        </div>
        <Button
          variant="secondary"
          onClick={() => {
            void statusQuery.refetch();
            void profilesQuery.refetch();
          }}
          isDisabled={statusQuery.isFetching || profilesQuery.isFetching}
        >
          {statusQuery.isFetching || profilesQuery.isFetching ? t('common.refreshing') : t('common.refresh')}
        </Button>
      </div>

      {!selection && profiles.some(profile => profile.runtime_backend === "llama-cpp") ? (
        <Alert isInline variant="info" title="CPU/GPU 수동 선택">
          아래 프로필에서 CPU 또는 GPU 모델의 전환 영향을 검토하고 적용할 수 있습니다. 선택한 모델은 재시작 뒤에도 유지됩니다. 자동 전환은 사용하지 않습니다.
        </Alert>
      ) : null}
      {selection ? (
        <Card>
          <CardTitle>실행 정책 · {executionPolicyPresentation[selection.mode].label}</CardTitle>
          <CardBody>
            <p>활성 프로필: {active?.runtime_backend === "llama-cpp" ? "CPU · llama.cpp" : active?.runtime_backend === "vllm-cuda" ? "GPU · vLLM" : "준비 중"}</p>
            <p>{isRecoveringPolicy(selection.mode) ? (selectionReasons[selection.reason_code] ?? selection.reason_code) : "선택한 엔진의 모델을 유지합니다."}</p>
            <p>{executionPolicyPresentation[selection.mode].description}</p>
            <p>요청 상태: {status.gate === "open" ? "수락 중" : "새 요청 차단 중"}</p>
            {selection.observed_at ? <p>마지막 자원 관측: {new Date(selection.observed_at * 1000).toLocaleString()}</p> : null}
            {isRecoveringPolicy(selection.mode) ? selection.resources?.gpus.map(gpu => (
              <div key={gpu.uuid ?? gpu.index} style={{ overflowWrap: "anywhere" }}>
                <p>GPU {gpu.index}: {gpu.name ?? "제품명 확인 불가"} · 실측 여유 {gpu.free_mib.toLocaleString()} / 전체 {gpu.total_mib.toLocaleString()} MiB</p>
                <p>UUID: {gpu.uuid ?? "확인 불가"} · PCI: {gpu.pci_bus_id ?? "확인 불가"} · Compute Capability: {gpu.compute_capability ?? "확인 불가"} · Driver: {gpu.driver_version ?? "확인 불가"}</p>
              </div>
            )) : null}
            {isRecoveringPolicy(selection.mode) && gpuPolicy ? (
              <div style={{ overflowWrap: "anywhere" }}>
                <p>{active?.runtime_backend === "vllm-cuda" ? "할당 GPU" : "후보 GPU"}: {gpuPolicy.name ?? "제품명 확인 불가"} · {gpuPolicy.uuid}</p>
                <p>리소스 정책: {gpuPolicy.resource_variant ?? "Reference"} · 선택 근거: {gpuPolicy.policy_source === "operator" ? "운영자 지정" : "전체 VRAM 용량"}</p>
              </div>
            ) : null}
            {selection.gpu_condition && (selection.reason_code.startsWith("CPU_FALLBACK_") || selection.mode === "fallback") ? <p>GPU 상태: {selectionReasons[selection.gpu_condition] ?? selection.gpu_condition}</p> : null}
            {selection.gpu_retry_at && selection.reason_code === "GPU_FAILURE_BACKOFF" ? <p>GPU 재시도 가능 시각: {new Date(selection.gpu_retry_at * 1000).toLocaleString()}</p> : null}
            {selection.cpu_retry_at && status.gate === "closed" && selection.reason_code.startsWith("CPU_FALLBACK_") ? <p>CPU 재시도 가능 시각: {new Date(selection.cpu_retry_at * 1000).toLocaleString()}</p> : null}
            {!locked ? <div className="review-actions" aria-label="실행 정책 선택">
              {(['fallback', 'cpu'] as const).map(policyAction)}
              <details>
                <summary>고급 실행 정책</summary>
                <p>자동 복귀 또는 특정 GPU 모델 유지가 필요한 경우 선택합니다.</p>
                {(['automatic', 'gpu'] as const).map(policyAction)}
              </details>
            </div> : null}
            {!profiles.some(profile => profile.runtime_backend === 'vllm-cuda') ? <p>GPU 이미지를 준비한 뒤 GPU 고정을 선택할 수 있습니다.</p> : null}
            <p>중지·재개: <Link to="/runtimes">런타임</Link></p>
          </CardBody>
        </Card>
      ) : locked ? (
        <Alert isInline variant="warning" title="이 배포에서는 메인 모델 전환이 잠겨 있습니다.">
          상태와 프로필 정보는 조회할 수 있지만 Console에서 전환을 시작할 수 없습니다.
        </Alert>
      ) : null}
      {status.state_recovery_error ? (
        <Alert isInline variant="danger" title="메인 모델 상태 복구 오류가 기록되어 있습니다.">
          {status.state_recovery_error}
        </Alert>
      ) : null}
      {actionError ? <Alert isInline variant="danger" title="메인 모델 전환 요청에 실패했습니다.">{actionError}</Alert> : null}
      {active && observed?.profile_id && observed.profile_id !== active.id ? (
        <Alert isInline variant="danger" title="실제 모델이 활성 프로필과 일치하지 않습니다.">
          현재 프로필({active.id})과 Docker에서 관측한 프로필({observed.profile_id})이 다릅니다.
          요청 Gate와 Runtime 진단 및 작업 이력을 확인하세요.
        </Alert>
      ) : null}
      {status.gate !== 'open' && status.runtime_state !== 'stopped' ? (
        <Alert isInline variant="warning" title="메인 모델 요청이 차단되어 있습니다.">
          런타임 상태와 전환 결과를 확인하세요. 모델 준비가 완료되면 요청이 재개됩니다.
        </Alert>
      ) : null}

      {profiles.some(profile => profile.runtime_backend === 'llama-cpp') ? (
        <Card>
          <CardTitle>CPU llama.cpp 실행 설정</CardTitle>
          <CardBody>
            <p>CPU 문맥과 최대 출력을 프리셋으로 선택합니다. 변경은 기존 Main Model 전환 경로를 거쳐 요청 정리·재기동·응답 확인을 수행합니다.</p>
            <p className="configuration-help">기본 8,192 / 4,096 tokens · 동시 요청 1개 · Threads 4개 · 메모리 상한 4GiB. 입력과 출력은 동일한 문맥을 공유합니다.</p>
            <div className="chat-heading-actions" role="group" aria-label="CPU 실행 한도 프리셋">
              {profiles.filter(profile => profile.runtime_backend === 'llama-cpp').map(profile => (
                <Button
                  key={profile.id}
                  variant={profile.active ? 'primary' : 'secondary'}
                  isDisabled={profile.active || locked || busy || switchMutation.isPending}
                  onClick={() => {
                    setReviewPolicy('cpu');
                    setReviewProfileId(profile.id);
                    setConfirmed(false);
                    setActionError(null);
                  }}
                >
                  {formatTokenLimits(mainModelTokenLimits(profile))}
                  {profile.active ? ' · 적용 중' : ''}
                </Button>
              ))}
            </div>
            <p className="configuration-help">프리셋 선택 시 CPU 고정 정책이 적용됩니다. 자동 GPU 복구는 기본 CPU 프리셋을 사용하며, 실장비에서 확인하지 않은 프리셋은 별도 확인이 필요합니다.</p>
          </CardBody>
        </Card>
      ) : null}

      <Card>
        <CardTitle>현재 모델 상태</CardTitle>
        <CardBody>
          <dl className="facts">
            <dt>공개 모델 이름</dt><dd>{status.public_model}</dd>
            <dt>현재 프로필</dt><dd>{active?.display_name ?? '—'}{active ? ` (${active.id})` : ''}</dd>
            <dt>실제 모델</dt><dd>{active?.upstream_model_id ?? '—'}</dd>
            <dt>실행 방식</dt><dd>{modelRuntimeLabel(active?.runtime_backend)}</dd>
            <dt>문맥 / 최대 출력 토큰</dt><dd>{active ? formatTokenLimits(mainModelTokenLimits(active)) : '—'}</dd>
            <dt>리소스 정책</dt><dd>{active ? mainModelResourcePolicyLabel(active) : '—'}</dd>
            <dt>요청 상태</dt><dd><Label color={status.gate === 'open' ? 'green' : 'orange'}>{runtimeStateLabel(status.gate)}</Label></dd>
            <dt>런타임 상태</dt><dd>{runtimeStateLabel(status.runtime_state)}</dd>
            <dt>부팅 프로필</dt><dd>{status.boot_profile ?? '기본 프로필'}</dd>
            <dt>실제 런타임</dt><dd>{runtimeStateLabel(observed?.status ?? 'unavailable')}</dd>
            <dt>상태 확인</dt><dd>{runtimeStateLabel(observed?.health ?? 'unavailable')}</dd>
            <dt>실제 프로필</dt><dd>{observed?.profile_id ?? '—'}</dd>
          </dl>
        </CardBody>
      </Card>

      <Card>
        <CardTitle>사용 가능한 프로필</CardTitle>
        <CardBody>
          <p className="configuration-help">GPU 예약 비율은 정책값이며 실제 VRAM 사용량과 다릅니다.</p>
          <div className="table-scroll">
            <table className="runtime-table">
              <thead>
                <tr><th>프로필</th><th>호환성</th><th>검증 상태</th><th>리소스 정책</th><th>입력</th><th title="컨텍스트 길이 / 최대 출력 토큰">토큰 한도</th><th title="실제 VRAM 점유량이나 모델 가중치 예상 크기가 아닌 예약 정책 비율입니다.">GPU 예약 비율</th><th>실행 전 판단</th><th>작업</th></tr>
              </thead>
              <tbody>
                {profiles.map((profile) => {
                  const preflight = mainModelPreflightView(profile);
                  return (
                    <tr key={profile.id}>
                      <td><strong>{profile.display_name}</strong><br /><code>{profile.id}</code><br />{modelRuntimeLabel(profile.runtime_backend)}<br /><small>{profile.upstream_model_id}</small></td>
                      <td><Label color={compatibilityVariant(profile.compatibility.status)}>{compatibilityLabel(profile.compatibility.status)}</Label></td>
                      <td><Label color={qualificationVariant(profile.qualification.status)}>{qualificationLabel(profile.qualification.status)}</Label></td>
                      <td>{mainModelResourcePolicyLabel(profile)}</td>
                      <td>{inputList(profile.capabilities.deployed_input)}</td>
                      <td>{formatTokenLimits(mainModelTokenLimits(profile))}</td>
                      <td>{profile.runtime_backend === "llama-cpp" ? "해당 없음" : formatPercent(profile.vram_fraction)}</td>
                      <td><Label color={preflight.color}>{preflight.label}</Label></td>
                      <td>
                        {profile.active ? (
                          <span className="current-state-text">현재 사용 중</span>
                        ) : (
                          <Button
                            size="sm"
                            variant="secondary"
                            isDisabled={switchMutation.isPending || busy}
                            onClick={() => {
                              setReviewPolicy(profile.runtime_backend === "llama-cpp" ? "cpu" : "gpu");
                              setReviewProfileId(profile.id);
                              setConfirmed(false);
                              setActionError(null);
                            }}
                          >전환 검토</Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardBody>
      </Card>

      {reviewProfile ? (
        <Card className="review-card">
          <CardTitle>{isRecoveringPolicy(reviewPolicy) ? '실행 정책 변경 전 영향 확인' : '모델 전환 전 영향 확인'}</CardTitle>
          <CardBody>
            {reviewPolicy ? <p>적용할 실행 정책: {executionPolicyPresentation[reviewPolicy].label} · {executionPolicyPresentation[reviewPolicy].description}</p> : null}
            {isRecoveringPolicy(reviewPolicy) ? <p>GPU 후보: {gpuCandidateProfile?.display_name ?? selection?.gpu_profile ?? '준비 필요'}{gpuCandidateProfile ? ` · ${inputList(gpuCandidateProfile.capabilities.deployed_input)} · ${formatTokenLimits(mainModelTokenLimits(gpuCandidateProfile))}` : ''}</p> : null}
            {isRecoveringPolicy(reviewPolicy) ? <Alert isInline variant="warning" title={reviewPolicy === "fallback" ? "GPU 사용을 검토하고, 불가능하면 CPU를 유지합니다." : "CPU부터 검증한 뒤 GPU 여유에 따라 모델을 전환합니다."}>CPU와 GPU는 서로 다른 모델이며 지원 입력과 응답이 달라집니다. GPU 준비 실패 시 CPU를 유지합니다. {reviewPolicy === "fallback" ? "CPU 복구 후 GPU 복귀는 수동입니다." : "GPU 여유가 회복되면 자동 복귀를 시도합니다."}</Alert> : null}
            {active && switchImpact ? (
              <div className="profile-impact-summary" role="group" aria-label="전환 핵심 영향">
                <div className="profile-impact-summary-item">
                  <span>요청 처리</span>
                  <strong>전환 중 일시 중단 가능</strong>
                </div>
                <div className="profile-impact-summary-item" data-tone={switchImpact.removedInputs.length ? 'warning' : 'neutral'}>
                  <span>지원 입력</span>
                  <strong>{inputImpactLabel(switchImpact.addedInputs, switchImpact.removedInputs)}</strong>
                </div>
                <div className="profile-impact-summary-item" data-tone={switchImpact.resourcePolicyChanged ? 'info' : 'neutral'}>
                  <span>리소스 정책</span>
                  <strong>{switchImpact.resourcePolicyChanged ? '변경됨' : '변경 없음'}</strong>
                </div>
              </div>
            ) : null}
            <p className="configuration-help profile-comparison-intro">
              {active ? '전환 실패 시 이전 모델로 복구를 시도합니다.' : '첫 활성화에는 복구할 이전 모델이 없습니다.'}
            </p>

            {active && switchImpact ? (
              <>
                <div className="table-scroll profile-comparison-scroll">
                  <table className="runtime-table profile-comparison-table">
                    <thead>
                      <tr><th>항목</th><th>현재</th><th>{isRecoveringPolicy(reviewPolicy) ? 'CPU 준비 단계' : '전환 대상'}</th><th>변경</th></tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td><strong>프로필</strong></td>
                        <td>{active.display_name}<small><code>{active.id}</code></small></td>
                        <td>{reviewProfile.display_name}<small><code>{reviewProfile.id}</code></small></td>
                        <td><Label color="blue">전환</Label></td>
                      </tr>
                      <tr>
                        <td><strong>호환성</strong></td>
                        <td><Label color={compatibilityVariant(active.compatibility.status)}>{compatibilityLabel(active.compatibility.status)}</Label></td>
                        <td><Label color={compatibilityVariant(reviewProfile.compatibility.status)}>{compatibilityLabel(reviewProfile.compatibility.status)}</Label></td>
                        <td>{switchImpact.compatibilityChanged ? <Label color="blue">변경됨</Label> : <Label color="grey">변경 없음</Label>}</td>
                      </tr>
                      <tr>
                        <td><strong>검증 상태</strong></td>
                        <td><Label color={qualificationVariant(active.qualification.status)}>{qualificationLabel(active.qualification.status)}</Label></td>
                        <td><Label color={qualificationVariant(reviewProfile.qualification.status)}>{qualificationLabel(reviewProfile.qualification.status)}</Label></td>
                        <td>{switchImpact.qualificationChanged ? <Label color="blue">변경됨</Label> : <Label color="grey">변경 없음</Label>}</td>
                      </tr>
                      <tr>
                        <td><strong>리소스 정책 유형</strong></td>
                        <td>{mainModelResourcePolicyLabel(active)}</td>
                        <td>{mainModelResourcePolicyLabel(reviewProfile)}</td>
                        <td>{mainModelResourcePolicyLabel(active) !== mainModelResourcePolicyLabel(reviewProfile)
                          ? <Label color="blue">변경됨</Label>
                          : <Label color="grey">변경 없음</Label>}</td>
                      </tr>
                      <tr>
                        <td><strong>입력</strong></td>
                        <td>{inputList(active.capabilities.deployed_input)}</td>
                        <td>{inputList(reviewProfile.capabilities.deployed_input)}</td>
                        <td>{inputImpactLabel(switchImpact.addedInputs, switchImpact.removedInputs)}</td>
                      </tr>
                      <tr>
                        <td><strong>토큰 한도</strong><small>컨텍스트 / 최대 출력</small></td>
                        <td>{formatTokenLimits(mainModelTokenLimits(active))}</td>
                        <td>{formatTokenLimits(mainModelTokenLimits(reviewProfile))}</td>
                        <td>{formatTokenLimits(mainModelTokenLimits(active)) === formatTokenLimits(mainModelTokenLimits(reviewProfile))
                          ? <Label color="grey">변경 없음</Label>
                          : <Label color="blue">변경됨</Label>}</td>
                      </tr>
                      <tr>
                        <td><strong>GPU 정책 비율</strong></td>
                        <td>{active.runtime_backend === "llama-cpp" ? "해당 없음" : formatPercent(active.vram_fraction)}</td>
                        <td>{reviewProfile.runtime_backend === "llama-cpp" ? "해당 없음" : formatPercent(reviewProfile.vram_fraction)}</td>
                        <td>{vramImpactLabel(switchImpact.vramFractionDelta)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <div className="profile-impact-stack">
                  {switchImpact.removedInputs.length ? (
                    <Alert isInline variant="warning" title="지원 입력이 줄어듭니다.">
                      현재 프로필에서 가능한 {inputList(switchImpact.removedInputs)} 입력이 전환 뒤에는 제공되지 않습니다.
                    </Alert>
                  ) : null}
                </div>
              </>
            ) : (
              <Alert isInline variant="info" title="첫 활성화 · 현재 프로필 없음">
                현재 상태와의 차이를 계산할 수 없어 전환 대상 프로필 정보만 표시합니다.
              </Alert>
            )}

            <Alert
              isInline
              variant={reviewProfile.switch_preflight?.status === 'fits' ? 'info' : 'warning'}
              title={`${reviewProfile.runtime_backend === "llama-cpp" ? "CPU 실행 전 준비" : "GPU 실행 전 판단"} · ${mainModelPreflightView(reviewProfile).label}`}
            >
              <p>{mainModelPreflightView(reviewProfile).description}</p>
              {reviewProfile.switch_preflight?.required_fraction != null
                && reviewProfile.switch_preflight.available_fraction != null ? (
                <p>
                  예약 필요 {formatPercent(reviewProfile.switch_preflight.required_fraction)}
                  {' · '}현재 예약 가능 {formatPercent(reviewProfile.switch_preflight.available_fraction)}
                  {reviewProfile.switch_preflight.ceiling_fraction != null
                    ? ` · 정책 상한 ${formatPercent(reviewProfile.switch_preflight.ceiling_fraction)}`
                    : ''}
                </p>
              ) : null}
              {reviewProfile.switch_preflight?.status === 'needs_stop'
                && reviewProfile.switch_preflight.stop.length > 0 ? (
                <p>먼저 중지할 Runtime: {reviewProfile.switch_preflight.stop.join(', ')}. 자동 중지하지 않습니다.</p>
              ) : null}
            </Alert>

            <details className="profile-target-details">
              <summary>전환 대상 상세 정보</summary>
              <dl className="facts compact-facts">
                <dt>대상 프로필</dt><dd>{reviewProfile.display_name} ({reviewProfile.id})</dd>
                <dt>업스트림 모델</dt><dd>{reviewProfile.upstream_model_id}</dd>
                <dt>revision</dt><dd><code>{reviewProfile.revision}</code></dd>
                <dt>런타임 이미지</dt><dd><code>{reviewProfile.runtime_image}</code></dd>
              </dl>
            </details>

            {requiresConfirmation ? (
              <Alert isInline variant="warning" title="미검증 프로필 확인이 필요합니다.">
                <p>{isRecoveringPolicy(reviewPolicy) && gpuCandidateProfile?.qualification.status !== 'verified'
                  ? `GPU 후보 ${gpuCandidateProfile?.display_name ?? selection?.gpu_profile ?? ''}의 실제 장비 검증이 완료되지 않았습니다.`
                  : '전환 대상 프로필의 실제 장비 검증이 완료되지 않았습니다.'}</p>
                <label>
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(event) => setConfirmed(event.currentTarget.checked)}
                  />{' '}
                  미검증 상태를 확인했고 전환을 진행합니다.
                </label>
              </Alert>
            ) : null}
            <div className="review-actions">
              <Button variant="secondary" onClick={() => setReviewProfileId(null)} isDisabled={switchMutation.isPending || busy}>취소</Button>
              <Button
                variant="primary"
                isDisabled={switchMutation.isPending || busy || locked || !mainModelPolicySwitchable(reviewProfile, reviewPolicy) || (requiresConfirmation && !confirmed)}
                onClick={() => switchMutation.mutate({ profile: reviewProfile, accepted: confirmed })}
              >{switchMutation.isPending ? '요청 중…' : '전환 요청'}</Button>
            </div>
          </CardBody>
        </Card>
      ) : null}

      {operationId ? (
        <Card>
          <CardTitle>모델 전환 진행 상황</CardTitle>
          <CardBody>
            {operationQuery.isPending ? (
              <div className="inline-loading"><Spinner size="md" aria-label="메인 모델 전환 상태 불러오는 중" /> 전환 상태를 확인하는 중입니다.</div>
            ) : operationQuery.isError ? (
              <Alert isInline variant="danger" title="전환 상태를 불러오지 못했습니다.">{apiErrorMessage(operationQuery.error)}</Alert>
            ) : operationQuery.data ? (
              <>
                  <OperationProgress operation={operationQuery.data} />
                  {chatEnabled && operationQuery.data.status === 'completed' ? (
                    <p className="operation-follow-up"><Link to={playgroundPath('chat')}>Playground에서 새 모델 응답 확인 →</Link></p>
                  ) : null}
                </>
            ) : null}
          </CardBody>
        </Card>
      ) : status.last_operation ? (
        <Card>
          <CardTitle>최근 전환</CardTitle>
          <CardBody>
            <dl className="facts">
              <dt>작업 ID</dt><dd><code>{status.last_operation.id}</code></dd>
              <dt>요청 프로필</dt><dd>{status.last_operation.requested_profile}</dd>
              <dt>상태</dt><dd>{operationStatusLabel(status.last_operation.status)}</dd>
              <dt>단계</dt><dd>{mainModelOperationStagePresentation(status.last_operation.stage).label} <code>({status.last_operation.stage})</code></dd>
            </dl>
          </CardBody>
        </Card>
      ) : null}
    </section>
  );
}
