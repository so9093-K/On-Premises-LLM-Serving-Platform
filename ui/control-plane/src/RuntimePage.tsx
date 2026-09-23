import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, CardBody, CardTitle, Label, Spinner } from '@patternfly/react-core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  ApiError,
  applyRuntimeTransition,
  fetchRuntimeOperation,
  fetchRuntimes,
  planRuntimeTransition,
  type RuntimeListResponse,
  type RuntimeOperationResponse,
  type RuntimePlanResponse,
} from './api';
import {
  isRuntimePlanChanged,
  runtimeApplyRequest,
  runtimePlanRequiresForceReview,
} from './runtimeSafety';
import { apiErrorMessage, isUnauthorized } from './apiFeedback';
import { formatFraction, formatPercent, runtimeStateLabel, t, yesNoLabel } from './uiText';

type DesiredState = 'active' | 'stopped';
type RuntimeTopologyItem = NonNullable<RuntimeListResponse['topology']>[number];

function runtimeDisplayName(serviceKey: string): string {
  const names: Record<string, string> = {
    main: '메인 모델',
    main_llm: '메인 모델',
    embedding: '임베딩',
    embedding_ko: '한국어 임베딩',
    prompt_injection_detector: '프롬프트 인젝션 탐지기',
  };
  return names[serviceKey] ?? serviceKey;
}

function topologyReason(item: RuntimeTopologyItem): string {
  if (
    item.reason_code === 'MAIN_RESOURCE_POLICY_COMPOSITION_CONSTRAINT'
    && item.main_resource_variant
  ) {
    return `현재 메인 모델 리소스 정책(${item.main_resource_variant})과 함께 실행하지 않도록 구성되어 있습니다. GPU 제품 자체의 지원 여부나 장애를 뜻하지 않습니다.`;
  }
  return '현재 실행 환경의 유효 구성에서 사용할 수 없습니다. GPU 제품 자체의 지원 여부나 장애를 뜻하지 않습니다.';
}

type RuntimePageProps = {
  token: string | null;
  onUnauthorized: () => void;
};

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && isRuntimePlanChanged(error)) {
    return `${error.message} 현재 상태가 검토 시점과 달라졌으므로 변경 내용을 다시 확인하세요.`;
  }
  return apiErrorMessage(error);
}

function operationIdFromError(error: unknown): string | null {
  if (!(error instanceof ApiError) || typeof error.details !== 'object' || error.details === null) {
    return null;
  }
  const operationId = (error.details as Record<string, unknown>).operation_id;
  return typeof operationId === 'string' ? operationId : null;
}

function criticalityLabel(value: string | null | undefined): string {
  const labels: Record<string, string> = {
    primary_user_path: '주요 요청 경로',
    retrieval_support_path: '검색 지원 경로',
    risk_support_path: '위험 신호 지원',
  };
  return value ? labels[value] ?? value : '—';
}

function verificationSummary(operation: RuntimeOperationResponse): string {
  const verification = operation.verification;
  if (typeof verification !== 'object' || verification === null) {
    return '관측 정보 없음';
  }
  const converged = (verification as Record<string, unknown>).converged;
  if (converged === true) return '실제 상태가 원하는 상태로 수렴했습니다.';
  if (converged === false) return '실제 상태가 원하는 상태로 수렴하지 않았습니다.';
  return '상태 수렴 여부가 기록되지 않았습니다.';
}

