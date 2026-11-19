# 외부 사용자 접속

운영자가 서버의 Tailscale 연결을 준비하면 팀원은 **가입·앱 설치 없이 URL과 사용자 API 키**로 Playground와 API를 이용한다. 서버 운영자의 Tailscale 등록은 필요하다.

## 사용자

1. 운영자가 전달한 `https://<서버 이름>.ts.net:8443/playground/`를 연다.
2. **사용자 API 키**를 입력한다. 관리자 키는 사용하지 않는다.
3. Chat·Embedding·Retrieval·Risk 중 제공되는 기능을 이용한다. 실제 요청 가능 범위는 활성 모델과 서버 자원에 따른다.

API 연동 시 Base URL은 `https://<서버 이름>.ts.net:8443/v1`이다. 요청 예제의 `GATEWAY_URL`은 `/v1`을 뺀 주소를 사용한다. Playground의 **코드로 사용하기**에도 현재 접속 주소가 반영된다.

키와 대화는 브라우저 탭 메모리에만 보관하며 새로고침하면 지워진다. 키를 URL에 넣거나 관리자 키를 팀원에게 공유하지 않는다. `401`은 키 확인, `429`는 요청량·동시 요청 상한, 모델 사용 불가는 서버 운영자에게 문의한다.

## 서버 준비

