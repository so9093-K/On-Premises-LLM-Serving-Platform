# 원격 접속 가이드

이 문서의 **Host 설치·운영 명령은 Ubuntu/Linux GPU 서버**에서 이미 실행 중인 플랫폼을 Tailnet 내부에 제공하는 절차다.
Ubuntu 또는 macOS의 **외부 사용자 기기**에서는 Tailscale과 브라우저·SDK로 접속할 수 있다. 그러나 **macOS 자체를 원격 접속 Host로 운영하는 Tailscale Serve·팀원 Proxy 구성은 이 문서와 CI에서 검증되지 않았다.** Ubuntu의 `apt`, `systemctl`, Nginx 설정 경로를 macOS Host 명령으로 사용하지 않는다.
개인 도메인이나 공인 포트포워딩이 필요하지 않으며, 일반 인터넷 공개 절차가 아니다.

## 외부 기기에서 이용하기

**외부 사용자는 이 프로젝트 저장소를 내려받거나 서버의 `make` 명령을 실행하지 않는다.**
접속을 위해 필요한 Tailscale 권한과 주소·인증 정보는 서버 운영자가 미리 준비한다.
아래 주소는 형식 예시이며 실제 주소는 운영자에게 확인한다.

<a id="external-admin"></a>

### 외부 관리자: Control Plane 사용

1. 운영자가 지정한 Tailscale 계정으로 **본인의 기기에서** Tailscale 앱에 로그인하고 연결한다.
2. 운영자가 알려 준 `https://<실제-서버-tailnet-이름>/admin/console/` 주소를 브라우저에서 연다(HTTPS 443).
3. 관리자 인증 화면이 나오면 **Admin Key**를 입력한다. Playground에서 모델을 호출하려면 별도의 **사용자 API Key**가 필요할 수 있다.
4. **운영 개요**에서 상태를 확인하고 필요한 Control Plane 기능을 사용한다. 실제 Runtime 제어 범위는 배포 Target에 따라 다르다.

Tailscale 연결이 되더라도 **443 접근 권한**이 없으면 접속할 수 없다. 연결 실패는 Tailscale 상태·주소·관리자 Grants를, `401`은 Admin Key를 운영자에게 확인한다.
Admin Key를 팀원 API 사용자와 공유하지 않는다.

<a id="external-api"></a>

### 외부 API 사용자: 모델 호출

