import { CHAT_COMPLETIONS_PATH } from './publicChatRequest.ts';

// The serialized request sent to Gateway is the only authority for export.
// This module never reads the active model, the current composer or the API key.
export type ExportLanguage = 'python' | 'javascript' | 'curl';
export type ExportFiles = Record<'request.json' | 'client.py' | 'client.mjs' | 'client.sh' | 'README.md', string>;
export const EXPORT_LANGUAGES: readonly { id: ExportLanguage; label: string; file: keyof ExportFiles }[] = [
  { id: 'python', label: 'Python (HTTP)', file: 'client.py' },
  { id: 'javascript', label: 'JavaScript (Node.js)', file: 'client.mjs' },
  { id: 'curl', label: 'cURL (Bash)', file: 'client.sh' },
];

function validatedRequest(serialized: string): { stream: boolean } {
  const input: unknown = JSON.parse(serialized);
  if (input === null || typeof input !== 'object' || Array.isArray(input)) {
    throw new Error('전송 요청이 JSON 객체가 아닙니다.');
  }
  const body = input as Record<string, unknown>;
  if (typeof body.model !== 'string' || !Array.isArray(body.messages)) {
    throw new Error('Chat Completions 요청이 아닙니다.');
  }
  return { stream: body.stream === true };
}

// Raw HTTP rather than a guessed SDK parameter mapping is deliberate:
// it preserves vLLM extensions, tool history and media data byte-for-byte.
const PYTHON = [
  '"""Replay the Playground HTTP request with Python 3 (stdlib only)."""',
  'import json',
  'import os',
  'import sys',
  'from pathlib import Path',
  'from urllib.error import HTTPError, URLError',
  'from urllib.request import Request, urlopen',
  '',
  'payload = Path(__file__).with_name("request.json").read_bytes()',
  'stream = json.loads(payload).get("stream") is True',
  'gateway = os.environ.get("GATEWAY_URL", "http://127.0.0.1:9400").rstrip("/")',
  'key = os.environ.get("API_KEY")',
  'headers = {"Content-Type": "application/json",',
  '           "Accept": "text/event-stream" if stream else "application/json"}',
  'if key:',
  '    headers["Authorization"] = "Bearer " + key',
  'request = Request(gateway + "' + CHAT_COMPLETIONS_PATH + '",',
  '                  data=payload, headers=headers, method="POST")',
  'try:',
  '    with urlopen(request, timeout=180) as response:',
  '        if stream:',
  '            completed, failed = False, False',
  '            for raw_line in response:',
  '                line = raw_line.decode("utf-8")',
  '                print(line, end="", flush=True)',
  '                field, _, value = line.strip().partition(":")',
  '                if field == "event" and value.strip() == "error":',
  '                    failed = True',
  '                if field == "data":',
  '                    data = value.strip()',
  '                    if data == "[DONE]":',
  '                        completed = True',
  '                    elif data.startswith("{"):',
  '                        try:',
  '                            event = json.loads(data)',
  '                        except json.JSONDecodeError:',
  '                            pass',
  '                        else:',
  '                            if isinstance(event, dict) and "error" in event:',
  '                                failed = True',
  '            if failed:',
  '                raise SystemExit("Gateway SSE error (see event above)")',
  '            if not completed:',
  '                raise SystemExit("STREAM_INCOMPLETE: response ended without [DONE]")',
  '        else:',
  '            print(response.read().decode("utf-8"))',
  'except HTTPError as exc:',
  '    print("Gateway HTTP", exc.code,',
  '          exc.read().decode("utf-8", errors="replace"), file=sys.stderr)',
  '    raise SystemExit(1) from exc',
  'except URLError as exc:',
  '    print("Gateway connection failed:", exc.reason, file=sys.stderr)',
  '    raise SystemExit(1) from exc',
  '',
].join('\n');

