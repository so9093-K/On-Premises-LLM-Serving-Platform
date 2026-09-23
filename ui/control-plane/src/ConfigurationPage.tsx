import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, CardBody, CardTitle, Label, Spinner } from '@patternfly/react-core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  ApiError,
  applyConfigurationChange,
  fetchConfigurationEffective,
  fetchConfigurationSchema,
  planConfigurationChange,
  type ConfigurationApplyResponse,
  type ConfigurationChange,
  type ConfigurationEffectiveItem,
  type ConfigurationPlanResponse,
  type ConfigurationSchemaItem,
} from './api';
import { ConfigurationHistoryPanel } from './ConfigurationHistoryPanel';
import { apiErrorMessage, isUnauthorized } from './apiFeedback';
import {
  configurationApplyRequest,
  configurationItemApplies,
  configurationResetChange,
  configurationSetChange,
  parseConfigurationDraft,
} from './configurationSafety';
import { riskLabel, sourceLabel, t, yesNoLabel } from './uiText';

type ConfigurationPageProps = {
  token: string | null;
  onUnauthorized: () => void;
  deploymentFeatures: readonly string[];
};

type ReviewedConfiguration = {
  plan: ConfigurationPlanResponse;
  changes: ConfigurationChange[];
  etag: string;
};

type PlanIntent = {
  baseRevision: number;
  etag: string;
  changes: ConfigurationChange[];
};

type ConfigurationDraft = string | number | boolean | null;

function isRevisionConflict(error: unknown): boolean {
  return error instanceof ApiError
    && error.status === 412
    && error.code === 'CONFIG_REVISION_CONFLICT';
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && isRevisionConflict(error)) {
    return `${error.message} 설정 상태가 검토 시점과 달라졌으므로 새 상태를 조회한 뒤 변경 내용을 다시 검토하세요.`;
  }
  if (error instanceof ApiError && error.code === 'CONFIGURATION_APPLY_FAILED') {
    const details = typeof error.details === 'object' && error.details !== null
      ? error.details as Record<string, unknown>
      : null;
    const operationId = typeof details?.operation_id === 'string' ? details.operation_id : null;
    return operationId
      ? `${error.message} 작업 ID: ${operationId}. 현재 상태를 다시 조회한 뒤 변경 내용을 다시 검토하세요.`
      : `${error.message} 현재 상태를 다시 조회한 뒤 변경 내용을 다시 검토하세요.`;
  }
  return apiErrorMessage(error);
}

function formatConfigurationValue(metadata: ConfigurationSchemaItem, value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (Array.isArray(value)) return value.join(', ');
  if (typeof value === 'object') return JSON.stringify(value);
  if (typeof value === 'number') {
    if (metadata.unit === 'bytes' && value >= 1024 * 1024) {
      const mib = value / (1024 * 1024);
      return `${Number.isInteger(mib) ? mib : mib.toFixed(1)} MiB`;
    }
    if (metadata.unit === 'seconds' && value >= 60 && value % 60 === 0) {
      return `${value / 60}분`;
    }
    if (metadata.unit === 'items') return value.toLocaleString('ko-KR');
  }
  return String(value);
}

function displayValue(metadata: ConfigurationSchemaItem, item: ConfigurationEffectiveItem | null): string {
  if (item === null) return '—';
  if (item.sensitive) return item.configured ? '설정됨 (값 숨김)' : '설정되지 않음';
  return formatConfigurationValue(metadata, item.effective_value);
}

function displayOperatorValue(metadata: ConfigurationSchemaItem, item: ConfigurationEffectiveItem | null): string {
  if (item === null) return '—';
  return formatConfigurationValue(metadata, item.operator_value);
}

function draftFromEffective(
  metadata: ConfigurationSchemaItem,
  effective: ConfigurationEffectiveItem,
): ConfigurationDraft {
  const value = effective.operator_value ?? effective.effective_value;
  if (metadata.type === 'boolean') return Boolean(value);
  if (metadata.type === 'enum') {
    const declared = (metadata.enum ?? []).find((candidate) => Object.is(candidate, value));
    return declared === undefined ? '' : declared;
  }
  return value === null || value === undefined ? '' : String(value);
}

function applyStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    verified: '검증 완료',
    noop: '변경 없음',
    rejected: '거부됨',
    pending: '진행 중',
    failed: '실패',
    recovered_after_restart: '재시작 후 복구',
  };
  return labels[status] ?? status;
}

function riskColor(risk: string): 'grey' | 'blue' | 'orange' | 'red' {
  if (risk === 'critical' || risk === 'high') return 'red';
  if (risk === 'medium') return 'orange';
  if (risk === 'low') return 'blue';
  return 'grey';
}

export function ConfigurationPage({ token, onUnauthorized, deploymentFeatures }: ConfigurationPageProps) {
  const queryClient = useQueryClient();
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [draft, setDraft] = useState<ConfigurationDraft>('');
  const [review, setReview] = useState<ReviewedConfiguration | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [lastApply, setLastApply] = useState<ConfigurationApplyResponse | null>(null);
  const [rollbackActive, setRollbackActive] = useState(false);
  const authClass = token === null ? 'anonymous' : 'authenticated';

  const schemaQuery = useQuery({
    queryKey: ['configuration', 'schema', authClass],
    queryFn: () => fetchConfigurationSchema(token),
    retry: false,
    staleTime: 10_000,
  });
  const effectiveQuery = useQuery({
    queryKey: ['configuration', 'effective', authClass],
    queryFn: () => fetchConfigurationEffective(token),
    retry: false,
    staleTime: 10_000,
  });

  useEffect(() => {
    if (isUnauthorized(schemaQuery.error) || isUnauthorized(effectiveQuery.error)) onUnauthorized();
  }, [effectiveQuery.error, onUnauthorized, schemaQuery.error]);

  const refresh = async () => {
    setReview(null);
    setSelectedKey(null);
    await Promise.all([schemaQuery.refetch(), effectiveQuery.refetch()]);
  };

  const planMutation = useMutation({
    mutationFn: (intent: PlanIntent) => planConfigurationChange(token, {
      base_revision: intent.baseRevision,
      changes: intent.changes,
    }),
    retry: false,
    onMutate: () => {
      setActionError(null);
      setLastApply(null);
      setReview(null);
    },
    onSuccess: (plan, intent) => {
      setReview({ plan, changes: intent.changes, etag: intent.etag });
    },
    onError: async (error) => {
      if (isUnauthorized(error)) {
        onUnauthorized();
        return;
      }
      setActionError(errorMessage(error));
      if (isRevisionConflict(error)) {
        setSelectedKey(null);
        await queryClient.invalidateQueries({ queryKey: ['configuration'] });
      }
    },
  });

  const applyMutation = useMutation({
    mutationFn: (reviewed: ReviewedConfiguration) => applyConfigurationChange(
      token,
      reviewed.etag,
      configurationApplyRequest(reviewed.plan, reviewed.changes),
    ),
    retry: false,
    onMutate: () => setActionError(null),
    onSuccess: async (result) => {
      setLastApply(result);
      setReview(null);
      setSelectedKey(null);
      await queryClient.invalidateQueries({ queryKey: ['configuration'] });
    },
    onError: async (error) => {
      if (isUnauthorized(error)) {
        onUnauthorized();
        return;
      }
      setActionError(errorMessage(error));
      // Apply failure는 요청 도달 여부나 persist 단계가 불명확할 수 있다. 같은 review를
      // 재사용하지 않고 canonical state를 다시 읽은 뒤 새 Plan을 요구한다.
      setReview(null);
      setSelectedKey(null);
      await queryClient.invalidateQueries({ queryKey: ['configuration'] });
    },
  });

  const schemaItems = useMemo(
    () => (schemaQuery.data?.items ?? []).filter((item) => item.control_surface === 'configuration'),
    [schemaQuery.data],
  );
  const effectiveByKey = useMemo(() => new Map(
    (effectiveQuery.data?.data.items ?? []).map((item) => [item.key, item]),
  ), [effectiveQuery.data]);
  const selectedMetadata = schemaItems.find((item) => item.key === selectedKey) ?? null;
  const selectedEffective = selectedKey === null ? null : effectiveByKey.get(selectedKey) ?? null;

  if (schemaQuery.isPending || effectiveQuery.isPending) {
    return <div className="inline-loading"><Spinner size="lg" aria-label="설정 불러오는 중" /> 설정을 불러오는 중입니다.</div>;
  }
  if (schemaQuery.isError) {
    return <Alert isInline variant="danger" title="설정 메타데이터를 불러오지 못했습니다.">{errorMessage(schemaQuery.error)}</Alert>;
  }
  if (effectiveQuery.isError) {
    return <Alert isInline variant="danger" title="현재 적용 설정을 불러오지 못했습니다.">{errorMessage(effectiveQuery.error)}</Alert>;
  }

  const schema = schemaQuery.data;
  const effectiveRead = effectiveQuery.data;
  const effective = effectiveRead.data;
  if (schema.version !== effective.version) {
    return (
      <Alert isInline variant="danger" title="설정 계약 버전이 일치하지 않습니다.">
        메타데이터 버전 {schema.version}, 적용 버전 {effective.version}. 안전을 위해 설정 변경을 잠급니다.
      </Alert>
    );
  }

  const writeStatus = effective.write_status;
  const actionPending = planMutation.isPending || applyMutation.isPending;
  const pageActionLocked = actionPending || rollbackActive;

  const submitPlan = (changes: ConfigurationChange[]) => {
    planMutation.mutate({
      baseRevision: effective.revision,
      etag: effectiveRead.etag,
      changes,
    });
  };

  const planSelectedValue = () => {
    if (selectedMetadata === null) return;
    try {
      submitPlan([configurationSetChange(
        selectedMetadata.key,
        parseConfigurationDraft(selectedMetadata, draft),
      )]);
    } catch (error) {
      setActionError(errorMessage(error));
    }
  };

  return (
    <section className="runtime-page">
      <div className="page-heading">
        <div>
          <h1>설정</h1>
          <p>현재 적용값과 출처를 확인하고, 운영자 설정의 변경 영향을 검토한 뒤 적용합니다.</p>
        </div>
        <Button variant="secondary" onClick={() => void refresh()} isDisabled={schemaQuery.isFetching || effectiveQuery.isFetching || pageActionLocked}>
          {schemaQuery.isFetching || effectiveQuery.isFetching ? t('common.refreshing') : t('common.refresh')}
        </Button>
      </div>

      {!writeStatus.available ? (
        <Alert isInline variant="warning" title="설정 변경 기능을 사용할 수 없습니다.">
          이유: {writeStatus.reason ?? '알 수 없음'} · resolver revision: {writeStatus.resolver_revision} · runtime revision: {writeStatus.runtime_revision}
          {writeStatus.pending_operations !== null ? ` · 진행 중 작업: ${writeStatus.pending_operations}` : ''}
        </Alert>
      ) : null}
      {actionError ? <Alert isInline variant="danger" title="설정 작업을 완료하지 못했습니다.">{actionError}</Alert> : null}

      <Card>
        <CardTitle>설정 동기화 상태</CardTitle>
        <CardBody>
          <div className="configuration-sync-summary">
            <Label color={writeStatus.synchronized ? 'green' : 'orange'}>
              {writeStatus.synchronized ? '동기화됨' : '동기화 필요'}
            </Label>
            <strong>revision {effective.revision}</strong>
          </div>
          <details className="operator-details">
            <summary>내부 revision 상세 보기</summary>
            <dl className="facts compact-facts">
              <dt>현재 revision</dt><dd>{effective.revision}</dd>
              <dt>저장소 revision</dt><dd>{writeStatus.store_revision ?? '—'}</dd>
              <dt>Resolver revision</dt><dd>{writeStatus.resolver_revision}</dd>
              <dt>런타임 revision</dt><dd>{writeStatus.runtime_revision}</dd>
              <dt>동기화</dt><dd>{yesNoLabel(writeStatus.synchronized)}</dd>
            </dl>
          </details>
        </CardBody>
      </Card>

      <div className="table-scroll">
        <table className="runtime-table">
          <thead>
            <tr><th>설정</th><th>적용 값</th><th>출처</th><th>운영자 덮어쓰기</th><th>변경 위험</th><th>작업</th></tr>
          </thead>
          <tbody>
            {schemaItems.map((metadata) => {
              const value = effectiveByKey.get(metadata.key) ?? null;
              const applicable = configurationItemApplies(metadata, deploymentFeatures);
              const editable = writeStatus.available && metadata.editable && applicable;
              return (
                <tr key={metadata.key}>
                  <td>
                    <strong>{metadata.label}</strong>
                    <small>{metadata.key}{metadata.unit ? ` · ${metadata.unit}` : ''}</small>
                  </td>
                  <td>{displayValue(metadata, value)}</td>
                  <td>
                    {value?.effective_source ? sourceLabel(value.effective_source) : '—'}
                    {value?.operator_override_shadowed ? <small>운영자 값이 다른 계층에 가려짐</small> : null}
                  </td>
                  <td>{displayOperatorValue(metadata, value)}</td>
                  <td><Label color={riskColor(metadata.risk)}>{riskLabel(metadata.risk)}</Label></td>
                  <td>
                    {applicable ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        isDisabled={!editable || pageActionLocked || value === null}
                        onClick={() => {
                          if (value === null) return;
                          setSelectedKey(metadata.key);
                          setDraft(draftFromEffective(metadata, value));
                          setReview(null);
                          setActionError(null);
                        }}
                      >편집</Button>
                    ) : <Label color="grey">해당 없음</Label>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {selectedMetadata && selectedEffective ? (
        <Card className="review-card">
          <CardTitle>설정 편집 · {selectedMetadata.label}</CardTitle>
          <CardBody>
            <dl className="facts compact-facts">
              <dt>키</dt><dd><code>{selectedMetadata.key}</code></dd>
              <dt>현재 적용 값</dt><dd>{displayValue(selectedMetadata, selectedEffective)}</dd>
              <dt>출처</dt><dd>{sourceLabel(selectedEffective.effective_source)}</dd>
              <dt>운영자 덮어쓰기</dt><dd>{displayOperatorValue(selectedMetadata, selectedEffective)}</dd>
              <dt>적용 방식</dt><dd>{selectedMetadata.apply_mode}</dd>
              <dt>변경 위험</dt><dd>{riskLabel(selectedMetadata.risk)}</dd>
            </dl>
            <p className="configuration-help">{selectedMetadata.help}</p>
            <div className="configuration-editor">
              <label htmlFor="configuration-value">새 운영자 값</label>
              {selectedMetadata.type === 'boolean' ? (
                <label className="configuration-boolean">
                  <input
                    id="configuration-value"
                    type="checkbox"
                    checked={typeof draft === 'boolean' ? draft : false}
                    onChange={(event) => setDraft(event.currentTarget.checked)}
                  />{' '}사용
                </label>
              ) : selectedMetadata.type === 'enum' ? (
                <select
                  id="configuration-value"
                  value={String((selectedMetadata.enum ?? []).findIndex((value) => Object.is(value, draft)))}
                  onChange={(event) => {
                    const index = Number.parseInt(event.currentTarget.value, 10);
                    const values = selectedMetadata.enum ?? [];
                    if (Number.isInteger(index) && index >= 0 && index < values.length) {
                      setDraft(values[index]);
                    }
                  }}
                >
                  {(selectedMetadata.enum ?? []).map((value, index) => (
                    <option key={index} value={String(index)}>{String(value)}</option>
                  ))}
                </select>
              ) : (
                <input
                  id="configuration-value"
                  type={selectedMetadata.type === 'integer' || selectedMetadata.type === 'number' ? 'number' : 'text'}
                  min={selectedMetadata.minimum}
                  max={selectedMetadata.maximum}
                  step={selectedMetadata.type === 'integer' ? 1 : 'any'}
                  value={typeof draft === 'string' ? draft : ''}
                  onChange={(event) => setDraft(event.currentTarget.value)}
                />
              )}
            </div>
            <div className="review-actions">
              <Button variant="secondary" onClick={() => { setSelectedKey(null); setReview(null); }} isDisabled={pageActionLocked}>취소</Button>
              <Button
                variant="secondary"
                isDanger
                isDisabled={pageActionLocked || selectedEffective.operator_value === null || selectedEffective.operator_value === undefined}
                onClick={() => submitPlan([configurationResetChange(selectedMetadata.key)])}
              >운영자 값 초기화 검토</Button>
              <Button variant="primary" isDisabled={pageActionLocked} onClick={planSelectedValue}>
                {planMutation.isPending ? '변경 계산 중…' : '변경 내용 검토'}
              </Button>
            </div>
          </CardBody>
        </Card>
      ) : null}

      {review ? (
        <Card className="review-card">
          <CardTitle>설정 변경 검토</CardTitle>
          <CardBody>
            <dl className="facts compact-facts">
              <dt>기준 revision</dt><dd>{review.plan.base_revision}</dd>
              <dt>적용 후 revision</dt><dd>{review.plan.candidate_revision}</dd>
              <dt>실제 변경 발생</dt><dd>{yesNoLabel(review.plan.would_change)}</dd>
              <dt>계획 digest</dt><dd><code>{review.plan.plan_digest}</code></dd>
            </dl>
            <div className="table-scroll configuration-review-table">
              <table className="runtime-table">
                <thead><tr><th>키</th><th>작업</th><th>변경 전</th><th>변경 후</th><th>변경 후 출처</th><th>변경 위험</th></tr></thead>
                <tbody>
                  {review.plan.changes.map((change) => (
                    <tr key={change.key}>
                      <td><code>{change.key}</code></td>
                      <td>{change.operation}</td>
                      <td>{String(change.effective_before ?? '—')}</td>
                      <td>{String(change.effective_after ?? '—')}</td>
                      <td>
                        {change.effective_source_after}
                        {change.operator_override_shadowed_after ? <small>운영자 값이 다른 계층에 가려짐</small> : null}
                      </td>
                      <td><Label color={riskColor(change.risk)}>{riskLabel(change.risk)}</Label></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!review.plan.would_change ? (
              <Alert isInline variant="info" title="적용할 변경이 없습니다.">현재 운영자 설정과 같은 변경 내용이므로 적용하지 않습니다.</Alert>
            ) : null}
            <div className="review-actions">
              <Button variant="secondary" onClick={() => setReview(null)} isDisabled={pageActionLocked}>검토 닫기</Button>
              <Button
                variant="primary"
                isDisabled={!review.plan.would_change || pageActionLocked}
                onClick={() => applyMutation.mutate(review)}
              >{applyMutation.isPending ? '적용·검증 중…' : '검토한 변경 적용'}</Button>
            </div>
          </CardBody>
        </Card>
      ) : null}

      <ConfigurationHistoryPanel
        token={token}
        onUnauthorized={onUnauthorized}
        currentRevision={effective.revision}
        etag={effectiveRead.etag}
        writeAvailable={writeStatus.available}
        locked={actionPending || review !== null || selectedKey !== null}
        onReviewActiveChange={setRollbackActive}
      />

      {lastApply ? (
        <Card>
          <CardTitle>적용 결과</CardTitle>
          <CardBody>
            <dl className="facts operation-facts">
              <dt>작업 ID</dt><dd><code>{lastApply.operation_id}</code></dd>
              <dt>상태</dt><dd>{applyStatusLabel(lastApply.status)}</dd>
              <dt>변경됨</dt><dd>{yesNoLabel(lastApply.changed)}</dd>
              <dt>revision</dt><dd>{lastApply.revision}</dd>
              <dt>저장소 revision</dt><dd>{lastApply.verification.store_revision ?? '—'}</dd>
              <dt>Resolver revision</dt><dd>{lastApply.verification.resolver_revision}</dd>
              <dt>런타임 revision</dt><dd>{lastApply.verification.runtime_revision}</dd>
              <dt>동기화</dt><dd>{yesNoLabel(lastApply.verification.synchronized)}</dd>
            </dl>
          </CardBody>
        </Card>
      ) : null}
    </section>
  );
}
