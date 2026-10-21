import { EMBEDDINGS_PATH } from './embeddingPlayground.ts';
import { RISK_CHECKS } from './riskPlayground.ts';
import { RETRIEVAL_RERANK_PATH } from './retrievalPlayground.ts';

// Embedding·Retrieval·Risk 작업 화면의 "코드로 사용하기". 전송 당시의 요청 문자열만 authority이며
// 현재 화면 입력이나 API 키를 읽지 않는다. 요청은 미디어가 없는 짧은 JSON이므로 Chat처럼
// request.json 파일 묶음을 만들지 않고, 같은 바이트를 담은 단일 파일 예제를 만든다.
export type PublicExportKind = 'embeddings' | 'risk' | 'retrieval';
export type PublicExportLanguage = 'curl' | 'python' | 'javascript' | 'python-sdk';

export type PublicRequestRecord = {
  kind: PublicExportKind;
  path: string;
  // Gateway로 보낸 문자열 그대로다. 예제는 이 바이트를 다시 보낸다.
  requestJson: string;
};

export const PUBLIC_EXPORT_LANGUAGES: Readonly<Record<PublicExportKind, readonly { id: PublicExportLanguage; label: string }[]>> = {
  embeddings: [
    { id: 'curl', label: 'cURL (Bash)' },
    { id: 'python', label: 'Python (HTTP)' },
    { id: 'javascript', label: 'Node.js (fetch)' },
    { id: 'python-sdk', label: 'Python OpenAI SDK (Integration)' },
  ],
  // Risk는 플랫폼 고유 API라 SDK 예제를 만들지 않는다.
  risk: [
    { id: 'curl', label: 'cURL (Bash)' },
    { id: 'python', label: 'Python (HTTP)' },
    { id: 'javascript', label: 'Node.js (fetch)' },
  ],
  retrieval: [
    { id: 'curl', label: 'cURL (Bash)' },
    { id: 'python', label: 'Python (HTTP)' },
    { id: 'javascript', label: 'Node.js (fetch)' },
  ],
};

const RISK_PATHS = new Set(RISK_CHECKS.map((check) => check.path));

function validatedRecord(record: PublicRequestRecord): void {
  const parsed: unknown = JSON.parse(record.requestJson);
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('전송 요청이 JSON 객체가 아닙니다.');
  }
  const body = parsed as Record<string, unknown>;
  if (record.kind === 'embeddings' && (record.path !== EMBEDDINGS_PATH || typeof body.model !== 'string' || !('input' in body))) {
    throw new Error('Embedding 요청이 아닙니다.');
  }
  if (record.kind === 'risk' && (!RISK_PATHS.has(record.path) || typeof body.prompt !== 'string')) {
    throw new Error('Risk 요청이 아닙니다.');
  }
  if (record.kind === 'retrieval' && (record.path !== RETRIEVAL_RERANK_PATH || typeof body.model !== 'string'
    || typeof body.query !== 'string' || !Array.isArray(body.documents) || body.documents.some((item) => typeof item !== 'string'))) {
    throw new Error('Retrieval 요청이 아닙니다.');
  }
}

// JSON 문자열 literal은 Python·JavaScript 문자열 literal로도 유효하다.
function stringLiteral(value: string): string {
  return JSON.stringify(value);
}

function shellQuote(value: string): string {
  return "'" + value.replaceAll("'", "'\\''") + "'";
}

const RISK_RULE = '# HTTP 200만으로 미탐지가 아니다. status=completed, assessment_complete=true, '
  + 'system_signal_detected=false, risk_detected=false를 모두 확인한다.';
const POLICY_NOTE = '허용·차단은 이 신호를 받은 호출 서비스의 정책이 결정한다.';

function curlScript(record: PublicRequestRecord): string {
  return [
    '#!/usr/bin/env bash',
    `# Playground에서 전송한 ${record.kind === 'risk' ? 'Risk' : record.kind === 'retrieval' ? 'Retrieval' : 'Embedding'} 요청을 그대로 다시 보낸다.`,
    '# API 키는 API_KEY 환경변수에서만 읽는다.',
    ...(record.kind === 'risk' ? [RISK_RULE, `# ${POLICY_NOTE}`] : []),
    'set -euo pipefail',
    'gateway_url="${GATEWAY_URL:-http://127.0.0.1:9600}"',
    "headers=(-H 'Content-Type: application/json' -H 'Accept: application/json')",
    'if [[ -n "${API_KEY:-}" ]]; then',
    '  headers+=(-H "Authorization: Bearer ${API_KEY}")',
    'fi',
    `printf '%s' ${shellQuote(record.requestJson)} \\`,
    `  | curl --fail-with-body -sS --request POST "\${gateway_url%/}${record.path}" "\${headers[@]}" --data-binary @-`,
    'echo',
  ].join('\n') + '\n';
}

