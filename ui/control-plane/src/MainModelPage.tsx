import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, CardBody, CardTitle, Label, Spinner } from '@patternfly/react-core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  fetchMainModel,
  fetchMainModelOperation,
  fetchMainModelProfiles,
  switchMainModel,
  type MainModelOperationResponse,
  type MainModelProfile,
} from './api';
import { apiErrorMessage, isUnauthorized } from './apiFeedback';
import {
  isMainModelOperationTerminal,
  mainModelOperationProgress,
  mainModelOperationStagePresentation,
  mainModelProfileImpact,
  mainModelProfileRequiresConfirmation,
  mainModelProfileSwitchable,
  mainModelResourcePolicyLabel,
  mainModelSwitchRequest,
} from './mainModelSafety';
import { formatPercent, runtimeStateLabel, t } from './uiText';

type MainModelPageProps = {
  token: string | null;
  onUnauthorized: () => void;
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
  if (status === 'unverified') return '미검증 · 확인 필요';
  return status;
}

function inputLabel(value: string): string {
  const labels: Record<string, string> = {
    text: '텍스트',
    image: '이미지',
    audio: '오디오',
    video: '비디오',
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

export function MainModelPage({ token, onUnauthorized }: MainModelPageProps) {
  const queryClient = useQueryClient();
  const [reviewProfileId, setReviewProfileId] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
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
    void queryClient.invalidateQueries({ queryKey: ['main-model', 'status'] });
    void queryClient.invalidateQueries({ queryKey: ['main-model', 'profiles'] });
  }, [operationQuery.data, queryClient]);

  const profiles = profilesQuery.data?.profiles ?? [];
  const reviewProfile = useMemo(
    () => profiles.find((profile) => profile.id === reviewProfileId) ?? null,
    [profiles, reviewProfileId],
  );

  const switchMutation = useMutation({
    mutationFn: ({ profile, accepted }: { profile: MainModelProfile; accepted: boolean }) =>
      switchMainModel(token, mainModelSwitchRequest(profile, accepted)),
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
  const requiresConfirmation = reviewProfile ? mainModelProfileRequiresConfirmation(reviewProfile) : false;
  const switchImpact = reviewProfile && active
    ? mainModelProfileImpact(active, reviewProfile)
    : null;

  return (
    <section className="runtime-page">
      <div className="page-heading">
        <div>
          <h1>메인 모델</h1>
          <p>현재 모델과 전환 가능한 프로필을 비교하고, 실제 전환 진행 상태까지 확인합니다.</p>
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

      {locked ? (
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

      <details className="context-note">
        <summary>호환성과 검증 근거 안내</summary>
        <p>
          GPU 실행 가능성과 프로필 검증 근거는 서로 다른 정보입니다. 직접 검증 기록이 없다는 이유만으로
          GPU가 지원되지 않는 것으로 판단하지 않으며, 호환성·GPU 리소스 판단·런타임 검증을 함께 사용합니다.
          리소스 variant는 기준 정책이 맞지 않을 때만 사용하는 명시적 override입니다.
        </p>
      </details>

      <Card>
        <CardTitle>현재 모델 상태</CardTitle>
        <CardBody>
          <dl className="facts">
            <dt>공개 모델 이름</dt><dd>{status.public_model}</dd>
            <dt>현재 프로필</dt><dd>{active?.display_name ?? '—'}{active ? ` (${active.id})` : ''}</dd>
            <dt>리소스 정책</dt><dd>{active ? mainModelResourcePolicyLabel(active) : '—'}</dd>
            <dt>요청 상태</dt><dd><Label color={status.gate === 'open' ? 'green' : 'orange'}>{runtimeStateLabel(status.gate)}</Label></dd>
            <dt>런타임 상태</dt><dd>{runtimeStateLabel(status.runtime_state)}</dd>
            <dt>부팅 프로필</dt><dd>{status.boot_profile}</dd>
            <dt>실제 런타임</dt><dd>{runtimeStateLabel(observed?.status ?? 'unavailable')}</dd>
            <dt>상태 확인</dt><dd>{runtimeStateLabel(observed?.health ?? 'unavailable')}</dd>
            <dt>실제 프로필</dt><dd>{observed?.profile_id ?? '—'}</dd>
          </dl>
        </CardBody>
      </Card>

      <Card>
        <CardTitle>사용 가능한 프로필</CardTitle>
        <CardBody>
          <div className="table-scroll">
            <table className="runtime-table">
              <thead>
                <tr><th>프로필</th><th>호환성</th><th>검증 근거</th><th>리소스 정책</th><th>입력</th><th>VRAM</th><th>상태</th><th>작업</th></tr>
              </thead>
              <tbody>
                {profiles.map((profile) => {
                  const switchable = !locked && mainModelProfileSwitchable(profile);
                  return (
                    <tr key={profile.id}>
                      <td><strong>{profile.display_name}</strong><br /><code>{profile.id}</code></td>
                      <td><Label color={compatibilityVariant(profile.compatibility.status)}>{compatibilityLabel(profile.compatibility.status)}</Label></td>
                      <td><Label color={qualificationVariant(profile.qualification.status)}>{qualificationLabel(profile.qualification.status)}</Label></td>
                      <td>{mainModelResourcePolicyLabel(profile)}</td>
                      <td>{inputList(profile.capabilities.deployed_input)}</td>
                      <td>{formatPercent(profile.vram_fraction)}</td>
                      <td>{profile.active ? <Label color="green">현재 사용 중</Label> : '사용 가능'}</td>
                      <td>
                        {profile.active ? (
                          <span className="current-state-text">현재 사용 중</span>
                        ) : (
                          <Button
                            size="sm"
                            variant="secondary"
                            isDisabled={!switchable || switchMutation.isPending}
                            onClick={() => {
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
          <CardTitle>프로필 전환 검토</CardTitle>
          <CardBody>
            <p className="configuration-help profile-comparison-intro">
              전환 전에 현재 프로필과 후보 프로필의 운영 계약 차이를 확인합니다.
              호환성, 검증 근거, 리소스 정책은 서로 다른 정보이며 이 비교만으로 GPU 지원 여부를 판정하지 않습니다.
            </p>

            {active && switchImpact ? (
              <>
                <div className="table-scroll profile-comparison-scroll">
                  <table className="runtime-table profile-comparison-table">
                    <thead>
                      <tr><th>항목</th><th>현재</th><th>전환 대상</th><th>변경</th></tr>
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
                        <td><strong>검증 근거</strong></td>
                        <td><Label color={qualificationVariant(active.qualification.status)}>{qualificationLabel(active.qualification.status)}</Label></td>
                        <td><Label color={qualificationVariant(reviewProfile.qualification.status)}>{qualificationLabel(reviewProfile.qualification.status)}</Label></td>
                        <td>{switchImpact.qualificationChanged ? <Label color="blue">changes</Label> : <Label color="grey">unchanged</Label>}</td>
                      </tr>
                      <tr>
                        <td><strong>리소스 정책</strong></td>
                        <td>{mainModelResourcePolicyLabel(active)}</td>
                        <td>{mainModelResourcePolicyLabel(reviewProfile)}</td>
                        <td>{switchImpact.resourcePolicyChanged ? <Label color="blue">changes</Label> : <Label color="grey">unchanged</Label>}</td>
                      </tr>
                      <tr>
                        <td><strong>입력</strong></td>
                        <td>{inputList(active.capabilities.deployed_input)}</td>
                        <td>{inputList(reviewProfile.capabilities.deployed_input)}</td>
                        <td>{inputImpactLabel(switchImpact.addedInputs, switchImpact.removedInputs)}</td>
                      </tr>
                      <tr>
                        <td><strong>VRAM</strong></td>
                        <td>{formatPercent(active.vram_fraction)}</td>
                        <td>{formatPercent(reviewProfile.vram_fraction)}</td>
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
                  {switchImpact.addedInputs.length ? (
                    <Alert isInline variant="info" title="지원 입력이 추가됩니다.">
                      전환 뒤 {inputList(switchImpact.addedInputs)} 입력이 추가됩니다.
                    </Alert>
                  ) : null}
                  {switchImpact.resourcePolicyChanged ? (
                    <Alert isInline variant="info" title="적용 리소스 정책이 달라집니다.">
                      {mainModelResourcePolicyLabel(active)} → {mainModelResourcePolicyLabel(reviewProfile)}.
                      이 차이는 GPU 제품의 지원 여부가 아니라 선택한 런타임 리소스 정책의 차이입니다.
                    </Alert>
                  ) : null}
                </div>
              </>
            ) : (
              <Alert isInline variant="info" title="현재 사용 중인 프로필이 없습니다.">
                현재 상태와의 차이를 계산할 수 없어 전환 대상 프로필 정보만 표시합니다.
              </Alert>
            )}

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
              <Alert isInline variant="warning" title="프로필 검증 근거 확인이 필요합니다.">
                <p>이 확인은 현재 GPU가 미지원이라는 의미가 아닙니다. 이 프로필의 저장소 기반 검증 근거가 검증 완료 상태가 아님을 확인하는 절차입니다.</p>
                <label>
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(event) => setConfirmed(event.currentTarget.checked)}
                  />{' '}
                  검증 근거 상태를 확인했고 전환을 진행합니다.
                </label>
              </Alert>
            ) : null}
            <div className="review-actions">
              <Button variant="secondary" onClick={() => setReviewProfileId(null)} isDisabled={switchMutation.isPending}>취소</Button>
              <Button
                variant="primary"
                isDisabled={switchMutation.isPending || (requiresConfirmation && !confirmed)}
                onClick={() => switchMutation.mutate({ profile: reviewProfile, accepted: confirmed })}
              >{switchMutation.isPending ? '요청 중…' : '전환 요청'}</Button>
            </div>
          </CardBody>
        </Card>
      ) : null}

      {operationId ? (
        <Card>
          <CardTitle>전환 진행 상황</CardTitle>
          <CardBody>
            {operationQuery.isPending ? (
              <div className="inline-loading"><Spinner size="md" aria-label="메인 모델 전환 상태 불러오는 중" /> 전환 상태를 확인하는 중입니다.</div>
            ) : operationQuery.isError ? (
              <Alert isInline variant="danger" title="전환 상태를 불러오지 못했습니다.">{apiErrorMessage(operationQuery.error)}</Alert>
            ) : operationQuery.data ? (
              <OperationProgress operation={operationQuery.data} />
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
