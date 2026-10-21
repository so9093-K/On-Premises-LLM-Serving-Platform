import { useId, useMemo, useState } from 'react';
import { Button } from '@patternfly/react-core';
import { CodeViewer } from './CodeViewer';
import { codeLanguage } from './codeHighlight';

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
      setFeedback(label === '코드' ? '코드를 복사했습니다.' : '요청 JSON을 복사했습니다.');
    } catch {
      setFeedback(`${label} 복사에 실패했습니다. 브라우저 권한을 확인하세요.`);
    }
  }

  return (
    <div className="playground-export-content">
      <p>이 요청을 코드로 실행하세요. 예제는 한 파일로 실행할 수 있습니다.</p>
      {!completed ? (
        <p className="playground-export-warning">완료되지 않은 요청의 예제입니다.</p>
      ) : null}
      <p className="playground-export-warning">
        {record.kind === 'risk'
          ? '예제에 검사한 텍스트가 그대로 들어갑니다. 실제 개인정보나 Secret을 검사했다면 예제를 공유하지 마세요.'
          : '예제에 입력 텍스트가 그대로 들어갑니다.'}
        {' '}API 키는 포함하지 않으며 실행 시 <code>API_KEY</code> 환경변수에서 읽습니다.
      </p>
      <label htmlFor={languageId}>예제 형식</label>
      <select id={languageId} value={language} onChange={(event) => { setLanguage(event.currentTarget.value as PublicExportLanguage); setFeedback(''); }}>
        {PUBLIC_EXPORT_LANGUAGES[record.kind].map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select>
      <CodeViewer source={source} language={codeLanguage(language)}
        filename={language === 'curl' ? 'client.sh' : language === 'javascript' ? 'client.mjs' : 'client.py'}
        onCopy={() => { void copy(source, '코드'); }} />
      {record.kind === 'risk' ? (
        <p className="playground-export-hint">
          Python·Node.js는 검사 미완료 시 종료 코드 2를 반환합니다. 허용·차단 정책은 호출하는 서비스에서 결정하세요.
        </p>
      ) : null}
      <div className="playground-export-actions">
        <Button size="sm" variant="secondary" onClick={() => { void copy(record.requestJson, '요청 JSON'); }}>요청 JSON 복사</Button>
      </div>
      <details className="playground-export-json">
        <summary>요청 JSON 보기</summary>
        <CodeViewer source={pretty} language="json" filename="request.json"
          onCopy={() => { void copy(record.requestJson, '요청 JSON'); }} />
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
