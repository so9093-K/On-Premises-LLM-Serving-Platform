# 개발자 가이드

이 가이드는 플랫폼 자체를 수정하는 기여자용입니다.
플랫폼 API를 사용하는 서비스 개발은 [API 연동](api-integration.md), 설치·운영은
[빠른 시작](getting-started.md)과 [사용자 가이드](user-guide.md)를 따릅니다.

## 1. 개발 환경 준비

**준비:** Git, Python `>=3.12,<3.14`, [pyproject.toml](../../pyproject.toml)의 uv 허용 버전이 필요합니다.
Console 작업에는 [package.json](../../ui/control-plane/package.json)의 고정 Node.js/npm도 필요합니다.

```bash
git clone https://github.com/so9093-K/On-Premises-LLM-Serving-Platform.git
cd On-Premises-LLM-Serving-Platform
git switch -c feat/my-change
make setup-dev
```

`setup-dev`는 lock을 기준으로 개발 `.venv`를 준비합니다. Docker·GPU·운영 `.env` 없이 실행할 수 있습니다.
Python minor가 다른 기존 가상환경을 임의로 지우지 않으므로 오류 안내에 따라 환경을 분리하세요.
운영 스크립트까지 사용하는 macOS 환경은 Bash 4 이상도 준비합니다.

**성공 기준:** `.venv/bin/python --version`과 `.venv/bin/python -m pytest --version`이 동작합니다.
**실패 시:** uv/Python 버전과 기존 가상환경 안내를 확인합니다. [개발 환경 상세](../07_local_dev_build.md)를 참고하세요.

## 2. 코드·설정 소유권

**준비:** 변경할 사용자 동작과 실패 의미를 한 문장으로 정리합니다.

| 위치 | 책임 |
|---|---|
| `src/ai_model_serving/` | Gateway, Risk, Runtime Controller와 공유 application 코드 |
| `ui/control-plane/src/` | Console 화면·클라이언트 동작 |
| `configs/` | target·model profile·resource·access·service 정책 |
| `specs/` | OpenAPI 및 JSON Schema 계약 |
| `ops/` | Compose, Dockerfile, 이미지 patch·monitoring 설정 |
| `scripts/` | build·lifecycle·검증 진입점 |
| `tests/unit/`, `tests/contract/` | 동작·계약 회귀 검증 |
| `runtimes/mlx/` | native MLX의 독립 Python 프로젝트·lock |

1. [시스템 구성](../03_system_components.md)과 [요청 흐름](../02_request_flow.md)에서 소유 서비스를 찾습니다.
2. [설정 Source of Truth](../05_configuration.md)와 [변경 가이드](../13_change_guide.md)에서 영향 경계를 확인합니다.
3. target capability는 `configs/deployment_targets.yaml`, Main 정책은 `configs/main_model_profiles.yaml`,
   resource·topology는 `configs/gpu_budgets.yaml`·`configs/runtime_topology.yaml`에서 확인합니다.
4. API 구현·Schema·OpenAPI를 함께 맞추고 관련 생성물을 다시 만듭니다.

```bash
make render-runtime-assets
```

Console을 바꾼 경우 고정 Node/npm 환경에서 다음으로 checked-in bundle을 생성합니다.

```bash
make console-build
```

**성공 기준:** 원본과 generated artifact가 일치하며 diff가 의도한 계약을 설명합니다.
**실패 시:** generated UI bundle·`.runtime/` projection을 직접 원본처럼 편집하지 말고 생성 입력을 확인합니다.
모델의 `compatible`·`verified`, Gateway gate, 실제 Runtime readiness는 서로 다른 정보입니다.
화면 예시는 [사용자 가이드](user-guide.md#runtime-states)를 참고하세요.

## 3. 테스트·검증

**준비:** `make setup-dev` 완료. Console 검증에는 고정 Node/npm, Python·Bash가 필요합니다.

| 변경 범위 | 실행 |
|---|---|
| 설정·Schema·문서의 계약/생성물 정합성 | `make validate` + 변경한 문서의 링크·명령 확인 |
| Python application | `make app-check` (`validate` + `test`) |
| Application과 Console 전체 | `make check` |
| 특정 Python 동작을 작업 중 확인 | `.venv/bin/python -m pytest tests/unit/<해당-테스트>.py` |
| 실제 Linux managed Runtime 동작 | 준비된 GPU stack에서 `make runtime-validate` |

Target이 필요한 live 실행은 [빠른 시작](getting-started.md)을 따라 별도로 준비합니다.
`make runtime-validate`는 모든 OS에서 실행하는 범용 CI Gate가 아닙니다.
Console browser smoke의 mock API 검증도 실제 GPU 모델 qualification을 대신하지 않습니다.

`make validate`·`make test`·Console Node 테스트와 Playwright suite는 공통 검증 결과 인터페이스를 사용합니다.
결과는 기본 `reports/validation/<suite>/<run-id>/`의 `manifest.json`·`summary.json` 및 해당 suite의 JUnit에서 확인합니다.
Runner 종료 코드와 실패 항목을 먼저 읽으세요. 실제 GPU 결과는 별도의 `reports/runtime/` 경로를 사용합니다.
상세 명령·출력과 변경별 범위는 [테스트와 검증](../08_testing_validation.md)이 소유합니다.

**성공 기준:** 필요한 검증이 통과하고 원래 오류를 통과시키지 못하는 회귀 검증을 설명할 수 있습니다.
**실패 시:** 실패한 suite의 결과·원래 stderr를 확인합니다. 생성물 drift는 입력을 수정한 뒤 다시 생성합니다.
검증 실패를 무시하거나 GPU 없이 통과한 테스트를 실제 추론 검증이라고 기록하지 않습니다.

## 4. CI·PR

**준비:** 필요한 로컬 검증과 diff 검토를 마칩니다.

1. 키·로컬 `.env`·다운로드 요청 원문·민감 로그가 diff에 없는지 확인합니다.
2. 사용자·운영자 영향은 [CHANGELOG](../../CHANGELOG.md)에 기록하고 관련 안내를 갱신합니다.
3. 장기간의 구조 결정은 [ADR](../adr/README.md), 미완료 작업은 Issue 또는 Roadmap으로 관리합니다.
4. 커밋 설명과 PR 본문은 한국어를 기본으로 작성합니다. PR에는 **문제 / 변경 뒤 계약 / 검증**을 씁니다.
5. [.github/workflows/validate.yml](../../.github/workflows/validate.yml)의 실제 GitHub Checks 결과와 실패 Artifact를 확인합니다.

```bash
git diff --check
git diff --stat
```

**성공 기준:** PR이 사용자 동작·소유권·실패 의미를 설명하고 각 검증의 증명 범위가 분명합니다.
**실패 시:** CI의 실패 로그를 해결하고 필요한 검증을 다시 실행합니다. 일반 CI 상태는 GitHub Checks를 기준으로 봅니다.
테스트·기록의 세부 원칙은 [CONTRIBUTING](../../CONTRIBUTING.md)이 소유합니다.
