import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Alert, Button } from '@patternfly/react-core';

type PageErrorBoundaryProps = {
  children: ReactNode;
  // 다른 화면으로 이동하면 이전 화면의 렌더링 오류를 지운다.
  resetKey: string;
};

type PageErrorBoundaryState = {
  error: Error | null;
};

// 한 화면의 렌더링 오류가 탐색과 다른 화면까지 지우지 않도록 오류를 화면 안에 가둔다.
export class PageErrorBoundary extends Component<PageErrorBoundaryProps, PageErrorBoundaryState> {
  state: PageErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): PageErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Control Plane page render failed', error, info.componentStack);
  }

  componentDidUpdate(previous: PageErrorBoundaryProps): void {
    if (previous.resetKey !== this.props.resetKey && this.state.error !== null) {
      this.setState({ error: null });
    }
  }

  render(): ReactNode {
    const { error } = this.state;
    if (error === null) {
      return this.props.children;
    }
    return (
      <Alert isInline variant="danger" title="이 화면을 표시하지 못했습니다.">
        <p>다른 화면은 계속 사용할 수 있습니다. 문제가 반복되면 Gateway 로그에서 원인을 확인하세요.</p>
        <p><code>{error.message}</code></p>
        <Button variant="secondary" onClick={() => this.setState({ error: null })}>다시 시도</Button>
      </Alert>
    );
  }
}
