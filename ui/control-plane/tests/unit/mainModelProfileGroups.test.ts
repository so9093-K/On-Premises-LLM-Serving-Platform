import { describe, expect, it } from 'vitest';
import { mainModelProfileGroups, profileVariantLabel } from '../../src/mainModelProfileGroups';
import type { MainModelProfile } from '../../src/api';

function profile(id: string, model: string, revision: string, backend: string, context: number, output: number): MainModelProfile {
  return {
    id, upstream_model_id: model, revision, runtime_backend: backend, display_name: id,
    gateway_policy: { request_limits: { max_model_len: context }, max_output_tokens: output },
  } as MainModelProfile;
}

describe('메인 모델과 실행 프로필 표시', () => {
  it('같은 GGUF 모델의 CPU 한도 세 가지는 모델 하나로 묶는다', () => {
    const rows = [
      profile('cpu-4k', 'Qwen/Qwen3-0.6B-GGUF', 'pinned', 'llama-cpp', 4096, 1024),
      profile('cpu-8k', 'Qwen/Qwen3-0.6B-GGUF', 'pinned', 'llama-cpp', 8192, 4096),
      profile('cpu-16k', 'Qwen/Qwen3-0.6B-GGUF', 'pinned', 'llama-cpp', 16384, 4096),
    ];
    const groups = mainModelProfileGroups(rows);
    expect(groups).toHaveLength(1);
    expect(groups[0].profiles.map((p) => p.id)).toEqual(['cpu-4k', 'cpu-8k', 'cpu-16k']);
    expect(profileVariantLabel(rows[1])).toContain('기본');
  });
  it('모델 ID·Revision·Backend가 다르면 합치지 않는다', () => {
    expect(mainModelProfileGroups([
      profile('a', 'model-A', 'rev1', 'vllm-cuda', 4096, 1024),
      profile('b', 'model-A', 'rev2', 'vllm-cuda', 4096, 1024),
      profile('c', 'model-A', 'rev1', 'llama-cpp', 4096, 1024),
      profile('d', 'model-B', 'rev1', 'vllm-cuda', 4096, 1024),
    ])).toHaveLength(4);
  });
});
