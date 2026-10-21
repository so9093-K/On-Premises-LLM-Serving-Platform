import { useMemo } from 'react';
import { Button } from '@patternfly/react-core';
import { highlightCode, type CodeLanguage } from './codeHighlight';

const LANGUAGE_NAMES: Record<CodeLanguage, string> = {
  bash: 'Bash', python: 'Python', javascript: 'JavaScript', json: 'JSON',
};

export function CodeViewer({ source, language, filename, onCopy, disabled = false }: {
  source: string;
  language: CodeLanguage;
  filename: string;
  onCopy: () => void;
  disabled?: boolean;
}) {
  const tokens = useMemo(() => highlightCode(source, language), [source, language]);
  const numbers = tokens ? Array.from({ length: source.split('\n').length }, (_, i) => i + 1).join('\n') : null;
  return (
    <section className="code-viewer" aria-label={`${filename} 코드`}>
      <div className="code-viewer-toolbar">
        <span className="code-viewer-file">{filename}</span>
        <span className="code-viewer-language">{LANGUAGE_NAMES[language]}</span>
        <Button size="sm" variant="plain" isDisabled={disabled} onClick={onCopy}
          aria-label={language === 'json' ? `${filename} 복사` : '코드 복사'}>복사</Button>
      </div>
      <div className="code-viewer-body" tabIndex={0} role="region" aria-label={`${filename} 코드 내용`}>
        {numbers !== null && <div className="code-viewer-gutter" aria-hidden="true">{numbers}</div>}
        <pre className="playground-export-code"><code>{tokens
          ? tokens.map((token, index) => <span key={index} className={token.classes.map((name) => `syntax-${name}`).join(' ')}>{token.text}</span>)
          : source}</code></pre>
      </div>
    </section>
  );
}
