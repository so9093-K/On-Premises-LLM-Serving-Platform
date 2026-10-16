import type { ChatControls, ChatSettings, PublicModel } from './chatSession';

export type ExampleSampleId = 'chart' | 'order' | 'audio';

export type ExampleSampleAsset = {
  modality: 'image' | 'audio';
  filename: string;
  mimeType: string;
  bytes: number;
  caption: string;
  imageAlt?: string;
};

// The sizes are pinned to the canonical public demo assets. Binary integrity
// and media-header tests protect the limits advertised in this catalog.
export const EXAMPLE_SAMPLE_ASSETS: Readonly<Record<ExampleSampleId, ExampleSampleAsset>> = {
  chart: { modality: 'image', filename: 'sample-chart.png', mimeType: 'image/png', bytes: 24099, caption: 'sample-chart.png', imageAlt: '예제 요청 수 막대그래프' },
  order: { modality: 'image', filename: 'sample-order.png', mimeType: 'image/png', bytes: 34473, caption: 'sample-order.png', imageAlt: '예제 가상 주문서' },
  audio: { modality: 'audio', filename: 'sample-audio.wav', mimeType: 'audio/wav', bytes: 158350, caption: 'sample-audio.wav' },
};
export const EXAMPLE_SAMPLE_BYTES: Readonly<Record<ExampleSampleId, number>> = {
  chart: EXAMPLE_SAMPLE_ASSETS.chart.bytes,
  order: EXAMPLE_SAMPLE_ASSETS.order.bytes,
  audio: EXAMPLE_SAMPLE_ASSETS.audio.bytes,
};

export type PlaygroundExample = {
  id: string;
  title: string;
  description: string;
  prompt: string;
  category: 'text' | 'image' | 'audio' | 'structured';
  sample?: ExampleSampleId;
  systemPrompt?: string;
  sampleTranscript?: string;
  schema?: { name: string; value: string };
};

const INFORMATION_SCHEMA = {
  type: 'object',
  properties: {
    name: { type: 'string' },
    date: { type: 'string' },
  },
  required: ['name', 'date'],
  additionalProperties: false,
};

export const PLAYGROUND_EXAMPLES: readonly PlaygroundExample[] = [
  {
    id: 'summarize',
    title: '한국어 요약',
    description: '긴 문장에서 핵심 사항을 세 가지로 정리',
    category: 'text',
    prompt: '다음 문장을 핵심 세 가지로 요약해 주세요.\n\n온프레미스 AI 서빙은 자체 서버에서 모델을 운영하는 방식입니다. 데이터와 인프라의 통제권을 유지할 수 있지만, GPU 자원 관리와 모델 변경, 장애 대응은 운영자가 직접 책임져야 합니다.',
  },
  {
    id: 'chart',
    title: '그래프 분석',
    description: '샘플 그래프의 최대·최소값 읽기',
    category: 'image',
    sample: 'chart',
    prompt: '이 막대그래프에서 요청이 가장 많은 요일과 건수, 가장 적은 요일과 건수를 한국어 두 문장으로 알려주세요.',
  },
  {
    id: 'order',
    title: '주문서 정보 추출',
    description: '샘플 주문서에서 다섯 개 항목 읽기',
    category: 'image',
    sample: 'order',
    prompt: '이미지에서 Order ID, Item, Quantity, Unit price, Total을 읽어 각 항목을 한 줄씩 정확히 적어주세요. 설명은 생략하세요.',
  },
  {
    id: 'audio',
    title: '오디오 분석',
    description: '음성에서 시각과 소요 시간 구분',
    category: 'audio',
    sample: 'audio',
    prompt: '오디오에서 사람들이 나간 시각과 외출한 시간을 각각 알려주세요. 들을 수 없는 정보는 추측하지 마세요.',
    sampleTranscript: '그들은 세시에 나갔어요. 그들은 세시간을 나갔다 왔어요.',
  },
  {
    id: 'system-prompt',
    title: '역할 지정',
    description: '시스템 프롬프트로 답변 범위 설정',
    category: 'text',
    systemPrompt: '당신은 사내 IT 지원 도우미입니다. 비밀번호 재설정, VPN 접속, 업무용 PC 문제에 대해서만 한국어로 안내하세요. 지원 범위를 벗어나는 요청에는 지원 가능한 주제를 알려주세요.',
    prompt: '사내 VPN에 연결되지 않을 때 확인할 사항을 세 가지 알려주세요.',
  },
  {
    id: 'structured',
    title: 'JSON 정보 추출',
    description: '지정한 JSON Schema로 결과 받기',
    category: 'structured',
    prompt: '다음 문장에서 이름과 날짜를 추출해 JSON으로 답변해 주세요.\n\n김민수 님의 방문 예정일은 2026년 10월 20일입니다.',
    schema: { name: 'person_visit', value: JSON.stringify(INFORMATION_SCHEMA, null, 2) },
  },
];

