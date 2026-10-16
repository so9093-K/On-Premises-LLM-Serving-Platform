// A wire receipt owns the exact byte sequence, not a second mutable request body.
// Media and long conversation strings retain references to the existing
// immutable input values instead of copying them into every request JSON.
export type RequestSegment =
  | Readonly<{ kind: 'text'; value: string }>
  | Readonly<{ kind: 'media'; value: string }>
  | Readonly<{ kind: 'shared'; value: string }>;

export type RequestReceipt = Readonly<{
  parts: readonly RequestSegment[];
  byteLength: number;
  streaming: boolean;
}>;

function immutableReceipt(parts: RequestSegment[], byteLength: number, streaming: boolean): RequestReceipt {
  // TypeScript's Readonly is compile-time only. Freeze the receipt and each
  // segment to prevent a later UI edit from corrupting a recorded wire request.
  parts.forEach(Object.freeze);
  return Object.freeze({ parts: Object.freeze(parts), byteLength, streaming });
}

const encoder = new TextEncoder();
const CHUNK_CHARS = 32 * 1024;
// Below this size, fragmenting short fields would cost more metadata than it saves.
const MIN_SHARED_TEXT_CHARS = 512;

// Slice on a UTF-16 code point boundary to avoid replacing a surrogate pair
// when independently encoding chunks of a large Unicode prompt.
function stringSlices(text: string): Generator<string> {
  return (function* () {
    let start = 0;
    while (start < text.length) {
      let end = Math.min(start + CHUNK_CHARS, text.length);
      if (end < text.length) {
        const previous = text.charCodeAt(end - 1);
        const next = text.charCodeAt(end);
        if (previous >= 0xd800 && previous <= 0xdbff && next >= 0xdc00 && next <= 0xdfff) end -= 1;
      }
      yield text.slice(start, end);
      start = end;
    }
  })();
}

function utf8ByteLength(text: string): number {
  let size = 0;
  for (const part of stringSlices(text)) size += encoder.encode(part).byteLength;
  return size;
}

// FileReader data URLs and extracted audio payloads are JSON-safe ASCII.
// Do not apply this optimization to arbitrary strings that need escaping.
function safeMedia(data: string): boolean {
  return data.length > 0 && /^[\x20-\x21\x23-\x5b\x5d-\x7e]*$/.test(data);
}

// JSON string escaping is performed in bounded chunks so multiline prompts,
// quotes, backslashes and unpaired surrogates remain shareable without changing
// the original wire JSON bytes.
function* escapedStringSlices(value: string): Generator<string> {
  for (const portion of stringSlices(value)) {
    yield JSON.stringify(portion).slice(1, -1);
  }
}

function escapedUtf8ByteLength(value: string): number {
  let size = 0;
  for (const portion of escapedStringSlices(value)) size += utf8ByteLength(portion);
  return size;
}

function collectSharedText(value: unknown, into: Set<string>, media: Set<string>, visited = new WeakSet<object>()): void {
  if (typeof value === 'string') {
    if (value.length >= MIN_SHARED_TEXT_CHARS && !media.has(value)) into.add(value);
  } else if (Array.isArray(value)) {
    if (visited.has(value)) return;
    visited.add(value);
    for (const item of value) collectSharedText(item, into, media, visited);
  } else if (value !== null && typeof value === 'object') {
    if (visited.has(value)) return;
    visited.add(value);
    for (const item of Object.values(value)) collectSharedText(item, into, media, visited);
  }
}

