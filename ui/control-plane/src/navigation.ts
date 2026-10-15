import type { UiTextKey } from './uiText';

// 메뉴와 Route가 같은 경로 및 target capability를 사용한다.
// 그룹 순서는 UI preference이지만 각 기능의 가용 여부는 deployment feature 계약이 소유한다.
export const NAVIGATION_GROUPS = ['service', 'operations', 'development'] as const;
export type NavigationGroup = typeof NAVIGATION_GROUPS[number];

export const NAVIGATION_SECTIONS = [
  { path: '/', labelKey: 'nav.overview', group: 'service' },
  { path: '/main-model', labelKey: 'nav.mainModel', group: 'service', feature: 'model_switching' },
  { path: '/runtimes', labelKey: 'nav.runtimes', group: 'service', feature: 'runtime_control' },
  { path: '/operations', labelKey: 'nav.activity', group: 'operations' },
  { path: '/configuration', labelKey: 'nav.configuration', group: 'operations' },
  { path: '/chat', labelKey: 'nav.chat', group: 'development', feature: 'chat' },
] as const satisfies readonly {
  path: string;
  labelKey: UiTextKey;
  group: NavigationGroup;
  feature?: string;
}[];

export type NavigationPath = typeof NAVIGATION_SECTIONS[number]['path'];

export function visibleNavigationSections(features: readonly string[]) {
  return NAVIGATION_SECTIONS.filter(
    (section) => !('feature' in section) || features.includes(section.feature),
  );
}
