import { expect, test } from '@playwright/test';

test('Bootstrap 조회가 실패하면 화면에서 오류를 안내한다', async ({ page }) => {
  await page.route('**/admin/control-plane/bootstrap', async (route) => {
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ error: { code: 'UNAVAILABLE', message: 'service unavailable' } }),
    });
  });
  await page.goto('/');
  await expect(page.getByText('Control Plane 정보를 불러오지 못했습니다.')).toBeVisible();
});

test('관리자 인증이 필요한 배포에서는 인증 화면을 우선 표시한다', async ({ page }) => {
  await page.route('**/admin/control-plane/bootstrap', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ bootstrap_version: 4, access: { admin_auth_required: true } }),
    });
  });
  await page.goto('/');
  await expect(page.getByText('관리자 인증')).toBeVisible();
  await expect(page.getByLabel('관리자 키')).toBeVisible();
});


test('Playground 화면 이동 후 Chat 초안과 선택 모델을 함께 보존한다', async ({ page }) => {
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      bootstrap_version: 4,
      access: { admin_auth_required: false },
      deployment: {
        target: 'linux-nvidia-dynamic',
        display_name: '테스트 Linux',
        runtime_backend: 'llama-cpp',
        features: ['chat', 'risk'],
      },
      links: { grafana: null, docs: null },
    }),
  }));
  await page.route('**/v1/models', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      object: 'list',
      data: ['first-model', 'second-model'].map((id) => ({
        id,
        backend: 'llama-cpp',
        capabilities: ['chat.completions'],
        input_modalities: ['text'],
        context_window: 8192,
        request_parameters: {},
      })),
    }),
  }));

  await page.goto('/admin/console/playground/chat');
  const picker = page.getByLabel('현재 모델');
  await expect(picker).toBeVisible();
  await picker.selectOption('second-model');
  await page.getByLabel('메시지').fill('전송하지 않은 중요한 초안');

  await page.getByRole('link', { name: 'Risk', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Risk' })).toBeVisible();
  await page.getByRole('link', { name: 'Chat', exact: true }).click();

  await expect(page.getByLabel('현재 모델')).toHaveValue('second-model');
  await expect(page.getByLabel('메시지')).toHaveValue('전송하지 않은 중요한 초안');
});

test('Risk 예제 선택은 작성 중 입력을 확인 없이 교체하지 않는다', async ({ page }) => {
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      bootstrap_version: 4,
      access: { admin_auth_required: false },
      deployment: {
        target: 'linux-core',
        display_name: 'Core',
        runtime_backend: 'none',
        features: ['risk'],
      },
      links: { grafana: null, docs: null },
    }),
  }));
  await page.route('**/v1/models', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ object: 'list', data: [] }),
  }));
  await page.goto('/admin/console/playground/risk');
  const prompt = page.getByLabel('검사할 텍스트');
  await prompt.fill('작성 중인 내부 검사 내용');
  await page.getByRole('button', { name: /연락처 정보/ }).click();
  await expect(page.getByText('작성 중인 검사 텍스트를 합성 예제로 교체합니다.')).toBeVisible();
  await expect(prompt).toHaveValue('작성 중인 내부 검사 내용');
  await page.getByRole('button', { name: '취소' }).click();
  await expect(prompt).toHaveValue('작성 중인 내부 검사 내용');
  await page.getByRole('button', { name: /연락처 정보/ }).click();
  await page.getByRole('button', { name: '기존 입력 교체' }).click();
  await expect(prompt).toContainText('gildong.hong@example.com');
});

