import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Button } from '@patternfly/react-core';
import { EXPORT_LANGUAGES, exportTemplates, type ExportLanguage } from './playgroundExport';
import { canStreamDirectToFile, MAX_BUFFERED_DOWNLOAD_BYTES, saveRequestJson, saveRequestZip } from './exportDownload.ts';
import { estimatedArchiveBytes, receiptArchiveEntries } from './exportPipeline.ts';
import { receiptText, type RequestReceipt } from './requestReceipt.ts';
import type { TurnStatus } from './chatSession';

function RequestExportContents({ receipt, status }: { receipt: RequestReceipt; status: TurnStatus }) {
  const languageId = useId();
  const [language, setLanguage] = useState<ExportLanguage>('python');
  const [feedback, setFeedback] = useState('');
  const [working, setWorking] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const files = useMemo(() => exportTemplates(receipt.streaming), [receipt.streaming]);
  const zipBytes = useMemo(() => estimatedArchiveBytes(receiptArchiveEntries(receipt)), [receipt]);
  const supportsLargeDownloads = canStreamDirectToFile();
  const jsonRequiresPicker = receipt.byteLength > MAX_BUFFERED_DOWNLOAD_BYTES;
  const zipRequiresPicker = zipBytes > MAX_BUFFERED_DOWNLOAD_BYTES;
  const jsonUnsupported = jsonRequiresPicker && !supportsLargeDownloads;
  const zipUnsupported = zipRequiresPicker && !supportsLargeDownloads;
  const selected = EXPORT_LANGUAGES.find((item) => item.id === language) ?? EXPORT_LANGUAGES[0];
  const source = files[selected.file];
  const preview = useMemo(() => {
    if (receipt.byteLength > 12_000) return null;
    try { return JSON.stringify(JSON.parse(receiptText(receipt)), null, 2); }
    catch { return null; }
  }, [receipt]);

  async function copyCode(): Promise<void> {
    try {
      await navigator.clipboard.writeText(source);
      setFeedback('코드를 복사했습니다. 실행에는 request.json이 필요합니다.');
    } catch { setFeedback('코드 복사에 실패했습니다. ZIP 다운로드를 사용하세요.'); }
  }

  async function copyJson(): Promise<void> {
    // Clipboard APIs require materializing one contiguous JS string.
    if (receipt.byteLength > 1024 * 1024) {
      setFeedback('1MiB를 초과한 요청은 클립보드에서 전체 문자열을 복제하지 않습니다. JSON 파일로 내려받으세요.');
      return;
    }
    try {
      await navigator.clipboard.writeText(receiptText(receipt));
      setFeedback('전송한 Request JSON을 복사했습니다. 붙여넣기 대상의 민감정보 노출에 주의하세요.');
    } catch { setFeedback('JSON 복사에 실패했습니다. 브라우저 권한을 확인하세요.'); }
  }

  async function download(kind: 'json' | 'zip'): Promise<void> {
    if (working) return;
    const job = new AbortController();
    controller.current = job;
    setWorking(true);
    setProgress(0);
    setFeedback('내보내기를 준비하고 있습니다.');
    try {
      const report = (done: number, total: number) => {
        if (!job.signal.aborted) setProgress((previous) => {
          const nextPercent = total > 0 ? Math.min(99, Math.round((done / total) * 100)) : 99;
          return previous === nextPercent ? previous : nextPercent;
        });
      };
      const result = kind === 'json'
        ? await saveRequestJson(receipt, job.signal, report)
        : await saveRequestZip(receipt, job.signal, report);
      if (!job.signal.aborted) setFeedback(result);
    } catch (error) {
      setFeedback(error instanceof Error && error.name === 'AbortError'
        ? '내보내기가 취소됐습니다.'
        : '내보내기 실패: ' + (error instanceof Error ? error.message : '알 수 없는 오류'));
    } finally {
      if (controller.current === job) controller.current = null;
      setWorking(false);
      setProgress(null);
    }
  }

  return (
    <div className="playground-export-content">
      <p>전송 당시의 <strong>실제 요청 바이트</strong>를 내보냅니다. 현재 모델이나 설정으로 다시 만들지 않습니다.</p>
      {status !== 'complete' && (
        <p className="playground-export-warning">이 요청은 정상 완료되지 않았습니다. 재현 데이터만 제공하며 성공을 보장하지 않습니다.</p>
      )}
      <p className="playground-export-warning">
        요청에는 대화·미디어·개인정보가 포함될 수 있습니다. 인증 헤더의 API 키는 자동으로 포함되지 않지만, 프롬프트에 직접 입력한 비밀정보는 그대로 포함됩니다.
      </p>
      <p className="playground-export-hint">원본 요청 크기: {receipt.byteLength.toLocaleString('ko-KR')}바이트. 큰 파일은 지원 브라우저에서 직접 스트리밍 저장합니다.</p>
      {(jsonUnsupported || zipUnsupported) && (
        <p role="alert" className="playground-export-warning">
          이 브라우저는 대용량 직접 저장을 지원하지 않습니다.
          {jsonUnsupported ? ' 요청 JSON 저장' : ''}{zipUnsupported ? ' ZIP 저장' : ''}은
          사용자 승인을 받는 파일 스트림을 지원하는 브라우저에서 가능합니다.
          다른 방법으로 전체 데이터를 생략하거나 무제한 메모리에 조립하지 않습니다.
        </p>
      )}
      <label htmlFor={languageId}>개발 언어</label>
      <select id={languageId} value={language} disabled={working} onChange={(event) => { setLanguage(event.currentTarget.value as ExportLanguage); setFeedback(''); }}>
        {EXPORT_LANGUAGES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select>
      <pre className="playground-export-code"><code>{source}</code></pre>
      <p className="playground-export-hint">클라이언트는 request.json을 같은 폴더에서 읽어 Gateway로 전송합니다. 모든 확장 파라미터와 미디어가 보존됩니다.</p>
      <div className="playground-export-actions">
        <Button size="sm" variant="secondary" isDisabled={working} onClick={() => { void copyCode(); }}>코드 복사</Button>
        <Button size="sm" variant="secondary" isDisabled={working} onClick={() => { void copyJson(); }}>요청 JSON 복사</Button>
        <Button size="sm" variant="secondary" isDisabled={working || jsonUnsupported} onClick={() => { void download('json'); }}>요청 JSON 받기</Button>
        <Button size="sm" variant="primary" isDisabled={working || zipUnsupported} onClick={() => { void download('zip'); }}>전체 예제 ZIP 받기</Button>
        {working && <Button size="sm" variant="danger" onClick={() => controller.current?.abort()}>내보내기 취소</Button>}
      </div>
      {working && <p role="progressbar" aria-label="요청 내보내기 진행" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress ?? 0}>
        내보내기 진행: {progress ?? 0}%
      </p>}
      <details className="playground-export-json">
        <summary>전송한 Request JSON</summary>
        {preview === null
          ? <p>큰 요청의 미리보기는 생략합니다. JSON 파일로 손실 없이 확인할 수 있습니다.</p>
          : <pre className="playground-export-code"><code>{preview}</code></pre>}
      </details>
      <p role="status" aria-live="polite" className="playground-export-feedback">{feedback}</p>
      <p className="playground-export-hint">local-main의 활성 프로필이 바뀌면 같은 요청에도 응답이 달라질 수 있습니다. Tool은 자동 실행하지 않습니다.</p>
    </div>
  );
}

export function RequestExportPanel(props: { receipt: RequestReceipt; status: TurnStatus }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <details className="playground-export" onToggle={(event) => setExpanded(event.currentTarget.open)}>
      <summary>코드로 사용하기</summary>
      {expanded ? <RequestExportContents {...props} /> : null}
    </details>
  );
}
