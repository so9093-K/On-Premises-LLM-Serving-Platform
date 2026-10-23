import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, CardBody, CardTitle, Label, Spinner } from '@patternfly/react-core';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';

import {
  fetchConfigurationHistory,
  fetchMainModelOperations,
  fetchRuntimeOperations,
  type ConfigurationHistoryItem,
  type MainModelOperation,
  type RuntimeOperation,
} from './api';
import { apiErrorMessage, isUnauthorized } from './apiFeedback';
import {
  mainRuntimeDiagnosticsUrl,
  requestLogDiagnosticsUrl,
} from './activityDiagnostics';
import { formatTimestamp, isoTimestamp } from './timeFormat';
import { mergeOperationPages } from './operationsHistory';

type OperationsPageProps = {
  token: string | null;
  onUnauthorized: () => void;
  deploymentFeatures: readonly string[];
  grafanaUrl: string | null;
  runtimeBackend: string;
};

type LabelColor = 'blue' | 'green' | 'orange' | 'red' | 'grey';
type ActivitySourceKey = 'runtime' | 'main-model' | 'configuration';
type ActivityFilter = 'all' | ActivitySourceKey;

type ActivityItem = {
  key: string;
  source: ActivitySourceKey;
  sourceLabel: string;
  sourceColor: LabelColor;
  updatedAt: number;
  title: string;
  status: string;
  statusColor: LabelColor;
  phase: string;
  detail: string;
  metadata: Array<{ label: string; value: string }>;
  diagnostics: Array<{ label: string; href: string }>;
};

function runtimeStatusColor(status: RuntimeOperation['status']): LabelColor {
  if (status === 'verified') return 'green';
  if (status === 'noop') return 'grey';
  if (status === 'rejected') return 'orange';
  if (status === 'pending') return 'blue';
  return 'red';
}

function mainModelStatusColor(status: MainModelOperation['status']): LabelColor {
  if (status === 'completed') return 'green';
  if (status === 'failed') return 'orange';
  if (status === 'rollback_failed') return 'red';
  return 'blue';
}

function configurationStatusColor(status: ConfigurationHistoryItem['status']): LabelColor {
  if (status === 'verified') return 'green';
  if (status === 'noop') return 'grey';
  if (status === 'rejected') return 'orange';
  if (status === 'recovered_after_restart') return 'blue';
  if (status === 'pending') return 'blue';
  return 'red';
}

function runtimeVerification(value: unknown): string {
  if (typeof value !== 'object' || value === null) return '검증 정보 없음';
  const converged = (value as Record<string, unknown>).converged;
  if (converged === true) return '목표 상태로 수렴';
  if (converged === false) return '목표 상태로 수렴하지 않음';
  return '검증 정보 기록됨';
}

function mainModelFailure(operation: MainModelOperation): string | null {
  if (operation.error && operation.rollback_error) {
    return `${operation.error} · 복구: ${operation.rollback_error}`;
  }
  if (operation.error) return operation.error;
  if (operation.rollback_error) return `복구: ${operation.rollback_error}`;
  return null;
}

function configurationVerification(item: ConfigurationHistoryItem): string {
  if (item.verification === null) return '검증 정보 없음';
  return item.verification.synchronized ? '설정 동기화 확인' : '설정 동기화 불일치';
}

function actorText(actor: { auth_method: string; actor_id: string }): string {
  return `${actor.actor_id} · ${actor.auth_method}`;
}

function runtimeActivity(operation: RuntimeOperation, grafanaUrl: string | null): ActivityItem {
  const detail = [
    runtimeVerification(operation.verification),
    operation.force ? '필요한 런타임 자동 중지 허용' : null,
    operation.durable ? '영구 기록' : '메모리 기록',
  ].filter(Boolean).join(' · ');

  return {
    key: `runtime:${operation.operation_id}`,
    source: 'runtime',
    sourceLabel: '런타임',
    sourceColor: 'blue',
    updatedAt: operation.updated_at,
    title: `${operation.service_key} → ${operation.desired_state}`,
    status: operation.status,
    statusColor: runtimeStatusColor(operation.status),
    phase: operation.phase,
    detail,
    metadata: [
      { label: '작업 ID', value: operation.operation_id },
      { label: '요청 ID', value: operation.request_id },
      { label: '실행 주체', value: actorText(operation.actor) },
      { label: '계획 digest', value: operation.plan_digest ?? '—' },
    ],
    diagnostics: (() => {
      const href = requestLogDiagnosticsUrl(grafanaUrl, operation.request_id, operation.updated_at);
      return href ? [{ label: '요청 로그', href }] : [];
    })(),
  };
}

