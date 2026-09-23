import { useEffect } from 'react';
import { Button, Card, CardBody, CardTitle, Label, Spinner } from '@patternfly/react-core';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import {
  fetchMainModel,
  fetchRuntimes,
  type BootstrapResponse,
  type RuntimeListResponse,
} from './api';
import { apiErrorMessage, isUnauthorized } from './apiFeedback';
import { mainModelOverviewSignals, type OverviewSignalTone } from './overviewSignals';
import {
  accessProfileLabel,
  CAPABILITY_KEYS,
  capabilityPresentation,
  controlModeLabel,
  deploymentTargetLabel,
  formatFraction,
  implementationStatusLabel,
  lifecycleOwnerLabel,
  qualificationStatusLabel,
  runtimeStateLabel,
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

function signalColor(tone: OverviewSignalTone): 'blue' | 'orange' | 'red' {
  if (tone === 'danger') return 'red';
  if (tone === 'warning') return 'orange';
  return 'blue';
}

function mainModelSummary(
  enabled: boolean,
  pending: boolean,
  mainModel: ReturnType<typeof fetchMainModel> extends Promise<infer T> ? T | undefined : never,
): string {
  if (!enabled) return '외부 / 네이티브 관리';
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

  useEffect(() => {
    if (isUnauthorized(runtimesQuery.error) || isUnauthorized(mainModelQuery.error)) {
      onUnauthorized();
    }
  }, [mainModelQuery.error, onUnauthorized, runtimesQuery.error]);

  const refreshing = runtimesQuery.isFetching || mainModelQuery.isFetching;
  const refresh = () => {
    if (runtimeControlEnabled) void runtimesQuery.refetch();
    if (modelSwitchingEnabled) void mainModelQuery.refetch();
  };

  const release = bootstrap.platform.release_id ?? 'development';
  const runtimes = runtimesQuery.data?.runtimes ?? [];
  const topology = runtimesQuery.data?.topology ?? [];
  const unavailableTopology = topology.filter((item) => !item.available);
  const budget = runtimesQuery.data?.budget;
  const mainModel = mainModelQuery.data;
  const mainModelSignals = mainModelOverviewSignals(mainModel);
  const attentionSignals = mainModelSignals.filter((signal) => signal.tone !== 'info');
  const informationalSignals = mainModelSignals.filter((signal) => signal.tone === 'info');
  const checking = (
    (runtimeControlEnabled && runtimesQuery.isPending)
    || (modelSwitchingEnabled && mainModelQuery.isPending)
  );
  const hasAttention = (
    runtimesQuery.isError
    || mainModelQuery.isError
    || attentionSignals.length > 0
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
      : { label: '정상', color: 'green' as const, description: '현재 즉시 조치가 필요한 항목은 없습니다.' };

  const capabilities = CAPABILITY_KEYS.map((feature) => capabilityPresentation(
    feature,
    bootstrap.deployment.features,
    bootstrap.deployment.lifecycle_owner,
  ));

  return (
    <section className="overview-page">
      <div className="page-heading">
        <div>
          <h1>개요</h1>
          <p>현재 서비스 상태, 실행 환경과 운영자가 할 수 있는 작업을 한눈에 확인합니다.</p>
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
              <strong>{operatorStatus.description}</strong>
            </div>
            <dl className="facts overview-status-facts">
              <dt>메인 모델</dt>
              <dd>{mainModelSummary(modelSwitchingEnabled, mainModelQuery.isPending, mainModel)}</dd>
              <dt>런타임</dt>
              <dd>
                {runtimeControlEnabled
                  ? `${runtimeStateCount(runtimes, 'active')}개 실행 중 · ${runtimeStateCount(runtimes, 'starting')}개 시작 중`
                  : '외부 / 네이티브 관리'}
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

      {hasPolicyNotice ? (
        <Card className="overview-policy-card">
          <CardTitle>운영 참고</CardTitle>
          <CardBody className="overview-policy-list">
            {bootstrap.deployment.lifecycle_owner === 'external' ? (
              <p>
                이 실행 환경의 메인 런타임 lifecycle은 외부 또는 네이티브 구성요소가 관리합니다.
                Control Plane은 서버가 선언한 지원 기능만 표시하며, 숨겨진 메뉴는 오류나 권한 부족을 뜻하지 않습니다.
              </p>
            ) : null}
            {informationalSignals.map((signal) => (
              <p key={signal.key}>{signal.title} {signal.detail}</p>
            ))}
            {unavailableTopology.length ? (
              <p>
                {unavailableTopology.length}개 런타임은 현재 리소스 정책상 동시에 실행하지 않도록 제외되어 있습니다.
                GPU 지원 여부나 장애 판정이 아닙니다.{' '}
                <Link className="overview-inline-action" to="/runtimes">런타임에서 이유 확인 →</Link>
              </p>
            ) : null}
            {!bootstrap.configuration.write_available ? (
              <p>
                현재 실행 환경에서는 설정 변경을 사용할 수 없습니다. 상태 조회 자체의 오류를 뜻하지 않습니다.{' '}
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
                  <dt>관리 주체</dt><dd>{lifecycleOwnerLabel(bootstrap.deployment.lifecycle_owner)}</dd>
                  <dt>제어 방식</dt><dd>{controlModeLabel(bootstrap.deployment.control_mode)}</dd>
                </dl>
                <p className="overview-muted overview-ownership-note">
                  이 실행 환경에서는 Control Plane이 메인 모델 전환을 수행하지 않습니다.
                </p>
              </>
            ) : mainModelQuery.isPending ? (
              <div className="inline-loading"><Spinner size="md" aria-label="메인 모델 상태 불러오는 중" /> 상태를 불러오는 중입니다.</div>
            ) : mainModel ? (
              <dl className="facts">
                <dt>공개 모델 이름</dt><dd>{mainModel.public_model}</dd>
                <dt>현재 프로필</dt><dd>{mainModel.active_profile?.display_name ?? '—'}</dd>
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
                  <dt>관리 주체</dt><dd>{lifecycleOwnerLabel(bootstrap.deployment.lifecycle_owner)}</dd>
                  <dt>제어 방식</dt><dd>{controlModeLabel(bootstrap.deployment.control_mode)}</dd>
                </dl>
                <p className="overview-muted overview-ownership-note">
                  이 실행 환경에서는 런타임 시작·중지와 GPU 실행 가능성 판단을 외부 구성요소가 관리합니다.
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
                <dd><Label color={unavailableTopology.length ? 'orange' : 'green'}>{unavailableTopology.length}</Label></dd>
                <dt>GPU 상한</dt><dd>{formatFraction(budget?.ceiling)}</dd>
                <dt>GPU 사용</dt><dd>{formatFraction(budget?.used)}</dd>
                <dt>GPU 여유</dt><dd>{formatFraction(budget?.free)}</dd>
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
              <dt>스키마</dt><dd>v{bootstrap.configuration.schema_version}</dd>
              <dt>리비전</dt><dd>{bootstrap.configuration.revision}</dd>
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

      <div className="page-grid overview-secondary-grid">
        <Card>
          <CardTitle>실행 환경과 접근</CardTitle>
          <CardBody>
            <dl className="facts">
              <dt>실행 환경</dt><dd>{deploymentTargetLabel(bootstrap.deployment.target, bootstrap.deployment.display_name)}</dd>
              <dt>환경 ID</dt><dd><code>{bootstrap.deployment.target}</code></dd>
              <dt>런타임 백엔드</dt><dd>{bootstrap.deployment.runtime_backend}</dd>
              <dt>관리 주체</dt><dd>{lifecycleOwnerLabel(bootstrap.deployment.lifecycle_owner)}</dd>
              <dt>제어 방식</dt><dd>{controlModeLabel(bootstrap.deployment.control_mode)}</dd>
              <dt>구현 상태</dt><dd>{implementationStatusLabel(bootstrap.deployment.implementation_status)}</dd>
              <dt>검증 상태</dt><dd>{qualificationStatusLabel(bootstrap.deployment.qualification_status)}</dd>
              <dt>접근 프로필</dt><dd>{accessProfileLabel(bootstrap.access.profile)}</dd>
              <dt>관리자 인증</dt><dd>{bootstrap.access.admin_auth_required ? '필요' : '필요 없음'}</dd>
            </dl>
          </CardBody>
        </Card>

        <Card>
          <CardTitle>플랫폼과 관측</CardTitle>
          <CardBody>
            <dl className="facts">
              <dt>버전</dt><dd>{bootstrap.platform.version}</dd>
              <dt>릴리스</dt><dd>{release}</dd>
              <dt>관측 기능</dt><dd>{bootstrap.monitoring.available ? '사용 가능' : '사용할 수 없음'}</dd>
              <dt>Grafana</dt><dd>{bootstrap.monitoring.grafana_available ? '사용 가능' : '사용할 수 없음'}</dd>
            </dl>
            <div className="overview-card-actions">
              {bootstrap.links.docs ? (
                <a href={bootstrap.links.docs} target="_blank" rel="noreferrer">API 문서에서 사용법 확인 ↗</a>
              ) : null}
              {bootstrap.links.grafana ? (
                <a href={bootstrap.links.grafana} target="_blank" rel="noreferrer">Grafana에서 진단 ↗</a>
              ) : null}
              <Link to="/operations">활동에서 변경 이력 확인 →</Link>
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardTitle>지원 기능</CardTitle>
          <CardBody className="capability-grid">
            {capabilities.map((capability) => (
              <div className="capability-item" key={capability.key}>
                <div>
                  <strong>{capability.label}</strong>
                  <small>{capability.detail}</small>
                </div>
                <Label color={capability.tone}>{capability.status}</Label>
              </div>
            ))}
          </CardBody>
        </Card>
      </div>
    </section>
  );
}