export function RuntimePage({ token, onUnauthorized }: RuntimePageProps) {
  const queryClient = useQueryClient();
  const [review, setReview] = useState<RuntimePlanResponse | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [operationId, setOperationId] = useState<string | null>(null);

  const authClass = token === null ? 'anonymous' : 'authenticated';
  const runtimesQuery = useQuery({
    queryKey: ['runtime-control', 'runtimes', authClass],
    queryFn: () => fetchRuntimes(token),
    retry: false,
    refetchInterval: () => document.visibilityState === 'visible' ? 10_000 : false,
    refetchIntervalInBackground: false,
  });

  useEffect(() => {
    if (isUnauthorized(runtimesQuery.error)) {
      onUnauthorized();
    }
  }, [onUnauthorized, runtimesQuery.error]);

  const operationQuery = useQuery({
    queryKey: ['runtime-control', 'operation', operationId, authClass],
    queryFn: () => {
      if (operationId === null) throw new Error('operation id is required');
      return fetchRuntimeOperation(token, operationId);
    },
    enabled: operationId !== null,
    retry: false,
  });

  useEffect(() => {
    if (isUnauthorized(operationQuery.error)) {
      onUnauthorized();
    }
  }, [onUnauthorized, operationQuery.error]);

  const planMutation = useMutation({
    mutationFn: ({ serviceKey, desiredState, force }: {
      serviceKey: string;
      desiredState: DesiredState;
      force: boolean;
    }) => planRuntimeTransition(token, serviceKey, { desired_state: desiredState, force }),
    retry: false,
    onMutate: () => {
      setActionError(null);
      setOperationId(null);
    },
    onSuccess: (plan) => setReview(plan),
    onError: (error) => {
      if (isUnauthorized(error)) {
        onUnauthorized();
        return;
      }
      setActionError(errorMessage(error));
    },
  });

  const applyMutation = useMutation({
    mutationFn: (plan: RuntimePlanResponse) => applyRuntimeTransition(
      token,
      plan.service_key,
      runtimeApplyRequest(plan),
    ),
    retry: false,
    onMutate: () => setActionError(null),
    onSuccess: async (result) => {
      setOperationId(result.operation_id);
      setReview(null);
      await queryClient.invalidateQueries({ queryKey: ['runtime-control', 'runtimes'] });
    },
    onError: async (error) => {
      if (isUnauthorized(error)) {
        onUnauthorized();
        return;
      }
      const failedOperationId = operationIdFromError(error);
      if (failedOperationId !== null) setOperationId(failedOperationId);
      if (isRuntimePlanChanged(error)) setReview(null);
      setActionError(errorMessage(error));
      await queryClient.invalidateQueries({ queryKey: ['runtime-control', 'runtimes'] });
    },
  });

  const selectedRuntime = useMemo(() => {
    if (review === null || runtimesQuery.data === undefined) return null;
    return runtimesQuery.data.runtimes.find((runtime) => runtime.service_key === review.service_key) ?? null;
  }, [review, runtimesQuery.data]);

  if (runtimesQuery.isPending) {
    return <div className="inline-loading"><Spinner size="lg" aria-label="Runtime 상태 loading" /> Runtime 상태를 불러오는 중입니다.</div>;
  }

  if (runtimesQuery.isError) {
    return <Alert isInline variant="danger" title="Runtime 상태를 불러오지 못했습니다.">{errorMessage(runtimesQuery.error)}</Alert>;
  }

  const { runtimes, budget } = runtimesQuery.data;
  const unavailableTopology = (runtimesQuery.data.topology ?? []).filter(
    (item) => !item.available,
  );
  const actionPending = planMutation.isPending || applyMutation.isPending;

  return (
    <section className="runtime-page">
      <div className="page-heading">
        <div>
          <h1>런타임</h1>
          <p>현재 실행 상태와 GPU 여유를 확인하고, 필요한 런타임만 시작하거나 중지합니다.</p>
        </div>
        <Button variant="secondary" onClick={() => runtimesQuery.refetch()} isDisabled={runtimesQuery.isFetching}>
          {runtimesQuery.isFetching ? t('common.refreshing') : t('common.refresh')}
        </Button>
      </div>

      {budget ? (
        <Card>
          <CardTitle>GPU 메모리 예산</CardTitle>
          <CardBody>
            <div className="gpu-budget-summary">
              <strong>{formatPercent(budget.used)} 사용</strong>
              <span>운영 상한 {formatPercent(budget.ceiling)} · 여유 {formatPercent(budget.free)}</span>
            </div>
            <div className="gpu-budget-track" aria-label={`GPU 사용 ${formatPercent(budget.used)}, 운영 상한 ${formatPercent(budget.ceiling)}`}>
              <span className="gpu-budget-used" style={{ width: `${Math.min(100, Math.max(0, budget.used * 100))}%` }} />
              <span className="gpu-budget-ceiling" style={{ left: `${Math.min(100, Math.max(0, budget.ceiling * 100))}%` }} />
            </div>
            <p className="configuration-help">상한은 동시에 실행할 수 있는 런타임 조합을 판단하는 운영 기준입니다.</p>
          </CardBody>
        </Card>
      ) : (
        <Alert isInline variant="warning" title="GPU 예산 정보를 사용할 수 없습니다.">
          런타임 상태는 표시하지만 자원 영향은 변경 검토 결과를 기준으로 판단하세요.
        </Alert>
      )}

      {unavailableTopology.length ? (
        <Card>
          <CardTitle>현재 사용할 수 없는 런타임</CardTitle>
          <CardBody>
            <p className="overview-muted">
              선언에는 존재하지만 현재 리소스 정책에서는 제어·시작 대상에서 제외된 런타임입니다.
            </p>
            {unavailableTopology.map((item) => (
              <div className="impact-block" key={item.service_key}>
                <p>
                  <strong>{runtimeDisplayName(item.service_key)}</strong>{' '}
                  <Label color="orange">정책상 제외</Label>
                </p>
                <p>{topologyReason(item)}</p>
                <dl className="facts compact-facts">
                  <dt>서비스 키</dt><dd>{item.service_key}</dd>
                  <dt>지원 기능</dt><dd>{item.features.join(', ') || '—'}</dd>
                  <dt>리소스 정책</dt><dd>{item.main_resource_variant ?? '—'}</dd>
                </dl>
              </div>
            ))}
          </CardBody>
        </Card>
      ) : null}

      {actionError ? <Alert isInline variant="danger" title="런타임 작업을 완료하지 못했습니다.">{actionError}</Alert> : null}

      <div className="table-scroll">
        <table className="runtime-table">
          <thead>
            <tr>
              <th>런타임</th>
              <th>원하는 상태</th>
              <th>실제 상태</th>
              <th>VRAM</th>
              <th>역할</th>
              <th>작업</th>
            </tr>
          </thead>
          <tbody>
            {runtimes.map((runtime) => {
              const nextState: DesiredState = runtime.state === 'active' ? 'stopped' : 'active';
              const starting = runtime.state === 'starting';
              return (
                <tr key={runtime.service_key}>
                  <td>
                    <strong>{runtimeDisplayName(runtime.service_key)}</strong>
                    <small><code>{runtime.service_key}</code>{runtime.active_profile ? ` · ${runtime.active_profile}` : ''}</small>
                  </td>
                  <td><Label>{runtimeStateLabel(runtime.state)}</Label></td>
                  <td>{runtimeStateLabel(runtime.container_status)}</td>
                  <td>{formatPercent(runtime.vram_fraction)}</td>
                  <td>{criticalityLabel(runtime.criticality)}</td>
                  <td className="runtime-actions">
                    {starting ? (
                      <Button size="sm" variant="secondary" isDisabled>변경 진행 중</Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="secondary"
                        isDanger={runtime.state === 'active'}
                        isDisabled={actionPending}
                        onClick={() => planMutation.mutate({
                          serviceKey: runtime.service_key,
                          desiredState: nextState,
                          force: false,
                        })}
                      >
                        {runtime.state === 'active' ? '중지 검토' : '시작 검토'}
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {planMutation.isPending ? <div className="inline-loading"><Spinner size="md" aria-label="Runtime 변경 계산 중" /> 변경 영향을 계산하는 중입니다.</div> : null}

      {review ? (
        <Card className="review-card">
          <CardTitle>런타임 변경 검토 · {runtimeDisplayName(review.service_key)}</CardTitle>
          <CardBody>
            <div className="review-grid">
              <dl className="facts compact-facts">
                <dt>현재 원하는 상태</dt><dd>{runtimeStateLabel(review.current_state)}</dd>
                <dt>변경 후 상태</dt><dd>{runtimeStateLabel(review.desired_state)}</dd>
                <dt>현재 실제 상태</dt><dd>{runtimeStateLabel(selectedRuntime?.container_status ?? 'unavailable')}</dd>
                <dt>실제 변경 발생</dt><dd>{yesNoLabel(!review.no_op)}</dd>
                <dt>적용 가능</dt><dd>{yesNoLabel(review.admissible)}</dd>
                <dt>자동 중지 허용</dt><dd>{yesNoLabel(review.force)}</dd>
                <dt>자동 중지 필요</dt><dd>{yesNoLabel(review.requires_force)}</dd>
              </dl>
              <dl className="facts compact-facts">
                <dt>GPU 사용 전</dt><dd>{formatPercent(review.budget.before.used)} / 상한 {formatPercent(review.budget.before.ceiling)}</dd>
                <dt>GPU 사용 후</dt><dd>{formatPercent(review.budget.after.used)} / 상한 {formatPercent(review.budget.after.ceiling)}</dd>
                <dt>시작 대상</dt><dd>{review.start.length ? review.start.map(runtimeDisplayName).join(', ') : '—'}</dd>
                <dt>중지 대상</dt><dd>{review.stop.length ? review.stop.map(runtimeDisplayName).join(', ') : '—'}</dd>
                <dt>선행 조건</dt><dd>{review.prerequisites.length ? review.prerequisites.join(', ') : '—'}</dd>
              </dl>
            </div>

            {review.impact.length ? (
              <div className="impact-block">
                <strong>서비스 영향</strong>
                <ul>
                  {review.impact.map((item) => (
                    <li key={`${item.service_key}:${item.action}`}>{runtimeDisplayName(item.service_key)}: {item.action} ({criticalityLabel(item.criticality)})</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {review.reason ? <Alert isInline variant={review.admissible ? 'info' : 'warning'} title="변경 검토 결과">{review.reason}</Alert> : null}

            <div className="review-actions">
              <Button variant="secondary" onClick={() => setReview(null)} isDisabled={actionPending}>취소</Button>
              {runtimePlanRequiresForceReview(review) ? (
                <Button
                  variant="warning"
                  isDisabled={actionPending}
                  onClick={() => planMutation.mutate({
                    serviceKey: review.service_key,
                    desiredState: review.desired_state,
                    force: true,
                  })}
                >
                  필요한 Runtime 자동 중지를 허용하고 다시 계산
                </Button>
              ) : null}
              <Button
                variant="primary"
                isDisabled={!review.admissible || actionPending}
                onClick={() => applyMutation.mutate(review)}
              >
                {applyMutation.isPending ? '적용·검증 중…' : '검토한 변경 적용'}
              </Button>
            </div>
          </CardBody>
        </Card>
      ) : null}

      {operationId !== null ? (
        <Card>
          <CardTitle>적용 결과</CardTitle>
          <CardBody>
            {operationQuery.isPending ? <div className="inline-loading"><Spinner size="md" aria-label="런타임 적용 결과 불러오는 중" /> 적용 결과를 불러오는 중입니다.</div> : null}
            {operationQuery.isError ? <Alert isInline variant="danger" title="적용 결과를 불러오지 못했습니다.">{errorMessage(operationQuery.error)}</Alert> : null}
            {operationQuery.data ? (
              <>
                <dl className="facts operation-facts">
                  <dt>작업 ID</dt><dd><code>{operationQuery.data.operation_id}</code></dd>
                  <dt>상태</dt><dd>{runtimeStateLabel(operationQuery.data.status)}</dd>
                  <dt>단계</dt><dd>{operationQuery.data.phase}</dd>
                  <dt>런타임</dt><dd>{runtimeDisplayName(operationQuery.data.service_key)}</dd>
                  <dt>원하는 상태</dt><dd>{runtimeStateLabel(operationQuery.data.desired_state)}</dd>
                  <dt>검토한 계획 사용</dt><dd>{yesNoLabel(operationQuery.data.reviewed_plan)}</dd>
                  <dt>실행 주체</dt><dd><code>{operationQuery.data.actor.actor_id}</code></dd>
                  <dt>요청 ID</dt><dd><code>{operationQuery.data.request_id}</code></dd>
                  <dt>검증</dt><dd>{verificationSummary(operationQuery.data)}</dd>
                  <dt>영구 기록</dt><dd>{yesNoLabel(operationQuery.data.durable)}</dd>
                </dl>
                {operationQuery.data.verification ? <pre className="evidence-json">{JSON.stringify(operationQuery.data.verification, null, 2)}</pre> : null}
              </>
            ) : null}
          </CardBody>
        </Card>
      ) : null}
    </section>
  );
}
