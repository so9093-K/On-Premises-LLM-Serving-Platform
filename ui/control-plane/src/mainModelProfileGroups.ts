import type { MainModelProfile } from './api';
import { mainModelTokenLimits } from './mainModelSafety';

export type MainModelProfileGroup = {
  key: string;
  modelId: string;
  revision: string;
  backend: string;
  profiles: MainModelProfile[];
};

/** 실제 모델의 신원은 모델 ID·Revision·Runtime backend가 소유한다. */
export function mainModelProfileGroups(profiles: readonly MainModelProfile[]): MainModelProfileGroup[] {
  const groups = new Map<string, MainModelProfileGroup>();
  for (const profile of profiles) {
    const key = JSON.stringify([profile.upstream_model_id, profile.revision ?? '', profile.runtime_backend]);
    const group = groups.get(key);
    if (group) {
      group.profiles.push(profile);
    } else {
      groups.set(key, {
        key, modelId: profile.upstream_model_id, revision: profile.revision ?? '미표시',
        backend: profile.runtime_backend, profiles: [profile],
      });
    }
  }
  return Array.from(groups.values());
}

export function profileVariantLabel(profile: Pick<MainModelProfile, 'runtime_backend' | 'display_name' | 'gateway_policy'>): string {
  if (profile.runtime_backend !== 'llama-cpp') return profile.display_name;
  const { contextTokens, maxOutputTokens } = mainModelTokenLimits(profile);
  if (contextTokens === null || maxOutputTokens === null) return profile.display_name;
  const label = contextTokens === 4096 ? '경량' : contextTokens === 8192 ? '기본' : contextTokens === 16384 ? '확장' : 'CPU 구성';
  return `${label} · ${contextTokens.toLocaleString('ko-KR')} / ${maxOutputTokens.toLocaleString('ko-KR')} tokens`;
}
