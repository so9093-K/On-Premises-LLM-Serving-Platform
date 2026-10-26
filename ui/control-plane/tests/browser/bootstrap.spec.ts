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
  await expect(page.locator('.chat-model-context').getByText('first-model', { exact: true })).toBeVisible();
  await prompt.fill('키 A로 작성한 초안');
  await page.getByRole('link', { name: /요청 설정/ }).click();
  await page.getByLabel('시스템 프롬프트').fill('키 A의 시스템 프롬프트');
  await expect(page.getByText(/요청 설정 · 변경됨/)).toBeVisible();
  await page.getByRole('button', { name: 'API 키 지우기' }).click();
  await expect(page.getByText('진행 중인 Chat 요청을 중지하고')).toBeVisible();
  await page.getByRole('button', { name: 'API 키 및 작업 데이터 지우기' }).click();
  await expect(page.getByLabel('API 키')).toBeVisible();
  await page.getByLabel('API 키').fill('second-user-key');
  await page.getByRole('button', { name: '사용', exact: true }).click();
  await expect(page.getByLabel('메시지')).toHaveValue('');
  await expect(page.locator('.chat-model-context').getByText('second-model', { exact: true })).toBeVisible();
  await expect(page.locator('.chat-model-context').getByText('first-model', { exact: true })).toHaveCount(0);
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

test('새 Chat의 예제를 표시하고 응답 후에도 대화 입력을 제공한다', async ({ page }) => {
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      bootstrap_version: 4, access: { admin_auth_required: false },
      deployment: { target: 'linux-cpu-managed', display_name: 'CPU', runtime_backend: 'llama-cpp', features: ['chat', 'risk'] },
      links: { grafana: null, docs: null },
    }),
  }));
  await page.route('**/v1/models', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      object: 'list',
      data: [{ id: 'local-main', backend: 'llama-cpp', display_name: 'CPU Model', capabilities: ['chat.completions'], input_modalities: ['text'], context_window: 8192, request_parameters: {} }],
    }),
  }));
  await page.route('**/v1/chat/completions', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      id: 'chatcmpl-test', object: 'chat.completion', model: 'local-main', choices: [
        { index: 0, message: { role: 'assistant', content: '응답 '.repeat(450) }, finish_reason: 'stop' },
      ],
      usage: { prompt_tokens: 2, completion_tokens: 500, total_tokens: 502 },
    }),
  }));
  await page.goto('/admin/console/playground/chat');
  const conversation = page.getByRole('region', { name: '대화와 시작 예제' });
  const input = page.getByRole('textbox', { name: '메시지' });
  await expect(page.getByRole('button', { name: '예제 닫기' })).toBeVisible();
  await expect(conversation.getByRole('group', { name: '예제 선택' })).toBeVisible();
  await expect(conversation.getByText('현재 모델은 이미지 입력을 지원하지 않습니다.', { exact: false }).first()).toBeVisible();
  await input.fill('긴 답변');
  await page.getByRole('button', { name: '보내기' }).click();
  await expect(conversation.getByText('응답 ', { exact: false }).first()).toBeVisible();
  await expect(input).toBeEditable();
  await expect(page.getByRole('button', { name: '예제로 시작하기' })).toBeVisible();
});

