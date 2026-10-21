import assert from 'node:assert/strict';
import test from 'node:test';
import { codeLanguage, highlightCode, MAX_HIGHLIGHT_CHARACTERS } from '../src/codeHighlight.ts';

test('code highlighting preserves source exactly, including markup, Unicode and line endings', () => {
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

test('large input skips syntax parsing without changing the underlying source', () => {
  assert.equal(highlightCode('x'.repeat(MAX_HIGHLIGHT_CHARACTERS + 1), 'python'), null);
  assert.equal(highlightCode('\n'.repeat(501), 'bash'), null);
});

test('HTTP and SDK export formats share the correct syntax language', () => {
  assert.equal(codeLanguage('curl'), 'bash');
  assert.equal(codeLanguage('python'), 'python');
  assert.equal(codeLanguage('python-sdk'), 'python');
  assert.equal(codeLanguage('javascript'), 'javascript');
  assert.equal(codeLanguage('javascript-sdk'), 'javascript');
});