const JAVASCRIPT = [
  '// Node.js 18+; request.json is the original Playground HTTP body.',
  "import { readFile } from 'node:fs/promises';",
  "const payload = await readFile(new URL('./request.json', import.meta.url));",
  "const stream = JSON.parse(payload.toString('utf8')).stream === true;",
  "const gateway = (process.env.GATEWAY_URL ?? 'http://127.0.0.1:9400').replace(/\\/$/, '');",
  'const headers = {',
  "  'Content-Type': 'application/json',",
  "  Accept: stream ? 'text/event-stream' : 'application/json',",
  '};',
  "if (process.env.API_KEY) headers.Authorization = 'Bearer ' + process.env.API_KEY;",
  'try {',
  "  const response = await fetch(gateway + '" + CHAT_COMPLETIONS_PATH + "', {",
  "    method: 'POST', headers, body: payload,",
  '  });',
  '  if (!response.ok) {',
  "    console.error('Gateway HTTP ' + response.status + ': ' + await response.text());",
  '    process.exitCode = 1;',
  '  } else if (stream && response.body) {',
  '    const decoder = new TextDecoder();',
  "    let pending = '';",
  '    let completed = false;',
  '    let failed = false;',
  '    const inspectLine = (raw) => {',
  "      const line = raw.replace(/\\r$/, '');",
  "      const separator = line.indexOf(':');",
  '      if (separator < 0) return;',
  '      const field = line.slice(0, separator);',
  '      const value = line.slice(separator + 1).trim();',
  "      if (field === 'event' && value === 'error') failed = true;",
  "      if (field === 'data' && value === '[DONE]') completed = true;",
  "      if (field === 'data' && value.startsWith('{')) {",
  '        try {',
  '          const event = JSON.parse(value);',
  "          if (event && typeof event === 'object' && 'error' in event) failed = true;",
  '        } catch { /* Ignore malformed non-error data, as Playground does. */ }',
  '      }',
  '    };',
  '    for await (const chunk of response.body) {',
  '      process.stdout.write(chunk);',
  '      pending += decoder.decode(chunk, { stream: true });',
  '      let end;',
  "      while ((end = pending.indexOf('\\n')) >= 0) {",
  '        inspectLine(pending.slice(0, end));',
  '        pending = pending.slice(end + 1);',
  '      }',
  '    }',
  '    pending += decoder.decode();',
  '    if (pending) inspectLine(pending);',
  "    if (failed) { console.error('Gateway SSE error (see event above)'); process.exitCode = 1; }",
  "    else if (!completed) { console.error('STREAM_INCOMPLETE: response ended without [DONE]'); process.exitCode = 1; }",
  '  } else if (stream) {',
  "    console.error('STREAM_INCOMPLETE: response body is missing');",
  '    process.exitCode = 1;',
  '  } else {',
  '    console.log(await response.text());',
  '  }',
  '} catch (error) {',
  "  console.error('Gateway connection failed:', error);",
  '  process.exitCode = 1;',
  '}',
  '',
].join('\n');

function curlScript(stream: boolean): string {
  const lines = [
    '#!/usr/bin/env bash',
    'set -euo pipefail',
    'gateway_url="${GATEWAY_URL:-http://127.0.0.1:9400}"',
    "headers=(-H 'Content-Type: application/json' -H 'Accept: " + (stream ? 'text/event-stream' : 'application/json') + "')",
    'if [[ -n "${API_KEY:-}" ]]; then',
    '  headers+=(-H "Authorization: Bearer ${API_KEY}")',
    'fi',
    'curl --fail-with-body --no-buffer --request POST "${gateway_url%/}' + CHAT_COMPLETIONS_PATH + '" \\',
    '  "${headers[@]}" --data-binary @"$(dirname "$0")/request.json"' + (stream ? " | awk '" : ''),
  ];
  if (stream) {
    lines.push(
      "  /^event:[[:space:]]*error[[:space:]]*$/ { failed = 1 }",
      "  /^data:/ {",
      "    data = $0",
      "    sub(/^data:[[:space:]]*/, \"\", data)",
      "    sub(/\\r$/, \"\", data)",
      "    if (data == \"[DONE]\") completed = 1",
      "    if (data ~ /^\\{[[:space:]]*\"error\"[[:space:]]*:/) failed = 1",
      "  }",
      "  { print; fflush() }",
      "  END {",
      "    if (failed) { print \"Gateway SSE error (see event above)\" > \"/dev/stderr\"; exit 1 }",
      "    if (!completed) { print \"STREAM_INCOMPLETE: response ended without [DONE]\" > \"/dev/stderr\"; exit 1 }",
      "  }",
      "'",
    );
  }
  return lines.join('\n') + '\n';
}

