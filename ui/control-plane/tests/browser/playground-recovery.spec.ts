import { expect, test, type Page } from '@playwright/test';

async function bootstrap(page: Page, features: string[]) {
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    json: {
      bootstrap_version: 4, access: { admin_auth_required: false },
      deployment: { target: 'linux-nvidia-dynamic', display_name: '테스트 Linux', runtime_backend: 'vllm-cuda', features },
      links: { grafana: null, docs: null },
    },
  }));
}

test('API 키를 지운 뒤 완료된 파일 읽기는 새 세션에 첨부를 복원하지 않는다', async ({ page }) => {
  await bootstrap(page, ['chat', 'risk']);
  await page.addInitScript(() => {
    const pending: { reader: FileReader; file: Blob }[] = [];
    const original = FileReader.prototype.readAsDataURL;
    FileReader.prototype.readAsDataURL = function (file) { pending.push({ reader: this, file }); };
    Object.assign(window, { releaseFileReads: () => Promise.all(pending.map(({ reader, file }) => new Promise<void>((resolve) => {
      reader.addEventListener('loadend', () => resolve(), { once: true });
      original.call(reader, file);
    }))) });
  });
  await page.route('**/v1/models', (route) => route.request().headers().authorization
    ? route.fulfill({ json: { object: 'list', data: [{
      id: 'vision-main', backend: 'vllm-cuda', capabilities: ['chat.completions'],
      input_modalities: ['text', 'image'], context_window: 8192, request_parameters: {},
      request_limits: { image: { max_inputs: 2, max_bytes: 1_000_000, allowed_schemes: ['data'], allowed_mime_types: ['image/png'] } },
    }] } })
    : route.fulfill({ status: 401, json: { error: { code: 'UNAUTHORIZED', message: 'API key required' } } }));
  await page.goto('/admin/console/playground/chat');
  await page.getByLabel('API 키', { exact: true }).fill('first-key');
  await page.getByRole('button', { name: '사용', exact: true }).click();
  await page.locator('#chat-attachments').setInputFiles({
    name: 'previous-user.png', mimeType: 'image/png', buffer: Buffer.from('test image bytes'),
  });
  await expect(page.getByText('첨부 파일 읽는 중…')).toBeVisible();
  await page.getByRole('button', { name: 'API 키 지우기', exact: true }).click();
  await page.getByRole('button', { name: 'API 키 및 작업 데이터 지우기' }).click();
  await page.getByLabel('API 키', { exact: true }).fill('second-key');
  await page.getByRole('button', { name: '사용', exact: true }).click();
  await expect(page.getByLabel('메시지', { exact: true })).toBeVisible();
  await page.evaluate(async () => {
    await (window as unknown as { releaseFileReads(): Promise<void> }).releaseFileReads();
    await new Promise(requestAnimationFrame);
  });
  await expect(page.getByText('previous-user.png', { exact: false })).toHaveCount(0);
});

const embeddingModel = (id: string) => ({
  id, backend: 'vllm-cuda', capabilities: ['embeddings'], input_modalities: ['text'],
  embedding: { dimensions: [3] }, request_parameters: {},
});

test('Embedding 모델이 사라져도 다른 모델을 자동 선택하거나 초안을 숨기지 않는다', async ({ page }) => {
  await page.clock.install();
  await bootstrap(page, ['embeddings']);
  let changed = false;
  let requests = 0;
  await page.route('**/v1/models', (route) => route.fulfill({
    json: { object: 'list', data: [embeddingModel(changed ? 'replacement-embed' : 'chosen-embed')] },
  }));
  await page.route('**/v1/embeddings', (route) => { requests += 1; return route.abort(); });
  await page.goto('/admin/console/playground/embeddings');
  await page.getByLabel('텍스트', { exact: true }).fill('유지할 Embedding 입력');
  await expect(page.getByLabel('Embedding 모델', { exact: true })).toHaveValue('chosen-embed');
  changed = true;
  await page.clock.fastForward(16_000);
  await expect(page.getByText('이전에 선택한 Embedding 모델을 사용할 수 없습니다.')).toBeVisible();
  await expect(page.getByLabel('텍스트', { exact: true })).toHaveValue('유지할 Embedding 입력');
  await expect(page.getByRole('button', { name: '벡터 생성' })).toBeDisabled();
  expect(requests).toBe(0);
  await page.getByLabel('Embedding 모델', { exact: true }).selectOption('replacement-embed');
  await expect(page.getByRole('button', { name: '벡터 생성' })).toBeEnabled();
  await expect(page.getByLabel('텍스트', { exact: true })).toHaveValue('유지할 Embedding 입력');
});

test('Embedding 모델 재조회 실패는 초안과 결과를 보존하고 재조회로 복구한다', async ({ page }) => {
  await page.clock.install();
  await bootstrap(page, ['embeddings']);
  let failed = false;
  let requests = 0;
  await page.route('**/v1/models', (route) => route.fulfill(failed
    ? { status: 503, json: { error: { code: 'UNAVAILABLE', message: 'temporary model list failure' } } }
    : { json: { object: 'list', data: [embeddingModel('chosen-embed')] } }));
  await page.route('**/v1/embeddings', (route) => {
    requests += 1;
    return route.fulfill({ json: { model: 'chosen-embed', data: [{ index: 0, embedding: [1, 0, 0] }] } });
  });
  await page.goto('/admin/console/playground/embeddings');
  await page.getByLabel('텍스트', { exact: true }).fill('유지할 입력');
  await page.getByRole('button', { name: '벡터 생성' }).click();
  await expect(page.getByRole('region', { name: 'Embedding 결과' })).toBeVisible();
  failed = true;
  await page.clock.fastForward(16_000);
  await expect(page.getByText('모델 목록을 불러오지 못했습니다.')).toBeVisible();
  await expect(page.getByLabel('텍스트', { exact: true })).toHaveValue('유지할 입력');
  await expect(page.getByRole('region', { name: 'Embedding 결과' })).toBeVisible();
  await expect(page.getByRole('button', { name: '벡터 생성' })).toBeDisabled();
  expect(requests).toBe(1);
  failed = false;
  await page.getByRole('button', { name: '모델 정보 다시 조회' }).click();
  await expect(page.getByRole('button', { name: '벡터 생성' })).toBeEnabled();
});

test('모바일 메뉴는 작업 화면을 가리지 않고 키보드로 열고 닫을 수 있다', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await bootstrap(page, ['chat', 'risk']);
  await page.route('**/v1/models', (route) => route.fulfill({ json: { object: 'list', data: [{
    id: 'local-main', backend: 'llama-cpp', capabilities: ['chat.completions'], input_modalities: ['text'], request_parameters: {},
  }] } }));
  await page.goto('/admin/console/playground/chat');
  const navigation = page.getByRole('complementary', { name: 'Control Plane 탐색' });
  const toggle = page.getByRole('button', { name: '메뉴', exact: true });
  await expect(navigation).toBeHidden();
  expect((await page.getByRole('heading', { name: 'Playground', exact: true }).boundingBox())!.y).toBeLessThan(160);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(navigation).toBeVisible();
  await navigation.getByRole('link', { name: 'Playground', exact: true }).focus();
  await page.keyboard.press('Escape');
  await expect(navigation).toBeHidden();
  await expect(toggle).toBeFocused();
  await page.keyboard.press('Enter');
  await navigation.getByRole('link', { name: '운영 활동', exact: true }).click();
  await expect(navigation).toBeHidden();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(page.locator('main.content')).toBeFocused();
});