const PYTHON_SEND = (record: PublicRequestRecord) => [
  'import json',
  'import os',
  'import sys',
  'from urllib.error import HTTPError, URLError',
  'from urllib.request import Request, urlopen',
  '',
  `REQUEST_JSON = ${stringLiteral(record.requestJson)}`,
  'gateway = os.environ.get("GATEWAY_URL", "http://127.0.0.1:9600").rstrip("/")',
  'headers = {"Content-Type": "application/json", "Accept": "application/json"}',
  'if os.environ.get("API_KEY"):',
  '    headers["Authorization"] = "Bearer " + os.environ["API_KEY"]',
  `request = Request(gateway + ${stringLiteral(record.path)}, data=REQUEST_JSON.encode("utf-8"),`,
  '                  headers=headers, method="POST")',
  'try:',
  '    with urlopen(request, timeout=60) as response:',
  '        result = json.load(response)',
  'except HTTPError as error:',
  '    print(error.read().decode("utf-8", "replace"), file=sys.stderr)',
  '    sys.exit(1)',
  'except URLError as error:',
  '    print(f"Gateway connection failed: {error.reason}", file=sys.stderr)',
  '    sys.exit(1)',
  '',
];

function pythonScript(record: PublicRequestRecord): string {
  if (record.kind === 'retrieval') {
    return [
      '"""Playground에서 전송한 문서 관련도 요청을 다시 보낸다."""',
      ...PYTHON_SEND(record),
      'print("model:", result["model"], "score_mode:", result["score_mode"])',
      'for rank, item in enumerate(result["results"], 1):',
      '    print(f"rank={rank} index={item[\'index\']} score={item[\'score\']:.4f}")',
      '    print(item["document"])',
    ].join('\n') + '\n';
  }
  if (record.kind === 'embeddings') {
    return [
      '"""Playground에서 전송한 Embedding 요청을 Python 표준 라이브러리로 다시 보낸다."""',
      ...PYTHON_SEND(record),
      'for item in result["data"]:',
      '    vector = item["embedding"]',
      '    print(f"index={item[\'index\']} dimensions={len(vector)} preview={vector[:4]}")',
      'print("usage:", json.dumps(result.get("usage")))',
    ].join('\n') + '\n';
  }
  return [
    '"""Playground에서 전송한 Risk 요청을 다시 보내고 신호를 해석한다."""',
    ...PYTHON_SEND(record),
    RISK_RULE,
    'complete = result["status"] == "completed" and result["assessment_complete"] is True',
    'sources = (',
    '    {item.get("source_model") for item in result["categories"]}',
    '    | {item.get("source") for item in result["system_signals"]}',
    ')',
    'detectors = sorted(source for source in sources if isinstance(source, str))',
    'print("executed detectors:", ", ".join(detectors) or "unknown")',
    'if result["risk_detected"]:',
    '    for category in result["categories"]:',
    '        if category["detected"]:',
    '            print(f"signal {category[\'code\']} {category.get(\'label\')} count={category.get(\'span_count\')}")',
    'if not complete or result["system_signal_detected"]:',
    '    print("assessment incomplete: do not treat as no-signal", file=sys.stderr)',
    '    sys.exit(2)',
    'if not result["risk_detected"]:',
    '    print("no risk signal from the executed detectors")',
    `# ${POLICY_NOTE}`,
  ].join('\n') + '\n';
}