function mainModelActivity(
  operation: MainModelOperation,
  grafanaUrl: string | null,
  runtimeBackend: string,
): ActivityItem {
  const failure = mainModelFailure(operation);
  const detail = failure
    ?? (operation.recovered_after_restart
      ? '재시작 뒤 런타임 재관측으로 최종 상태를 복구했습니다.'
      : `현재 단계: ${operation.stage}`);

  return {
    key: `main-model:${operation.id}`,
    source: 'main-model',
    sourceLabel: '메인 모델',
    sourceColor: 'green',
    updatedAt: operation.updated_at,
    title: `${operation.previous_profile ?? '현재 프로필 없음'} → ${operation.requested_profile}`,
    status: operation.status,
    statusColor: mainModelStatusColor(operation.status),
    phase: operation.stage,
    detail,
    metadata: [
      { label: '작업 ID', value: operation.id },
      { label: '클라이언트 요청 ID', value: operation.client_request_id ?? '—' },
      { label: '이전 프로필', value: operation.previous_profile ?? '—' },
      { label: '재시작 후 복구', value: operation.recovered_after_restart ? '예' : '아니요' },
    ],
    diagnostics: (() => {
      const href = mainRuntimeDiagnosticsUrl(grafanaUrl, runtimeBackend, operation.updated_at);
      return href ? [{ label: '메인 런타임 상태', href }] : [];
    })(),
  };
}

function configurationActivity(operation: ConfigurationHistoryItem, grafanaUrl: string | null): ActivityItem {
  const operationLabel = operation.kind === 'configuration_rollback' ? '이전 상태 복원' : '설정 변경';
  const revision = operation.applied_revision ?? operation.candidate_revision;
  return {
    key: `configuration:${operation.operation_id}`,
    source: 'configuration',
    sourceLabel: '설정',
    sourceColor: 'grey',
    updatedAt: operation.updated_at,
    title: `${operationLabel}: revision ${operation.base_revision} → ${revision}`,
    status: operation.status,
    statusColor: configurationStatusColor(operation.status),
    phase: operation.phase,
    detail: `${operation.changes.length}개 변경 · ${configurationVerification(operation)}`,
    metadata: [
      { label: '작업 ID', value: operation.operation_id },
      { label: '요청 ID', value: operation.request_id },
      { label: '실행 주체', value: actorText(operation.actor) },
      { label: '계획 digest', value: operation.plan_digest },
    ],
    diagnostics: (() => {
      const href = requestLogDiagnosticsUrl(grafanaUrl, operation.request_id, operation.updated_at);
      return href ? [{ label: '요청 로그', href }] : [];
    })(),
  };
}

function sourceCountLabel(source: ActivitySourceKey, count: number): string {
  if (source === 'runtime') return `런타임 ${count}`;
  if (source === 'main-model') return `메인 모델 ${count}`;
  return `설정 ${count}`;
}

function activityStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    verified: '검증 완료',
    noop: '변경 없음',
    rejected: '거부됨',
    pending: '진행 중',
    completed: '완료',
    failed: '실패',
    rollback_failed: '복구 실패',
    recovered_after_restart: '재시작 후 복구',
  };
  return labels[status] ?? status;
}