test('관리형 CPU 서버 한도 조정은 확인 후 Runtime Controller 요청으로 전달한다', async ({ page }) => {
  const profile = {
    id: 'cpu-gguf-text', display_name: 'Qwen3 0.6B · 기본 CPU',
    context_tokens_ceiling: 16384,
    upstream_model_id: 'Qwen/Qwen3-0.6B-GGUF', revision: 'a'.repeat(40),
    runtime_backend: 'llama-cpp', served_model_name: 'local-main',
    compatibility: { status: 'compatible' }, qualification: { status: 'verified' },
    capabilities: { deployed_input: ['text'] }, vram_fraction: 0,
    resource_variant: null, resource_variants: [],
    gateway_policy: {
      max_output_tokens: 4096,
      request_limits: { max_model_len: 8192, input_modalities: ['text'] },
    },
    active: true, switch_preflight: { status: 'current' },
  };
  let submitted: Record<string, unknown> | null = null;
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      bootstrap_version: 4, access: { admin_auth_required: false },
      deployment: {
        target: 'linux-nvidia-dynamic', display_name: 'GPU/CPU Controller',
        runtime_backend: 'llama-cpp', control_mode: 'runtime_controller',
        lifecycle_owner: 'platform', features: ['model_switching', 'chat'],
      },
      links: { grafana: null, docs: null },
    }),
  }));
  await page.route('**/admin/main-model/profiles', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ profiles: [profile] }),
  }));
  await page.route('**/admin/main-model', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      public_model: 'local-main', active_profile: profile,
      last_known_good_profile: profile.id, last_operation: null,
      gate: 'open', runtime_state: 'active', boot_profile: profile.id,
      profile_locked: false,
      observed_runtime: { status: 'ready', health: 'healthy', profile_id: profile.id },
      runtime_selection: { mode: 'cpu', reason_code: 'OPERATOR_SELECTED', cpu_profile: profile.id },
      stats: {},
    }),
  }));
  await page.route('**/admin/main-model/switch', (route) => {
    submitted = route.request().postDataJSON() as Record<string, unknown>;
    return route.fulfill({
      status: 202, contentType: 'application/json',
      body: JSON.stringify({ operation_id: 'test-limit-operation', status: 'pending', reused: false }),
    });
  });
  await page.route('**/admin/main-model/operations/**', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      operation_id: 'test-limit-operation', status: 'pending', stage: 'pending',
      requested_profile: profile.id, created_at: 0, updated_at: 0,
    }),
  }));
  await page.goto('/admin/console/main-model');
  await page.getByRole('button', { name: '현재 구성 한도 조정' }).click();
  const settings = page.getByRole('group', { name: '서버 실행 토큰 한도 편집' });
  await expect(settings).toBeVisible();
  await settings.getByLabel('문맥 토큰').fill('12288');
  await settings.getByLabel('최대 출력 토큰').fill('2048');
  await expect(page.getByText('서버 실행 설정이 변경됩니다.')).toBeVisible();
  await page.getByRole('checkbox', { name: /미검증 상태를 확인했고/ }).check();
  await page.getByRole('button', { name: '실행 한도 변경 요청' }).click();
  await expect.poll(() => submitted).toMatchObject({
    profile: 'cpu-gguf-text', execution_policy: 'cpu',
    confirm_unverified: true,
    server_limits: { context_tokens: 12288, max_output_tokens: 2048 },
  });
});


test('같은 GPU 모델의 더 큰 프로필이 선택 기준의 문맥 상한을 올리지 않는다', async ({ page }) => {
  const gpuProfile = (id: string, context: number, active: boolean) => ({
    id, display_name: id, upstream_model_id: 'google/gemma-4-E4B-it',
    revision: 'b'.repeat(40), served_model_name: 'local-main',
    runtime_backend: 'vllm-cuda',
    compatibility: { status: 'compatible' }, qualification: { status: 'verified' },
    capabilities: { deployed_input: ['text'] }, vram_fraction: 0.5,
    resource_variant: null, resource_variants: [],
    gateway_policy: {
      max_output_tokens: 4096,
      request_limits: { max_model_len: context, input_modalities: ['text'] },
    },
    active, switch_preflight: { status: active ? 'current' : 'fits' },
  });
  const small = gpuProfile('gpu-small', 8192, true);
  const large = gpuProfile('gpu-large', 32768, false);
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      bootstrap_version: 4, access: { admin_auth_required: false },
      deployment: {
        target: 'linux-nvidia-dynamic', display_name: '관리형 Linux',
        runtime_backend: 'vllm-cuda', control_mode: 'runtime_controller',
        lifecycle_owner: 'platform', features: ['model_switching', 'chat'],
      },
      links: { grafana: null, docs: null },
    }),
  }));
  await page.route('**/admin/main-model/profiles', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ profiles: [small, large] }),
  }));
  await page.route('**/admin/main-model', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      public_model: 'local-main', active_profile: small,
      last_known_good_profile: small.id, last_operation: null,
      gate: 'open', runtime_state: 'active', boot_profile: small.id,
      profile_locked: false,
      observed_runtime: { status: 'ready', health: 'healthy', profile_id: small.id },
      runtime_selection: { mode: 'gpu', reason_code: 'OPERATOR_SELECTED', gpu_profile: small.id },
      stats: {},
    }),
  }));
  await page.goto('/admin/console/main-model');
  await page.getByRole('button', { name: '현재 구성 한도 조정' }).click();
  const group = page.getByRole('group', { name: '서버 실행 토큰 한도 편집' });
  const context = group.getByLabel('문맥 토큰');
  await expect(context).toHaveAttribute('max', '8192');
  await context.fill('12288');
  await expect(page.getByText('실행 한도 값이 유효하지 않습니다.')).toBeVisible();
  await expect(page.getByRole('button', { name: '실행 한도 변경 요청' })).toBeDisabled();
});

