import { useEffect } from 'react';
import { Button, Card, CardBody, CardTitle, Label, Spinner } from '@patternfly/react-core';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import {
  fetchGatewayReadiness,
  fetchMainModel,
  fetchRecentTraffic,
  fetchRuntimes,
  type BootstrapResponse,
  type RuntimeListResponse,
} from './api';
import { serviceOverviewDashboardUrl } from './activityDiagnostics';
import { playgroundPath } from './navigation';
import { apiErrorMessage, isUnauthorized } from './apiFeedback';
import { trafficTiles, trafficWindowLabel, type TrafficTone } from './trafficSummary';
import { gatewayReadinessSignals, mainModelOverviewSignals, unmanagedModelSummary, type OverviewSignalTone } from './overviewSignals';
import {
  accessProfileLabel,
  CAPABILITY_KEYS,
  capabilityPresentation,
  controlModeLabel,
  deploymentTargetLabel,
  formatPercent,
  implementationStatusLabel,
  lifecycleOwnerLabel,
  qualificationStatusLabel,
  runtimeStateLabel,
  modelRuntimeLabel,
  t,
} from './uiText';

type OverviewPageProps = {
  bootstrap: BootstrapResponse;
  token: string | null;
  onUnauthorized: () => void;
};

function runtimeStateCount(
  runtimes: RuntimeListResponse['runtimes'],
  state: RuntimeListResponse['runtimes'][number]['state'],
): number {
  return runtimes.filter((runtime) => runtime.state === state).length;
}

function trafficToneClass(tone: TrafficTone): string {
  return `traffic-tile traffic-tile-${tone}`;
}

function signalColor(tone: OverviewSignalTone): 'blue' | 'orange' | 'red' {
  if (tone === 'danger') return 'red';
  if (tone === 'warning') return 'orange';
  return 'blue';
}

function mainModelSummary(
  enabled: boolean,
  pending: boolean,
  mainModel: ReturnType<typeof fetchMainModel> extends Promise<infer T> ? T | undefined : never,
  deployment: BootstrapResponse['deployment'],
): string {
  if (!enabled) return unmanagedModelSummary(
    deployment.runtime_backend, deployment.control_mode, deployment.lifecycle_owner,
  );
  if (pending) return '확인 중';
  if (!mainModel) return '상태 확인 불가';
  if (mainModel.runtime_state === 'stopped') return '중지됨';
  const observed = mainModel.observed_runtime?.status
    ? runtimeStateLabel(mainModel.observed_runtime.status)
    : '관측값 없음';
  return `${runtimeStateLabel(mainModel.gate)} · ${observed}`;
}

