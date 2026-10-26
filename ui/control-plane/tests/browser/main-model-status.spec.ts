import { expect, test, type Page } from '@playwright/test';

async function mockMainModel(page: Page, gate: 'open' | 'closed' = 'open') {
  const cpu = {
    id: 'cpu-gguf-text', display_name: 'Qwen3 0.6B · CPU',
    upstream_model_id: 'Qwen/Qwen3-0.6B-GGUF', revision: 'a'.repeat(40),
    runtime_backend: 'llama-cpp', served_model_name: 'local-main',
    context_tokens_ceiling: 16384,
    compatibility: { status: 'compatible' }, qualification: { status: 'verified' },
    capabilities: { deployed_input: ['text'] }, vram_fraction: 0,
    resource_variant: null, resource_variants: [], active: true,
    gateway_policy: { max_output_tokens: 4096, request_limits: { max_model_len: 8192, input_modalities: ['text'] } },
    switch_preflight: { status: 'current' },
  };
  const gpu = { ...cpu, id: 'gemma-gpu', upstream_model_id: 'google/gemma-4-E4B-it',
    display_name: 'Gemma · GPU', runtime_backend: 'vllm-cuda', active: false,
    vram_fraction: 0.5, switch_preflight: { status: 'fits' } };
  await page.route('**/admin/control-plane/bootstrap', route => route.fulfill({ json: {
    bootstrap_version: 4, access: { admin_auth_required: false },
    deployment: { target: 'linux-nvidia-dynamic', display_name: 'GPU/CPU',
      runtime_backend: 'vllm-cuda', features: ['chat', 'model_switching', 'runtime_control'] },
    links: { grafana: null, docs: null },
  } }));
  await page.route('**/admin/main-model/profiles', route => route.fulfill({ json: { profiles: [cpu, gpu] } }));
  await page.route('**/admin/main-model', route => route.fulfill({ json: {
    public_model: 'local-main', active_profile: cpu, last_known_good_profile: cpu.id,
    last_operation: null, gate, runtime_state: 'active', boot_profile: gpu.id, profile_locked: false,
    observed_runtime: { status: 'running', health: 'healthy', profile_id: cpu.id },
    runtime_selection: { mode: 'fallback', reason_code: 'CPU_FALLBACK_ACTIVE',
      cpu_profile: cpu.id, gpu_profile: gpu.id, gpu_condition: 'GPU_RUNTIME_UNHEALTHY',
      observed_at: 1792974960,
      resources: { gpus: [{ index: 0, name: 'NVIDIA GeForce RTX 4090',
        free_mib: 23145, total_mib: 24564, uuid: 'GPU-test-device-uuid',
        pci_bus_id: '00000000:01:00.0', compute_capability: '8.9', driver_version: '580.178.04' }] },
    }, stats: {},
  } }));
}

for (const width of [1440, 390]) {
  test(`CPU 서빙과 마지막 GPU 판단을 구분하고 정책 변경은 검토를 거친다 (${width}px)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockMainModel(page);
    let switches = 0;
    await page.route('**/admin/main-model/switch', route => { switches += 1; return route.abort(); });
    await page.goto('/admin/console/main-model');
    const card = page.locator('.main-execution-card');
    await expect(card.getByText('CPU · llama.cpp', { exact: true })).toBeVisible();
    await expect(card.getByText('요청 수락 중', { exact: true })).toBeVisible();
    await expect(card.getByText('새 요청 차단 중', { exact: true })).toHaveCount(0);
    await expect(card.getByText('GPU-test-device-uuid', { exact: true })).toBeHidden();
    const retry = card.getByRole('button', { name: 'GPU 다시 확인', exact: true });
    const cpu = card.getByRole('button', { name: 'CPU 고정', exact: true });
    expect((await retry.boundingBox())!.height).toBeLessThan(50);
    expect((await cpu.boundingBox())!.height).toBeLessThan(50);
    await expect(card.getByRole('button', { name: 'GPU 고정', exact: true })).toBeHidden();
    await card.getByText('GPU 상태 및 장치 정보', { exact: true }).click();
    await expect(card.getByText('GPU 런타임 응답 확인 실패', { exact: true })).toBeVisible();
    await expect(card.getByText('GPU-test-device-uuid', { exact: true })).toBeVisible();
    await expect(card.getByText('요청 수락 중', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await card.getByText('고급 실행 정책', { exact: true }).click();
    await expect(card.getByRole('button', { name: 'GPU 고정', exact: true })).toBeVisible();
    expect((await retry.boundingBox())!.height).toBeLessThan(50);
    await retry.click();
    await expect(page.getByRole('region', { name: '모델 전환 영향 확인' })).toBeVisible();
    await expect(page.getByRole('heading', { name: /GPU 사용을 검토하고, 불가능하면 CPU를 유지합니다/ })).toBeVisible();
    expect(switches).toBe(0);
  });
}

test('실제 Gate가 닫혀 있으면 CPU 프로필이어도 요청 차단 상태를 표시한다', async ({ page }) => {
  await mockMainModel(page, 'closed');
  await page.goto('/admin/console/main-model');
  const card = page.locator('.main-execution-card');
  await expect(card.getByText('새 요청 차단 중', { exact: true })).toBeVisible();
  await expect(card.getByText('요청 수락 중', { exact: true })).toHaveCount(0);
});