test('Bootstrap의 일시적인 503 오류를 화면에서 복구한다', async ({ page }) => {
  let reads = 0;
  await page.route('**/admin/control-plane/bootstrap', async (route) => {
    reads += 1;
    await route.fulfill({
      status: reads === 1 ? 503 : 200,
      contentType: 'application/json',
      body: reads === 1
        ? JSON.stringify({ error: { code: 'UNAVAILABLE', message: 'service unavailable' } })
        : JSON.stringify({ bootstrap_version: 4, access: { admin_auth_required: true } }),
    });
  });
  await page.goto('/');
  await expect(page.getByText('Control Plane 정보를 불러오지 못했습니다.')).toBeVisible();
  await page.getByRole('button', { name: '다시 시도' }).click();
  await expect(page.getByText('관리자 인증')).toBeVisible();
  expect(reads).toBe(2);
});

test('설정 412 충돌 후 최신 상태를 읽어도 작성 중인 값을 보존한다', async ({ page }) => {
  let revision = 1;
  let effectiveValue = 10;
  const status = () => ({
    available: true, reason: null, store_revision: revision,
    resolver_revision: revision, runtime_revision: revision,
    synchronized: true, pending_operations: 0,
  });
  const key = 'operational.max_retrieval_documents';
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      bootstrap_version: 4, access: { admin_auth_required: false },
      deployment: { target: 'linux-core', display_name: 'Core', runtime_backend: 'none', features: ['risk'] },
      configuration: { write_available: true },
      links: { grafana: null, docs: null },
    }),
  }));
  await page.route('**/admin/config/schema', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      version: 2, write_status: status(),
      items: [{
        key, label: 'Maximum Retrieval Documents', group: 'retrieval', order: 1,
        type: 'integer', owner: 'operator', editable: true, control_surface: 'configuration',
        sensitive: false, effective_source: 'operator', apply_mode: 'hot_reload', risk: 'low',
        applicability: { features: [] }, meaning: '검색 문서 최대 수', help: '설정 변경 검토',
        related_adrs: ['ADR-0021'], minimum: 1, maximum: 50,
      }],
    }),
  }));
  await page.route('**/admin/config/effective', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    headers: { etag: `"revision-${revision}"` },
    body: JSON.stringify({
      version: 2, revision, write_status: status(),
      items: [{
        key, default_value: 10, operator_value: effectiveValue,
        effective_value: effectiveValue, effective_source: 'operator',
        owner: 'operator', control_surface: 'configuration',
        editable: true, sensitive: false, configured: true,
      }],
    }),
  }));
  await page.route('**/admin/config/plans', (route) => {
    revision = 2;
    effectiveValue = 12;
    return route.fulfill({
      status: 412, contentType: 'application/json',
      body: JSON.stringify({ error: { code: 'CONFIG_REVISION_CONFLICT', message: '다른 운영자가 변경했습니다.' } }),
    });
  });
  await page.route('**/admin/config/history**', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ items: [], next_cursor: null }),
  }));

  await page.goto('/admin/console/configuration');
  await page.getByRole('button', { name: '편집' }).click();
  await page.getByLabel('새 운영자 값').fill('16');
  await page.getByRole('button', { name: '변경 내용 검토' }).click();
  await expect(page.getByText('편집 중 설정이 변경됐습니다.')).toBeVisible();
  await expect(page.getByLabel('새 운영자 값')).toHaveValue('16');
  await expect(page.getByText('편집 시작 값')).toBeVisible();
  await expect(page.getByText('최신 적용 값')).toBeVisible();
  await expect(page.getByText('작성 중인 값')).toBeVisible();
  await expect(page.getByText('12', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('16', { exact: true }).first()).toBeVisible();
});

