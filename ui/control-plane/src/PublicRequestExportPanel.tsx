import { useId, useMemo, useState } from 'react';
import { Button } from '@patternfly/react-core';

import {
  prettyRequestJson,
  PUBLIC_EXPORT_LANGUAGES,
  publicExportSource,
  type PublicExportLanguage,
  type PublicRequestRecord,
} from './publicRequestExport';

function PublicRequestExportContents({ record, completed }: { record: PublicRequestRecord; completed: boolean }) {
  const languageId = useId();
  const [language, setLanguage] = useState<PublicExportLanguage>('curl');
  const [feedback, setFeedback] = useState('');
  const source = useMemo(() => publicExportSource(record, language), [record, language]);
  const pretty = useMemo(() => prettyRequestJson(record), [record]);

  async function copy(text: string, label: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      setFeedback(`${label}을(를) 복사했습니다. 붙여넣는 곳의 민감정보 노출에 주의하세요.`);
    } catch {
      setFeedback(`${label} 복사에 실패했습니다. 브라우저 권한을 확인하세요.`);
    }
  }

  return (
    <div className="playground-export-content">
      <p>전송 당시의 <strong>실제 요청 바이트</strong>를 담은 단일 파일 예제입니다. 현재 입력으로 다시 만들지 않습니다.</p>
      {!completed ? (
        <p className="playground-export-warning">이 요청은 정상 완료되지 않았습니다. 재현 예제만 제공하며 성공을 보장하지 않습니다.</p>
      ) : null}
      <p className="playground-export-warning">
        {record.kind === 'risk'
          ? '예제에 검사한 텍스트가 그대로 들어갑니다. 실제 개인정보나 Secret을 검사했다면 예제를 공유하지 마세요.'
          : '예제에 입력 텍스트가 그대로 들어갑니다.'}
        {' '}API 키는 포함하지 않으며 실행 시 <code>API_KEY</code> 환경변수에서 읽습니다.
      </p>
      <label htmlFor={languageId}>개발 언어</label>
      <select id={languageId} value={language} onChange={(event) => { setLanguage(event.currentTarget.value as PublicExportLanguage); setFeedback(''); }}>
        {PUBLIC_EXPORT_LANGUAGES[record.kind].map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select>
      <pre className="playground-export-code"><code>{source}</code></pre>
      {record.kind === 'risk' ? (
        <p className="playground-export-hint">
          Python·Node.js 예제는 응답의 완료 조건을 확인하고, 검사가 완료되지 않았으면 미탐지로 처리하지 않고 종료 코드 2로 끝납니다.
          허용·차단 판단은 포함하지 않습니다.
        </p>
      ) : null}
      <div className="playground-export-actions">
        <Button size="sm" variant="secondary" onClick={() => { void copy(source, '코드'); }}>코드 복사</Button>
        <Button size="sm" variant="secondary" onClick={() => { void copy(record.requestJson, '요청 JSON'); }}>요청 JSON 복사</Button>
      </div>
      <details className="playground-export-json">
        <summary>전송한 Request JSON</summary>
        <pre className="playground-export-code"><code>{pretty}</code></pre>
      </details>
      <p role="status" aria-live="polite" className="playground-export-feedback">{feedback}</p>
    </div>
  );
}

// 코드는 사용자가 펼칠 때만 만든다. 입력이 민감할 수 있으므로 자동 저장·다운로드하지 않는다.
export function PublicRequestExportPanel(props: { record: PublicRequestRecord; completed: boolean }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <details className="playground-export" onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary>코드로 사용하기</summary>
      {expanded ? <PublicRequestExportContents {...props} /> : null}
    </details>
  );
}
