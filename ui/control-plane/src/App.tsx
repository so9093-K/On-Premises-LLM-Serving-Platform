import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Alert, Button, Card, CardBody, CardTitle, Spinner } from '@patternfly/react-core';
import { useQuery } from '@tanstack/react-query';
import { Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom';

import { ApiError, fetchBootstrap, type BootstrapResponse, verifyAdminToken } from './api';
import { useAdminSession } from './auth/AdminSessionContext';
import { ChatSessionProvider } from './ChatSessionContext';
import { ConfigurationPage } from './ConfigurationPage';
import { MainModelPage } from './MainModelPage';
import { OperationsPage } from './OperationsPage';
import { OverviewPage } from './OverviewPage';
import { PageErrorBoundary } from './PageErrorBoundary';
import { PlaygroundPage } from './PlaygroundPage';
import { RuntimePage } from './RuntimePage';
import { NAVIGATION_GROUPS, playgroundPath, visibleNavigationSections, type NavigationPath } from './navigation';
import { deploymentTargetLabel, t } from './uiText';

// The generated OpenAPI literal version is the compile-time contract for the Console.
const SUPPORTED_BOOTSTRAP_VERSION: BootstrapResponse['bootstrap_version'] = 4;

function LoadingScreen() {
  return (
    <main className="centered-state" aria-live="polite">
      <Spinner aria-label="Control Plane 정보 불러오는 중" />
      <p>{t('common.loading')}</p>
    </main>
  );
}

function FailureScreen({ title, children, onRetry, retrying = false }: { title: string; children: ReactNode; onRetry?: () => void; retrying?: boolean }) {
  return (
    <main className="centered-state">
      <Alert isInline variant="danger" title={title}>
        {children}
        {onRetry ? (
          <div className="state-recovery-actions">
            <Button variant="secondary" isDisabled={retrying} onClick={onRetry}>
              {retrying ? '다시 확인 중…' : '다시 시도'}
            </Button>
            <small>계속 실패하면 서버에서 <code>make status</code>와 <code>make logs</code>로 상태를 확인하세요.</small>
          </div>
        ) : null}
      </Alert>
    </main>
  );
}

function AuthGate() {
  const { setToken } = useAdminSession();
  const [draft, setDraft] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = draft.trim();
    if (!token) {
      setError('관리자 키를 입력하세요.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await verifyAdminToken(token);
      setToken(token);
      setDraft('');
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) {
        setError('관리자 키가 유효하지 않습니다.');
      } else {
        setError(reason instanceof Error ? reason.message : '관리자 인증 확인에 실패했습니다.');
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-shell">
      <Card className="auth-card">
        <CardTitle>관리자 인증</CardTitle>
        <CardBody>
          <p>
            관리자 키를 입력하세요. 키는 현재 브라우저 탭에만 유지되며
            새로고침하면 사라집니다.
          </p>
          <form className="auth-form" onSubmit={submit}>
            <label htmlFor="admin-key">관리자 키</label>
            <input
              id="admin-key"
              type="password"
              autoComplete="off"
              value={draft}
              onChange={(event) => setDraft(event.currentTarget.value)}
            />
            {error ? <p className="form-error" role="alert">{error}</p> : null}
            <Button type="submit" variant="primary" isDisabled={submitting}>
              {submitting ? '확인 중…' : '확인'}
            </Button>
          </form>
        </CardBody>
      </Card>
    </main>
  );
}

function Shell({ bootstrap }: { bootstrap: BootstrapResponse }) {
  const { token, clearToken } = useAdminSession();
  const location = useLocation();
  const [navigationOpen, setNavigationOpen] = useState(false);
  const navigationToggleRef = useRef<HTMLButtonElement | null>(null);
  const contentRef = useRef<HTMLElement | null>(null);
  useEffect(() => setNavigationOpen(false), [location.pathname]);
  const sections = visibleNavigationSections(bootstrap.deployment.features);
  const pages: Record<NavigationPath, ReactNode> = {
    '/': <OverviewPage bootstrap={bootstrap} token={token} onUnauthorized={clearToken} />,
    '/main-model': <MainModelPage token={token} onUnauthorized={clearToken} chatEnabled={bootstrap.deployment.features.includes('chat')} />,
    '/runtimes': <RuntimePage token={token} onUnauthorized={clearToken} grafanaUrl={bootstrap.links.grafana} />,
    '/operations': <OperationsPage token={token} onUnauthorized={clearToken} deploymentFeatures={bootstrap.deployment.features} grafanaUrl={bootstrap.links.grafana} runtimeBackend={bootstrap.deployment.runtime_backend} />,
    '/configuration': <ConfigurationPage token={token} onUnauthorized={clearToken} deploymentFeatures={bootstrap.deployment.features} />,
    '/playground': <PlaygroundPage features={bootstrap.deployment.features} grafanaUrl={bootstrap.links.grafana} docsUrl={bootstrap.links.docs} />,
  };
  const externalLinks = [
    [t('link.apiDocs'), bootstrap.links.docs],
    ['Grafana', bootstrap.links.grafana],
  ] as const;

  return (
    <div className="console-shell">
      <header className="topbar">
        <div>
          <strong>AI 모델 서빙 Control Plane</strong>
          <span>{deploymentTargetLabel(bootstrap.deployment.target, bootstrap.deployment.display_name)}</span>
        </div>
        <button type="button" className="mobile-navigation-toggle" ref={navigationToggleRef}
          aria-expanded={navigationOpen} aria-controls="console-navigation"
          onClick={() => setNavigationOpen((open) => !open)}>메뉴</button>
        {bootstrap.access.admin_auth_required ? (
          <Button variant="secondary" onClick={clearToken}>관리자 키 지우기</Button>
        ) : null}
      </header>
      <div className="workspace">
        <aside id="console-navigation" className={`sidebar${navigationOpen ? ' is-open' : ''}`} aria-label="Control Plane 탐색"
          onKeyDown={(event) => {
            if (event.key === 'Escape' && navigationOpen) {
              setNavigationOpen(false);
              navigationToggleRef.current?.focus();
            }
          }}>
          <nav>
            {NAVIGATION_GROUPS.map((group) => {
              const items = sections.filter((section) => section.group === group);
              return items.length ? (
                <div className="nav-group" key={group}>
                  <span className="nav-group-label">{t(`navGroup.${group}`)}</span>
                  {items.map((section) => (
                    <NavLink key={section.path} to={section.path} end={section.path === '/'}
                      onClick={() => {
                        if (navigationOpen) {
                          setNavigationOpen(false);
                          contentRef.current?.focus();
                        }
                      }}>
                      {t(section.labelKey)}
                    </NavLink>
                  ))}
                </div>
              ) : null;
            })}
          </nav>
          <div className="external-links">
            {externalLinks.map(([label, href]) => href ? (
              <a key={label} href={href} target="_blank" rel="noreferrer">{label} ↗</a>
            ) : null)}
          </div>
        </aside>
        <main className="content" ref={contentRef} tabIndex={-1}>
          <PageErrorBoundary resetKey={location.pathname}>
            <Routes>
              {sections.map((section) => (
                <Route
                  key={section.path}
                  path={'nested' in section ? `${section.path}/*` : section.path}
                  element={pages[section.path]}
                />
              ))}
              {sections.some((section) => section.path === '/playground') ? (
                // 이전 Chat 전용 주소의 북마크를 Playground의 Chat 화면으로 잇는다.
                <Route path="/chat" element={<Navigate to={playgroundPath('chat')} replace />} />
              ) : null}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </PageErrorBoundary>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  const { token } = useAdminSession();
  const bootstrapQuery = useQuery({
    queryKey: ['control-plane-bootstrap'],
    queryFn: fetchBootstrap,
    retry: false,
    staleTime: 30_000,
  });

  if (bootstrapQuery.isPending) {
    return <LoadingScreen />;
  }
  if (bootstrapQuery.isError) {
    return (
      <FailureScreen title="Control Plane 정보를 불러오지 못했습니다."
        onRetry={() => { void bootstrapQuery.refetch(); }} retrying={bootstrapQuery.isFetching}>
        {bootstrapQuery.error.message}
      </FailureScreen>
    );
  }

  const bootstrap = bootstrapQuery.data;
  if (bootstrap.bootstrap_version !== SUPPORTED_BOOTSTRAP_VERSION) {
    return (
      <FailureScreen title="지원하지 않는 Control Plane 계약입니다.">
        현재 Console은 bootstrap version {SUPPORTED_BOOTSTRAP_VERSION}만 지원합니다. 안전을 위해 모든 변경 작업을 잠급니다.
      </FailureScreen>
    );
  }
  if (bootstrap.access.admin_auth_required && token === null) {
    return <AuthGate />;
  }
  // 채팅 대화는 Shell과 수명을 같이 하되 화면 오류 경계 밖에 둔다. 다른 화면의 렌더 오류는
  // 대화를 지우지 않고, 관리자 키를 지워 Shell이 사라지면 대화와 API 키도 사라진다.
  return (
    <ChatSessionProvider>
      <Shell bootstrap={bootstrap} />
    </ChatSessionProvider>
  );
}
