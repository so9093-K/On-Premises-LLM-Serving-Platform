import { Alert, Button, Spinner } from '@patternfly/react-core';
import { useQuery } from '@tanstack/react-query';
import { Navigate, Route, Routes } from 'react-router-dom';

import { fetchPlaygroundConfiguration } from './api';
import { isUnauthorized } from './apiFeedback';
import { useChatSession } from './ChatSessionContext';
import { PageErrorBoundary } from './PageErrorBoundary';
import { PlaygroundPage, PublicApiKeyForm } from './PlaygroundPage';

export function PublicPlaygroundApp() {
  const { apiKey, credentialRevision } = useChatSession();
  const config = useQuery({
    queryKey: ['playground-configuration', credentialRevision],
    queryFn: () => fetchPlaygroundConfiguration(apiKey),
    staleTime: 30_000,
    gcTime: 0,
  });

  return (
    <main className="public-playground content">
      <PageErrorBoundary resetKey={String(credentialRevision)}>
        {config.isPending ? <Spinner aria-label="Playground 불러오는 중" /> :
          isUnauthorized(config.error) ? <>
            <h1>Playground</h1>
            <PublicApiKeyForm rejected={apiKey !== null} />
          </> : config.isError ? (
            <Alert isInline variant="danger" title="Playground에 연결하지 못했습니다.">
              <p>{config.error.message}</p>
              <Button variant="secondary" isDisabled={config.isFetching} onClick={() => { void config.refetch(); }}>다시 시도</Button>
            </Alert>
          ) : config.data ? (
            <Routes>
              <Route path="/playground/*" element={<PlaygroundPage features={config.data.features} grafanaUrl={null} docsUrl={null} />} />
              <Route path="*" element={<Navigate to="/playground/" replace />} />
            </Routes>
          ) : null}
      </PageErrorBoundary>
    </main>
  );
}
