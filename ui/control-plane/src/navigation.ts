import type { UiTextKey } from './uiText';

// 메뉴와 Route가 같은 경로 및 target capability를 사용한다.
// 그룹 순서는 UI preference이지만 각 기능의 가용 여부는 deployment feature 계약이 소유한다.
export const NAVIGATION_GROUPS = ['service', 'operations', 'development'] as const;
export type NavigationGroup = typeof NAVIGATION_GROUPS[number];

// Playground 안의 작업 화면이다. 각 화면은 해당 공개 API를 제공하는 feature가 있을 때만
// 요청을 보내고, Playground 메뉴는 그중 하나라도 있으면 보인다. Chat이 없는 Core에서도
// PII·Secret Risk 화면에 접근할 수 있어야 한다. 제공하지 않는 화면도 탭으로는 보여
// 기능의 존재와 미제공 이유를 알린다.
export const PLAYGROUND_WORKSPACES = [
  { path: 'chat', label: 'Chat', feature: 'chat' },
  { path: 'embeddings', label: 'Embedding', feature: 'embeddings' },
  { path: 'risk', label: 'Risk', feature: 'risk' },
] as const;

export type PlaygroundWorkspace = typeof PLAYGROUND_WORKSPACES[number];

export const NAVIGATION_SECTIONS = [
  { path: '/', labelKey: 'nav.overview', group: 'service' },
  { path: '/main-model', labelKey: 'nav.mainModel', group: 'service', features: ['model_switching'] },
  { path: '/runtimes', labelKey: 'nav.runtimes', group: 'service', features: ['runtime_control'] },
  { path: '/operations', labelKey: 'nav.activity', group: 'operations' },
  { path: '/configuration', labelKey: 'nav.configuration', group: 'operations' },
  {
    path: '/playground',
    labelKey: 'nav.playground',
    group: 'development',
    features: PLAYGROUND_WORKSPACES.map((workspace) => workspace.feature),
    nested: true,
  },
] as const satisfies readonly {
  path: string;
  labelKey: UiTextKey;
  group: NavigationGroup;
  // 하나라도 활성화돼 있으면 화면을 제공한다.
  features?: readonly string[];
  // 하위 경로를 화면이 직접 소유한다.
  nested?: boolean;
}[];

export type NavigationPath = typeof NAVIGATION_SECTIONS[number]['path'];

export function visibleNavigationSections(features: readonly string[]) {
  return NAVIGATION_SECTIONS.filter(
    (section) => !('features' in section)
      || (section.features as readonly string[]).some((feature) => features.includes(feature)),
  );
}

export function visiblePlaygroundWorkspaces(features: readonly string[]): PlaygroundWorkspace[] {
  return PLAYGROUND_WORKSPACES.filter((workspace) => features.includes(workspace.feature));
}

export function unavailablePlaygroundWorkspaces(features: readonly string[]): PlaygroundWorkspace[] {
  return PLAYGROUND_WORKSPACES.filter((workspace) => !features.includes(workspace.feature));
}

export function playgroundPath(workspace: PlaygroundWorkspace['path']): string {
  return `/playground/${workspace}`;
}
