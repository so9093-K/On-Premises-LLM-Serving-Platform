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