export function exampleAvailability(
  example: PlaygroundExample,
  model: PublicModel,
  controls: ChatControls,
  validateRequest: (example: PlaygroundExample) => string | null,
): { available: boolean; reason: string | null } {
  if (!model.capabilities.includes('chat.completions')) {
    return { available: false, reason: '현재 모델은 채팅 API를 지원하지 않습니다.' };
  }
  if (example.sample) {
    const asset = EXAMPLE_SAMPLE_ASSETS[example.sample];
    const label = asset.modality === 'image' ? '이미지' : '오디오';
    if (!(model.input_modalities ?? []).includes(asset.modality)) {
      return { available: false, reason: `현재 모델은 ${label} 입력을 지원하지 않습니다.` };
    }
    const maxBytes = asset.modality === 'image'
      ? model.request_limits?.image?.max_bytes
      : model.request_limits?.audio?.max_bytes;
    const maxInputs = asset.modality === 'image'
      ? model.request_limits?.image?.max_inputs
      : model.request_limits?.audio?.max_inputs;
    if (typeof maxBytes === 'number' && asset.bytes > maxBytes) {
      return { available: false, reason: `현재 모델의 ${label} 크기 제한을 초과하는 예제입니다.` };
    }
    if (typeof maxInputs === 'number' && maxInputs < 1) {
      return { available: false, reason: `현재 모델은 ${label} 첨부를 허용하지 않습니다.` };
    }
    if (asset.modality === 'image') {
      const allowed = model.request_limits?.image?.allowed_mime_types;
      if (Array.isArray(allowed) && allowed.length > 0 && !allowed.includes(asset.mimeType)) {
        return { available: false, reason: '현재 모델은 예제 PNG 이미지 형식을 지원하지 않습니다.' };
      }
    } else {
      const allowed = model.request_limits?.audio?.allowed_formats;
      if (Array.isArray(allowed) && allowed.length > 0 && !allowed.includes('wav')) {
        return { available: false, reason: '현재 모델은 예제 WAV 오디오 형식을 지원하지 않습니다.' };
      }
    }
  }
  if (example.schema) {
    if (!controls.responseFormat?.allowedTypes.includes('json_schema')) {
      return { available: false, reason: '현재 모델은 JSON Schema 출력을 지원하지 않습니다.' };
    }
    // Per-model schema policy remains owned by the existing request validator,
    // injected by ChatPage to keep this catalog testable without runtime imports.
    const error = validateRequest(example);
    if (error) return { available: false, reason: error };
  }
  return { available: true, reason: null };
}

export function exampleAttachmentSummary(
  attachments: readonly { modality: 'image' | 'audio' | 'video' }[],
): string {
  const names = { image: '이미지', audio: '오디오', video: '비디오' } as const;
  return (['image', 'audio', 'video'] as const)
    .map((modality) => {
      const count = attachments.filter((item) => item.modality === modality).length;
      return count ? `${names[modality]} ${count}개` : null;
    })
    .filter((value): value is string => value !== null)
    .join(' · ');
}

export function exampleSettingsPatch(
  example: PlaygroundExample,
  defaults: ChatSettings,
): Partial<ChatSettings> {
  // Only example-owned settings are replaced. Sampling and advanced knobs stay untouched.
  // Reset incompatible Tools/response-format state so it cannot leak into an example request.
  return {
    systemPrompt: example.systemPrompt ?? defaults.systemPrompt,
    responseFormat: example.schema ? 'json_schema' : defaults.responseFormat,
    jsonSchemaName: example.schema?.name ?? defaults.jsonSchemaName,
    jsonSchemaText: example.schema?.value ?? defaults.jsonSchemaText,
    jsonSchemaStrict: defaults.jsonSchemaStrict,
    toolDrafts: [],
    toolChoice: defaults.toolChoice,
    toolChoiceName: defaults.toolChoiceName,
  };
}

export function exampleRequiresFreshConversation(example: PlaygroundExample): boolean {
  return Boolean(example.systemPrompt || example.schema);
}

/** Detect changes only to fields that an example actually overwrites. */
export function exampleSettingsConflict(
  settings: ChatSettings,
  patch: Partial<ChatSettings>,
): boolean {
  return (Object.keys(patch) as (keyof ChatSettings)[]).some(
    (key) => JSON.stringify(settings[key]) !== JSON.stringify(patch[key]),
  );
}
