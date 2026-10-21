import Prism from 'prismjs';
import 'prismjs/components/prism-bash.js';
import 'prismjs/components/prism-python.js';
import 'prismjs/components/prism-json.js';

// React가 DOM을 소유한다. Prism은 HTML 렌더링 없이 토큰화만 담당한다.
Prism.manual = true;

export type CodeLanguage = 'bash' | 'python' | 'javascript' | 'json';
export type CodeToken = { text: string; classes: string[] };
export const MAX_HIGHLIGHT_CHARACTERS = 24_000;

export function codeLanguage(language: string): CodeLanguage {
  if (language === 'curl') return 'bash';
  return language.startsWith('python') ? 'python' : 'javascript';
}

export function highlightCode(source: string, language: CodeLanguage): CodeToken[] | null {
  if (source.length > MAX_HIGHLIGHT_CHARACTERS || source.split('\n').length > 500) return null;
  const result: CodeToken[] = [];
  function visit(content: string | Prism.Token | (string | Prism.Token)[], classes: string[] = []): void {
    if (typeof content === 'string') {
      result.push({ text: content, classes });
    } else if (Array.isArray(content)) {
      content.forEach((part) => visit(part, classes));
    } else {
      const aliases = typeof content.alias === 'string' ? [content.alias] : content.alias ?? [];
      visit(content.content, [...classes, content.type, ...aliases]);
    }
  }
  visit(Prism.tokenize(source, Prism.languages[language]));
  return result;
}