test('API 키를 삭제하면 이전 Chat 초안과 요청 설정이 함께 초기화된다', async ({ page }) => {
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      bootstrap_version: 4,
      access: { admin_auth_required: false },
      deployment: {
        target: 'linux-cpu-managed',
        display_name: 'CPU',
        runtime_backend: 'llama-cpp',
        features: ['chat', 'risk'],
      },
      links: { grafana: null, docs: null },
    }),
  }));
  await page.route('**/v1/models', (route) => route.fulfill({
    status: route.request().headers()['authorization'] ? 200 : 401,
    contentType: 'application/json',
    body: route.request().headers()['authorization']
      ? JSON.stringify({ object: 'list', data: [{
        id: route.request().headers()['authorization'].includes('second-user-key')
          ? 'second-model' : 'first-model',
        backend: 'llama-cpp',
        capabilities: ['chat.completions'],
        input_modalities: ['text'],
        context_window: 8192,
        request_parameters: {},
      }] })
      : JSON.stringify({ error: { code: 'UNAUTHORIZED', message: 'API key required' } }),
  }));
  await page.goto('/admin/console/playground/chat');
  await expect(page.getByLabel('API 키')).toBeVisible();
  await page.getByLabel('API 키').fill('first-user-key');
  await page.getByRole('button', { name: '사용', exact: true }).click();

  const prompt = page.getByLabel('메시지');
  await expect(prompt).toBeVisible();
  await expect(page.getByLabel('현재 요청 모델 한도').getByText('first-model', { exact: true })).toBeVisible();
  await prompt.fill('키 A로 작성한 초안');
  await page.getByRole('link', { name: /요청 설정/ }).click();
  await page.getByLabel('시스템 프롬프트').fill('키 A의 시스템 프롬프트');
  await expect(page.getByText(/요청 설정 · 변경됨/)).toBeVisible();
  await page.getByRole('button', { name: 'API 키 지우기' }).click();
  await expect(page.getByText('진행 중인 Chat 요청을 중지하고')).toBeVisible();
  await page.getByRole('button', { name: 'API 키 및 Chat 세션 지우기' }).click();
  await expect(page.getByLabel('API 키')).toBeVisible();
  await page.getByLabel('API 키').fill('second-user-key');
  await page.getByRole('button', { name: '사용', exact: true }).click();
  await expect(page.getByLabel('메시지')).toHaveValue('');
  await expect(page.getByLabel('현재 요청 모델 한도').getByText('second-model', { exact: true })).toBeVisible();
  await expect(page.getByLabel('현재 요청 모델 한도').getByText('first-model', { exact: true })).toHaveCount(0);
  await page.getByRole('link', { name: /요청 설정/ }).click();
  await expect(page.getByLabel('시스템 프롬프트')).toHaveValue('');
});

test('Risk 입력을 변경하면 마지막 실행 결과로 구분한다', async ({ page }) => {
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      bootstrap_version: 4,
      access: { admin_auth_required: false },
      deployment: { target: 'linux-core', display_name: 'Core', runtime_backend: 'none', features: ['risk'] },
      links: { grafana: null, docs: null },
    }),
  }));
  await page.route('**/v1/models', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ object: 'list', data: [] }),
  }));
  await page.route('**/v1/risk/detectors/pii/assessments', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      status: 'completed', assessment_complete: true, risk_detected: false,
      system_signal_detected: false, categories: [], system_signals: [],
    }),
  }));
  await page.goto('/admin/console/playground/risk');
  await page.getByLabel('검사할 텍스트').fill('첫 검사 입력');
  await page.getByRole('button', { name: '검사', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Risk 결과' })).toBeVisible();
  await page.getByLabel('검사할 텍스트').fill('수정된 검사 입력');
  await expect(page.getByText('이전 입력의 검사 결과입니다.')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Risk 결과' })).toContainText('마지막 검사 결과');
  await page.getByRole('button', { name: '검사', exact: true }).click();
  await expect(page.getByText('이전 입력의 검사 결과입니다.')).toHaveCount(0);
});

test('Embedding 입력 변경 뒤 기존 벡터를 마지막 실행 결과로 표시한다', async ({ page }) => {
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      bootstrap_version: 4,
      access: { admin_auth_required: false },
      deployment: {
        target: 'linux-nvidia-dynamic', display_name: 'GPU',
        runtime_backend: 'vllm-cuda', features: ['embeddings'],
      },
      links: { grafana: null, docs: null },
    }),
  }));
  await page.route('**/v1/models', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      object: 'list',
      data: [{
        id: 'local-embed',
        backend: 'vllm-cuda',
        capabilities: ['embeddings'],
        input_modalities: ['text'],
        request_parameters: {},
      }],
    }),
  }));
  await page.route('**/v1/embeddings', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      object: 'list', model: 'local-embed',
      data: [{ index: 0, object: 'embedding', embedding: [0.5, 0.2, 0.1] }],
      usage: { prompt_tokens: 3, total_tokens: 3 },
    }),
  }));
  await page.goto('/admin/console/playground/embeddings');
  const input = page.getByLabel('텍스트', { exact: true });
  await input.fill('최초 임베딩 입력');
  await page.getByRole('button', { name: '벡터 생성' }).click();
  await expect(page.getByRole('region', { name: 'Embedding 결과' })).toBeVisible();
  await input.fill('수정된 임베딩 입력');
  await expect(page.getByText('이전 입력의 실행 결과입니다.')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Embedding 결과' })).toContainText('마지막 실행 결과');
});

