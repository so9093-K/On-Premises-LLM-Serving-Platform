import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const chatPage = readFileSync(new URL('../src/ChatPage.tsx', import.meta.url), 'utf8');
const chatToolResultForm = readFileSync(new URL('../src/ChatToolResultForm.tsx', import.meta.url), 'utf8');
const chatExchangeView = readFileSync(new URL('../src/ChatExchangeView.tsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');
import { conversationEndNearViewport } from '../src/chatScroll.ts';

test('tool result input captures event value before the deferred state updater runs', () => {
  assert.doesNotMatch(
    chatToolResultForm,
    /setValues\(\(current\)[\s\S]{0,240}event\.currentTarget\.value/,
  );
  assert.match(chatToolResultForm, /const value = event\.currentTarget\.value;[\s\S]{0,180}\[call\.id\]: value/);
});

test('first tool result field receives focus when a pending tool-call form mounts', () => {
  assert.match(chatToolResultForm, /calls\.map\(\(call, index\)[\s\S]{0,500}autoFocus=\{index === 0\}/);
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
  assert.equal(conversationEndNearViewport(840, 844), true);
  assert.equal(conversationEndNearViewport(1003, 844), true);
  assert.equal(conversationEndNearViewport(1004, 844), false);
  assert.equal(conversationEndNearViewport(500, 844), false);
  assert.equal(conversationEndNearViewport(Number.NaN, 844), false);
});

test('Playground presents model capabilities before the example gallery', () => {
  const modelBar = chatPage.indexOf('className="chat-model-bar"');
  const gallery = chatPage.indexOf('<PlaygroundExampleGallery');
  const composer = chatPage.indexOf('className="chat-composer"');
  assert.ok(modelBar >= 0 && modelBar < gallery && gallery < composer);
  assert.match(chatPage, /<ModelContext model=\{model\} showIdentity=\{models\.length === 1\}/);
  assert.match(chatPage, /<label htmlFor="chat-model">현재 모델<\/label>/);
  assert.match(styles, /\.chat-model-bar\s*\{/);
});

test('Playground model switch displays the active model and prevents ambiguous requests', () => {
  assert.match(chatPage, /value=\{model\.id\}/);
  assert.match(chatPage, /planModelSwitch\(nextModel, session\.settings, exchanges, attachments, draft\)/);
  assert.match(chatPage, /role="group" aria-label="모델 변경 확인"/);
  assert.match(chatPage, /\{model\.id\} → \{pendingModel\.id\}/);
  assert.match(chatPage, /if \(attachmentBusy \|\| exampleLoading \|\| pendingModelId !== null\) return/);
  assert.match(chatPage, /pendingModelId !== null \|\| \(!draft\.trim\(\)/);
  assert.match(chatPage, /if \(busy \|\| attachmentBusy \|\| exampleLoading \|\| pendingToolExchange\) return/);
  assert.match(chatPage, /plan\.conversationError && !resetConversation/);
  assert.match(chatPage, /commitModelChange\(pendingModel\.id, true\)/);
});

test('example application is a dismissible origin note, not an assertion of unchanged content', () => {
  assert.match(chatPage, /className="chat-applied-example" role="status"/);
  assert.match(chatPage, /setAppliedExampleId\(example\.id\)/);
  assert.match(chatPage, /예제에서 시작/);
  assert.match(chatPage, /aria-label="예제 적용 표시 닫기"/);
  assert.match(chatPage, /if \(error === null\) \{[\s\S]{0,140}setAppliedExampleId\(null\)/);
});

test('API docs follow the Bootstrap source of truth and hide if unavailable', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  assert.match(app, /docsUrl=\{bootstrap\.links\.docs\}/);
  assert.match(chatExchangeView, /docsUrl && turn\.status === 'complete'/);
  assert.match(chatExchangeView, /href=\{docsUrl\} target="_blank" rel="noreferrer"/);
  assert.doesNotMatch(chatExchangeView, /href="\/docs"/);
});

test('example previews expose advanced source only on demand', () => {
  const gallery = readFileSync(new URL('../src/PlaygroundExampleGallery.tsx', import.meta.url), 'utf8');
  assert.match(gallery, /<details className="playground-example-technical">/);
  assert.match(gallery, /aria-pressed=\{selectedId === example\.id\}/);
  assert.match(gallery, /className="playground-example-check" aria-hidden="true"/);
  assert.doesNotMatch(gallery, /기존 고급 생성 설정과 완료된 대화는 유지됩니다/);
});
