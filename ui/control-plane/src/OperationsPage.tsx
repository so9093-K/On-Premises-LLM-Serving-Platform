import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, CardBody, CardTitle, Label, Spinner } from '@patternfly/react-core';
import { useQuery } from '@tanstack/react-query';

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

type OperationsPageProps = {
  token: string | null;
  onUnauthorized: () => void;
  deploymentFeatures: readonly string[];
  grafanaUrl: string | null;
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

function formatTimestamp(value: number): string {
  return new Date(value * 1000).toLocaleString('ko-KR');
}

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

function mainModelActivity(operation: MainModelOperation, grafanaUrl: string | null): ActivityItem {
  const failure = mainModelFailure(operation);
  const detail = failure
    ?? (operation.recovered_after_restart
      ? 'process restart 뒤 runtime 재관측으로 terminal 상태를 복구했습니다.'
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
      const href = mainRuntimeDiagnosticsUrl(grafanaUrl, operation.updated_at);
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
      return href ? [{ label: 'Request logs', href }] : [];
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

export function OperationsPage({ token, onUnauthorized, deploymentFeatures, grafanaUrl }: OperationsPageProps) {
  const authClass = token === null ? 'anonymous' : 'authenticated';
  const runtimeEnabled = deploymentFeatures.includes('runtime_control');
  const mainModelEnabled = deploymentFeatures.includes('model_switching');
  const pollWhileVisible = () => document.visibilityState === 'visible' ? 10_000 : false;
  const [filter, setFilter] = useState<ActivityFilter>('all');

  const runtimeQuery = useQuery({
    queryKey: ['operations', 'runtime', authClass],
    queryFn: () => fetchRuntimeOperations(token),
    enabled: runtimeEnabled,
    retry: false,
    refetchInterval: pollWhileVisible,
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
  const configurationQuery = useQuery({
    queryKey: ['operations', 'configuration', authClass],
    queryFn: () => fetchConfigurationHistory(token),
    retry: false,
    refetchInterval: pollWhileVisible,
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

  const activity = useMemo(() => {
    const items: ActivityItem[] = [];
    if (runtimeEnabled && runtimeQuery.data) {
      items.push(...runtimeQuery.data.items.map((item) => runtimeActivity(item, grafanaUrl)));
    }
    if (mainModelEnabled && mainModelQuery.data) {
      items.push(...mainModelQuery.data.items.map((item) => mainModelActivity(item, grafanaUrl)));
    }
    if (configurationQuery.data) {
      items.push(...configurationQuery.data.items.map((item) => configurationActivity(item, grafanaUrl)));
    }
    return items.sort((left, right) => (
      right.updatedAt - left.updatedAt || left.key.localeCompare(right.key)
    ));
  }, [
    configurationQuery.data,
    grafanaUrl,
    mainModelEnabled,
    mainModelQuery.data,
    runtimeEnabled,
    runtimeQuery.data,
  ]);

  const filteredActivity = filter === 'all'
    ? activity
    : activity.filter((item) => item.source === filter);

  const runtimeCount = runtimeEnabled ? (runtimeQuery.data?.items.length ?? 0) : 0;
  const mainModelCount = mainModelEnabled ? (mainModelQuery.data?.items.length ?? 0) : 0;
  const configurationCount = configurationQuery.data?.items.length ?? 0;
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
  const hasOlderHistory = Boolean(
    runtimeQuery.data?.next_cursor || configurationQuery.data?.next_cursor,
  );

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
          <h1>활동</h1>
          <p>런타임, 메인 모델, 설정에서 발생한 최근 운영 작업을 시간순으로 확인합니다.</p>
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
          다른 source의 activity는 계속 표시합니다. {apiErrorMessage(mainModelQuery.error)}
        </Alert>
      ) : null}
      {configurationQuery.isError ? (
        <Alert isInline variant="warning" title="설정 활동을 불러오지 못했습니다.">
          다른 source의 activity는 계속 표시합니다. {apiErrorMessage(configurationQuery.error)}
        </Alert>
      ) : null}

      <Card>
        <CardTitle>최근 활동</CardTitle>
        <CardBody>
          <p className="configuration-help activity-intro">
            각 영역이 기록한 최근 운영 작업을 시간순으로 모아 보여줍니다. 원본 작업 이력과 검증 근거의 소유권은 각 런타임·메인 모델·설정 영역에 그대로 있습니다.
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
                      <time dateTime={new Date(item.updatedAt * 1000).toISOString()}>
                        {formatTimestamp(item.updatedAt)}
                      </time>
                    </header>
                    <p className="activity-event-detail">
                      <span className="activity-phase">{item.phase}</span>
                      <span>{item.detail}</span>
                    </p>
                    <details className="activity-details">
                      <summary>작업 상세 정보</summary>
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

          {hasOlderHistory ? (
            <p className="configuration-help">
              이 화면은 최근 기록을 우선 보여줍니다. 더 오래된 런타임·설정 이력은 각 영역의 원본 history API가 계속 소유합니다.
            </p>
          ) : null}
        </CardBody>
      </Card>
    </section>
  );
}
