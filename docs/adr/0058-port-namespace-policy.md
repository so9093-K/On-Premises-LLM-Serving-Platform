# ADR-0058: 프로젝트 Port Namespace를 고정 Offset으로 관리한다

## Status

Accepted. 기본 대역과 이관 절차는 [ADR-0059](0059-explicit-port-migration-and-cache-preservation.md)로 보완됐다.
아래 96xx 이관 설명은 최초 결정 당시의 기록이다. 현재 설정은 `configs/services.yaml`을 따른다.

## Context

기존 94xx 정책은 여러 Runtime·Compose·Nginx·문서와 검증 코드에 포트 숫자가 분산되어 있었다. 대역 이동 시 누락될 위험이 있고, 모델 서비스의 배치도 역할 순서를 충분히 반영하지 못했다.

## Decision

1. `configs/services.yaml`의 `port_namespace.base`와 `offsets`가 프로젝트 관리 포트의 권위다. 서비스별 구체적인 내부·Host 포트와 소비자 설정은 이 정책과 일치해야 한다.
2. 최초 96xx 이관에 한해 Offset을 재정리한다. Gateway(+0), Main(+1), General Embedding(+2), Korean Embedding(+3), Prompt Detector(+4), Risk(+5), Grafana Host(+10), MLX Metrics(+16), 팀원 API Nginx(+80)를 사용한다. 이후 서비스 삭제·추가 시 기존 Offset은 자동 압축하지 않는다.
3. `make ports BASE=<대역>`가 변경 계획을 보여 주고 승인 후 프로젝트 소유 설정을 이관한다. 실제 실행 중 서비스 반영은 `make up`이 맡는다.
4. Grafana 컨테이너 3000, Prometheus 9090, DCGM exporter 내부 9400, Tailscale Serve HTTPS 443/8443, 외부 Main Runtime 등 프로젝트가 소유하지 않는 포트는 변경하지 않는다.
5. ADR-0045의 Host 공개 경계와 ADR-0051의 선택형 Nginx·Tailscale 소유권은 유지한다. 운영자가 지정한 개별 Host 포트, Host 방화벽, Tailnet 정책은 무조건 덮어쓰지 않는다.

## Consequences

운영자는 단일 명령으로 Port Namespace를 변경하고 검증할 수 있다. 이 명령은 체크아웃 소스와 생성 파일을 갱신하는 Maintainer 도구이며, Source/Console 빌드 및 정적 검증을 위한 개발 도구가 필요하다. 포트 변경은 클라이언트 URL과 프로세스 가용성에 영향을 줄 수 있으므로 운영자는 변경 계획을 확인하고 `make up`으로 재수렴한다. 외부 Host 프록시는 해당 운영자가 별도 적용한다.

## Operational impact

```bash
make ports BASE=9600
make up
make status
```

비대화형 환경은 `YES=1`로 확인만 생략한다. 포트·생성 산출물 검증은 계속 실행한다.

## Migration notes

94xx를 사용하던 배포에서 새 체크아웃으로 업그레이드하면 먼저 `make ports BASE=9600`으로 기존 `.env`의 기본 포트를 이관한다. 수동 지정한 포트는 명시적으로 정리해야 하며, 외부 클라이언트·방화벽·프록시 구성은 운영자가 변경을 적용한다.

## Related

- [ADR-0004](0004-port-policy-9400.md)
- [ADR-0045](0045-host-exposure-invariant.md)
- [ADR-0051](0051-private-remote-team-access.md)