export function OperationsPage({ token, onUnauthorized, deploymentFeatures, grafanaUrl, runtimeBackend }: OperationsPageProps) {
  const authClass = token === null ? 'anonymous' : 'authenticated';
  const runtimeEnabled = deploymentFeatures.includes('runtime_control');
  const mainModelEnabled = deploymentFeatures.includes('model_switching');
  const pollWhileVisible = () => document.visibilityState === 'visible' ? 10_000 : false;
  const [filter, setFilter] = useState<ActivityFilter>('all');

  const runtimeQuery = useInfiniteQuery({
    queryKey: ['operations', 'runtime', authClass],
    queryFn: ({ pageParam }) => fetchRuntimeOperations(token, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: runtimeEnabled,
    retry: false,
    refetchInterval: (query) =>
      (query.state.data?.pages.length ?? 0) > 1 ? false : pollWhileVisible(),
    refetchIntervalInBackground: false,
  });
  const mainModelQuery = useQuery({
    queryKey: ['operations', 'main-model', authClass],
    queryFn: () => fetchMainModelOperations(token),
    enabled: mainModelEnabled,
    retry: false,
    refetchInterval: pollWhileVisible,
    refetchIntervalInBackground: false,
  });
  const configurationQuery = useInfiniteQuery({
    queryKey: ['operations', 'configuration', authClass],
    queryFn: ({ pageParam }) => fetchConfigurationHistory(token, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    retry: false,
    refetchInterval: (query) =>
      (query.state.data?.pages.length ?? 0) > 1 ? false : pollWhileVisible(),
    refetchIntervalInBackground: false,
  });

  useEffect(() => {
    if (
      isUnauthorized(runtimeQuery.error)
      || isUnauthorized(mainModelQuery.error)
      || isUnauthorized(configurationQuery.error)
    ) {
      onUnauthorized();
    }
  }, [configurationQuery.error, mainModelQuery.error, onUnauthorized, runtimeQuery.error]);

  const runtimeItems = useMemo(() => mergeOperationPages(
    runtimeQuery.data?.pages.map((page) => page.items) ?? [],
  ), [runtimeQuery.data]);
  const configurationItems = useMemo(() => mergeOperationPages(
    configurationQuery.data?.pages.map((page) => page.items) ?? [],
  ), [configurationQuery.data]);

  const activity = useMemo(() => {
    const items: ActivityItem[] = [];
    if (runtimeEnabled) {
      items.push(...runtimeItems.map((item) => runtimeActivity(item, grafanaUrl)));
    }
    if (mainModelEnabled && mainModelQuery.data) {
      items.push(...mainModelQuery.data.items.map((item) => mainModelActivity(item, grafanaUrl, runtimeBackend)));
    }
    items.push(...configurationItems.map((item) => configurationActivity(item, grafanaUrl)));
    return items.sort((left, right) => (
      right.updatedAt - left.updatedAt || left.key.localeCompare(right.key)
    ));
  }, [
    configurationItems,
    grafanaUrl,
    mainModelEnabled,
    mainModelQuery.data,
    runtimeBackend,
    runtimeEnabled,
    runtimeItems,
  ]);

  const filteredActivity = filter === 'all'
    ? activity
    : activity.filter((item) => item.source === filter);

  const runtimeCount = runtimeEnabled ? runtimeItems.length : 0;
  const mainModelCount = mainModelEnabled ? (mainModelQuery.data?.items.length ?? 0) : 0;
  const configurationCount = configurationItems.length;
  const isRefreshing = (
    (runtimeEnabled && runtimeQuery.isFetching)
    || (mainModelEnabled && mainModelQuery.isFetching)
    || configurationQuery.isFetching
  );
  const isInitialLoading = (
    (runtimeEnabled && runtimeQuery.isPending)
    || (mainModelEnabled && mainModelQuery.isPending)
    || configurationQuery.isPending
  ) && activity.length === 0;
  const hasOlderHistory = runtimeQuery.hasNextPage || configurationQuery.hasNextPage;
  const olderPagesLoaded = (runtimeQuery.data?.pages.length ?? 0) > 1
    || (configurationQuery.data?.pages.length ?? 0) > 1;

  const filters: Array<{ key: ActivityFilter; label: string; disabled?: boolean }> = [
    { key: 'all', label: `전체 ${activity.length}` },
    {
      key: 'runtime',
      label: runtimeEnabled ? sourceCountLabel('runtime', runtimeCount) : '런타임 해당 없음',
      disabled: !runtimeEnabled,
    },
    {
      key: 'main-model',
      label: mainModelEnabled ? sourceCountLabel('main-model', mainModelCount) : '메인 모델 해당 없음',
      disabled: !mainModelEnabled,
    },
    {
      key: 'configuration',
      label: sourceCountLabel('configuration', configurationCount),
    },
  ];

  return (
    <section className="runtime-page">
      <div className="page-heading">
        <div>
          <h1>운영 활동</h1>
          <p>모델 전환 · 런타임 시작·중지 · 설정 변경</p>
        </div>
        <Button
          variant="secondary"
          isDisabled={isRefreshing}
          onClick={() => {
            if (runtimeEnabled) void runtimeQuery.refetch();
            if (mainModelEnabled) void mainModelQuery.refetch();
            void configurationQuery.refetch();
          }}
        >
          {isRefreshing ? '새로고침 중…' : '새로고침'}
        </Button>
      </div>

      {runtimeEnabled && runtimeQuery.isError ? (
        <Alert isInline variant="warning" title="런타임 활동을 불러오지 못했습니다.">
          다른 영역의 활동은 계속 표시합니다. {apiErrorMessage(runtimeQuery.error)}
        </Alert>
      ) : null}
      {mainModelEnabled && mainModelQuery.isError ? (
        <Alert isInline variant="warning" title="메인 모델 활동을 불러오지 못했습니다.">
          다른 영역의 작업 기록은 계속 표시합니다. {apiErrorMessage(mainModelQuery.error)}
        </Alert>
      ) : null}
      {configurationQuery.isError ? (
        <Alert isInline variant="warning" title="설정 활동을 불러오지 못했습니다.">
          다른 source의 activity는 계속 표시합니다. {apiErrorMessage(configurationQuery.error)}
        </Alert>
      ) : null}

      <Card>
        <CardTitle>최근 운영 작업</CardTitle>
        <CardBody>
          <p className="configuration-help activity-intro">
            운영 변경 이력 · 추론 요청 로그와 구분
          </p>

          {activity.length > 0 ? (
            <div className="activity-filters" role="group" aria-label="활동 영역 필터">
              {filters.filter((item) => !item.disabled).map((item) => (
                <Button
                  key={item.key}
                  variant={filter === item.key ? 'primary' : 'secondary'}
                  aria-pressed={filter === item.key}
                  onClick={() => setFilter(item.key)}
                >
                  {item.label}
                </Button>
              ))}
            </div>
          ) : null}

          {isInitialLoading ? (
            <div className="inline-loading">
              <Spinner size="md" aria-label="최근 활동 불러오는 중" />
              최근 활동을 불러오는 중입니다.
            </div>
          ) : filteredActivity.length === 0 ? (
            <div className="empty-state">
              <strong>{filter === 'all' ? '아직 기록된 운영 활동이 없습니다.' : '선택한 영역에 최근 활동이 없습니다.'}</strong>
              <p>
                런타임 시작·중지, 메인 모델 전환, 설정 변경이 발생하면 이곳에 시간순으로 표시됩니다.
              </p>
            </div>
          ) : (
            <ol className="activity-timeline">
              {filteredActivity.map((item) => (
                <li className="activity-timeline-item" data-tone={item.statusColor} key={item.key}>
                  <span className="activity-timeline-marker" aria-hidden="true" />
                  <article className="activity-event">
                    <header className="activity-event-header">
                      <div className="activity-event-heading">
                        <div className="activity-event-labels">
                          <Label color={item.sourceColor}>{item.sourceLabel}</Label>
                          <Label color={item.statusColor}>{activityStatusLabel(item.status)}</Label>
                        </div>
                        <strong>{item.title}</strong>
                      </div>
                      <time dateTime={isoTimestamp(item.updatedAt)}>
                        {formatTimestamp(item.updatedAt)}
                      </time>
                    </header>
                    <p className="activity-event-detail">
                      <span className="activity-phase">{item.phase}</span>
                      <span>{item.detail}</span>
                    </p>
                    <details className="activity-details">
                      <summary>작업 식별자 및 기술 상세 보기</summary>
                      <dl className="facts compact-facts">
                        {item.metadata.map((entry) => (
                          <div className="activity-fact" key={entry.label}>
                            <dt>{entry.label}</dt>
                            <dd><code>{entry.value}</code></dd>
                          </div>
                        ))}
                      </dl>
                    </details>
                    {item.diagnostics.length ? (
                      <div className="activity-diagnostics" aria-label="진단 링크">
                        {item.diagnostics.map((diagnostic) => (
                          <a
                            className="activity-diagnostic-link"
                            href={diagnostic.href}
                            key={diagnostic.label}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {diagnostic.label} ↗
                          </a>
                        ))}
                      </div>
                    ) : null}
                  </article>
                </li>
              ))}
            </ol>
          )}

          {olderPagesLoaded ? (
            <p className="configuration-help" role="status">
              이전 작업 내역을 펼친 동안에는 해당 영역의 자동 갱신을 중지합니다. 최신 작업 상태를 확인하려면 상단 새로고침을 누르세요.
            </p>
          ) : null}

          {hasOlderHistory ? (
            <div className="activity-pagination" role="group" aria-label="이전 운영 활동 보기">
              {runtimeQuery.hasNextPage ? (
                <Button variant="secondary" isDisabled={runtimeQuery.isFetchingNextPage} onClick={() => { void runtimeQuery.fetchNextPage(); }}>
                  {runtimeQuery.isFetchingNextPage ? '런타임 작업 불러오는 중…' : '이전 런타임 작업 더 보기'}
                </Button>
              ) : null}
              {configurationQuery.hasNextPage ? (
                <Button variant="secondary" isDisabled={configurationQuery.isFetchingNextPage} onClick={() => { void configurationQuery.fetchNextPage(); }}>
                  {configurationQuery.isFetchingNextPage ? '설정 변경 불러오는 중…' : '이전 설정 변경 더 보기'}
                </Button>
              ) : null}
              <p className="configuration-help">기존 History API의 이전 페이지를 불러옵니다. 조회한 작업은 위 목록과 필터에 반영됩니다.</p>
            </div>
          ) : null}
          {runtimeQuery.isFetchNextPageError || configurationQuery.isFetchNextPageError ? (
            <Alert isInline variant="warning" title="이전 운영 활동을 불러오지 못했습니다.">
              이미 확인한 작업은 유지됩니다. 다시 시도하려면 해당 버튼을 누르세요.
            </Alert>
          ) : null}
        </CardBody>
      </Card>
    </section>
  );
}