export function captureRequestReceipt(
  body: Record<string, unknown>,
  candidateMedia: readonly { data: string }[],
): RequestReceipt {
  const media = new Set(candidateMedia.map((item) => item.data).filter(safeMedia));
  const sharedText = new Set<string>();
  collectSharedText(body, sharedText, media);
  if (media.size === 0 && sharedText.size === 0) {
    const wire = JSON.stringify(body);
    return immutableReceipt([{ kind: 'text', value: wire }], utf8ByteLength(wire), body.stream === true);
  }
  // Replace shared values while serializing: slicing a large wire JSON may
  // retain its entire backing string in V8, defeating memory deduplication.
  const replacements = new Map<string, { marker: string; value: string; kind: 'media' | 'shared' }>();
  let index = 0;
  for (const value of media) {
    replacements.set(value, { marker: '__playground_media_' + crypto.randomUUID() + '_' + index++ + '__', value, kind: 'media' });
  }
  for (const value of sharedText) {
    replacements.set(value, { marker: '__playground_content_' + crypto.randomUUID() + '_' + index++ + '__', value, kind: 'shared' });
  }
  const skeleton = JSON.stringify(body, (_key, value: unknown) => (
    typeof value === 'string' ? replacements.get(value)?.marker ?? value : value
  ));
  const candidates = [...replacements.values()].map((value) => ({ ...value, token: JSON.stringify(value.marker) }));
  const parts: RequestSegment[] = [];
  let cursor = 0;
  while (cursor < skeleton.length) {
    let closest: { marker: string; value: string; kind: 'media' | 'shared'; token: string; start: number } | null = null;
    for (const candidate of candidates) {
      const start = skeleton.indexOf(candidate.token, cursor);
      if (start !== -1 && (closest === null || start < closest.start)) closest = { ...candidate, start };
    }
    if (!closest) break;
    parts.push({ kind: 'text', value: skeleton.slice(cursor, closest.start) + '"' });
    parts.push({ kind: closest.kind, value: closest.value });
    cursor = closest.start + closest.token.length;
    // The following text fragment begins with the closing JSON quote.
    parts.push({ kind: 'text', value: '"' });
  }
  if (cursor < skeleton.length) parts.push({ kind: 'text', value: skeleton.slice(cursor) });
  // Defensive fallback for unusual objects with custom toJSON/replacer semantics.
  // For normal Playground objects this is not reached.
  if (!parts.some((part) => part.kind !== 'text')) {
    const wire = JSON.stringify(body);
    return immutableReceipt([{ kind: 'text', value: wire }], utf8ByteLength(wire), body.stream === true);
  }
  // The original JSON string uses the same bounded JSON escaping for shared
  // values; check the byte length without assembling another large payload.
  const byteLength = parts.reduce((length, part) => length + (
    part.kind === 'media'
      ? part.value.length
      : part.kind === 'shared'
        ? escapedUtf8ByteLength(part.value)
        : utf8ByteLength(part.value)
  ), 0);
  return immutableReceipt(parts, byteLength, body.stream === true);
}

export function receiptText(receipt: RequestReceipt): string {
  return receipt.parts.map((part) => (
    part.kind === 'shared' ? [...escapedStringSlices(part.value)].join('') : part.value
  )).join('');
}

export async function* receiptChunks(
  receipt: RequestReceipt,
  signal?: AbortSignal,
): AsyncGenerator<Uint8Array<ArrayBuffer>> {
  for (const part of receipt.parts) {
    // Chunk even small text, without splitting non-ASCII code points.
    if (part.kind === 'text' || part.kind === 'shared') {
      const source = part.kind === 'shared' ? escapedStringSlices(part.value) : stringSlices(part.value);
      for (const portion of source) {
        if (signal?.aborted) throw new DOMException('내보내기가 취소됐습니다.', 'AbortError');
        yield encoder.encode(portion);
      }
    } else {
      // Base64/data URL is ASCII by construction. This never creates a
      // second persistent copy of the large media string.
      for (let start = 0; start < part.value.length; start += CHUNK_CHARS) {
        if (signal?.aborted) throw new DOMException('내보내기가 취소됐습니다.', 'AbortError');
        yield encoder.encode(part.value.slice(start, start + CHUNK_CHARS));
      }
    }
  }
}

export function receiptStream(receipt: RequestReceipt, signal?: AbortSignal): ReadableStream<Uint8Array<ArrayBuffer>> {
  const iterator = receiptChunks(receipt, signal);
  return new ReadableStream({
    async pull(controller) {
      try {
        const next = await iterator.next();
        if (next.done) controller.close();
        else controller.enqueue(next.value);
      } catch (error) { controller.error(error); }
    },
    async cancel() { await iterator.return(undefined); },
  });
}
