import { useId, useMemo, useState } from 'react';
import { Button } from '@patternfly/react-core';
import {
  EXPORT_LANGUAGES, buildExportFiles, createExportZip, requestPreview,
  type ExportLanguage,
} from './playgroundExport';
import type { TurnStatus } from './chatSession';

function downloadBlob(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  try {
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = filename;
    link.hidden = true;
    document.body.append(link);
    try {
      link.click();
    } finally {
      link.remove();
    }
  } finally {
    // The download can start asynchronously after a.click().
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
  }
}

function RequestExportContents({
  requestJson,
  status,
}: {
  requestJson: string;
  status: TurnStatus;
}) {
  const languageId = useId();
  const [language, setLanguage] = useState<ExportLanguage>('python');
  const [feedback, setFeedback] = useState('');
  // Render only the exact request recorded at transmission, not the current UI state.
  const files = useMemo(() => buildExportFiles(requestJson), [requestJson]);
  const preview = useMemo(() => requestPreview(requestJson), [requestJson]);
  const selected = EXPORT_LANGUAGES.find((item) => item.id === language) ?? EXPORT_LANGUAGES[0];
  const source = files[selected.file];

  async function copyJson(): Promise<void> {
    try {
      await navigator.clipboard.writeText(requestJson);
      setFeedback('전송한 Request JSON을 복사했습니다. 민감정보가 포함될 수 있으니 붙여넣기 위치를 확인하세요.');
    } catch {
      setFeedback('요청 JSON 복사에 실패했습니다. 클립보드 권한을 확인하거나 JSON 파일을 내려받으세요.');
    }
  }

  async function copyCode(): Promise<void> {
    try {
      await navigator.clipboard.writeText(source);
      setFeedback(selected.label + ' 코드를 복사했습니다. 실행에는 request.json이 필요합니다.');
    } catch {
      setFeedback('복사에 실패했습니다. 브라우저 권한을 확인하거나 ZIP 파일을 사용하세요.');
    }
  }

  function download(filename: 'request.json' | 'playground-request.zip'): void {
    try {
      if (filename === 'request.json') {
        downloadBlob(
          new Blob([files['request.json']], { type: 'application/json;charset=utf-8' }),
          filename,
        );
      } else {
        downloadBlob(createExportZip(files), filename);
      }
      setFeedback(filename + ' 내려받기를 요청했습니다. 브라우저 다운로드를 확인하세요.');
    } catch (error) {
      setFeedback(error instanceof Error ? '내보내기 실패: ' + error.message : '내보내기에 실패했습니다.');
    }
  }

  return (
      <div className="playground-export-content">
        <p>이 요청에 <strong>실제로 전송한 JSON</strong>을 내보냅니다. 현재 모델이나 설정으로 다시 만들지 않습니다.</p>
        {status !== 'complete' ? (
          <p className="playground-export-warning">
            {status === 'failed' ? '실패한' : status === 'stopped' ? '중지한' : '진행 중인'} 요청입니다.
            재전송 데이터만 제공하며 성공한 요청으로 표시하지 않습니다.
          </p>
        ) : null}
        <p className="playground-export-warning">
          요청 파일에는 프롬프트·대화·미디어와 민감정보가 포함될 수 있습니다. API 키는 포함하지 않습니다.
        </p>
        <label htmlFor={languageId}>개발 언어</label>
        <select id={languageId} value={language} onChange={(event) => { setLanguage(event.currentTarget.value as ExportLanguage); setFeedback(''); }}>
          {EXPORT_LANGUAGES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
        <pre className="playground-export-code"><code>{source}</code></pre>
        <p className="playground-export-hint">
          코드는 request.json을 같은 폴더에 두고 실행합니다. 실제 HTTP Body를 그대로 전송하므로 확장 파라미터도 유지합니다.
        </p>
        <div className="playground-export-actions">
          <Button size="sm" variant="secondary" onClick={() => { void copyCode(); }}>코드 복사</Button>
          <Button size="sm" variant="secondary" onClick={() => { void copyJson(); }}>요청 JSON 복사</Button>
          <Button size="sm" variant="secondary" onClick={() => download('request.json')}>요청 JSON 받기</Button>
          <Button size="sm" variant="primary" onClick={() => download('playground-request.zip')}>전체 예제 ZIP 받기</Button>
        </div>
        <details className="playground-export-json">
          <summary>전송한 Request JSON</summary>
          {preview === null ? (
            <p>큰 요청의 화면 미리보기는 생략합니다. 손실 없는 원본을 내려받아 확인하세요.</p>
          ) : <pre className="playground-export-code"><code>{preview}</code></pre>}
        </details>
        <p role="status" aria-live="polite" className="playground-export-feedback">{feedback}</p>
        <p className="playground-export-hint">
          같은 local-main 이름이라도 활성 프로필이 바뀌면 결과가 달라질 수 있습니다. Tool은 자동 실행하지 않습니다.
        </p>
      </div>
  );
}

// Large inline media requests are not parsed or copied merely because a message
// appears. The exporter mounts only when the user explicitly opens this turn.
export function RequestExportPanel(props: { requestJson: string; status: TurnStatus }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <details className="playground-export" onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary>코드로 사용하기</summary>
      {expanded ? <RequestExportContents {...props} /> : null}
    </details>
  );
}
