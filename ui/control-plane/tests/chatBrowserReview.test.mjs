import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const chatPage = readFileSync(new URL('../src/ChatPage.tsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');

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
