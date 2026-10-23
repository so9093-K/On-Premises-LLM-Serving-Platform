import { useState, type FormEvent, type ReactNode } from 'react';
import { Button, Card, CardBody, CardTitle } from '@patternfly/react-core';
import { Navigate, NavLink, Route, Routes } from 'react-router-dom';

import { isUnauthorized } from './apiFeedback';
import { ChatPage } from './ChatPage';
import { useChatSession } from './ChatSessionContext';
import { EmbeddingPlayground } from './EmbeddingPlayground';
import { playgroundPath, visiblePlaygroundWorkspaces, type PlaygroundWorkspace } from './navigation';
import { usePublicModels } from './publicModelsQuery';
import { RiskPlayground } from './RiskPlayground';

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

// Playground는 Deployment Target이 공개한 기능별 작업 화면을 묶는다. 각 화면은 기존 공개
// Gateway API만 호출하며, API 키는 화면 사이에서 공유하되 탭 메모리 밖에 저장하지 않는다.
export function PlaygroundPage({ features, grafanaUrl, docsUrl }: PlaygroundPageProps) {
  const { apiKey, setApiKey, apiKeyRejected } = useChatSession();
  const modelsQuery = usePublicModels(apiKey);
  const workspaces = visiblePlaygroundWorkspaces(features);
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
            <p>Chat 대화·작성 중인 메시지·첨부·요청 설정은 같은 탭에서 화면을 이동해도 유지됩니다. Embedding·Risk의 입력과 결과는 해당 화면을 떠나면 삭제됩니다. 새로고침하면 API 키와 Chat 세션도 지워집니다. 입력은 브라우저의 영구 저장소에 보관하지 않습니다.</p>
          </details>
        </div>
        {apiKey !== null ? (
          <div className="chat-heading-actions">
            <Button variant="secondary" onClick={() => setApiKey(null)}>API 키 지우기</Button>
          </div>
        ) : null}
      </div>
      <nav className="playground-tabs" aria-label="Playground 기능">
        {workspaces.map((workspace) => (
          <NavLink key={workspace.path} to={playgroundPath(workspace.path)}>{workspace.label}</NavLink>
        ))}
      </nav>
      {needsKey ? <PublicApiKeyForm rejected={apiKey !== null} /> : null}
      <Routes>
        {workspaces.map((workspace) => (
          <Route key={workspace.path} path={workspace.path} element={elements[workspace.path]} />
        ))}
        {workspaces.length > 0 ? (
          <Route path="*" element={<Navigate to={playgroundPath(workspaces[0].path)} replace />} />
        ) : null}
      </Routes>
    </section>
  );
}
