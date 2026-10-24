import { useState, type FormEvent, type ReactNode } from 'react';
import { Alert, Button, Card, CardBody, CardTitle } from '@patternfly/react-core';
import { Link, Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom';

import { isUnauthorized } from './apiFeedback';
import { ChatPage } from './ChatPage';
import { useChatSession } from './ChatSessionContext';
// 같은 이름의 소문자 .ts 모듈이 있다. 대소문자를 구분하지 않는 macOS 파일시스템에서
// 확장자 없는 import는 .ts를 먼저 찾아 잘못 해석되므로 .tsx를 명시한다.
import { EmbeddingPlayground } from './EmbeddingPlayground.tsx';
import {
  PLAYGROUND_WORKSPACES,
  playgroundPath,
  unavailablePlaygroundWorkspaces,
  visiblePlaygroundWorkspaces,
  type PlaygroundWorkspace,
} from './navigation';
import { usePublicModels } from './publicModelsQuery';
import { RiskPlayground } from './RiskPlayground.tsx';

type PlaygroundPageProps = {
  features: readonly string[];
  grafanaUrl: string | null;
  docsUrl: string | null;
};

function PublicApiKeyForm({ rejected }: { rejected: boolean }) {
  const { setApiKey } = useChatSession();
  const [draft, setDraft] = useState('');

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const key = draft.trim();
    if (!key) return;
    setApiKey(key);
    setDraft('');
  }

  return (
    <Card className="chat-key-card">
      <CardTitle>API 키 필요</CardTitle>
      <CardBody>
        <p>
          이 Gateway의 공개 API는 Bearer 인증을 요구합니다. 관리자 키가 아니라 API 사용자에게 발급한
          키를 입력하세요. 키는 현재 브라우저 탭 메모리에만 있고 새로고침하면 사라집니다.
        </p>
        <form className="auth-form" onSubmit={submit}>
          <label htmlFor="chat-api-key">API 키</label>
          <input
            id="chat-api-key"
            type="password"
            autoComplete="off"
            value={draft}
            onChange={(event) => setDraft(event.currentTarget.value)}
          />
          {rejected ? <p className="form-error" role="alert">API 키가 유효하지 않습니다.</p> : null}
          <Button type="submit" variant="primary" isDisabled={!draft.trim()}>사용</Button>
        </form>
      </CardBody>
    </Card>
  );
}

// 배포가 제공하지 않는 기능은 숨기지 않고 무엇인지·왜 없는지·어떻게 쓸 수 있는지 안내한다.
// Embedding은 실제 화면을 미리보기로 보여 준다. 모델 정보가 있어야 그릴 수 있는 Chat(모델 없는 Core)은
// 이 안내만 보여 준다. 어느 쪽도 요청을 보내지 않는다.
function UnavailableWorkspace({ workspace }: { workspace: PlaygroundWorkspace }) {
  const headingId = `playground-unavailable-${workspace.path}`;
  return (
    <section className="playground-workspace" aria-labelledby={headingId}>
      <div className="playground-panel-heading">
        <div>
          <h2 id={headingId}>{workspace.label}</h2>
          <p>{workspace.description}</p>
        </div>
      </div>
      <Alert isInline variant="info" title="현재 배포 환경에서는 제공하지 않습니다.">
        <p>이 배포의 지원 기능에 {workspace.label} 기능이 포함되지 않아 이 화면에서는 요청을 보내지 않습니다. 장애가 아니라 배포 구성에 따른 범위입니다.</p>
        <p>사용하려면 서버 운영자가 이 기능을 제공하는 배포 환경을 구성해야 합니다. 현재 배포의 지원 기능은 운영 개요의 실행 환경 정보에서 확인할 수 있습니다.</p>
        <Link to="/">운영 개요로 이동 →</Link>
      </Alert>
    </section>
  );
}

