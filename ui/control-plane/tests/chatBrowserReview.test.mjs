import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const chatPage = readFileSync(new URL('../src/ChatPage.tsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');
import { CHAT_FOLLOW_DISTANCE_PX, conversationEndNearViewport } from '../src/chatScroll.ts';

test('tool result input captures event value before the deferred state updater runs', () => {
  assert.doesNotMatch(
    chatPage,
    /setValues\(\(current\)[\s\S]{0,240}event\.currentTarget\.value/,
  );
  assert.match(chatPage, /const value = event\.currentTarget\.value;[\s\S]{0,180}\[call\.id\]: value/);
});

test('first tool result field receives focus when a pending tool-call form mounts', () => {
  assert.match(chatPage, /calls\.map\(\(call, index\)[\s\S]{0,500}autoFocus=\{index === 0\}/);
});

test('mobile chat layout preserves DOM order instead of visually reordering the settings pane', () => {
  const mobile = styles.match(/@media \(max-width: 980px\) \{[\s\S]*?\n\}/)?.[0] ?? '';
  assert.match(mobile, /\.chat-side\s*\{[\s\S]*?position:\s*static;/);
  assert.doesNotMatch(mobile, /order\s*:\s*-1/);
});

test('streaming follows the conversation end rather than the document end below mobile settings', () => {
  assert.match(chatPage, /conversationEndRef\.current\?\.scrollIntoView/);
  assert.match(chatPage, /ref=\{conversationEndRef\}/);
  assert.doesNotMatch(chatPage, /window\.scrollTo\(\{ top: document\.documentElement\.scrollHeight/);
  assert.match(chatPage, /conversationEndNearViewport\(end\.getBoundingClientRect\(\)\.top, window\.innerHeight\)/);
});

test('the mobile settings shortcut has a real target and a way back to the composer', () => {
  assert.match(chatPage, /href="#chat-model-settings"/);
  assert.match(chatPage, /id="chat-model-settings"/);
  assert.match(chatPage, /href="#chat-input"/);
});

test('conversation follow threshold has observable viewport boundary behavior', () => {
  assert.equal(CHAT_FOLLOW_DISTANCE_PX, 160);
  assert.equal(conversationEndNearViewport(840, 844), true);
  assert.equal(conversationEndNearViewport(1003, 844), true);
  assert.equal(conversationEndNearViewport(1004, 844), false);
  assert.equal(conversationEndNearViewport(500, 844), false);
  assert.equal(conversationEndNearViewport(Number.NaN, 844), false);
});
