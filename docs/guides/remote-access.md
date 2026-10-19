# 원격 접속 가이드

이 절차는 Linux GPU 서버 한 대에 이미 실행 중인 플랫폼을 **Tailnet 내부에서만** 제공한다.
개인 도메인이나 공인 포트포워딩이 필요하지 않다. 일반 인터넷 사용자에게 공개하는 절차가 아니다.

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
- Nginx와 Tailscale을 OS 운영자가 별도로 설치·업데이트한다. 프로젝트는 이들을 자동 설치하지 않는다.
- Nginx나 Tailscale의 기존 설정이 있다면 백업하고 포트 443·8443·9480 충돌을 확인한다.
- API Key와 Admin Key는 별도 값이다. 실제 키를 Git·Issue·Screenshot·Shell history에 기록하지 않는다.

```bash
make up ACCESS=edge
# 표시된 설정 변경 내용을 검토한 뒤 운영자가 명시적으로 적용
make up ACCESS=edge CONFIRM=access
make status
./.venv/bin/python scripts/access/remote_access.py preflight
./.venv/bin/python scripts/access/remote_access.py plan
```

사전 점검은 기존 엄격한 dotenv parser와 canonical Access Profile 판정을 재사용하며,
`edge`의 API 문서 노출 금지·내부 서비스 인증·Host Loopback·API/Admin 인증,
키 분리, Gateway 포트가 예제 설정과 맞지 않으면 실패한다.
`make up`이 준비한 `.venv`의 Python을 사용한다.
이 결과는 `.env` 설정만 검사하며 **실제로 실행 중인 Gateway의 bind 상태, Tailscale 정책 적용 여부를 증명하지 않는다.**
이 도구는 키·Tailnet 상태를 변경하지 않는다.

## 3. 팀원 API Proxy

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
Tailnet Admin Console의 Policy Editor에서
[정책 예제](../../ops/access/tailnet-policy.example.hujson)를 **실제 조직의 기존 Tailnet 전체 정책과 병합 검토**한다.

1. `operator@example.com`과 `teammate@example.com`을 실제 계정으로 바꾼다.
2. 서버는 관리자만 Tag를 부여할 수 있는 `tag:llm-server`로 등록한다.
3. 관리자 그룹은 `443`과 `8443`에, 팀원 그룹은 `8443`에만 접근을 허용한다.
   **두 그룹을 중복 배정하지 않는다.** 중복 소속이라면 관리자 허용이 우선 적용될 수 있다.
4. 기존 모든 접근 허용 Grants/ACL 및 Subnet Router/Exit Node 경로가 이를 우회하지 않는지 검토한다.
5. Policy Editor에서 `tests`가 통과해야 한다. ACL/Grants는 허용의 합집합이므로
   더 넓은 기존 규칙이 있으면 단순한 새 규칙 추가로 접근을 제한할 수 없다.

[공식 Policy 문법](https://tailscale.com/docs/reference/syntax/policy-file) ·
[Grants](https://tailscale.com/docs/reference/syntax/grants)

## 5. HTTPS 접속

Tailscale 버전에서 Serve HTTPS 포트 및 `--bg` 동작을 확인한다.
**기존 Serve 및 Funnel 설정을 먼저 확인하고, 충돌이 없을 때만** 아래 명령을 실행한다.

```bash
tailscale serve status
tailscale funnel status
tailscale serve --bg --https=443 http://127.0.0.1:9400
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

서로 다른 **관리자 기기와 일반 팀원 기기**에서 검증한다.

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

## 7. 상태·해제·복구

`status` 명령은 Tailscale이 보고하는 상태를 **화면에 표시하는 조회 명령**이다.
Serve 443/8443의 정확한 Target, Funnel 비활성, 실제 사용자별 Grants는
운영자가 별도로 확인해야 한다. 명령의 종료 코드 0만으로 인터넷 비공개나 정책
안전성을 확정하지 않는다.

```bash
./.venv/bin/python scripts/access/remote_access.py status
# 해당 두 Listener를 이 플랫폼 전용으로 구성한 경우에만 선택적으로 해제
tailscale serve --https=8443 off
tailscale serve --https=443 off
tailscale serve status
```

기존 Serve 구성을 공유한다면 해당 포트의 소유권을 먼저 확인한다.
Nginx 또는 Tailscale 설치·설정 변경은 기존 `make down`이나 `make reset`이 소유하지 않는다.
Nginx의 예제 Config 제거/재적용은 OS 운영자가 명시적으로 수행한다.

## 8. 검증 범위

`make check`는 API/Auth/Compose와 설정 계약을 확인한다. Linux CI는 실제
Nginx로 허용·거부·인코딩 경로를 검증한다. Tailnet 그룹 초대/태그 부여/정책
적용/재부팅/지역 간 실제 추론은 GitHub-hosted CI에서 증명할 수 없으므로
별도의 운영자 E2E 승인 후 실사용 완료를 선언한다.

**향후 공개 인터넷용 HTTPS API는 별도 배포 정책·인증/사용량 제한·보안 검증이 필요하다.
이 가이드는 공개 진입점이나 Funnel을 활성화하지 않는다.**
