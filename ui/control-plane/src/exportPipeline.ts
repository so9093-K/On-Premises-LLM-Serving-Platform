import { receiptChunks, type RequestReceipt } from './requestReceipt.ts';
import { exportTemplates } from './playgroundExport.ts';

export type ArchiveEntry = Readonly<{
  name: string;
  byteLength: number;
  chunks: (signal?: AbortSignal) => AsyncIterable<Uint8Array>;
}>;

export type ArchiveSink = {
  write: (bytes: Uint8Array) => Promise<void>;
  close: () => Promise<void>;
  abort: (reason?: unknown) => Promise<void>;
};

const encoder = new TextEncoder();
const CRC32 = Uint32Array.from({ length: 256 }, (_, value) => {
  let crc = value;
  for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  return crc >>> 0;
});
const TICK_BYTES = 256 * 1024;

function crc32Update(crc: number, bytes: Uint8Array): number {
  for (const byte of bytes) crc = CRC32[(crc ^ byte) & 255] ^ (crc >>> 8);
  return crc;
}

function write16(view: DataView, pos: number, value: number) { view.setUint16(pos, value, true); }
function write32(view: DataView, pos: number, value: number) { view.setUint32(pos, value, true); }
function write64(view: DataView, pos: number, value: bigint) { view.setBigUint64(pos, value, true); }
function rejectIfAborted(signal?: AbortSignal) {
  if (signal?.aborted) throw new DOMException('내보내기가 취소됐습니다.', 'AbortError');
}
function yieldToBrowser(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

export function receiptArchiveEntries(receipt: RequestReceipt): ArchiveEntry[] {
  const templates = exportTemplates(receipt.streaming);
  const entries: ArchiveEntry[] = [{
    name: 'request.json',
    byteLength: receipt.byteLength,
    chunks: (signal) => receiptChunks(receipt, signal),
  }];
  for (const [name, text] of Object.entries(templates)) {
    entries.push({
      name,
      byteLength: encoder.encode(text).byteLength,
      async *chunks() { yield encoder.encode(text); },
    });
  }
  return entries;
}

// ZIP64 STORE with a data descriptor allows bytes to be written as received,
// without first buffering request.json, calculating its CRC, or knowing an output
// Blob size. Always writing ZIP64 avoids a hidden format change near the 4GiB limit.
export async function writeZip64(
  entries: readonly ArchiveEntry[],
  sink: ArchiveSink,
  options: { signal?: AbortSignal; onProgress?: (bytes: number, total: number) => void } = {},
): Promise<void> {
  const { signal, onProgress } = options;
  const directory: Uint8Array[] = [];
  let offset = 0n;
  let workSinceYield = 0;
  const total = entries.reduce((bytes, item) => bytes + item.byteLength, 0);
  let done = 0;
  const send = async (bytes: Uint8Array) => {
    rejectIfAborted(signal);
    await sink.write(bytes);
    offset += BigInt(bytes.length);
    workSinceYield += bytes.length;
    if (workSinceYield >= TICK_BYTES) {
      workSinceYield = 0;
      await yieldToBrowser();
      rejectIfAborted(signal);
    }
  };
  try {
    for (const entry of entries) {
      rejectIfAborted(signal);
      const name = encoder.encode(entry.name);
      if (name.length > 0xffff) throw new Error('ZIP 파일 이름이 너무 깁니다.');
      const position = offset;
      const local = new Uint8Array(30 + name.length + 20);
      const header = new DataView(local.buffer);
      write32(header, 0, 0x04034b50);
      write16(header, 4, 45);
      write16(header, 6, 0x0808); // UTF-8 + trailing data descriptor
      write16(header, 8, 0); // STORE
      write32(header, 18, 0xffffffff);
      write32(header, 22, 0xffffffff);
      write16(header, 26, name.length);
      write16(header, 28, 20);
      local.set(name, 30);
      write16(header, 30 + name.length, 1); // ZIP64 extra field
      write16(header, 32 + name.length, 16);
      await send(local);
      let crc = 0xffffffff;
      let size = 0n;
      for await (const bytes of entry.chunks(signal)) {
        rejectIfAborted(signal);
        crc = crc32Update(crc, bytes);
        size += BigInt(bytes.length);
        await send(bytes);
        done += bytes.length;
        onProgress?.(done, total);
      }
      if (size !== BigInt(entry.byteLength)) throw new Error('내보내기 원본 길이가 예상 값과 일치하지 않습니다.');
      crc = (crc ^ 0xffffffff) >>> 0;
      const descriptor = new Uint8Array(24);
      const d = new DataView(descriptor.buffer);
      write32(d, 0, 0x08074b50);
      write32(d, 4, crc);
      write64(d, 8, size);
      write64(d, 16, size);
      await send(descriptor);
      const central = new Uint8Array(46 + name.length + 28);
      const c = new DataView(central.buffer);
      write32(c, 0, 0x02014b50);
      write16(c, 4, 45);
      write16(c, 6, 45);
      write16(c, 8, 0x0808);
      write32(c, 16, crc);
      write32(c, 20, 0xffffffff);
      write32(c, 24, 0xffffffff);
      write16(c, 28, name.length);
      write16(c, 30, 28);
      write32(c, 42, 0xffffffff);
      central.set(name, 46);
      write16(c, 46 + name.length, 1);
      write16(c, 48 + name.length, 24);
      write64(c, 50 + name.length, size);
      write64(c, 58 + name.length, size);
      write64(c, 66 + name.length, position);
      directory.push(central);
    }
    const directoryOffset = offset;
    for (const part of directory) await send(part);
    const centralSize = offset - directoryOffset;
    const zip64Offset = offset;
    const end64 = new Uint8Array(56);
    const e = new DataView(end64.buffer);
    write32(e, 0, 0x06064b50);
    write64(e, 4, 44n);
    write16(e, 12, 45);
    write16(e, 14, 45);
    write64(e, 24, BigInt(entries.length));
    write64(e, 32, BigInt(entries.length));
    write64(e, 40, centralSize);
    write64(e, 48, directoryOffset);
    await send(end64);
    const locator = new Uint8Array(20);
    const l = new DataView(locator.buffer);
    write32(l, 0, 0x07064b50);
    write64(l, 8, zip64Offset);
    write32(l, 16, 1);
    await send(locator);
    const end = new Uint8Array(22);
    const ev = new DataView(end.buffer);
    write32(ev, 0, 0x06054b50);
    write16(ev, 8, 0xffff);
    write16(ev, 10, 0xffff);
    write32(ev, 12, 0xffffffff);
    write32(ev, 16, 0xffffffff);
    await send(end);
    rejectIfAborted(signal);
    await sink.close();
  } catch (error) {
    // The original failure (including AbortError / corrupted input) owns the
    // user-visible result. A secondary sink cleanup error must not replace it.
    try { await sink.abort(error); } catch { /* retain original failure */ }
    throw error;
  }
}

export function estimatedArchiveBytes(entries: readonly ArchiveEntry[]): number {
  return entries.reduce((sum, entry) => sum +
    entry.byteLength + 30 + 20 + 24 + 46 + 28 + encoder.encode(entry.name).length * 2, 98);
}

export async function archiveToBlob(
  entries: readonly ArchiveEntry[],
  options: { signal?: AbortSignal; onProgress?: (bytes: number, total: number) => void } = {},
): Promise<Blob> {
  const parts: Uint8Array<ArrayBuffer>[] = [];
  await writeZip64(entries, {
    async write(bytes) { parts.push(bytes.slice()); },
    async close() {},
    async abort() { parts.length = 0; },
  }, options);
  return new Blob(parts, { type: 'application/zip' });
}
