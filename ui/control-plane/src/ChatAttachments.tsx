import {
  classifyAttachment,
  inputModalityLabel,
  validateChatAttachments,
  type ChatAttachment,
  type PublicModel,
} from './chatSession';

// 브라우저 파일 읽기를 화면 표시에서 분리하고, 검증 권한은 chatSession에 유지한다.
function formatFileBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

function readFileDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('파일을 읽지 못했습니다.'));
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        reject(new Error('파일을 base64로 변환하지 못했습니다.'));
        return;
      }
      resolve(reader.result);
    };
    reader.readAsDataURL(file);
  });
}

export async function chatAttachmentFromFile(
  file: File,
  model: PublicModel,
  existing: readonly ChatAttachment[],
): Promise<{ attachment: ChatAttachment | null; error: string | null }> {
  const classified = classifyAttachment(model, {
    name: file.name,
    mimeType: file.type,
    sizeBytes: file.size,
  });
  if (!('modality' in classified)) return { attachment: null, error: classified.error };

  const dataUrl = await readFileDataUrl(file);
  const comma = dataUrl.indexOf(',');
  if (comma < 0) return { attachment: null, error: '파일을 data URL로 변환하지 못했습니다.' };
  const attachment: ChatAttachment = {
    id: crypto.randomUUID(),
    name: file.name,
    modality: classified.modality,
    mimeType: file.type.toLowerCase(),
    sizeBytes: file.size,
    data: classified.modality === 'audio' ? dataUrl.slice(comma + 1) : dataUrl,
    ...(classified.audioFormat ? { audioFormat: classified.audioFormat } : {}),
  };
  const error = validateChatAttachments(model, [...existing, attachment]);
  return error ? { attachment: null, error } : { attachment, error: null };
}

export function AttachmentList({
  attachments,
  removable = false,
  onRemove,
}: {
  attachments: readonly ChatAttachment[];
  removable?: boolean;
  onRemove?: (id: string) => void;
}) {
  if (attachments.length === 0) return null;
  return (
    <ul className="chat-attachment-list" aria-label="첨부 파일">
      {attachments.map((attachment) => (
        <li key={attachment.id}>
          <span>
            <strong>{inputModalityLabel(attachment.modality)}</strong>
            {' · '}
            {attachment.name}
            {' · '}
            {formatFileBytes(attachment.sizeBytes)}
          </span>
          {removable && onRemove ? (
            <button type="button" onClick={() => onRemove(attachment.id)} aria-label={`${attachment.name} 첨부 제거`}>
              제거
            </button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

