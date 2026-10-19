# ADR-0051: Tailnet 경계와 팀원 API 전용 로컬 Proxy를 분리한다

## Status

Accepted

## Context

기존 `ACCESS=edge`는 Gateway를 Loopback에 유지하면서 API/Admin Bearer 인증을
활성화한다. 동일 Gateway에는 일반 API와 운영 API가 있으므로 Tailnet 구성원 전체가
443번 HTTPS에 접근하면 인증 키 구분과 별개로 관리 표면도 네트워크에 노출된다.
Tailnet Grants는 TCP 포트 권한을 소유하지만 HTTP 경로를 분리하지 않는다.

ADR-0045는 Host publication을 Gateway와 조건부 Grafana로 제한한다.
ADR-0039는 `make up`의 생명주기 수렴을 소유하며, Tailscale과 Nginx 같은 운영자 외부
소프트웨어의 배포를 암묵적으로 수행하지 않는다.

## Decision

1. 일반 배포 Access Profile은 기존 `local/private/edge`를 유지한다. 원격 VPN
   시나리오는 `ACCESS=edge`의 Loopback·인증 정책을 재사용한다.
2. Tailscale Serve 443은 관리자만 접근할 수 있는 Gateway 전체 진입점이다.
   Serve 8443은 `127.0.0.1:9480`에서 실행되는 팀원 API 전용 Nginx로 보낸다.
3. 팀원용 Nginx는 호스트 Loopback만 수신하고 고정 HTTP 메서드·경로만 Gateway에
   전달한다. 다른 모든 경로와 인코딩/접미 경로는 거부한다.
4. Tailnet 관리자가 사용자/기기 그룹 및 443·8443 포트별 Grants를 소유한다.
   모든 기존 Grants/ACL을 포함한 최종 권한의 합집합을 정책 테스트로 확인한다.
5. Gateway는 기존 API/Admin Key 인증의 유일한 Source of Truth를 유지한다.
   팀원에게 Admin Key를 배포하지 않으며, 사용자의 탈퇴는 Tailnet 접근과 API Key를
   모두 폐기해야 완료된다.
6. Nginx/Tailscale은 선택형 Host 운영 어댑터다. Compose 서비스 Registry와
   Host-published service 역할은 변경하지 않는다. `make up/down`이 외부 소프트웨어
   설치·삭제·기존 Serve 구성 초기화를 수행하지 않는다.
7. 사전 점검 도구는 로컬 `.env`를 canonical Access Profile 정책과 대조하고
   내부 서비스 인증·API 문서 노출·Loopback까지 읽기 전용으로 검증한다.
   실제 실행 중인 서비스와 Tailnet 상태는 별도 검증한다.
   Tailscale·Nginx 변경 명령은 운영자가 명시적으로 선택하게 한다.
8. 인터넷 공개를 위해 Funnel이나 공인 포트를 활성화하지 않는다. 공개 API 서비스의
   인증·요청량 보호·운영 경로 차단은 별도 정책 및 검증을 요구한다.

## Consequences

- 개인 관리자와 팀원이 같은 GPU Runtime을 안전하게 공동 이용할 수 있는 명시적 경계를 갖는다.
- Tailnet 사용자 자격, API Key, HTTP 경로 정책은 별개이며 서로 대체하지 않는다.
- Tailnet의 실제 Grants 적용과 외부 지역 접속·재부팅·GPU 추론은 운영자 환경에서만 증명된다.
- Linux Host에 Nginx/Tailscale 관리 책임과 업데이트·포트 충돌 검토가 추가된다.
- 정책 예제 및 Host Adapter는 제품 image의 새 서비스 또는 신규 Gateway 역할 시스템이 아니다.

## 검증

- Linux CI는 실제 Nginx로 API allowlist/메서드/인코딩 경로 차단을 검증한다.
- Python 계약 테스트는 기존 `ACCESS=edge`·Loopback·인증·키 분리 조건의 Fail-Closed 판정을 확인한다.
- [원격 접근 사용자 가이드](../guides/remote-access.md)의 실제 Tailnet/E2E 체크는
  CI 검증과 구분한다.

## Related

- ADR-0025, ADR-0039, ADR-0043, ADR-0045
- `configs/access_profiles.yaml`, `configs/auth_profiles.yaml`, `configs/services.yaml`
- `ops/access/team-api.nginx.conf`, `ops/access/tailnet-policy.example.hujson`
