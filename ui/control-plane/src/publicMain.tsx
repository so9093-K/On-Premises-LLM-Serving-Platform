import '@patternfly/react-core/dist/styles/base.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';

import { ChatSessionProvider } from './ChatSessionContext';
import { PublicPlaygroundApp } from './PublicPlaygroundApp';
import './styles.css';

const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
const root = document.getElementById('root');
if (!root) throw new Error('Playground root element is missing');

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <ChatSessionProvider>
          <PublicPlaygroundApp />
        </ChatSessionProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
