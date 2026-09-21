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
  if (status === 'compatible') return 'Compatible';
  if (status === 'incompatible') return 'Incompatible';
  if (status === 'unknown') return 'Unknown';
  return status;
}

function qualificationVariant(status: string): 'green' | 'orange' | 'grey' {
  if (status === 'verified') return 'green';
  if (status === 'unverified') return 'orange';
  return 'grey';
}

function qualificationLabel(status: string): string {
  if (status === 'verified') return 'Evidence verified';
  if (status === 'unverified') return 'Evidence not verified · confirmation required';
  return status;
}

function inputImpactLabel(added: string[], removed: string[]): string {
  const parts = [
    added.length ? `추가: ${added.join(', ')}` : null,
    removed.length ? `제거: ${removed.join(', ')}` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : '변경 없음';
}

function vramImpactLabel(delta: number): string {
  if (Math.abs(delta) < 0.0001) return '변경 없음';
  return `${delta > 0 ? '+' : ''}${delta.toFixed(2)}`;
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
      <ol className="operation-progress" aria-label="Main Model 전환 진행 단계">
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
        <dt>Operation ID</dt><dd><code>{operation.id}</code></dd>
        <dt>Requested profile</dt><dd>{operation.requested_profile}</dd>
        <dt>Previous profile</dt><dd>{operation.previous_profile ?? '—'}</dd>
        <dt>Controller status</dt><dd>{operation.status}</dd>
        <dt>Current stage</dt><dd>{presentation.label} <code>({operation.stage})</code></dd>
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
    return <div className="inline-loading"><Spinner size="lg" aria-label="Main Model 상태 loading" /> Main Model 상태를 불러오는 중입니다.</div>;
  }
  if (statusQuery.isError) {
    return <Alert isInline variant="danger" title="Main Model 상태를 불러오지 못했습니다.">{apiErrorMessage(statusQuery.error)}</Alert>;
  }
  if (profilesQuery.isError) {
    return <Alert isInline variant="danger" title="Main Model 프로필을 불러오지 못했습니다.">{apiErrorMessage(profilesQuery.error)}</Alert>;
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
          <h1>Main Model</h1>
          <p>Compatibility와 GPU resource admission이 실행 가능성을 판단하고, Profile evidence는 검증 근거를 표시합니다. 전환 중에는 Controller의 실제 stage를 단계별로 추적합니다.</p>
        </div>
        <Button
          variant="secondary"
          onClick={() => {
            void statusQuery.refetch();
            void profilesQuery.refetch();
          }}
          isDisabled={statusQuery.isFetching || profilesQuery.isFetching}
        >
          {statusQuery.isFetching || profilesQuery.isFetching ? '새로고침 중…' : '새로고침'}
        </Button>
      </div>

      {locked ? (
        <Alert isInline variant="warning" title="이 배포는 Main Model profile이 잠겨 있습니다.">
          상태와 profile metadata는 조회할 수 있지만 Console에서 profile switch를 시작할 수 없습니다.
        </Alert>
      ) : null}
      {status.state_recovery_error ? (
        <Alert isInline variant="danger" title="Main Model state recovery 오류가 기록되어 있습니다.">
          {status.state_recovery_error}
        </Alert>
      ) : null}
      {actionError ? <Alert isInline variant="danger" title="Main Model 전환 요청에 실패했습니다.">{actionError}</Alert> : null}

      <Alert isInline variant="info" title="Hardware support와 Profile evidence는 별개입니다.">
        새 GPU 제품명에 대한 직접 qualification record가 없다는 이유만으로 unsupported가 되지 않습니다.
        실행 가능성은 Compatibility, GPU resource admission과 runtime validation이 판단하며,
        resource variant는 reference policy가 맞지 않을 때만 사용하는 명시적 override입니다.
      </Alert>

      <Card>
        <CardTitle>Current control state</CardTitle>
        <CardBody>
          <dl className="facts">
            <dt>Public model alias</dt><dd>{status.public_model}</dd>
            <dt>Active profile</dt><dd>{active?.display_name ?? '—'}{active ? ` (${active.id})` : ''}</dd>
            <dt>Active resource policy</dt><dd>{active ? mainModelResourcePolicyLabel(active) : '—'}</dd>
            <dt>Gate</dt><dd><Label color={status.gate === 'open' ? 'green' : 'orange'}>{status.gate}</Label></dd>
            <dt>Runtime state</dt><dd>{status.runtime_state}</dd>
            <dt>Boot profile</dt><dd>{status.boot_profile}</dd>
            <dt>Observed runtime</dt><dd>{observed?.status ?? 'unavailable'}</dd>
            <dt>Observed health</dt><dd>{observed?.health ?? '—'}</dd>
            <dt>Observed profile</dt><dd>{observed?.profile_id ?? '—'}</dd>
          </dl>
        </CardBody>
      </Card>

      <Card>
        <CardTitle>Available profiles</CardTitle>
        <CardBody>
          <div className="table-scroll">
            <table className="runtime-table">
              <thead>
                <tr><th>Profile</th><th>Compatibility</th><th>Profile evidence</th><th>Resource policy</th><th>Inputs</th><th>VRAM</th><th>State</th><th>Action</th></tr>
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
                      <td>{profile.capabilities.deployed_input.join(', ')}</td>
                      <td>{profile.vram_fraction.toFixed(2)}</td>
                      <td>{profile.active ? <Label color="green">active</Label> : 'available'}</td>
                      <td>
                        <Button
                          size="sm"
                          variant="secondary"
                          isDisabled={!switchable || switchMutation.isPending}
                          onClick={() => {
                            setReviewProfileId(profile.id);
                            setConfirmed(false);
                            setActionError(null);
                          }}
                        >검토</Button>
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
          <CardTitle>Profile switch review</CardTitle>
          <CardBody>
            <p className="configuration-help profile-comparison-intro">
              전환 전에 현재 profile과 후보 profile의 운영 계약 차이를 확인합니다.
              Compatibility, evidence, resource policy는 서로 다른 의미이며 이 비교는 hardware support 판정이 아닙니다.
            </p>

            {active && switchImpact ? (
              <>
                <div className="table-scroll profile-comparison-scroll">
                  <table className="runtime-table profile-comparison-table">
                    <thead>
                      <tr><th>Dimension</th><th>Current</th><th>Target</th><th>Change</th></tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td><strong>Profile</strong></td>
                        <td>{active.display_name}<small><code>{active.id}</code></small></td>
                        <td>{reviewProfile.display_name}<small><code>{reviewProfile.id}</code></small></td>
                        <td><Label color="blue">switch</Label></td>
                      </tr>
                      <tr>
                        <td><strong>Compatibility</strong></td>
                        <td><Label color={compatibilityVariant(active.compatibility.status)}>{compatibilityLabel(active.compatibility.status)}</Label></td>
                        <td><Label color={compatibilityVariant(reviewProfile.compatibility.status)}>{compatibilityLabel(reviewProfile.compatibility.status)}</Label></td>
                        <td>{switchImpact.compatibilityChanged ? <Label color="blue">changes</Label> : <Label color="grey">unchanged</Label>}</td>
                      </tr>
                      <tr>
                        <td><strong>Profile evidence</strong></td>
                        <td><Label color={qualificationVariant(active.qualification.status)}>{qualificationLabel(active.qualification.status)}</Label></td>
                        <td><Label color={qualificationVariant(reviewProfile.qualification.status)}>{qualificationLabel(reviewProfile.qualification.status)}</Label></td>
                        <td>{switchImpact.qualificationChanged ? <Label color="blue">changes</Label> : <Label color="grey">unchanged</Label>}</td>
                      </tr>
                      <tr>
                        <td><strong>Resource policy</strong></td>
                        <td>{mainModelResourcePolicyLabel(active)}</td>
                        <td>{mainModelResourcePolicyLabel(reviewProfile)}</td>
                        <td>{switchImpact.resourcePolicyChanged ? <Label color="blue">changes</Label> : <Label color="grey">unchanged</Label>}</td>
                      </tr>
                      <tr>
                        <td><strong>Inputs</strong></td>
                        <td>{active.capabilities.deployed_input.join(', ')}</td>
                        <td>{reviewProfile.capabilities.deployed_input.join(', ')}</td>
                        <td>{inputImpactLabel(switchImpact.addedInputs, switchImpact.removedInputs)}</td>
                      </tr>
                      <tr>
                        <td><strong>VRAM fraction</strong></td>
                        <td>{active.vram_fraction.toFixed(2)}</td>
                        <td>{reviewProfile.vram_fraction.toFixed(2)}</td>
                        <td>{vramImpactLabel(switchImpact.vramFractionDelta)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <div className="profile-impact-stack">
                  {switchImpact.removedInputs.length ? (
                    <Alert isInline variant="warning" title="입력 capability가 줄어듭니다.">
                      현재 profile에서 가능한 {switchImpact.removedInputs.join(', ')} 입력이 전환 뒤에는 제공되지 않습니다.
                    </Alert>
                  ) : null}
                  {switchImpact.addedInputs.length ? (
                    <Alert isInline variant="info" title="입력 capability가 추가됩니다.">
                      전환 뒤 {switchImpact.addedInputs.join(', ')} 입력 capability가 추가됩니다.
                    </Alert>
                  ) : null}
                  {switchImpact.resourcePolicyChanged ? (
                    <Alert isInline variant="info" title="적용 resource policy가 달라집니다.">
                      {mainModelResourcePolicyLabel(active)} → {mainModelResourcePolicyLabel(reviewProfile)}.
                      이 차이는 GPU 제품의 지원/미지원 판정이 아니라 선택된 runtime resource-policy 차이입니다.
                    </Alert>
                  ) : null}
                </div>
              </>
            ) : (
              <Alert isInline variant="info" title="현재 active profile이 없습니다.">
                현재 상태와의 차이를 계산할 수 없어 target profile 정보만 표시합니다.
              </Alert>
            )}

            <details className="profile-target-details">
              <summary>Target identity</summary>
              <dl className="facts compact-facts">
                <dt>Target</dt><dd>{reviewProfile.display_name} ({reviewProfile.id})</dd>
                <dt>Upstream</dt><dd>{reviewProfile.upstream_model_id}</dd>
                <dt>Revision</dt><dd><code>{reviewProfile.revision}</code></dd>
                <dt>Runtime image</dt><dd><code>{reviewProfile.runtime_image}</code></dd>
              </dl>
            </details>

            {requiresConfirmation ? (
              <Alert isInline variant="warning" title="Profile evidence 확인이 필요합니다.">
                <p>이 확인은 현재 GPU가 미지원이라는 의미가 아닙니다. 이 profile의 repository-governed qualification evidence가 verified 상태가 아님을 확인하는 절차입니다.</p>
                <label>
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(event) => setConfirmed(event.currentTarget.checked)}
                  />{' '}
                  Profile evidence 상태를 확인했고 전환을 진행합니다.
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
          <CardTitle>Switch progress</CardTitle>
          <CardBody>
            {operationQuery.isPending ? (
              <div className="inline-loading"><Spinner size="md" aria-label="Main Model switch loading" /> 전환 상태를 확인하는 중입니다.</div>
            ) : operationQuery.isError ? (
              <Alert isInline variant="danger" title="전환 상태를 불러오지 못했습니다.">{apiErrorMessage(operationQuery.error)}</Alert>
            ) : operationQuery.data ? (
              <OperationProgress operation={operationQuery.data} />
            ) : null}
          </CardBody>
        </Card>
      ) : status.last_operation ? (
        <Card>
          <CardTitle>Latest switch</CardTitle>
          <CardBody>
            <dl className="facts">
              <dt>Operation ID</dt><dd><code>{status.last_operation.id}</code></dd>
              <dt>Requested profile</dt><dd>{status.last_operation.requested_profile}</dd>
              <dt>Status</dt><dd>{status.last_operation.status}</dd>
              <dt>Stage</dt><dd>{mainModelOperationStagePresentation(status.last_operation.stage).label} <code>({status.last_operation.stage})</code></dd>
            </dl>
          </CardBody>
        </Card>
      ) : null}
    </section>
  );
}