test('외부 모델 정책 변경을 활성 Playground가 반영하고 미전송 메시지를 유지한다', async ({ page }) => {
  await page.clock.install();
  let unavailable = false;
  let requests = 0;
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      bootstrap_version: 4, access: { admin_auth_required: false },
      deployment: {
        target: 'linux-nvidia-dynamic', display_name: '테스트 Linux',
        runtime_backend: 'llama-cpp', features: ['chat', 'model_switching'],
      },
      links: { grafana: null, docs: null },
    }),
  }));
  await page.route('**/v1/models', (route) => {
    requests += 1;
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        object: 'list', data: [{
          id: 'local-main', backend: unavailable ? 'unknown' : 'llama-cpp',
          serving_policy_status: unavailable ? 'controller_unavailable' : 'active',
          capabilities: ['chat.completions'], input_modalities: ['text'],
          context_window: unavailable ? undefined : 8192, request_parameters: {},
        }],
      }),
    });
  });
  await page.goto('/admin/console/playground/chat');
  await expect(page.getByLabel('메시지')).toBeVisible();
  await page.getByLabel('메시지').fill('보호해야 하는 미전송 초안');
  unavailable = true;
  await page.clock.fastForward(16_000);
  await expect(page.getByText('모델 제어 서비스에 연결할 수 없습니다.')).toBeVisible();
  await expect(page.getByLabel('메시지')).toHaveValue('보호해야 하는 미전송 초안');
  await expect(page.getByRole('button', { name: '보내기' })).toBeDisabled();
  expect(requests).toBeGreaterThan(1);
});

test('Risk 작업 중 API 키 삭제는 모든 Playground 데이터에 대해 확인한다', async ({ page }) => {
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      bootstrap_version: 4, access: { admin_auth_required: false },
      deployment: { target: 'linux-core', display_name: 'Core', runtime_backend: 'none', features: ['risk'] },
      links: { grafana: null, docs: null },
    }),
  }));
  await page.route('**/v1/models', (route) => route.fulfill({
    status: route.request().headers()['authorization'] ? 200 : 401,
    contentType: 'application/json',
    body: route.request().headers()['authorization']
      ? JSON.stringify({ object: 'list', data: [] })
      : JSON.stringify({ error: { code: 'UNAUTHORIZED', message: 'API key required' } }),
  }));
  await page.goto('/admin/console/playground/risk');
  await page.getByLabel('API 키').fill('user-test-key');
  await page.getByRole('button', { name: '사용', exact: true }).click();
  await page.getByLabel('검사할 텍스트').fill('진행 중인 검사 초안');
  await page.getByRole('button', { name: 'API 키 지우기' }).click();
  await expect(page.getByText(/Embedding·Retrieval·Risk 작업 화면의 입력과 결과도 사라집니다/)).toBeVisible();
  await page.getByRole('button', { name: '취소' }).click();
  await expect(page.getByLabel('검사할 텍스트')).toHaveValue('진행 중인 검사 초안');
  await page.getByRole('button', { name: 'API 키 지우기' }).click();
  await page.getByRole('button', { name: 'API 키 및 작업 데이터 지우기' }).click();
  await expect(page.getByLabel('API 키')).toBeVisible();
});

test('모델 없는 Core의 모바일 화면에서 Risk 진입과 다음 안내를 제공한다', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      bootstrap_version: 4, access: { admin_auth_required: false, profile: 'local' },
      deployment: {
        target: 'linux-core', display_name: 'Core', runtime_backend: 'none', features: ['risk'],
        control_mode: 'static', lifecycle_owner: 'external',
        implementation_status: 'implemented', qualification_status: 'unverified',
      },
      configuration: { revision: 1, write_available: false },
      platform: { version: 'test' },
      monitoring: { available: false, grafana_available: false },
      links: { grafana: null, docs: null },
    }),
  }));
  await page.route('**/admin/traffic/recent', (route) => route.fulfill({
    status: 503, contentType: 'application/json',
    body: JSON.stringify({ error: { code: 'UNAVAILABLE', message: 'test unavailable' } }),
  }));
  await page.route('**/v1/models', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ object: 'list', data: [] }),
  }));
  await page.goto('/admin/console/');
  await expect(page.getByText(/Chat을 사용하려면 서버 운영자가/)).toBeVisible();
  await page.getByRole('link', { name: /PII·Secret 탐지 테스트/ }).click();
  await expect(page.getByRole('heading', { name: 'Risk' })).toBeVisible();
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('검사할 텍스트')).toBeVisible();
});

