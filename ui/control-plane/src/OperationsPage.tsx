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

type OperationsPageProps = {
  token: string | null;
  onUnauthorized: () => void;
  deploymentFeatures: readonly string[];
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
  if (typeof value !== 'object' || value === null) return 'verification 없음';
  const converged = (value as Record<string, unknown>).converged;
  if (converged === true) return '목표 상태로 수렴';
  if (converged === false) return '목표 상태로 수렴하지 않음';
  return 'verification 기록됨';
}

function mainModelFailure(operation: MainModelOperation): string | null {
  if (operation.error && operation.rollback_error) {
    return `${operation.error} · rollback: ${operation.rollback_error}`;
  }
  if (operation.error) return operation.error;
  if (operation.rollback_error) return `rollback: ${operation.rollback_error}`;
  return null;
}

function configurationVerification(item: ConfigurationHistoryItem): string {
  if (item.verification === null) return 'verification 없음';
  return item.verification.synchronized ? 'configuration 동기화 확인' : 'configuration 동기화 불일치';
}

function actorText(actor: { auth_method: string; actor_id: string }): string {
  return `${actor.actor_id} · ${actor.auth_method}`;
}

function runtimeActivity(operation: RuntimeOperation): ActivityItem {
  const detail = [
    runtimeVerification(operation.verification),
    operation.force ? 'auto-stop 허용' : null,
    operation.durable ? 'persisted evidence' : 'in-memory evidence',
  ].filter(Boolean).join(' · ');

  return {
    key: `runtime:${operation.operation_id}`,
    source: 'runtime',
    sourceLabel: 'Runtime',
    sourceColor: 'blue',
    updatedAt: operation.updated_at,
    title: `${operation.service_key} → ${operation.desired_state}`,
    status: operation.status,
    statusColor: runtimeStatusColor(operation.status),
    phase: operation.phase,
    detail,
    metadata: [
      { label: 'Operation ID', value: operation.operation_id },
      { label: 'Request ID', value: operation.request_id },
      { label: 'Actor', value: actorText(operation.actor) },
      { label: 'Plan digest', value: operation.plan_digest ?? '—' },
    ],
  };
}

function mainModelActivity(operation: MainModelOperation): ActivityItem {
  const failure = mainModelFailure(operation);
  const detail = failure
    ?? (operation.recovered_after_restart
      ? 'process restart 뒤 runtime 재관측으로 terminal 상태를 복구했습니다.'
      : `현재 stage: ${operation.stage}`);

  return {
    key: `main-model:${operation.id}`,
    source: 'main-model',
    sourceLabel: 'Main Model',
    sourceColor: 'green',
    updatedAt: operation.updated_at,
    title: `${operation.previous_profile ?? 'no active profile'} → ${operation.requested_profile}`,
    status: operation.status,
    statusColor: mainModelStatusColor(operation.status),
    phase: operation.stage,
    detail,
    metadata: [
      { label: 'Operation ID', value: operation.id },
      { label: 'Client request ID', value: operation.client_request_id ?? '—' },
      { label: 'Previous profile', value: operation.previous_profile ?? '—' },
      { label: 'Recovered after restart', value: operation.recovered_after_restart ? 'yes' : 'no' },
    ],
  };
}

function configurationActivity(operation: ConfigurationHistoryItem): ActivityItem {
  const operationLabel = operation.kind === 'configuration_rollback' ? 'Rollback' : 'Apply';
  const revision = operation.applied_revision ?? operation.candidate_revision;
  return {
    key: `configuration:${operation.operation_id}`,
    source: 'configuration',
    sourceLabel: 'Configuration',
    sourceColor: 'grey',
    updatedAt: operation.updated_at,
    title: `${operationLabel}: revision ${operation.base_revision} → ${revision}`,
    status: operation.status,
    statusColor: configurationStatusColor(operation.status),
    phase: operation.phase,
    detail: `${operation.changes.length}개 change · ${configurationVerification(operation)}`,
    metadata: [
      { label: 'Operation ID', value: operation.operation_id },
      { label: 'Request ID', value: operation.request_id },
      { label: 'Actor', value: actorText(operation.actor) },
      { label: 'Plan digest', value: operation.plan_digest },
    ],
  };
}

