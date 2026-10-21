import assert from 'node:assert/strict';
import test from 'node:test';
import { codeLanguage, highlightCode, MAX_HIGHLIGHT_CHARACTERS } from '../src/codeHighlight.ts';

test('구문 강조는 마크업·유니코드·줄바꿈을 포함한 원문을 정확히 보존한다', () => {
  const fixtures = {
    bash: '#!/usr/bin/env bash\r\ntext=\'<img src=x onerror="alert(1)"> 한글 🦊\'\nprintf "%s" "$text"\n',
    python: 'import json\npayload = "<script>alert(1)</script> & 한글"\nprint(payload)\n',
    javascript: 'const payload = "<img src=x onerror=alert(1)>";\nconsole.log(payload);\n',
    json: '{"prompt":"<script>alert(1)</script>","count":1,"active":true}',
  };
  for (const [language, source] of Object.entries(fixtures)) {
    const tokens = highlightCode(source, language);
    assert.ok(tokens);
    assert.equal(tokens.map((token) => token.text).join(''), source);
    assert.ok(tokens.some((token) => token.classes.length > 0), language);
  }
});

test('대용량 입력은 원문 변경 없이 구문 분석을 생략한다', () => {
  assert.equal(highlightCode('x'.repeat(MAX_HIGHLIGHT_CHARACTERS + 1), 'python'), null);
  assert.equal(highlightCode('\n'.repeat(501), 'bash'), null);
});

test('HTTP·SDK 내보내기는 형식에 맞는 구문 언어를 사용한다', () => {
  assert.equal(codeLanguage('curl'), 'bash');
  assert.equal(codeLanguage('python'), 'python');
  assert.equal(codeLanguage('python-sdk'), 'python');
  assert.equal(codeLanguage('javascript'), 'javascript');
  assert.equal(codeLanguage('javascript-sdk'), 'javascript');
});
