// 배포 포트·접근 주소는 빌드 시점 상수가 아니라 현재 Console의 접속 주소를 따른다.
// 내보낸 스크립트는 여전히 GATEWAY_URL로 실행 환경의 주소를 덮어쓸 수 있다.
export function withGatewayOrigin(source: string): string {
  const origin = globalThis.location?.origin;
  if (!origin) return source;
  const url = new URL(origin);
  if (!['http:', 'https:'].includes(url.protocol)) return source;
  // 직렬화된 요청 본문에 같은 문자열이 있어도 변경하면 안 된다.
  return source.split('\n').map((line) => /^(?:gateway_url=|gateway =|const gateway =|\s*base_url=|\s*baseURL:|기본 주소는 )/.test(line)
    ? line.replaceAll('http://127.0.0.1:9400', url.origin) : line).join('\n');
}
