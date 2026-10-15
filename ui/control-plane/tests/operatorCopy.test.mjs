import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf8');

test('overview uses concise operator status without blanket inference claims', () => {
  const overview = source('OverviewPage.tsx');
  assert.match(overview, /조회된 주의 항목 없음/);
  assert.match(overview, /Gateway API 요청 집계 · 재시작 시 초기화/);
  assert.doesNotMatch(overview, /운영 상태는 모델 응답을 보증하지 않습니다/);
  assert.doesNotMatch(overview, /숨겨진 메뉴는 오류나 권한 부족을 뜻하지 않습니다/);
});

test('model change retains actual interruption and recovery warning', () => {
  const model = source('MainModelPage.tsx');
  assert.match(model, /전환 중 요청이 일시 중단될 수 있습니다/);
  assert.match(model, /실패 시 이전 모델로 복구를 시도합니다/);
  assert.match(model, /GPU 정책 비율/);
  assert.doesNotMatch(model, /<strong>VRAM<\/strong>/);
});

test('configuration and activity present task information instead of internal source ownership', () => {
  assert.match(source('ConfigurationPage.tsx'), /설정 그룹 · 적용값 · 수정 가능 여부/);
  assert.match(source('OperationsPage.tsx'), /운영 변경 이력 · 추론 요청 로그와 구분/);
  assert.doesNotMatch(source('OperationsPage.tsx'), /원본 작업 기록은 각/);
  assert.match(source('RuntimePage.tsx'), /동시 실행 판단용 정책 비율/);
});
