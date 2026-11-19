# ADR-0067: 사용자 Playground·API는 공개 진입점과 일반 API 인증으로 제공한다

## Status

Accepted

ADR-0051의 인터넷 공개 제외 결정(8번)을 대체한다. 관리자 443과 사용자 진입점의 권한 분리 원칙은 유지한다.

## Context

Tailnet 등록을 모든 API 사용자에게 요구하면 외부 개발자와 브라우저 사용자의 접속 부담이 커진다. 기존 Playground는 일반 API를 호출하지만 관리자 Console의 인증·탐색에 묶여 있다.

## Decision

- Gateway는 별도 `/playground/` 진입점과 사용자 API 키로 보호된 최소 기능 조회를 제공한다. 기능은 Deployment Target에서 투영하고 현재 모델 계약은 `/v1/models`가 소유한다.
- 사용자 화면에는 관리자 세션·운영 API·Grafana 연결을 제공하지 않는다. API 키와 대화는 탭 메모리만 소유한다.
- 기본 `make up`은 `ACCESS=edge`와 공개 공유를 준비한다. 명시적 `ACCESS=local/private`는 공개 공유를 끈다. `SHARE=on/off`는 `PUBLIC_ACCESS_ENABLED`로 보관하며 외부 공유 상태는 플랫폼 준비 상태와 별도로 표시한다.
- 외부 공유는 사용자 전용 Loopback Nginx와 Funnel 8443을 사용한다. 서버 운영자의 Tailscale 등록·권한은 필요하며 이용자의 가입·앱 설치는 필요 없다. 관리자 Serve 443은 별도 비공개 진입점이다.
- Nginx는 명시적 경로·메서드만 허용하고 전체 요청량·동시 추론·본문 크기를 제한한다. Gateway가 사용자 API 인증과 모델 요청 판단을 소유한다. 사용자별 역할·할당량은 이 진입점의 계약이 아니다.
- 공개 전에 실행 중 Proxy의 운영 경로 차단·사용자 인증·화면을 확인한다. 도구·권한·Funnel 준비 실패는 공개를 중단하고 Core·모델의 실행을 유지한다.
- 공유 생명주기는 `.runtime/public-access/`에 기록한다. 설정 변경 전과 `down/reset/purge` 시 해당 checkout의 공개 경로를 먼저 해제한다. 현재 Funnel Handler와 기록된 대상이 다르면 자동 변경을 거부한다. 관리자 443·다른 Listener·Tailscale 계정은 운영자가 소유한다.

## Consequences

외부 사용자는 HTTPS 주소와 사용자 키만으로 브라우저·SDK를 사용할 수 있다. 운영자는 Nginx와 Tailscale을 준비해야 하며 Funnel의 중계·대역폭 제약을 받는다. 로컬 전용 배포는 명시적으로 선택할 수 있다. 외부 경로의 장애가 로컬 모델 실행 실패를 의미하지 않는다.