// Playground는 Deployment Target이 공개한 기능별 작업 화면을 묶는다. 각 화면은 기존 공개
// Gateway API만 호출하며, API 키는 화면 사이에서 공유하되 탭 메모리 밖에 저장하지 않는다.
export function PlaygroundPage({ features, grafanaUrl, docsUrl }: PlaygroundPageProps) {
  const { apiKey, credentialRevision, setApiKey, apiKeyRejected } = useChatSession();
  const [confirmKeyClear, setConfirmKeyClear] = useState(false);
  const modelsQuery = usePublicModels(apiKey, credentialRevision);
  const workspaces = visiblePlaygroundWorkspaces(features);
  const unavailable = unavailablePlaygroundWorkspaces(features);
  // 미제공 안내는 공개 API를 호출하지 않으므로 API 키 입력 없이 보여 준다.
  const { pathname } = useLocation();
  const unavailableSelected = unavailable.some((workspace) => pathname.endsWith(playgroundPath(workspace.path)));
  const needsKey = isUnauthorized(modelsQuery.error) || apiKeyRejected;
  const elements: Record<PlaygroundWorkspace['path'], ReactNode> = {
    chat: <ChatPage grafanaUrl={grafanaUrl} docsUrl={docsUrl} />,
    embeddings: <EmbeddingPlayground features={features} />,
    risk: <RiskPlayground features={features} />,
  };

  return (
    <section className="playground-page">
      <div className="page-heading">
        <div>
          <h1>Playground</h1>
          <p>공개 Gateway API로 모델 기능을 확인합니다.</p>
          <details className="playground-data-help">
            <summary>입력 보관 안내</summary>
            <p>Chat 대화·작성 중인 메시지·첨부·요청 설정은 같은 탭에서 화면을 이동해도 유지됩니다. API 키를 교체·삭제하거나 새로고침하면 Chat 세션은 삭제됩니다. Embedding·Risk의 입력과 결과는 해당 화면을 떠나면 삭제됩니다. 입력은 브라우저의 영구 저장소에 보관하지 않습니다.</p>
          </details>
        </div>
        {apiKey !== null ? (
          <div className="chat-heading-actions">
            <Button variant="secondary" onClick={() => {
              setConfirmKeyClear(true);
            }}>API 키 지우기</Button>
          </div>
        ) : null}
      </div>
      {confirmKeyClear ? (
        <div className="playground-credential-confirm" role="group" aria-label="API 키와 Playground 작업 삭제 확인">
          <p>API 키를 지우면 진행 중인 Chat 요청을 중지하고 대화·초안·첨부·요청 설정을 삭제합니다. 현재 Embedding·Retrieval·Risk 작업 화면의 입력과 결과도 사라집니다. 다른 키로 이전 작업을 복원할 수 없습니다.</p>
          <div className="chat-heading-actions">
            <Button variant="secondary" onClick={() => setConfirmKeyClear(false)}>취소</Button>
            <Button variant="danger" onClick={() => {
              setConfirmKeyClear(false);
              setApiKey(null);
            }}>API 키 및 작업 데이터 지우기</Button>
          </div>
        </div>
      ) : null}
      <nav className="playground-tabs" aria-label="Playground 기능">
        {PLAYGROUND_WORKSPACES.map((workspace) => unavailable.includes(workspace) ? (
          <NavLink key={workspace.path} to={playgroundPath(workspace.path)} className="is-unavailable">
            {workspace.label}{' '}<span className="playground-tab-badge">미제공</span>
          </NavLink>
        ) : (
          <NavLink key={workspace.path} to={playgroundPath(workspace.path)}>{workspace.path === 'embeddings' && features.includes('retrieval') ? 'Embedding · Retrieval' : workspace.label}</NavLink>
        ))}
      </nav>
      {needsKey && !unavailableSelected ? <PublicApiKeyForm rejected={apiKey !== null} /> : null}
      {!needsKey || unavailableSelected ? <Routes key={credentialRevision}>
        {workspaces.map((workspace) => (
          <Route key={workspace.path} path={workspace.path} element={elements[workspace.path]} />
        ))}
        {unavailable.map((workspace) => (
          <Route key={workspace.path} path={workspace.path} element={workspace.path === 'embeddings'
            ? <EmbeddingPlayground features={features} preview />
            : <UnavailableWorkspace workspace={workspace} />} />
        ))}
        {workspaces.length > 0 ? (
          <Route path="*" element={<Navigate to={playgroundPath(workspaces[0].path)} replace />} />
        ) : null}
      </Routes> : null}
    </section>
  );
}
