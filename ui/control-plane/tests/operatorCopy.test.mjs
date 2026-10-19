import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf8');

test('model change retains actual interruption and recovery warning', () => {
  const model = source('MainModelPage.tsx');
  assert.match(model, /전환 중 일시 중단 가능/);
  assert.match(model, /전환 실패 시 이전 모델로 복구를 시도합니다/);
  assert.match(model, /첫 활성화에는 복구할 이전 모델이 없습니다/);
  assert.match(model, /GPU 정책 비율/);
  assert.doesNotMatch(model, /<strong>VRAM<\/strong>/);
});

test('admin authentication and GPU reservation explain user action without changing the security meaning', () => {
  const auth = source('App.tsx');
  const runtimes = source('RuntimePage.tsx');
  assert.match(auth, /관리자 키를 입력하세요/);
  assert.match(auth, /현재 브라우저 탭에만 유지/);
  assert.match(runtimes, /<CardTitle>GPU 예약 현황<\/CardTitle>/);
  assert.match(runtimes, /실측 GPU 메모리가 아닌/);
});
