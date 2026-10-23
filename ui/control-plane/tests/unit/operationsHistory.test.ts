import { describe, expect, it } from 'vitest';
import { mergeOperationPages } from '../../src/operationsHistory';

type Operation = { operation_id: string; updated_at: number; status: string };

describe('운영 활동 커서 페이지 결합', () => {
  it('같은 작업은 한 번만 표시하고 새로운 상태를 유지한다', () => {
    const pages: Operation[][] = [
      [{ operation_id: 'id-a', updated_at: 200, status: 'verified' }],
      [
        { operation_id: 'id-a', updated_at: 100, status: 'pending' },
        { operation_id: 'id-b', updated_at: 95, status: 'failed' },
      ],
    ];
    expect(mergeOperationPages(pages)).toEqual([
      { operation_id: 'id-a', updated_at: 200, status: 'verified' },
      { operation_id: 'id-b', updated_at: 95, status: 'failed' },
    ]);
  });

  it('늦게 읽힌 페이지의 실제 updated_at이 새로우면 그 상태를 사용한다', () => {
    const pages: Operation[][] = [
      [{ operation_id: 'id-a', updated_at: 100, status: 'pending' }],
      [{ operation_id: 'id-a', updated_at: 150, status: 'verified' }],
    ];
    expect(mergeOperationPages(pages)[0].status).toBe('verified');
  });

  it('동일한 타임스탬프의 중복 작업에서는 최근 페이지의 값을 유지한다', () => {
    expect(mergeOperationPages<Operation>([
      [{ operation_id: 'id-a', updated_at: 100, status: 'completed' }],
      [{ operation_id: 'id-a', updated_at: 100, status: 'pending' }],
    ])[0].status).toBe('completed');
  });
});