const README = [
  '# Playground 요청 재현',
  '',
  '이 패키지의 request.json은 Playground가 실제로 전송한 단일',
  'POST /v1/chat/completions 요청 본문입니다. Python, Node.js, cURL은',
  '동일 파일을 그대로 보내므로 SDK별 암묵적 기본값·확장 필드 누락이 없습니다.',
  '',
  '## 실행 준비',
  '',
  'Gateway에 접속 가능한 개발 머신에서 GATEWAY_URL을 지정합니다.',
  '기본 주소는 http://127.0.0.1:9400 입니다.',
  '인증이 활성화된 경우 사용자 API Key를 API_KEY 환경변수로 지정합니다.',
  '관리자 키를 사용하지 마세요.',
  '',
  '## 실행 (하나만 선택)',
  '',
  'python3 client.py',
  'node client.mjs    (Node.js 18 이상)',
  'bash client.sh',
  '',
  '별도 SDK 설치는 필요 없습니다. Streaming 예제는 SSE 원문을 출력하고',
  'Gateway SSE 오류 및 [DONE] 누락을 실패로 처리합니다. 서비스 앱에서는',
  '이벤트 파싱과 Tool 실행·결과 처리를 별도로 구현해야 합니다.',
  '',
  '## 재현 범위와 보안',
  '',
  '- request.json에는 실제 프롬프트, 대화·Tool 내역, 미디어 Base64 및',
  '  개인정보/기밀정보가 포함될 수 있습니다. 내보낸 파일의 보관에 유의하세요.',
  '- 인증 키와 브라우저 세션은 저장하지 않습니다.',
  '- 동일한 요청도 현재 활성 모델 프로필, 서버 설정과 샘플링에 따라',
  '  다른 결과를 낼 수 있습니다. local-main은 논리적 모델 이름입니다.',
  '- Tool Calling 예제는 선택한 한 번의 HTTP 요청만 보냅니다.',
  '  Playground처럼 별도 Tool 실행을 자동으로 수행하지 않습니다.',
  '- 다운로드 전에만 브라우저 탭 메모리를 사용하며 서버에 저장하지 않습니다.',
  '',
].join('\n');

export function buildExportFiles(serializedRequest: string): ExportFiles {
  const { stream } = validatedRequest(serializedRequest);
  return {
    'request.json': serializedRequest,
    'client.py': PYTHON,
    'client.mjs': JAVASCRIPT,
    'client.sh': curlScript(stream),
    'README.md': README,
  };
}

export function requestPreview(serializedRequest: string, maxCharacters = 12000): string | null {
  if (serializedRequest.length > maxCharacters) return null;
  validatedRequest(serializedRequest);
  return JSON.stringify(JSON.parse(serializedRequest), null, 2);
}

const CRC32_TABLE = Uint32Array.from({ length: 256 }, (_, index) => {
  let crc = index;
  for (let bit = 0; bit < 8; bit += 1) {
    crc = (crc >>> 1) ^ ((crc & 1) !== 0 ? 0xedb88320 : 0);
  }
  return crc >>> 0;
});

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc = CRC32_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

export function createExportZip(files: ExportFiles): Blob {
  const encoder = new TextEncoder();
  const parts: BlobPart[] = [];
  const centralDirectory: Uint8Array<ArrayBuffer>[] = [];
  const entries = Object.entries(files);
  let offset = 0;
  for (const [filename, content] of entries) {
    const name = encoder.encode(filename);
    const data = encoder.encode(content);
    if (data.length > 0xffffffff || offset + 30 + name.length + data.length > 0xffffffff) {
      throw new Error('ZIP32에서 지원하지 않는 요청 크기입니다.');
    }
    const checksum = crc32(data);
    const local = new Uint8Array(30 + name.length);
    const l = new DataView(local.buffer);
    l.setUint32(0, 0x04034b50, true);
    l.setUint16(4, 20, true);
    l.setUint16(6, 0x0800, true);
    l.setUint32(14, checksum, true);
    l.setUint32(18, data.length, true);
    l.setUint32(22, data.length, true);
    l.setUint16(26, name.length, true);
    local.set(name, 30);
    parts.push(local, data);
    const central = new Uint8Array(46 + name.length);
    const c = new DataView(central.buffer);
    c.setUint32(0, 0x02014b50, true);
    c.setUint16(4, 20, true);
    c.setUint16(6, 20, true);
    c.setUint16(8, 0x0800, true);
    c.setUint32(16, checksum, true);
    c.setUint32(20, data.length, true);
    c.setUint32(24, data.length, true);
    c.setUint16(28, name.length, true);
    c.setUint32(42, offset, true);
    central.set(name, 46);
    centralDirectory.push(central);
    offset += local.length + data.length;
  }
  const directorySize = centralDirectory.reduce((sum, chunk) => sum + chunk.length, 0);
  if (offset + directorySize > 0xffffffff) throw new Error('ZIP32 크기 제한을 초과했습니다.');
  const footer = new Uint8Array(22);
  const e = new DataView(footer.buffer);
  e.setUint32(0, 0x06054b50, true);
  e.setUint16(8, entries.length, true);
  e.setUint16(10, entries.length, true);
  e.setUint32(12, directorySize, true);
  e.setUint32(16, offset, true);
  return new Blob([...parts, ...centralDirectory, footer], { type: 'application/zip' });
}
