import { archiveToBlob, estimatedArchiveBytes, receiptArchiveEntries, writeZip64, type ArchiveSink } from './exportPipeline.ts';
import { receiptChunks, receiptText, type RequestReceipt } from './requestReceipt.ts';

// A bounded compatibility path, not a guessed device-memory tuning parameter.
// Larger exports require a user-approved streaming file destination.
export const MAX_BUFFERED_DOWNLOAD_BYTES = 64 * 1024 * 1024;

type SaveHandle = {
  createWritable: () => Promise<{
    write: (bytes: Uint8Array) => Promise<void>;
    close: () => Promise<void>;
    abort: (reason?: unknown) => Promise<void>;
  }>;
};
type SavePicker = (options: {
  suggestedName: string;
  types: { description: string; accept: Record<string, string[]> }[];
}) => Promise<SaveHandle>;

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  try {
    anchor.href = url;
    anchor.download = filename;
    anchor.hidden = true;
    document.body.append(anchor);
    anchor.click();
  } finally {
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }
}

export function canStreamDirectToFile(): boolean {
  return typeof window !== 'undefined'
    && typeof (window as Window & { showSaveFilePicker?: SavePicker }).showSaveFilePicker === 'function';
}

function streamingPicker(): SavePicker | null {
  if (!canStreamDirectToFile()) return null;
  return (window as Window & { showSaveFilePicker?: SavePicker }).showSaveFilePicker ?? null;
}

async function openSaveDestination(filename: string, mimeType: string, extension: string): Promise<ArchiveSink> {
  const picker = streamingPicker();
  if (!picker) {
    throw new Error('이 브라우저는 대용량 파일 직접 저장을 지원하지 않습니다. 지원되는 브라우저에서 다시 시도해 주세요.');
  }
  // Called synchronously from the user's button click path before any async work.
  const handle = await picker.call(window, {
    suggestedName: filename,
    types: [{ description: filename, accept: { [mimeType]: [extension] } }],
  });
  const writable = await handle.createWritable();
  return {
    write: (bytes) => writable.write(bytes),
    close: () => writable.close(),
    abort: (reason) => writable.abort(reason),
  };
}

export async function saveRequestJson(
  receipt: RequestReceipt,
  signal: AbortSignal,
  report: (done: number, total: number) => void,
): Promise<string> {
  if (receipt.byteLength <= MAX_BUFFERED_DOWNLOAD_BYTES) {
    if (signal.aborted) throw new DOMException('취소됨', 'AbortError');
    downloadBlob(new Blob([receiptText(receipt)], { type: 'application/json;charset=utf-8' }), 'request.json');
    report(receipt.byteLength, receipt.byteLength);
    return 'request.json 내려받기를 요청했습니다.';
  }
  const sink = await openSaveDestination('request.json', 'application/json', '.json');
  let completed = false;
  try {
    let written = 0;
    for await (const part of receiptChunks(receipt, signal)) {
      if (signal.aborted) throw new DOMException('취소됨', 'AbortError');
      await sink.write(part);
      written += part.byteLength;
      report(written, receipt.byteLength);
      // Cooperatively yield for long JSON strings even with a fast disk.
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    }
    if (written !== receipt.byteLength) throw new Error('요청 JSON 길이가 일치하지 않습니다.');
    await sink.close();
    completed = true;
    return '요청 JSON 파일 저장을 완료했습니다.';
  } finally {
    if (!completed) await sink.abort().catch(() => {});
  }
}

export async function saveRequestZip(
  receipt: RequestReceipt,
  signal: AbortSignal,
  report: (done: number, total: number) => void,
): Promise<string> {
  const entries = receiptArchiveEntries(receipt);
  if (estimatedArchiveBytes(entries) <= MAX_BUFFERED_DOWNLOAD_BYTES) {
    const blob = await archiveToBlob(entries, { signal, onProgress: report });
    if (signal.aborted) throw new DOMException('취소됨', 'AbortError');
    downloadBlob(blob, 'playground-request.zip');
    return 'ZIP 내려받기를 요청했습니다.';
  }
  const sink = await openSaveDestination('playground-request.zip', 'application/zip', '.zip');
  await writeZip64(entries, sink, { signal, onProgress: report });
  return 'ZIP 파일 저장을 완료했습니다.';
}
