import { describe, expect, it } from 'vitest';
import { unavailablePlaygroundWorkspaces, visibleNavigationSections, visiblePlaygroundWorkspaces } from '../../src/navigation';

describe('배포 Capability 기반 탐색', () => {
  it('지원하지 않는 작업 화면을 노출하지 않는다', () => {
    const sections = visibleNavigationSections(['risk']);
    expect(sections.some((section) => section.path === '/main-model')).toBe(false);
    expect(sections.some((section) => section.path === '/playground')).toBe(true);
  });

  it('Playground는 지원 기능만 요청 화면으로 열고 나머지는 미제공으로 구분한다', () => {
    expect(visiblePlaygroundWorkspaces(['risk']).map((item) => item.path)).toEqual(['risk']);
    expect(unavailablePlaygroundWorkspaces(['risk']).map((item) => item.path)).toEqual(['chat', 'embeddings']);
  });
});