export function OverviewPage({ bootstrap, token, onUnauthorized }: OverviewPageProps) {
  const authClass = token === null ? 'anonymous' : 'authenticated';
  const runtimeControlEnabled = bootstrap.deployment.features.includes('runtime_control');
  const modelSwitchingEnabled = bootstrap.deployment.features.includes('model_switching');
  const noMainModel = bootstrap.deployment.runtime_backend === 'none';

  const runtimesQuery = useQuery({
    queryKey: ['runtime-control', 'runtimes', authClass],
    queryFn: () => fetchRuntimes(token),
    enabled: runtimeControlEnabled,
    retry: false,
    staleTime: 10_000,
    refetchInterval: () => document.visibilityState === 'visible' ? 10_000 : false,
    refetchIntervalInBackground: false,
  });

  const mainModelQuery = useQuery({
    queryKey: ['main-model', 'status', authClass],
    queryFn: () => fetchMainModel(token),
    enabled: modelSwitchingEnabled,
    retry: false,
    staleTime: 10_000,
    refetchInterval: () => document.visibilityState === 'visible' ? 10_000 : false,
    refetchIntervalInBackground: false,
  });

  const trafficQuery = useQuery({
    queryKey: ['traffic', 'recent', authClass],
    queryFn: () => fetchRecentTraffic(token),
    retry: false,
    staleTime: 10_000,
    refetchInterval: () => document.visibilityState === 'visible' ? 10_000 : false,
    refetchIntervalInBackground: false,
  });

  // 메인 모델 상태 API가 없는 Target에서는 Gateway readiness가 유일한 서빙 준비 근거다.
  // 조회 실패는 다른 지표 조회 실패와 달리 주의로 올리지 않는다. 원인 진단은 make status가 소유한다.
  const readinessEnabled = !modelSwitchingEnabled;
  const readinessQuery = useQuery({
    queryKey: ['gateway', 'readiness', authClass],
    queryFn: () => fetchGatewayReadiness(token),
    enabled: readinessEnabled,
    retry: false,
    staleTime: 10_000,
    refetchInterval: () => document.visibilityState === 'visible' ? 10_000 : false,
    refetchIntervalInBackground: false,
  });

  useEffect(() => {
    if (
      isUnauthorized(runtimesQuery.error)
      || isUnauthorized(mainModelQuery.error)
      || isUnauthorized(trafficQuery.error)
      || isUnauthorized(readinessQuery.error)
    ) {
      onUnauthorized();
    }
  }, [mainModelQuery.error, onUnauthorized, readinessQuery.error, runtimesQuery.error, trafficQuery.error]);

  const refreshing = runtimesQuery.isFetching || mainModelQuery.isFetching || trafficQuery.isFetching
    || readinessQuery.isFetching;
  const refresh = () => {
    if (runtimeControlEnabled) void runtimesQuery.refetch();
    if (modelSwitchingEnabled) void mainModelQuery.refetch();
    if (readinessEnabled) void readinessQuery.refetch();
    void trafficQuery.refetch();
  };
  const serviceDashboardUrl = serviceOverviewDashboardUrl(bootstrap.links.grafana);

  const runtimes = runtimesQuery.data?.runtimes ?? [];
  const topology = runtimesQuery.data?.topology ?? [];
  const unavailableTopology = topology.filter((item) => !item.available);
  const budget = runtimesQuery.data?.budget;
  const mainModel = mainModelQuery.data;
  const mainModelSignals = mainModelOverviewSignals(mainModel, runtimeStateLabel);
  const attentionSignals = [
    ...mainModelSignals.filter((signal) => signal.tone !== 'info'),
    ...gatewayReadinessSignals(readinessEnabled ? readinessQuery.data : null),
  ];
  const informationalSignals = mainModelSignals.filter((signal) => signal.tone === 'info');
  const checking = (
    (runtimeControlEnabled && runtimesQuery.isPending)
    || (modelSwitchingEnabled && mainModelQuery.isPending)
    || (readinessEnabled && readinessQuery.isPending)
    || trafficQuery.isPending
  );
  const hasAttention = (
    runtimesQuery.isError
    || mainModelQuery.isError
    || attentionSignals.length > 0
    || trafficQuery.isError
  );
  const hasPolicyNotice = (
    informationalSignals.length > 0
    || unavailableTopology.length > 0
    || !bootstrap.configuration.write_available
    || bootstrap.deployment.lifecycle_owner === 'external'
  );

  const operatorStatus = checking
    ? { label: '상태 확인 중', color: 'blue' as const, description: '현재 제어 상태를 확인하고 있습니다.' }
    : hasAttention
      ? { label: '확인 필요', color: 'orange' as const, description: '운영자가 확인해야 할 상태가 있습니다.' }
      : { label: '조회 결과 · 주의 없음', color: 'grey' as const, description: '' };

  const capabilities = CAPABILITY_KEYS.map((feature) => capabilityPresentation(
    feature,
    bootstrap.deployment.features,
    bootstrap.deployment.lifecycle_owner,
    bootstrap.deployment.runtime_backend,
  ));

  return (
    <section className="overview-page">
      <div className="page-heading">
        <div>
          <h1>운영 개요</h1>
          <p>모델 · 런타임 · 최근 요청</p>
        </div>
        <Button variant="secondary" onClick={refresh} isDisabled={refreshing}>
          {refreshing ? t('common.refreshing') : t('common.refresh')}
        </Button>
      </div>

      <div className={`overview-priority-grid ${hasAttention ? '' : 'overview-priority-grid-single'}`}>
        <Card className="overview-status-card">
          <CardTitle>운영 상태</CardTitle>
          <CardBody>
            <div className="overview-status-heading">
              <Label color={operatorStatus.color}>{operatorStatus.label}</Label>
              {operatorStatus.description ? <strong>{operatorStatus.description}</strong> : null}
            </div>
            <dl className="facts overview-status-facts">
              <dt>메인 모델</dt>
              <dd>{mainModelSummary(modelSwitchingEnabled, mainModelQuery.isPending, mainModel, bootstrap.deployment)}</dd>
              <dt>런타임</dt>
              <dd>
                {runtimeControlEnabled
                  ? `${runtimeStateCount(runtimes, 'active')}개 실행 중 · ${runtimeStateCount(runtimes, 'starting')}개 시작 중`
                  : noMainModel ? '모델 Runtime 없음 · Risk 기본 서비스' : '외부 / 네이티브 관리'}
              </dd>
              <dt>설정</dt>
              <dd>{bootstrap.configuration.write_available ? '변경 가능' : '읽기 전용 / 변경 불가'}</dd>
            </dl>
            {checking ? (
              <div className="inline-loading compact-loading">
                <Spinner size="md" aria-label="현재 상태 확인 중" />
                현재 상태를 확인하는 중입니다.
              </div>
            ) : null}
          </CardBody>
        </Card>

        {hasAttention ? (
          <Card className="overview-attention-card">
            <CardTitle>확인 필요</CardTitle>
            <CardBody>
              <div className="overview-signal-list">
                {trafficQuery.isError ? (
                  <div className="overview-signal">
                    <Label color="orange">요청 지표</Label>
                    <div>
                      <strong>최근 요청 지표를 조회하지 못했습니다.</strong>
                      <small>{apiErrorMessage(trafficQuery.error)}</small>
                      {serviceDashboardUrl ? <a className="overview-inline-action" href={serviceDashboardUrl} target="_blank" rel="noreferrer">Grafana에서 확인 ↗</a> : null}
                    </div>
                  </div>
                ) : null}
                {runtimesQuery.isError ? (
                  <div className="overview-signal">
                    <Label color="orange">런타임</Label>
                    <div>
                      <strong>런타임 상태를 조회하지 못했습니다.</strong>
                      <small>{apiErrorMessage(runtimesQuery.error)}</small>
                      <Link className="overview-inline-action" to="/runtimes">런타임에서 확인 →</Link>
                    </div>
                  </div>
                ) : null}
                {mainModelQuery.isError ? (
                  <div className="overview-signal">
                    <Label color="orange">메인 모델</Label>
                    <div>
                      <strong>메인 모델 상태를 조회하지 못했습니다.</strong>
                      <small>{apiErrorMessage(mainModelQuery.error)}</small>
                      <Link className="overview-inline-action" to="/main-model">메인 모델에서 확인 →</Link>
                    </div>
                  </div>
                ) : null}
                {attentionSignals.map((signal) => (
                  <div className="overview-signal" key={signal.key}>
                    <Label color={signalColor(signal.tone)}>상태</Label>
                    <div>
                      <strong>{signal.title}</strong>
                      <small>{signal.detail}</small>
                      {modelSwitchingEnabled ? (
                        <Link className="overview-inline-action" to="/main-model">메인 모델에서 확인 →</Link>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            </CardBody>
          </Card>
        ) : null}
      </div>

      <Card className="traffic-card">
        <CardTitle>
          지금 서비스
          {trafficQuery.data ? <span className="traffic-window">{trafficWindowLabel(trafficQuery.data)}</span> : null}
        </CardTitle>
        <CardBody>
          {trafficQuery.isPending ? (
            <div className="inline-loading"><Spinner size="md" aria-label="최근 트래픽 불러오는 중" /> 최근 요청을 집계하는 중입니다.</div>
          ) : trafficQuery.isError ? (
            <p className="overview-muted">최근 요청 요약을 불러오지 못했습니다. {apiErrorMessage(trafficQuery.error)}</p>
          ) : (
            <div className="traffic-tiles">
              {trafficTiles(trafficQuery.data).map((tile) => (
                <div className={trafficToneClass(tile.tone)} key={tile.key}>
                  <span className="traffic-tile-label">{tile.label}</span>
                  <strong className="traffic-tile-value">{tile.value}</strong>
                  <small>{tile.detail}</small>
                </div>
              ))}
            </div>
          )}
          <p className="traffic-footnote">
            Gateway API 요청 집계 · 재시작 시 초기화
            {serviceDashboardUrl ? (
              <> <a className="overview-inline-action" href={serviceDashboardUrl} target="_blank" rel="noreferrer">Grafana에서 추이 보기 ↗</a></>
            ) : null}
          </p>
        </CardBody>
      </Card>

      <Card className="overview-next-actions">
        <CardTitle>빠른 작업</CardTitle>
        <CardBody>
          <div className="overview-action-grid">
            {bootstrap.deployment.features.includes('chat') ? (
              <Link className="overview-action-tile" to={playgroundPath('chat')}>
                <strong>모델 응답 테스트 →</strong>
              </Link>
            ) : null}
            {bootstrap.deployment.features.includes('risk') ? (
              <Link className="overview-action-tile" to={playgroundPath('risk')}>
                <strong>PII·Secret 탐지 테스트 →</strong>
              </Link>
            ) : null}
            {modelSwitchingEnabled ? (
              <Link className="overview-action-tile" to="/main-model">
                <strong>모델 상태·전환 →</strong>
              </Link>
            ) : null}
            {runtimeControlEnabled ? (
              <Link className="overview-action-tile" to="/runtimes">
                <strong>런타임 확인 →</strong>
              </Link>
            ) : null}
            <Link className="overview-action-tile" to="/operations">
              <strong>최근 운영 작업 →</strong>
            </Link>
            {bootstrap.links.docs ? (
              <a className="overview-action-tile" href={bootstrap.links.docs} target="_blank" rel="noreferrer">
                <strong>API 문서 ↗</strong>
              </a>
            ) : null}
          </div>
        </CardBody>
      </Card>

      {hasPolicyNotice ? (
        <Card className="overview-policy-card">
          <CardTitle>실행 환경 안내</CardTitle>
          <CardBody className="overview-policy-list">
            {noMainModel ? (
              <p>이 배포에는 메인 모델이 없습니다. Risk 등 제공되는 기본 API를 사용할 수 있으며 모델 장애로 해석하지 않습니다. Chat을 사용하려면 서버 운영자가 지원되는 모델 Runtime 배포 환경을 구성해야 합니다. Core 화면에서는 모델을 직접 시작할 수 없습니다.</p>
            ) : bootstrap.deployment.lifecycle_owner === 'external' ? (
              <p>메인 모델 실행·전환은 외부 또는 네이티브 런타임에서 관리됩니다.</p>
            ) : null}
            {informationalSignals.map((signal) => (
              <p key={signal.key}>{signal.title} {signal.detail}</p>
            ))}
            {unavailableTopology.length ? (
              <p>
                동시 실행 제한: {unavailableTopology.length}개 런타임 · 현재 리소스 정책{' '}
                <Link className="overview-inline-action" to="/runtimes">런타임에서 이유 확인 →</Link>
              </p>
            ) : null}
            {!bootstrap.configuration.write_available ? (
              <p>
                설정 변경 미지원 · 현재 실행 환경{' '}
                <Link className="overview-inline-action" to="/configuration">설정에서 확인 →</Link>
              </p>
            ) : null}
          </CardBody>
        </Card>
      ) : null}

      <div className="page-grid overview-primary-grid">
        <Card>
          <CardTitle>메인 모델</CardTitle>
          <CardBody>
            {!modelSwitchingEnabled ? (
              <>
                <dl className="facts">
                  <dt>관리 주체</dt><dd>{noMainModel ? '모델 없음' : lifecycleOwnerLabel(bootstrap.deployment.lifecycle_owner)}</dd>
                  <dt>제어 방식</dt><dd>{noMainModel ? '해당 없음' : controlModeLabel(bootstrap.deployment.control_mode)}</dd>
                </dl>
                <p className="overview-muted overview-ownership-note">
                  {noMainModel
                    ? '이 배포에는 메인 모델이 없으며 Risk 등 기본 기능만 제공합니다.'
                    : '이 실행 환경에서는 Control Plane이 메인 모델 전환을 수행하지 않습니다.'}
                </p>
              </>
            ) : mainModelQuery.isPending ? (
              <div className="inline-loading"><Spinner size="md" aria-label="메인 모델 상태 불러오는 중" /> 상태를 불러오는 중입니다.</div>
            ) : mainModel ? (
              <dl className="facts">
                <dt>공개 모델 이름</dt><dd>{mainModel.public_model}</dd>
                <dt>현재 프로필</dt><dd>{mainModel.active_profile?.display_name ?? '—'}</dd>
                <dt>실제 모델</dt><dd>{mainModel.active_profile?.upstream_model_id ?? '—'}</dd>
                <dt>실행 방식</dt><dd>{modelRuntimeLabel(mainModel.active_profile?.runtime_backend)}</dd>
                <dt>요청 상태</dt>
                <dd><Label color={mainModel.gate === 'open' ? 'green' : 'orange'}>{runtimeStateLabel(mainModel.gate)}</Label></dd>
                <dt>런타임 상태</dt><dd>{runtimeStateLabel(mainModel.runtime_state)}</dd>
                <dt>실제 상태</dt><dd>{runtimeStateLabel(mainModel.observed_runtime?.status ?? 'unavailable')}</dd>
                <dt>상태 확인</dt><dd>{runtimeStateLabel(mainModel.observed_runtime?.health ?? 'unavailable')}</dd>
              </dl>
            ) : (
              <p className="overview-muted">메인 모델 상태를 표시할 수 없습니다.</p>
            )}
            {modelSwitchingEnabled ? (
              <div className="overview-card-actions">
                <Link to="/main-model">메인 모델 운영으로 이동 →</Link>
              </div>
            ) : null}
          </CardBody>
        </Card>

        <Card>
          <CardTitle>런타임과 GPU</CardTitle>
          <CardBody>
            {!runtimeControlEnabled ? (
              <>
                <dl className="facts">
                  <dt>관리 주체</dt><dd>{noMainModel ? '모델 Runtime 없음' : lifecycleOwnerLabel(bootstrap.deployment.lifecycle_owner)}</dd>
                  <dt>제어 방식</dt><dd>{noMainModel ? '해당 없음' : controlModeLabel(bootstrap.deployment.control_mode)}</dd>
                </dl>
                <p className="overview-muted overview-ownership-note">
                  {noMainModel
                    ? '메인 모델 Runtime은 구성되지 않았습니다. 기본 서비스는 별도로 실행됩니다.'
                    : '이 실행 환경에서는 런타임 시작·중지와 GPU 실행 가능성 판단을 외부 구성요소가 관리합니다.'}
                </p>
              </>
            ) : runtimesQuery.isPending ? (
              <div className="inline-loading"><Spinner size="md" aria-label="런타임 상태 불러오는 중" /> 상태를 불러오는 중입니다.</div>
            ) : (
              <dl className="facts">
                <dt>실행 중</dt><dd>{runtimeStateCount(runtimes, 'active')}</dd>
                <dt>시작 중</dt><dd>{runtimeStateCount(runtimes, 'starting')}</dd>
                <dt>중지됨</dt><dd>{runtimeStateCount(runtimes, 'stopped')}</dd>
                <dt>정책상 제외</dt>
                <dd>{unavailableTopology.length ? <Label color="orange">{unavailableTopology.length}</Label> : '없음'}</dd>
                <dt>정책상 GPU 예약</dt><dd>{formatPercent(budget?.used)} / 상한 {formatPercent(budget?.ceiling)}</dd>
                <dt>정책상 GPU 여유</dt><dd>{formatPercent(budget?.free)}</dd>
              </dl>
            )}
            {runtimeControlEnabled ? (
              <div className="overview-card-actions">
                <Link to="/runtimes">런타임 운영으로 이동 →</Link>
              </div>
            ) : null}
          </CardBody>
        </Card>

        <Card>
          <CardTitle>설정</CardTitle>
          <CardBody>
            <dl className="facts">
              <dt>설정 버전</dt><dd>{bootstrap.configuration.revision}</dd>
              <dt>변경</dt>
              <dd><Label color={bootstrap.configuration.write_available ? 'green' : 'orange'}>
                {bootstrap.configuration.write_available ? '가능' : '사용할 수 없음'}
              </Label></dd>
            </dl>
            <div className="overview-card-actions">
              <Link to="/configuration">설정으로 이동 →</Link>
            </div>
          </CardBody>
        </Card>
      </div>

      <details className="overview-environment">
        <summary>실행 환경 정보</summary>
        <div className="overview-environment-body">
          <dl className="facts">
            <dt>실행 환경</dt><dd>{deploymentTargetLabel(bootstrap.deployment.target, bootstrap.deployment.display_name)}</dd>
            <dt>환경 ID</dt><dd><code>{bootstrap.deployment.target}</code></dd>
            <dt>메인 모델 운영 모드</dt><dd>{bootstrap.deployment.target === "linux-nvidia-dynamic" ? "CPU/GPU 수동 선택" : modelRuntimeLabel(bootstrap.deployment.runtime_backend)}</dd>
            <dt>관리 주체</dt><dd>{noMainModel ? '모델 Runtime 없음' : lifecycleOwnerLabel(bootstrap.deployment.lifecycle_owner)}</dd>
            <dt>제어 방식</dt><dd>{noMainModel ? '해당 없음' : controlModeLabel(bootstrap.deployment.control_mode)}</dd>
            <dt>구현·검증</dt>
            <dd>{implementationStatusLabel(bootstrap.deployment.implementation_status)} · {qualificationStatusLabel(bootstrap.deployment.qualification_status)}</dd>
          </dl>
          <dl className="facts">
            <dt>접근 프로필</dt><dd>{accessProfileLabel(bootstrap.access.profile)}</dd>
            <dt>관리자 인증</dt><dd>{bootstrap.access.admin_auth_required ? '필요' : '필요 없음'}</dd>
            <dt>버전</dt><dd>{bootstrap.platform.version}</dd>
            <dt>관측</dt>
            <dd>{bootstrap.monitoring.grafana_available ? 'Grafana 사용 가능' : bootstrap.monitoring.available ? '지표 수집만 사용 가능' : '사용할 수 없음'}</dd>
          </dl>
          <div>
            <span className="overview-environment-label">지원 기능</span>
            <ul className="capability-chips">
              {capabilities.map((capability) => (
                <li key={capability.key} title={capability.detail}>
                  <Label color={capability.tone}>{capability.label} · {capability.status}</Label>
                </li>
              ))}
            </ul>
            <div className="overview-card-actions">
              {bootstrap.links.docs ? (
                <a href={bootstrap.links.docs} target="_blank" rel="noreferrer">API 문서 ↗</a>
              ) : null}
              {bootstrap.links.grafana ? (
                <a href={bootstrap.links.grafana} target="_blank" rel="noreferrer">Grafana ↗</a>
              ) : null}
              <Link to="/operations">활동 기록 →</Link>
            </div>
          </div>
        </div>
      </details>
    </section>
  );
}