test('운영 활동에서 과거 페이지를 열어도 최신 작업 상태를 덮어쓰지 않는다', async ({ page }) => {
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      bootstrap_version: 4, access: { admin_auth_required: false },
      deployment: {
        target: 'linux-nvidia-dynamic', display_name: 'GPU',
        runtime_backend: 'vllm-cuda', features: ['runtime_control'],
      },
      links: { grafana: null, docs: null },
    }),
  }));
  const operation = (id: string, updatedAt: number, status: string, serviceKey = 'embedding') => ({
    operation_id: id, service_key: serviceKey, desired_state: 'active',
    status, phase: 'completed', updated_at: updatedAt, request_id: `request-${id}`,
    actor: { actor_id: 'operator', auth_method: 'admin' },
    plan_digest: null, verification: { converged: true }, force: false, durable: true,
  });
  await page.route('**/admin/runtimes/operations?*', (route) => {
    const cursor = new URL(route.request().url()).searchParams.get('cursor');
    const body = cursor
      ? { items: [
        operation('same-task', 100, 'pending'),
        operation('older-task', 90, 'noop', 'prompt_injection_detector'),
      ], next_cursor: null }
      : { items: [operation('same-task', 200, 'verified')], next_cursor: 'older-page' };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.route('**/admin/config/history*', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], next_cursor: null }),
  }));
  await page.goto('/admin/console/operations');
  await expect(page.locator('.activity-timeline-item')).toHaveCount(1);
  await page.getByRole('button', { name: '이전 런타임 작업 더 보기' }).click();
  await expect(page.locator('.activity-timeline-item')).toHaveCount(2);
  const current = page.locator('.activity-timeline-item').filter({ hasText: 'embedding → active' });
  await expect(current).toHaveCount(1);
  await expect(current).toContainText('검증 완료');
  await expect(current).not.toContainText('진행 중');
  await expect(page.getByText('자동 갱신을 중지합니다.', { exact: false })).toBeVisible();
});

test('런타임 시작 검토를 선택하면 영향 확인 영역에 키보드 포커스가 이동한다', async ({ page }) => {
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      bootstrap_version: 4, access: { admin_auth_required: false },
      deployment: {
        target: 'linux-nvidia-dynamic', display_name: 'GPU',
        runtime_backend: 'vllm-cuda', features: ['runtime_control'],
      },
      links: { grafana: null, docs: null },
    }),
  }));
  await page.route('**/admin/runtimes', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      runtimes: [{
        service_key: 'embedding', display_name: 'Embedding Runtime',
        state: 'stopped', container_status: 'stopped',
        runtime_backend: 'vllm-cuda', upstream_model_id: 'embed-model',
        vram_fraction: 0.1, criticality: 'retrieval_support_path',
      }],
      budget: { used: 0, free: 0.8, ceiling: 0.8 },
      topology: [],
    }),
  }));
  await page.route('**/admin/runtimes/embedding/plans', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      service_key: 'embedding', current_state: 'stopped', desired_state: 'active',
      no_op: false, admissible: true, force: false, requires_force: false,
      start: ['embedding'], stop: [], prerequisites: [], impact: [],
      budget: { before: { used: 0, free: 0.8, ceiling: 0.8 }, after: { used: 0.1, free: 0.7, ceiling: 0.8 } },
      plan_digest: 'test-plan', reason: null,
    }),
  }));
  await page.goto('/admin/console/runtimes');
  await page.getByRole('button', { name: '시작 검토' }).click();
  const review = page.getByRole('region', { name: '런타임 변경 영향 확인' });
  await expect(review).toBeVisible();
  await expect(review).toBeFocused();
  await review.getByRole('button', { name: '취소' }).click();
  await expect(review).toHaveCount(0);
});
