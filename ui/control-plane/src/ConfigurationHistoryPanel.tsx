import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, CardBody, CardTitle, Label, Spinner } from '@patternfly/react-core';
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import {
  ApiError,
  applyConfigurationRollback,
  fetchConfigurationHistory,
  planConfigurationRollback,
  type ConfigurationHistoryItem,
  type ConfigurationRollbackApplyResponse,
  type ConfigurationRollbackPlanResponse,
} from './api';
import { apiErrorMessage, isUnauthorized } from './apiFeedback';
import {
  configurationRollbackApplyRequest,
  configurationRollbackTargetRevision,
} from './configurationSafety';

type ConfigurationHistoryPanelProps = {
  token: string | null;
  onUnauthorized: () => void;
  currentRevision: number;
  etag: string;
  writeAvailable: boolean;
  locked: boolean;
  onReviewActiveChange: (active: boolean) => void;
};

type RollbackIntent = {
  baseRevision: number;
  targetRevision: number;
  etag: string;
};

type ReviewedRollback = {
  plan: ConfigurationRollbackPlanResponse;
  etag: string;
};

function isRevisionConflict(error: unknown): boolean {
  return error instanceof ApiError
    && error.status === 412
    && error.code === 'CONFIG_REVISION_CONFLICT';
}

function errorMessage(error: unknown): string {
  if (isRevisionConflict(error)) {
    return '설정 revision이 변경되어 기존 복원 검토를 사용할 수 없습니다. 최신 상태에서 새 계획을 검토하세요.';
  }
  return apiErrorMessage(error);
}

function formatTimestamp(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString('ko-KR');
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function statusColor(status: string): 'grey' | 'green' | 'orange' | 'red' | 'blue' {
  if (status === 'verified' || status === 'noop' || status === 'recovered_after_restart') return 'green';
  if (status === 'pending') return 'blue';
  if (status.includes('failed') || status.includes('interrupted')) return 'red';
  if (status === 'rejected') return 'orange';
  return 'grey';
}

function historyStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    verified: '검증 완료',
    noop: '변경 없음',
    recovered_after_restart: '재시작 후 복구',
    pending: '진행 중',
    rejected: '거부됨',
    failed: '실패',
    interrupted: '중단됨',
  };
  return labels[status] ?? status;
}

function historyKindLabel(kind: string): string {
  return kind === 'configuration_rollback' ? '이전 상태 복원' : '설정 변경';
}

function revisionLabel(item: ConfigurationHistoryItem): string {
  const applied = item.applied_revision === null ? '—' : `r${item.applied_revision}`;
  return `r${item.base_revision} → ${applied}`;
}