Ubuntu/Linux 서버 기준이다. 운영자는 [Tailscale 설치](https://tailscale.com/docs/install/linux)·서버 등록, Tailnet HTTPS와 [Funnel 사용 권한](https://tailscale.com/docs/features/tailscale-funnel)을 최초 한 번 준비한다. 접속하는 팀원은 이 절차가 필요 없다.

```bash
sudo apt-get install nginx
sudo tailscale up
sudo tailscale set --operator="$USER"

make up TARGET=linux-nvidia-dynamic
make status
```

운영 명령을 실행하는 사용자에게 Tailscale 설정 권한을 부여한다. HTTPS·Funnel 승인이 필요하면 Tailnet 관리자 화면에서 완료한 뒤 `make up`을 다시 실행한다. 기본 명령은 Gateway의 `ACCESS=edge` 인증과 사용자 Funnel을 준비한다. 기존 `.env`의 API 키·관리자 키·모델·포트는 보존한다. 기존 로컬 배포도 인증이 활성화되므로 Console에는 관리자 키가 필요하다.

`make up`은 Nginx·Tailscale을 전역 설치하거나 계정 로그인을 대신하지 않는다. 준비되지 않았다면 **Core·모델은 실행하고 `External UNAVAILABLE`에 이유를 표시**한다. `External READY`는 로컬 Proxy의 인증·차단과 Funnel 설정 확인 결과이며, 다른 인터넷 기기에서의 실제 접속까지 보장하는 표시는 아니다.

완료 출력:

```text
[platform] External READY  https://<서버 이름>.ts.net:8443/playground/
[platform] API Base URL   https://<서버 이름>.ts.net:8443/v1 · 사용자 API 키 필요
```

### 관리자 접속

관리자 443은 기존 비공개 Tailscale Serve를 사용한다. 아래 명령의 `9400`은 `make status`의 실제 Gateway 포트로 바꾼다. 기존 443 설정이 이 플랫폼 소유일 때 적용한다.

```bash
tailscale serve --bg --https=443 http://127.0.0.1:9400
```

관리자 Grants와 Admin Key는 [관리자 접속 가이드](remote-access.md#external-admin)를 따른다. 사용자 Funnel 8443은 Tailnet 회원 여부와 무관하게 인터넷에서 연결되며 Gateway API 키가 사용자 인증을 담당한다.

## 공개 범위와 제한

| 진입점 | 제공 범위 |
|---|---|
| 비공개 443 | 관리자 Console·운영 API. Tailnet 권한과 Admin Key 필요 |
| 공개 8443 | `/playground/`와 정적 자원·인증된 기능 조회, 명시적으로 허용한 사용자 API |
| 사용자 API | 모델 조회, Chat Completions, Responses, Embedding, Retrieval Score·Rerank, Risk 평가 |

공개 Proxy는 `/admin/*`, `/internal/*`, `/ready`, `/metrics`, `/docs`와 기타 경로를 차단한다. 사용자 화면도 운영 API를 조회하지 않는다. 서버·GPU·모델 변경 권한은 관리자에게 있다.

Nginx는 모든 이용자가 공유하는 **초당 10개 요청·순간 추가 40개, 동시 추론 요청 4개, JSON 본문 64 MiB** 상한을 적용한다. SSE 응답 버퍼링은 끄고, upstream 읽기 타임아웃은 300초로 둔다. 사용자별 요금·할당량·역할 관리는 제공하지 않는다. 값은 [공개 Proxy 설정](../../ops/access/public-playground.nginx.conf)이 소유하며 실제 모델 한도는 Gateway가 판정한다.

키는 사용자마다 별도로 발급해 `API_KEYS`에 쉼표로 구분해 등록하고 `make up`으로 적용한다. 관리자 허용 목록은 `ADMIN_API_KEYS`다. `API_KEY`·`ADMIN_API_KEY`는 운영 도구용 클라이언트 별칭이며, 목록에서 빠진 별칭은 기동 시 첫 번째 활성 키로 맞춘다. 공개 공유에는 API·관리자 키가 서로 달라야 하며, 각 키는 32자 이상의 무작위 값을 사용한다. 짧거나 공유된 키는 공개 전에 거부한다. 접근 철회 시 해당 키를 목록에서 제거하고 `make up`으로 적용한다. 발급한 키를 로그·Git·스크린샷에 기록하지 않는다.

Funnel에는 대역폭 제한이 있으므로 큰 미디어 업로드 성능은 실제 환경에서 확인한다. TLS는 서버에서 종료되고 Funnel 중계는 내용을 복호화하지 않지만 트래픽은 외부 중계를 경유한다. [Funnel 동작·제약](https://tailscale.com/docs/features/tailscale-funnel)

## 상태·해제·복구

```bash
make status
make up SHARE=off   # 공개 해제, 현재 Gateway 인증 유지
make up SHARE=on    # edge 인증과 사용자 Funnel 다시 준비
make down          # 이 checkout의 Funnel 8443·Proxy를 먼저 종료
```

로컬 전용 첫 실행은 `make up ACCESS=local`이다. 기존 배포의 인증도 local로 바꿀 때에는 `make up ACCESS=local CONFIRM=access`로 표시된 변경을 적용한다. `SHARE` 선택은 `PUBLIC_ACCESS_ENABLED`에 보관된다. `ACCESS=private`도 공개 공유를 끄고 LAN/VPN 인증 구성을 사용한다.

Nginx는 `.runtime/public-access/`의 전용 설정·PID를 사용한다. Gateway 기본 대역에서는 `127.0.0.1:9480`, 9600 대역에서는 `127.0.0.1:9680`을 수신한다. 저장소의 포트 대역 설정을 따르며 Funnel의 외부 포트는 8443이다.

기존 수동 Team Nginx가 같은 Listener를 점유하거나 다른 Serve/Funnel이 8443을 사용하면 덮어쓰지 않는다. 해당 설정의 소유자가 기존 Listener를 해제한 뒤 다시 실행한다. 공유 설정이 외부에서 바뀌면 자동 삭제를 중단한다. `.runtime/public-access/owner.json`을 지워 소유권 검사를 우회하지 않는다.

`make down/reset/purge`는 이 checkout이 기록하고 현재 Handler와 일치하는 Funnel 8443만 해제한다. 비공개 관리자 443, 다른 서비스, Tailscale 계정·데몬은 운영자가 관리한다. Funnel 연결은 백그라운드로 유지되지만 재부팅 시 전용 Nginx·Gateway도 필요하므로 `make up`을 다시 실행한다.
