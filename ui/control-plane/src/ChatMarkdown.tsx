import { createElement, useMemo, type ReactNode } from 'react';

import { parseChatInline, parseChatMarkdown } from './chatResponseFormat';

function inline(value: string): ReactNode[] {
  return parseChatInline(value).map((part, index) => {
    switch (part.kind) {
      case 'strong': return <strong key={index}>{part.value}</strong>;
      case 'emphasis': return <em key={index}>{part.value}</em>;
      case 'code': return <code key={index}>{part.value}</code>;
      default: return <span key={index}>{part.value}</span>;
    }
  });
}

// 사용자·모델 콘텐츠를 HTML로 삽입하지 않는다. 링크와 이미지도 자동 요청하지 않는다.
export function ChatMarkdown({ text }: { text: string }) {
  const blocks = useMemo(() => parseChatMarkdown(text), [text]);
  return (
    <div className="chat-response-markdown">
      {blocks.map((block, index) => {
        switch (block.kind) {
          case 'heading':
            return createElement('h' + Math.min(block.level + 2, 6), { key: index }, inline(block.text));
          case 'paragraph':
            return <p key={index}>{inline(block.text)}</p>;
          case 'code':
            return <pre key={index}><code>{block.text}</code></pre>;
          case 'list': {
            const items = block.items.map((item, position) => <li key={position}>{inline(item)}</li>);
            return block.ordered ? <ol key={index} start={block.start ?? 1}>{items}</ol> : <ul key={index}>{items}</ul>;
          }
          case 'quote':
            return <blockquote key={index}>{inline(block.text)}</blockquote>;
        }
      })}
    </div>
  );
}