function sourceCountLabel(source: ActivitySourceKey, count: number): string {
  if (source === 'runtime') return `Runtime ${count}`;
  if (source === 'main-model') return `Main Model ${count}`;
  return `Configuration ${count}`;
}

export function OperationsPage({ token, onUnauthorized, deploymentFeatures }: OperationsPageProps) {
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
      items.push(...runtimeQuery.data.items.map(runtimeActivity));
    }
    if (mainModelEnabled && mainModelQuery.data) {
      items.push(...mainModelQuery.data.items.map(mainModelActivity));
    }
    if (configurationQuery.data) {
      items.push(...configurationQuery.data.items.map(configurationActivity));
    }
    return items.sort((left, right) => (
      right.updatedAt - left.updatedAt || left.key.localeCompare(right.key)
    ));
  }, [
    configurationQuery.data,
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
    { key: 'all', label: `All ${activity.length}` },
    {
      key: 'runtime',
      label: runtimeEnabled ? sourceCountLabel('runtime', runtimeCount) : 'Runtime N/A',
      disabled: !runtimeEnabled,
    },
    {
      key: 'main-model',
      label: mainModelEnabled ? sourceCountLabel('main-model', mainModelCount) : 'Main Model N/A',
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
          <h1>Activity</h1>
          <p>Runtime, Main Model, Configuration의 최근 operation을 하나의 시간순 read-only projection으로 확인합니다.</p>
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
        <Alert isInline variant="warning" title="Runtime activity를 불러오지 못했습니다.">
          다른 source의 activity는 계속 표시합니다. {apiErrorMessage(runtimeQuery.error)}
        </Alert>
      ) : null}
      {mainModelEnabled && mainModelQuery.isError ? (
        <Alert isInline variant="warning" title="Main Model activity를 불러오지 못했습니다.">
          다른 source의 activity는 계속 표시합니다. {apiErrorMessage(mainModelQuery.error)}
        </Alert>
      ) : null}
      {configurationQuery.isError ? (
        <Alert isInline variant="warning" title="Configuration activity를 불러오지 못했습니다.">
          다른 source의 activity는 계속 표시합니다. {apiErrorMessage(configurationQuery.error)}
        </Alert>
      ) : null}

      <Card>
        <CardTitle>Recent activity</CardTitle>
        <CardBody>
          <p className="configuration-help activity-intro">
            이 화면은 세 operation source의 최근 기록을 시간순으로 합쳐 보여줄 뿐 새 audit authority를 만들지 않습니다.
            각 operation의 영속성, rollback, verification 의미는 원래 Runtime/Main Model/Configuration source가 계속 소유합니다.
          </p>

          <div className="activity-filters" role="group" aria-label="Activity source filter">
            {filters.map((item) => (
              <Button
                key={item.key}
                variant={filter === item.key ? 'primary' : 'secondary'}
                isDisabled={item.disabled}
                aria-pressed={filter === item.key}
                onClick={() => setFilter(item.key)}
              >
                {item.label}
              </Button>
            ))}
          </div>

          {isInitialLoading ? (
            <div className="inline-loading">
              <Spinner size="md" aria-label="Activity loading" />
              최근 operation을 불러오는 중입니다.
            </div>
          ) : filteredActivity.length === 0 ? (
            <p className="activity-empty">
              {filter === 'all' ? '표시할 최근 Activity가 없습니다.' : '선택한 source에 최근 Activity가 없습니다.'}
            </p>
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
                          <Label color={item.statusColor}>{item.status}</Label>
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
                      <summary>Operation details</summary>
                      <dl className="facts compact-facts">
                        {item.metadata.map((entry) => (
                          <div className="activity-fact" key={entry.label}>
                            <dt>{entry.label}</dt>
                            <dd><code>{entry.value}</code></dd>
                          </div>
                        ))}
                      </dl>
                    </details>
                  </article>
                </li>
              ))}
            </ol>
          )}

          {hasOlderHistory ? (
            <p className="configuration-help">
              이 화면은 최근 기록만 합칩니다. Runtime과 Configuration의 더 오래된 durable history는 각 source의 cursor API가 계속 소유합니다.
            </p>
          ) : null}
        </CardBody>
      </Card>
    </section>
  );
}
