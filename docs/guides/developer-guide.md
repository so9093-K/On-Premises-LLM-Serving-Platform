# 개발자 가이드

플랫폼 소스 코드를 수정하고 PR을 제출하는 기여자를 위한 안내입니다. API 소비자는 [API 연동 가이드](api-integration.md), 설치·운영자는 [빠른 시작](getting-started.md)을 참고하세요.

## 1. 개발 환경

Git, Python 3.12–3.13, [프로젝트 지정 uv 버전](../../pyproject.toml)이 필요합니다. Control Plane 작업에는 [지정된 Node.js/npm](../../ui/control-plane/package.json)도 준비하세요.

```bash
git clone https://github.com/so9093-K/On-Premises-LLM-Serving-Platform.git
cd On-Premises-LLM-Serving-Platform
make setup-dev
git switch -c feat/my-change
```

`make setup-dev`는 Docker·GPU·운영 `.env` 없이 개발 가상환경을 준비합니다. 문제가 생기면 [개발 환경](../07_local_dev_build.md)과 `make doctor-dev`를 확인하세요. 일부 운영 스크립트는 Bash 4 이상이 필요합니다.

## 2. 코드 수정

| 경로 | 주요 역할 |
|---|---|
| `src/ai_model_serving/` | Gateway·서비스 로직 |
| `ui/control-plane/src/` | Control Plane 화면 |
| `configs/` | 모델·Runtime·접근 정책 |
| `specs/` | API·Schema 계약 |
| `ops/` | Compose·이미지·관측 설정 |
| `scripts/`, `tests/` | 운영 명령·검증 및 회귀 테스트 |
| `runtimes/mlx/` | 별도 native MLX Runtime |

변경 전에 [설정 Source of Truth](../05_configuration.md)와 [변경 가이드](../13_change_guide.md)에서 원본과 영향을 받는 소비자를 확인하세요. 생성 파일은 직접 수정하지 말고, 해당 원본이 바뀐 경우에만 다시 생성합니다.

```bash
make console-build          # Control Plane 변경 시
make render-runtime-assets  # Runtime 생성물의 원본 변경 시
```

### 포트 네임스페이스 변경

포트 정책의 원본은 `configs/services.yaml`의 `port_namespace.base`와 `offsets`다.
기본 대역은 9400이며, 저장소 업데이트나 `make up`은 대역 변경 명령을 대신 실행하지 않는다.
서비스별 값·Compose·OpenAPI·Console 예제는 이 정책과 일치해야 하며 `make validate`가 불일치를 거부한다.

접속 포트만 변경하려면 `.env`의 `GATEWAY_PORT`와 필요한 경우 `GRAFANA_PORT`를 수정하고
`make up`을 실행한다. 내부 Runtime 포트를 포함한 전체 대역 변경은 다음 절차를 따른다.

```bash
make setup-dev
make ports BASE=9700 PLAN=1  # 변경 포트와 파일 목록만 확인
make ports BASE=9700 YES=1   # 파일 변경·생성물 재생성·검증
git diff                    # Git으로 관리하는 경우 변경 검토
make up                     # 이미지와 실행 서비스를 새 대역에 맞춤
make status
```

프로젝트 지정 Node.js/npm도 필요하다. `YES=1` 없이 실행하면 적용 전에 대화형 확인을 받는다.
`PLAN=1`은 변경 계획만 표시한다. 적용 시 소스·설정·문서와 Console 산출물,
`.env`의 관리 대상 포트·URL을 갱신한다. ZIP 소스에서도 실행할 수 있으며,
검증에 실패하면 변경 전 파일 상태를 복원한다.
기동 실패 시 실행 상태까지 자동으로 되돌린다는 뜻은 아니므로 `make status`와 `make logs`로 확인한다.

사용자가 지정한 Host 포트는 자동 덮어쓰지 않으며 충돌 시 명시적으로 정리해야 한다.
외부 Runtime URL, 인증키, 모델 캐시와 과거 ADR·촬영 기록은 변경 대상에서 제외된다.
외부 Nginx·Tailscale Serve·방화벽·클라이언트 주소는 운영자가 별도로 반영한다.

## 3. 테스트·검증

| 범위 | 명령 |
|---|---|
| 설정·계약·생성물 | `make validate` |
| Python·Application | `make app-check` |
| 저장소 전체·Control Plane | `make check` |
| 실제 Linux/NVIDIA Runtime | `make runtime-validate` (GPU 환경 필요) |

전체 검증에는 지정된 Node.js/npm이 필요합니다. 일반 CI·Mock 테스트 성공은 실제 GPU 추론 검증을 대신하지 않습니다. 실패한 항목과 결과 파일 확인은 [테스트와 검증](../08_testing_validation.md)을 참고하세요.

## 4. PR

```bash
git diff --check
git diff --stat
```

민감한 키·`.env`·요청 원문·로그가 포함되지 않았는지 확인한 뒤, 사용자에게 보이는 변경은 [CHANGELOG](../../CHANGELOG.md)에 반영하세요. PR 본문은 **문제 / 변경 뒤 계약 / 검증** 순서로 작성하고 GitHub Checks 결과를 확인합니다.

커밋 언어, 구조 결정(ADR), 리뷰·테스트 원칙은 [기여 규칙](../../CONTRIBUTING.md)을 따릅니다.