function javascriptScript(record: PublicRequestRecord): string {
  const send = [
    `const requestJson = ${stringLiteral(record.requestJson)};`,
    "const gateway = (process.env.GATEWAY_URL ?? 'http://127.0.0.1:9600').replace(/\\/+$/, '');",
    "const headers = { 'Content-Type': 'application/json', Accept: 'application/json' };",
    'if (process.env.API_KEY) headers.Authorization = `Bearer ${process.env.API_KEY}`;',
    'let response;',
    'try {',
    `  response = await fetch(gateway + ${stringLiteral(record.path)}, { method: 'POST', headers, body: requestJson });`,
    '} catch (error) {',
    '  console.error(`Gateway connection failed: ${error.cause?.message ?? error.message}`);',
    '  process.exit(1);',
    '}',
    'const text = await response.text();',
    'if (!response.ok) {',
    '  console.error(text);',
    '  process.exit(1);',
    '}',
    'const result = JSON.parse(text);',
    '',
  ];
  if (record.kind === 'retrieval') {
    return [
      '// Playground에서 전송한 문서 관련도 요청을 다시 보낸다. Node.js 18+, .mjs로 저장해 실행한다.',
      ...send,
      "console.log('model:', result.model, 'score_mode:', result.score_mode);",
      'for (const [rank, item] of result.results.entries()) {',
      '  console.log(`rank=${rank + 1} index=${item.index} score=${item.score.toFixed(4)}`);',
      '  console.log(item.document);',
      '}',
    ].join('\n') + '\n';
  }
  if (record.kind === 'embeddings') {
    return [
      '// Playground에서 전송한 Embedding 요청을 다시 보낸다. Node.js 18+, .mjs로 저장해 실행한다.',
      ...send,
      'for (const item of result.data) {',
      '  console.log(`index=${item.index} dimensions=${item.embedding.length} preview=${JSON.stringify(item.embedding.slice(0, 4))}`);',
      '}',
      "console.log('usage:', JSON.stringify(result.usage ?? null));",
    ].join('\n') + '\n';
  }
  return [
    '// Playground에서 전송한 Risk 요청을 다시 보내고 신호를 해석한다. Node.js 18+, .mjs로 저장해 실행한다.',
    ...send,
    RISK_RULE.replace(/^#/, '//'),
    "const complete = result.status === 'completed' && result.assessment_complete === true;",
    'const detectors = [...new Set([',
    '  ...result.categories.map((item) => item.source_model),',
    '  ...result.system_signals.map((item) => item.source),',
    "].filter((source) => typeof source === 'string'))].sort();",
    "console.log('executed detectors:', detectors.join(', ') || 'unknown');",
    'if (result.risk_detected) {',
    '  for (const category of result.categories.filter((item) => item.detected)) {',
    '    console.log(`signal ${category.code} ${category.label} count=${category.span_count}`);',
    '  }',
    '}',
    'if (!complete || result.system_signal_detected) {',
    "  console.error('assessment incomplete: do not treat as no-signal');",
    '  process.exit(2);',
    '}',
    'if (!result.risk_detected) {',
    "  console.log('no risk signal from the executed detectors');",
    '}',
    `// ${POLICY_NOTE}`,
  ].join('\n') + '\n';
}

function pythonSdkScript(record: PublicRequestRecord): string {
  return [
    '"""애플리케이션 통합 예시: pip install openai. 정확한 재현은 Python (HTTP) 예제를 사용한다."""',
    'import json',
    'import os',
    '',
    'from openai import OpenAI',
    '',
    `body = json.loads(${stringLiteral(record.requestJson)})`,
    '# SDK keyword argument가 아닌 Gateway 확장 필드는 extra_body로 전달한다.',
    'standard = {"model", "input", "dimensions", "encoding_format", "user"}',
    'kwargs = {key: value for key, value in body.items() if key in standard}',
    'extras = {key: value for key, value in body.items() if key not in standard}',
    'if extras:',
    '    kwargs["extra_body"] = extras',
    'client = OpenAI(',
    '    base_url=os.environ.get("GATEWAY_URL", "http://127.0.0.1:9600").rstrip("/") + "/v1",',
    '    api_key=os.environ.get("API_KEY") or "local-open",',
    ')',
    'result = client.embeddings.create(**kwargs)',
    'for item in result.data:',
    '    print(f"index={item.index} dimensions={len(item.embedding)}")',
  ].join('\n') + '\n';
}

export function publicExportSource(record: PublicRequestRecord, language: PublicExportLanguage): string {
  validatedRecord(record);
  if (!PUBLIC_EXPORT_LANGUAGES[record.kind].some((item) => item.id === language)) {
    throw new Error('이 요청에 제공하지 않는 예제입니다.');
  }
  if (language === 'curl') return curlScript(record);
  if (language === 'python') return pythonScript(record);
  if (language === 'javascript') return javascriptScript(record);
  return pythonSdkScript(record);
}

export function prettyRequestJson(record: PublicRequestRecord): string {
  return JSON.stringify(JSON.parse(record.requestJson), null, 2);
}
