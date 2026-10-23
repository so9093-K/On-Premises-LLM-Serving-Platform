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
