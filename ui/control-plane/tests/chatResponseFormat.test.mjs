import assert from 'node:assert/strict';
import test from 'node:test';

import { parseChatInline, parseChatMarkdown } from '../src/chatResponseFormat.ts';

test('응답 Markdown은 제목·목록·강조·코드와 원문 문자를 구분한다', () => {
  const blocks = parseChatMarkdown('# 요약\n\n1. **GPU** 사용\n2. `CUDA` 점검\n\n```python\nprint("ok")\n```');
  assert.deepEqual(blocks, [
    { kind: 'heading', level: 1, text: '요약' },
    { kind: 'list', ordered: true, items: ['**GPU** 사용', '`CUDA` 점검'] },
    { kind: 'code', language: 'python', text: 'print("ok")' },
  ]);
  assert.deepEqual(parseChatInline('**GPU**와 `CUDA`'), [
    { kind: 'strong', value: 'GPU' },
    { kind: 'text', value: '와 ' },
    { kind: 'code', value: 'CUDA' },
  ]);
});

test('스트리밍 도중 열린 코드 블록도 내용을 유지한다', () => {
  assert.deepEqual(parseChatMarkdown('```json\n{"ok":true}'), [
    { kind: 'code', language: 'json', text: '{"ok":true}' },
  ]);
});

test('HTML, 링크, 이미지 문구는 활성 DOM이 아닌 일반 문자로 남는다', () => {
  const source = '<script>alert(1)</script>\n![remote](https://invalid.test/a.png)\n[click](javascript:alert(1))';
  assert.deepEqual(parseChatMarkdown(source), [{ kind: 'paragraph', text: source }]);
  assert.deepEqual(parseChatInline('<img src=x onerror=alert(1)>'), [
    { kind: 'text', value: '<img src=x onerror=alert(1)>' },
  ]);
});

test('빈 문자열과 불완전한 강조 표시는 손실 없이 유지한다', () => {
  assert.deepEqual(parseChatMarkdown(''), []);
  assert.deepEqual(parseChatInline('**미완성'), [{ kind: 'text', value: '**미완성' }]);
});

test('이스케이프된 강조 기호는 장식 없이 출력한다', () => {
  assert.deepEqual(parseChatInline(String.raw`\*문자 그대로\*와 **강조**`), [
    { kind: 'text', value: '*문자 그대로*와 ' },
    { kind: 'strong', value: '강조' },
  ]);
  assert.deepEqual(parseChatInline(String.raw`\`원문\``), [
    { kind: 'text', value: '`원문`' },
  ]);
});

test('코드 블록 내부의 언어가 붙은 백틱은 종료로 오해하지 않는다', () => {
  assert.deepEqual(parseChatMarkdown('```txt\n첫 줄\n```python\n세 번째 줄\n```'), [
    { kind: 'code', language: 'txt', text: '첫 줄\n```python\n세 번째 줄' },
  ]);
});

test('일반 수식의 곱셈 별표와 공백을 강조 서식으로 바꾸지 않는다', () => {
  assert.deepEqual(parseChatInline('2 * 3 = 6 * 1'), [
    { kind: 'text', value: '2 * 3 = 6 * 1' },
  ]);
  assert.deepEqual(parseChatInline('** 띄어 쓴 강조 **'), [
    { kind: 'text', value: '** 띄어 쓴 강조 **' },
  ]);
  assert.deepEqual(parseChatInline('**정상 강조**와 *강조*'), [
    { kind: 'strong', value: '정상 강조' },
    { kind: 'text', value: '와 ' },
    { kind: 'emphasis', value: '강조' },
  ]);
});

test('연속된 이스케이프 강조 기호는 원문으로 보인다', () => {
  assert.deepEqual(parseChatInline(String.raw`\*\*literal\*\* and **bold**`), [
    { kind: 'text', value: '**literal** and ' },
    { kind: 'strong', value: 'bold' },
  ]);
});
