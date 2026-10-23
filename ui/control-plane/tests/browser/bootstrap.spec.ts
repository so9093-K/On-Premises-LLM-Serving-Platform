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