1. 본인에게 허용된 Tailscale 계정으로 연결한다. **HTTPS 8443 접근 권한**은 운영자가 부여한다.
2. 운영자로부터 **API Base URL**(형식 예: `https://<실제-서버-tailnet-이름>:8443`), **사용자 API Key**, 모델 별칭(일반적으로 `local-main`)을 전달받는다. 키는 별도의 안전한 수단으로 전달받는다.
3. 본인의 앱·SDK에서 해당 주소와 Key를 설정한 뒤 `GET /v1/models`로 연결을 확인한다. 실제 호출 예제는 [API 연동 가이드](api-integration.md#remote-api)에 있다.

팀원에게 제공되는 것은 **허용된 모델 API**이며, 관리자 Control Plane이나 웹 Playground가 아니다.
`/admin/*`, `/metrics` 등은 팀원 API 포트에서 차단된다. `401`이면 사용자 API Key, 연결 실패이면 주소·Tailscale/8443 Grants, `404`이면 허용 API 경로인지 운영자에게 확인한다.
외부 기기에서 서버 Git 저장소, Docker, Nginx, `make` 명령은 필요하지 않다.

---

<a id="operator-setup"></a>

## 서버 운영자: 접속 환경 구성

이하 설정 절차는 **Ubuntu/Linux GPU 서버의 Host 운영자만** 수행한다. 개인 관리자만 원격으로 사용하는 경우 **HTTPS 443만** 구성한다.
팀원에게 API를 제공할 때에만 **Nginx 9480 및 Tailscale HTTPS 8443**을 추가한다.
공유기 포트포워딩·Funnel을 통한 일반 인터넷 공개는 지원 범위가 아니다.
`ACCESS=edge`는 Gateway Loopback·인증 설정이며 Tailscale 연결을 자동 구성하지 않는다.

## 1. 접근 경계

| 계층 | 소유자 | 역할 |
|---|---|---|
| `ACCESS=edge` | 기존 플랫폼 | Gateway·Grafana Loopback, API/Admin 별도 Bearer 인증 |
| Tailscale Serve | 서버 운영자 | Tailnet HTTPS 443(관리자), 8443(팀원) |
| Tailnet Grants | Tailnet 관리자 | 사용자/기기별 TCP 포트 접근 허용·거부 |
| Team Nginx | 이 저장소의 선택형 host adapter | 127.0.0.1:9480, 공개 API 경로·메서드만 전달 |
| Gateway | 기존 플랫폼 | API Key·Admin Key 판정, 모델 요청 및 자원 Gate |
| 모델 Runtime | 기존 플랫폼 | Compose 내부에서만 실행 |

**주의:** Tailscale은 운영자 계정 인증을 대체하지 않는다. Tailscale Grants는 HTTP 경로와 Key 권한을 판정하지 않는다.
Gateway도 Tailnet 사용자별 Role·Quota를 제공하지 않는다. 팀원에게 Admin Key를 배포하지 않는다.
사내망의 다른 계정이 기존 Tailscale allow-all 정책으로 관리자 포트에 접근할 수 없도록 Tailnet 전체 정책을 검토해야 한다.

## 2. 설치 준비

- Linux 서버에 기존 `make up`이 준비돼 있고 Gateway가 동작해야 한다.
- `make up ACCESS=edge`는 기존 설정 변경 계획만 보여 준다.
  계획 검토 후에만 `make up ACCESS=edge CONFIRM=access`를 실행한다.
- `make status`, `make auth-status`로 상태를 확인한다.
- Tailscale은 서버 운영자가 설치·업데이트한다. **팀원 API를 공유할 때만** Nginx를 별도로 설치·관리한다. 프로젝트는 두 소프트웨어를 자동 설치하지 않는다.
- 기존 Tailscale Serve/Funnel 설정을 확인하고 관리자용 HTTPS 443 충돌을 검토한다. **팀원 API를 공유할 때만** Nginx 9480·HTTPS 8443 충돌도 확인한다.
- API Key와 Admin Key는 별도 값이다. 실제 키를 Git·Issue·Screenshot·Shell history에 기록하지 않는다.

```bash
make up ACCESS=edge
# 표시된 설정 변경 내용을 검토한 뒤 운영자가 명시적으로 적용
make up ACCESS=edge CONFIRM=access
make status
./.venv/bin/python scripts/access/remote_access.py preflight
```

사전 점검은 기존 엄격한 dotenv parser와 canonical Access Profile 판정을 재사용하며,
`edge`의 API 문서 노출 금지·내부 서비스 인증·Host Loopback·API/Admin 인증,
키 분리, Gateway 포트가 예제 설정과 맞지 않으면 실패한다.
`make up`이 준비한 `.venv`의 Python을 사용한다.
이 결과는 `.env` 설정만 검사하며 **실제로 실행 중인 Gateway의 bind 상태, Tailscale 정책 적용 여부를 증명하지 않는다.**
이 도구는 키·Tailnet 상태를 변경하지 않는다.

## 3. 팀원 API Proxy (팀원 공유 시에만)

서버에 Nginx를 설치한다(예: Ubuntu `sudo apt-get install nginx`).
설정을 검토한 뒤 Nginx의 `http` 컨텍스트에서 로드되는 경로로 복사한다.

```bash
sudo cp ops/access/team-api.nginx.conf /etc/nginx/conf.d/llm-team-api.conf
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
```

설정은 **127.0.0.1:9480만 수신**하며 Gateway **127.0.0.1:9400**으로 연결한다.
기존 호스트·포트와 일치하지 않으면 위 예제를 그대로 적용하지 말고 별도 검토한다.
새 Nginx Config를 `server` 블록으로 포함하도록 작성했으므로 다른 서비스를 덮어쓰는 전체 `nginx.conf`가 아니다.

허용 범위: `GET /v1/models`, `POST /v1/chat/completions`,
`POST /v1/responses`, `POST /v1/embeddings`.
그 외 URL·메서드는 거부한다. Path 인코딩·추가 접미 경로도 우회가 되지 않아야 한다.
팀원 API 인증은 원래 Gateway의 `API_KEYS`를 그대로 사용한다. Nginx는 Admin Key를 인증하지 않는다.
SSE를 위해 Proxy Response Buffering을 끈다. 요청 본문 크기와 타임아웃 제한은
운영 중 Gateway의 실제 계약과 함께 검토한다.

Proxy만 기동한 후 먼저 로컬에서 다음 조건을 확인한다.

- 유효한 **API Key**로 `127.0.0.1:9480/v1/models` 요청은 성공한다(모델이 준비된 경우).
- Key가 없으면 `401`이 반환된다.
- `/admin/console/`, `/admin/*`, `/ready`, `/metrics`, `/internal/*`은 차단된다.
- `127.0.0.1:9400`과 `127.0.0.1:9480`은 LAN 인터페이스에 수신하지 않는다.
- 팀원 진입점에서 `/v1/*` 전체를 포괄 허용하지 않는다.

## 4. Tailnet 접근 정책

운영자가 Tailscale을 설치하고 `tailscale up`으로 서버를 Tailnet에 등록한다.
Tailscale Serve의 HTTPS를 사용하려면 **Tailnet HTTPS 인증서 기능이 활성화되어야** 한다.
기능이 꺼져 있으면 Serve가 안내하는 관리자 동의 절차를 완료한 뒤 설정을 확인한다.

Tailnet Admin Console의 Policy Editor에서 기존 Grants/ACL 전체를 확인한다.
[정책 예제](../../ops/access/tailnet-policy.example.hujson)는 **팀원 API까지 공유하는 경우의 예제**이며,
개인 관리자 접속에 필요하지 않은 8443 권한을 그대로 복사해서는 안 된다.

1. 서버는 관리자만 Tag를 부여할 수 있는 `tag:llm-server`로 등록한다.
2. **개인 관리자만 접속:** 해당 관리자에게 서버의 `tcp:443`만 허용한다.
   팀원 그룹·`tcp:8443` 허용 규칙과 Nginx는 필요하지 않다.
3. **팀원 API까지 공유:** 예제의 `operator@example.com`과 `teammate@example.com`을
   실제 계정으로 바꾸고, 관리자 그룹에 `tcp:443`·`tcp:8443`,
   팀원 그룹에는 `tcp:8443`만 허용한다. **두 그룹을 중복 배정하지 않는다.**
4. 어느 경우든 기존 허용 Grants/ACL 및 Subnet Router/Exit Node 경로가
   의도한 포트 제한을 우회하지 않는지 검토한다.
5. 실제로 적용할 전체 정책에 대한 Policy Editor `tests`를 통과시킨다.
   기존 허용 규칙까지 합산하므로 규칙을 추가하는 것만으로 접근이 제한되지는 않는다.
   팀원 공유 시에는 팀원 계정에서 `tcp:443` 거부도 확인한다.

[공식 Policy 문법](https://tailscale.com/docs/reference/syntax/policy-file) ·
[Grants](https://tailscale.com/docs/reference/syntax/grants)

## 5. HTTPS 접속

개인 관리자 접속만 사용하는 경우에는 **443만 적용**한다. 다음 예제는 서버 운영자가 기존 Serve 설정의 소유권과 충돌을 확인한 뒤 수행한다.

Tailscale 버전에서 Serve HTTPS 포트 및 `--bg` 동작을 확인한다.
**기존 Serve 및 Funnel 설정을 먼저 확인하고, 충돌이 없을 때만** 아래 명령을 실행한다.

```bash
tailscale serve status
tailscale funnel status
tailscale serve --bg --https=443 http://127.0.0.1:9400
tailscale serve status
```

팀원 API를 공유할 때만 **3절의 Nginx를 먼저 검증하고**, HTTPS 8443을 추가한다.

```bash
tailscale serve --bg --https=8443 http://127.0.0.1:9480
tailscale serve status
```

`--bg` Serve는 Tailscale 데몬이 정상 복구되면 재부팅 뒤에도 계속 제공될 수 있다.
시스템 부팅 시 Nginx와 Gateway 서비스도 준비돼 있어야 한다.
`tailscale serve reset`은 다른 Serve 구성을 삭제할 수 있으므로 사용하지 않는다.
`tailscale funnel`은 인터넷 공개 기능이므로 사용하지 않는다.

관리자: `https://<실제-서버-tailnet-이름>/admin/console/` (443)
팀원: `https://<실제-서버-tailnet-이름>:8443/v1/models`

## 6. 접근 검증·권한 철회

관리자 기기에서 HTTPS 443과 Admin Key를 실제로 확인한다. 팀원 공유를 활성화한 경우에는 **별도의 팀원 기기**에서 아래 8443 허용 및 443 차단까지 검증한다.

| 시나리오 | 기대값 |
|---|---|
| 관리자 443 → Console, Admin Key | 인증 후 관리자 기능 사용 |
| 팀원 8443 → /v1/models + API Key | 성공 |
| 팀원 8443 → POST Chat | 실제 모델 준비 시 응답 수신 |
| 팀원 443 → 관리자 HTTPS | 네트워크 연결 차단 |
| 팀원 8443 → /admin/* | 404 등 거부 |
| 팀원 → Gateway 9400 · Grafana 9411 · SSH 22 | 차단 |
| Team API Key 없이 허용 API 호출 | 401 |
| Team Key 제거 후 기존 키로 요청 | 401 |
| 서버 재부팅 | Serve·Nginx·Gateway 재기동 및 동일 차단 계약 유지 |
| 인터넷/Tailscale 미가입 기기 | Serve URL 접근 불가; Funnel 미설정 |

권한 철회 시 팀원 Tailnet 자격과 기기 접근을 차단하고, `API_KEYS`에서 팀원에게
발급했던 Key를 제거·회전한다. `API_KEY`와 `ADMIN_API_KEY` 단일 값이 설정돼
있다면 각각 현재 활성 `API_KEYS` 및 `ADMIN_API_KEYS` 목록에 포함돼야 한다.
운영자 명령과 실제 Gateway가 서로 다른 키를 참조하지 않도록 검증한다. 운영자 가이드에 따라 서비스를 안전하게 재수렴한 뒤
이전 키로 요청이 거부되는지 확인한다. **네트워크 차단만으로 API 키 폐기가 완료되지 않는다.**

## 7. 상태·안전한 해제·복구

원격 접속은 플랫폼 바깥의 **선택형 Host 구성**이다. `make down`, `make reset`, `make purge`는 Tailscale·Nginx·Tailnet Grants를 소유하거나 자동 삭제하지 않는다. 아래 해제는 **이 플랫폼이 전용으로 소유한 항목**만 대상으로 하며, 공유 Host 구성과 다른 서비스는 보존한다.

### 7.1 현재 구성과 소유권 확인

```bash
./.venv/bin/python scripts/access/remote_access.py status
tailscale serve status
tailscale funnel status
```

`status`는 Tailscale 명령 결과를 조회할 뿐이다. 반환 코드 0만으로 실제 Serve Target, Funnel 비활성, 사용자별 Grants, 원격 연결 성공이나 안전성을 증명하지 않는다. 운영자는 **443이 이 플랫폼의 관리자 Gateway(127.0.0.1:9400), 8443이 팀원 Proxy(127.0.0.1:9480)에 속하는지** 기존 Serve 설정과 함께 확인한다. 각 포트를 다른 서비스가 사용한다면 해제하지 않는다.

### 7.2 이 플랫폼의 Serve Listener만 해제

팀원 API 공유를 끝낼 때는 **이 플랫폼 전용 8443 Listener**만 해제한다. 관리자의 원격 접속도 끝내는 경우에만 **이 플랫폼 전용 443 Listener**를 해제한다.

```bash
# 대상 포트와 기존 Serve 설정의 소유권을 확인한 뒤, 필요한 행만 실행
tailscale serve --https=8443 off
tailscale serve --https=443 off
tailscale serve status
```

`tailscale serve reset`은 다른 Serve 구성을 지울 수 있으므로 사용하지 않는다. `tailscale down`, Tailscale 앱 제거 또는 Funnel 변경도 이 기능 해제 과정에서 자동 수행하지 않는다. 외부 관리자·팀원 기기에서 이전 URL 접근이 차단됐는지 별도로 확인한다.

### 7.3 팀원 전용 Nginx 구성만 정리 (Ubuntu/Linux)

팀원 API를 제공하면서 이 가이드대로 **전용 파일 `/etc/nginx/conf.d/llm-team-api.conf`을 복사한 경우에 한해**, 해당 파일의 내용을 먼저 확인하고 다른 설정에서 참조하지 않는지 검토한 후 정리한다. 팀원 공유 기능을 계속 사용하거나 파일 소유권이 불명확하면 제거하지 않는다.

```bash
# 파일이 이 플랫폼 전용임을 확인한 후 운영자가 직접 실행
sudo rm -- /etc/nginx/conf.d/llm-team-api.conf
sudo nginx -t
# 검증 성공 시에만 기존 Nginx 서비스를 reload
sudo systemctl reload nginx
```

`nginx -t`가 실패하면 reload를 진행하지 않고 해당 파일을 복구해 원인을 확인한다. 공유 Nginx 패키지·서비스 전체를 중지하거나 삭제하지 않는다. macOS Host에는 이 Ubuntu 명령을 적용하지 않는다.

### 7.4 Tailnet 권한 및 인증 키 정리

- Tailnet 관리자는 최종 Grants/ACL 전체를 확인한 뒤 **이 플랫폼을 위해 추가한 허용 규칙·그룹·태그만** 조정한다. 다른 서비스에서 쓰는 그룹·Tag나 사용자 Tailnet 계정을 무조건 삭제하지 않는다. 팀원 443 차단 등 의도한 거부 정책을 다시 검증한다.
- 팀원 전용으로 발급된 API Key는 `API_KEYS`에서 폐기하고, 설정된 `API_KEY` 단일 값과 불일치가 생기지 않도록 정규 설정 변경 절차로 반영한다. **로컬 앱 등에서 공유 중인 키는 원격 기능 해제만으로 무조건 폐기하지 않으며**, 사용처 확인 후 필요하면 교체한다.
- 관리자 원격 접속을 끝내더라도 로컬 운영에 필요한 Admin Key는 자동으로 폐기하지 않는다. 공유 또는 유출된 키의 회전은 별도 인증 변경으로 처리한다. **이전 키로의 실제 요청 거부**를 검증한다.

### 7.5 로컬 사용 유지 및 복구 검증

원격 접속이 해제돼도 Gateway·Control Plane·Main Runtime은 그대로 사용할 수 있어야 한다. `ACCESS=edge`에서 로컬 `ACCESS=local`로 되돌릴 필요가 있는 경우에만 기존 `make up`의 **변경 계획 → 명시적 확인** 절차를 사용한다. 접근 프로필을 원격 기능 해제와 묶어 자동 변경하지 않는다.

```bash
# 로컬 Profile 복귀가 필요한 경우에만, 표시된 변경 계획 검토 후 적용
make up ACCESS=local
make up ACCESS=local CONFIRM=access
make status
```

`make status`만으로 충분하지 않으므로 로컬 Console 및 `GET /v1/models`를 확인하고, Main Runtime이 준비된 경우 실제 Chat 응답도 확인한다. 실환경에서 **원격 URL 차단·로컬 기능 유지·다른 Host 서비스 보존**을 확인해야 해제가 완료된다.

## 8. 검증 범위

`make check`는 API/Auth/Compose와 설정 계약을 확인한다. Linux CI는 실제
Nginx로 허용·거부·인코딩 경로를 검증한다. Tailnet 그룹 초대/태그 부여/정책
적용/재부팅/지역 간 실제 추론은 GitHub-hosted CI에서 증명할 수 없으므로
별도의 운영자 E2E 승인 후 실사용 완료를 선언한다.

**향후 공개 인터넷용 HTTPS API는 별도 배포 정책·인증/사용량 제한·보안 검증이 필요하다.
이 가이드는 공개 진입점이나 Funnel을 활성화하지 않는다.**