test('Controller 정책 변경 뒤에는 Tool Calling 후속 전송도 차단하고 입력을 보존한다', async ({ page }) => {
  await page.clock.install();
  let policy: 'active' | 'gate_closed' = 'active';
  let chatRequests = 0;
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      bootstrap_version: 4, access: { admin_auth_required: false },
      deployment: { target: 'linux-nvidia-dynamic', display_name: 'GPU', runtime_backend: 'vllm-cuda', features: ['chat', 'model_switching'] },
      links: { grafana: null, docs: null },
    }),
  }));
  await page.route('**/v1/models', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ object: 'list', data: [{
      id: 'local-main', backend: 'vllm-cuda', serving_policy_status: policy,
      capabilities: ['chat.completions', 'chat.completions.tools'],
      input_modalities: ['text'], request_parameters: {},
    }] }),
  }));
  await page.route('**/v1/chat/completions', (route) => {
    chatRequests += 1;
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ choices: [{
        index: 0, finish_reason: 'tool_calls',
        message: { role: 'assistant', content: null,
          tool_calls: [{ id: 'call_a', type: 'function', function: { name: 'lookup', arguments: '{}' } }] },
      }] }),
    });
  });
  await page.goto('/admin/console/playground/chat');
  await page.getByLabel('메시지').fill('도구 결과가 필요한 질문');
  await page.getByRole('button', { name: '보내기', exact: true }).click();
  const toolResult = page.getByLabel('lookup 결과');
  await expect(toolResult).toBeVisible();
  await toolResult.fill('아직 보내지 않은 도구 결과');
  policy = 'gate_closed';
  await page.clock.fastForward(16_000);
  await expect(page.getByText('현재 모델 요청이 차단돼 있습니다.')).toBeVisible();
  await expect(page.getByRole('button', { name: '도구 결과 보내기' })).toBeDisabled();
  await expect(toolResult).toHaveValue('아직 보내지 않은 도구 결과');
  expect(chatRequests).toBe(1);
});

test('모델 목록 재조회 실패 시 이전 계약으로 새 Chat 요청을 전송하지 않는다', async ({ page }) => {
  await page.clock.install();
  let failModelRead = false;
  let chatRequests = 0;
  await page.route('**/admin/control-plane/bootstrap', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      bootstrap_version: 4, access: { admin_auth_required: false },
      deployment: { target: 'linux-nvidia-dynamic', display_name: 'GPU', runtime_backend: 'vllm-cuda', features: ['chat'] },
      links: { grafana: null, docs: null },
    }),
  }));
  await page.route('**/v1/models', (route) => route.fulfill({
    status: failModelRead ? 503 : 200, contentType: 'application/json',
    body: failModelRead
      ? JSON.stringify({ error: { code: 'UNAVAILABLE', message: 'temporary failure' } })
      : JSON.stringify({ object: 'list', data: [{
        id: 'local-main', backend: 'vllm-cuda', capabilities: ['chat.completions'],
        serving_policy_status: 'active', input_modalities: ['text'], request_parameters: {},
      }] }),
  }));
  await page.route('**/v1/chat/completions', (route) => {
    chatRequests += 1;
    return route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ choices: [{ message: { role: 'assistant', content: 'ok' }, finish_reason: 'stop' }] }) });
  });
  await page.goto('/admin/console/playground/chat');
  const prompt = page.getByLabel('메시지');
  await prompt.fill('보존해야 하는 초안');
  failModelRead = true;
  await page.clock.fastForward(16_000);
  await expect(page.getByText('모델 목록을 불러오지 못했습니다.')).toBeVisible();
  await expect(page.getByRole('button', { name: '보내기', exact: true })).toBeDisabled();
  await expect(prompt).toHaveValue('보존해야 하는 초안');
  expect(chatRequests).toBe(0);
  failModelRead = false;
  await page.getByRole('button', { name: '모델 정보 다시 조회' }).click();
  await expect(page.getByText('모델 목록을 불러오지 못했습니다.')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '보내기', exact: true })).toBeEnabled();
});