export function ConfigurationHistoryPanel({
  token,
  onUnauthorized,
  currentRevision,
  etag,
  writeAvailable,
  locked,
  onReviewActiveChange,
}: ConfigurationHistoryPanelProps) {
  const queryClient = useQueryClient();
  const [review, setReview] = useState<ReviewedRollback | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [lastRollback, setLastRollback] = useState<ConfigurationRollbackApplyResponse | null>(null);
  const authClass = token === null ? 'anonymous' : 'authenticated';

  const historyQuery = useInfiniteQuery({
    queryKey: ['configuration', 'history', authClass],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => fetchConfigurationHistory(token, pageParam as string | null),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    retry: false,
    staleTime: 5_000,
  });

  useEffect(() => {
    if (isUnauthorized(historyQuery.error)) onUnauthorized();
  }, [historyQuery.error, onUnauthorized]);

  const historyItems = useMemo(
    () => historyQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [historyQuery.data],
  );

  const planMutation = useMutation({
    mutationFn: (intent: RollbackIntent) => planConfigurationRollback(token, {
      base_revision: intent.baseRevision,
      target_revision: intent.targetRevision,
    }),
    retry: false,
    onMutate: () => {
      setActionError(null);
      setLastRollback(null);
      setReview(null);
      onReviewActiveChange(true);
    },
    onSuccess: (plan, intent) => setReview({ plan, etag: intent.etag }),
    onError: async (error) => {
      onReviewActiveChange(false);
      if (isUnauthorized(error)) {
        onUnauthorized();
        return;
      }
      setActionError(errorMessage(error));
      if (isRevisionConflict(error)) {
        await queryClient.invalidateQueries({ queryKey: ['configuration'] });
      }
    },
  });

  const applyMutation = useMutation({
    mutationFn: (reviewed: ReviewedRollback) => applyConfigurationRollback(
      token,
      reviewed.etag,
      configurationRollbackApplyRequest(reviewed.plan),
    ),
    retry: false,
    onMutate: () => setActionError(null),
    onSuccess: async (result) => {
      setLastRollback(result);
      setReview(null);
      onReviewActiveChange(false);
      await queryClient.invalidateQueries({ queryKey: ['configuration'] });
    },
    onError: async (error) => {
      setReview(null);
      onReviewActiveChange(false);
      if (isUnauthorized(error)) {
        onUnauthorized();
        return;
      }
      setActionError(errorMessage(error));
      await queryClient.invalidateQueries({ queryKey: ['configuration'] });
    },
  });

  const rollbackPending = planMutation.isPending || applyMutation.isPending;

  return (
    <>
      <Card>
        <CardTitle>설정 변경 이력</CardTitle>
        <CardBody>
          <p>설정 변경과 이전 상태 복원 기록입니다. 이전 상태로 복원해도 revision 번호를 되돌리지 않고 현재 상태에서 새 변경을 만듭니다.</p>
          {historyQuery.isPending ? (
            <div className="inline-loading"><Spinner size="md" aria-label="설정 변경 이력 불러오는 중" /> 변경 이력을 불러오는 중입니다.</div>
          ) : historyQuery.isError ? (
            <Alert isInline variant="danger" title="설정 변경 이력을 불러오지 못했습니다.">{errorMessage(historyQuery.error)}</Alert>
          ) : historyItems.length === 0 ? (
            <div className="empty-state">
              <strong>아직 설정 변경 기록이 없습니다.</strong>
              <p>운영자 설정을 변경하거나 이전 상태로 복원하면 이곳에 시간순으로 표시됩니다.</p>
            </div>
          ) : (
            <div className="table-scroll">
              <table className="runtime-table">
                <thead>
                  <tr><th>시간</th><th>작업</th><th>상태</th><th>Revision</th><th>변경</th><th>검증</th><th>작업</th></tr>
                </thead>
                <tbody>
                  {historyItems.map((item) => {
                    const rollbackRevision = configurationRollbackTargetRevision(item, currentRevision);
                    const canRollback = rollbackRevision !== null
                      && writeAvailable
                      && !locked
                      && !rollbackPending
                      && review === null;
                    return (
                      <tr key={item.operation_id}>
                        <td>{formatTimestamp(item.created_at)}</td>
                        <td>{historyKindLabel(item.kind)}</td>
                        <td><Label color={statusColor(item.status)}>{historyStatusLabel(item.status)}</Label></td>
                        <td>
                          {revisionLabel(item)}
                          {item.target_revision !== null ? <small>대상 r{item.target_revision}</small> : null}
                        </td>
                        <td>
                          {item.changes.length}
                          <small>{item.changes.map((change) => change.key).join(', ')}</small>
                        </td>
                        <td>{item.verification ? (item.verification.synchronized ? '동기화 확인' : '동기화 불일치') : '—'}</td>
                        <td>
                          {rollbackRevision !== null ? (
                            <Button
                              size="sm"
                              variant="secondary"
                              isDisabled={!canRollback}
                              onClick={() => planMutation.mutate({
                                baseRevision: currentRevision,
                                targetRevision: rollbackRevision,
                                etag,
                              })}
                            >r{rollbackRevision} 상태로 복원 검토</Button>
                          ) : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {historyQuery.hasNextPage ? (
            <div className="review-actions">
              <Button
                variant="secondary"
                isDisabled={historyQuery.isFetchingNextPage}
                onClick={() => void historyQuery.fetchNextPage()}
              >{historyQuery.isFetchingNextPage ? '불러오는 중…' : '이전 기록 더 보기'}</Button>
            </div>
          ) : null}
        </CardBody>
      </Card>

      {actionError ? <Alert isInline variant="danger" title="설정 복원을 완료하지 못했습니다.">{actionError}</Alert> : null}

      {review ? (
        <Card className="review-card">
          <CardTitle>이전 설정 상태 복원 검토</CardTitle>
          <CardBody>
            <Alert isInline variant="warning" title={`Revision ${review.plan.target_revision} 상태를 기준으로 새 설정 변경을 생성합니다.`}>
              revision 번호는 과거로 돌아가지 않습니다. 적용에 성공하면 새 revision {review.plan.candidate_revision}이 생성됩니다.
            </Alert>
            <dl className="facts compact-facts">
              <dt>현재 revision</dt><dd>{review.plan.base_revision}</dd>
              <dt>복원 대상 revision</dt><dd>{review.plan.target_revision}</dd>
              <dt>적용 후 revision</dt><dd>{review.plan.candidate_revision}</dd>
              <dt>실제 변경 발생</dt><dd>{review.plan.would_change ? '예' : '아니요'}</dd>
              <dt>계획 digest</dt><dd><code>{review.plan.plan_digest}</code></dd>
            </dl>
            <div className="table-scroll configuration-review-table">
              <table className="runtime-table">
                <thead><tr><th>키</th><th>작업</th><th>운영자 값 이전</th><th>운영자 값 이후</th><th>적용 값 이후</th><th>변경 위험</th></tr></thead>
                <tbody>
                  {review.plan.changes.map((change) => (
                    <tr key={change.key}>
                      <td><code>{change.key}</code></td>
                      <td>{change.operation}</td>
                      <td>{formatValue(change.operator_before)}</td>
                      <td>{formatValue(change.operator_after)}</td>
                      <td>{formatValue(change.effective_after)}</td>
                      <td>{change.risk}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!review.plan.would_change ? (
              <Alert isInline variant="info" title="복원으로 변경되는 운영자 설정이 없습니다.">적용하지 않습니다.</Alert>
            ) : null}
            <div className="review-actions">
              <Button
                variant="secondary"
                isDisabled={rollbackPending}
                onClick={() => {
                  setReview(null);
                  onReviewActiveChange(false);
                }}
              >복원 검토 닫기</Button>
              <Button
                variant="primary"
                isDanger
                isDisabled={!review.plan.would_change || rollbackPending}
                onClick={() => applyMutation.mutate(review)}
              >{applyMutation.isPending ? '복원 적용·검증 중…' : '검토한 상태로 복원'}</Button>
            </div>
          </CardBody>
        </Card>
      ) : null}

      {lastRollback ? (
        <Card>
          <CardTitle>복원 적용 결과</CardTitle>
          <CardBody>
            <dl className="facts operation-facts">
              <dt>작업 ID</dt><dd><code>{lastRollback.operation_id}</code></dd>
              <dt>상태</dt><dd>{historyStatusLabel(lastRollback.status)}</dd>
              <dt>복원 대상 revision</dt><dd>{lastRollback.target_revision}</dd>
              <dt>새 revision</dt><dd>{lastRollback.revision}</dd>
              <dt>변경됨</dt><dd>{lastRollback.changed ? '예' : '아니요'}</dd>
              <dt>저장소 revision</dt><dd>{lastRollback.verification.store_revision ?? '—'}</dd>
              <dt>Resolver revision</dt><dd>{lastRollback.verification.resolver_revision}</dd>
              <dt>런타임 revision</dt><dd>{lastRollback.verification.runtime_revision}</dd>
              <dt>동기화</dt><dd>{lastRollback.verification.synchronized ? '예' : '아니요'}</dd>
            </dl>
          </CardBody>
        </Card>
      ) : null}
    </>
  );
}
