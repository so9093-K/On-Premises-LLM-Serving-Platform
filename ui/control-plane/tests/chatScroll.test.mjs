import assert from 'node:assert/strict';
import test from 'node:test';

import { conversationEndNearViewport } from '../src/chatScroll.ts';

test('대화 스크롤 자동 추적은 실제 화면 경계에서만 활성화된다', () => {
  assert.equal(conversationEndNearViewport(840, 844), true);
  assert.equal(conversationEndNearViewport(1003, 844), true);
  assert.equal(conversationEndNearViewport(1004, 844), false);
  assert.equal(conversationEndNearViewport(500, 844), false);
  assert.equal(conversationEndNearViewport(Number.NaN, 844), false);
});
