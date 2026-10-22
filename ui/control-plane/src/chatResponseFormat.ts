// Chat 응답의 표시 전용 Markdown subset. 원문이나 요청 데이터는 변경하지 않는다.
// 링크·HTML·이미지를 활성 콘텐츠로 해석하지 않고 React 텍스트로만 출력한다.
export type ChatInline = { kind: 'text' | 'strong' | 'emphasis' | 'code'; value: string };

export type ChatBlock =
  | { kind: 'paragraph'; text: string }
  | { kind: 'heading'; text: string; level: number }
  | { kind: 'code'; text: string; language: string }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'quote'; text: string };

export function parseChatInline(value: string): ChatInline[] {
  const parts: ChatInline[] = [];
  let plain = '';
  let index = 0;
  const flush = () => {
    if (plain) parts.push({ kind: 'text', value: plain });
    plain = '';
  };
  while (index < value.length) {
    if (value[index] === '\\' && index + 1 < value.length && '*`\\'.includes(value[index + 1])) {
      plain += value[index + 1];
      index += 2;
      continue;
    }
    const marker = value.startsWith('**', index) ? '**'
      : value[index] === '`' ? '`'
        : value[index] === '*' ? '*' : null;
    // 일반 문장의 곱셈 기호(`2 * 3 * 4`)나 띄어 쓴 별표를 강조로 오인하지 않는다.
    // 코드 스팬은 공백을 허용하지만 emphasis/strong의 양 끝에는 공백이 올 수 없다.
    if (marker !== null) {
      const openingIndex = index + marker.length;
      if (marker !== '`' && (openingIndex >= value.length || /\s/.test(value[openingIndex]))) {
        plain += value[index];
        index += 1;
        continue;
      }
      let end = value.indexOf(marker, openingIndex);
      while (end >= 0) {
        let escapes = 0;
        for (let pos = end - 1; pos >= 0 && value[pos] === '\\'; pos--) escapes += 1;
        if (escapes % 2 === 0 && (marker === '`' || (end > openingIndex && !/\s/.test(value[end - 1])))) break;
        end = value.indexOf(marker, end + marker.length);
      }
      if (end > index + marker.length) {
        flush();
        parts.push({
          kind: marker === '**' ? 'strong' : marker === '*' ? 'emphasis' : 'code',
          value: value.slice(index + marker.length, end),
        });
        index = end + marker.length;
        continue;
      }
    }
    plain += value[index];
    index += 1;
  }
  flush();
  return parts;
}

const heading = /^(#{1,6})[ \t]+(.+)$/;
const fence = /^[ \t]{0,3}\x60{3}([a-zA-Z0-9_+-]*)[ \t]*$/;
const fenceEnd = /^[ \t]{0,3}\x60{3,}[ \t]*$/;
const list = /^[ \t]{0,3}([-*+]|\d+[.)])[ \t]+(.+)$/;
const quote = /^[ \t]{0,3}>[ \t]?(.*)$/;

function blockStart(line: string): boolean {
  return heading.test(line) || fence.test(line) || list.test(line) || quote.test(line);
}

export function parseChatMarkdown(source: string): ChatBlock[] {
  if (!source) return [];
  const lines = source.replace(/\r\n?/g, '\n').split('\n');
  const blocks: ChatBlock[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { index += 1; continue; }
    const fenceMatch = line.match(fence);
    if (fenceMatch) {
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !fenceEnd.test(lines[index])) {
        code.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push({ kind: 'code', language: fenceMatch[1], text: code.join('\n') });
      continue;
    }
    const headingMatch = line.match(heading);
    if (headingMatch) {
      blocks.push({ kind: 'heading', level: headingMatch[1].length, text: headingMatch[2] });
      index += 1;
      continue;
    }
    const listMatch = line.match(list);
    if (listMatch) {
      const ordered = /\d/.test(listMatch[1][0]);
      const items: string[] = [];
      while (index < lines.length) {
        const item = lines[index].match(list);
        if (!item || /\d/.test(item[1][0]) !== ordered) break;
        items.push(item[2]);
        index += 1;
      }
      blocks.push({ kind: 'list', ordered, items });
      continue;
    }
    if (quote.test(line)) {
      const quoted: string[] = [];
      while (index < lines.length) {
        const match = lines[index].match(quote);
        if (!match) break;
        quoted.push(match[1]);
        index += 1;
      }
      blocks.push({ kind: 'quote', text: quoted.join('\n') });
      continue;
    }
    const paragraph: string[] = [];
    while (index < lines.length && lines[index].trim()) {
      if (paragraph.length && blockStart(lines[index])) break;
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ kind: 'paragraph', text: paragraph.join('\n') });
  }
  return blocks;
}
