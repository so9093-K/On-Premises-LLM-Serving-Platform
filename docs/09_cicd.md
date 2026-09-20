# 9. 자동화 경계

이 저장소는 GitHub를 Source Repository로 사용한다. 현재 자동화는
[GitHub 검증 워크플로](../.github/workflows/validate.yml)가 `main` push, Pull Request와
수동 실행에서 macOS·Ubuntu의 application/contract 검사, Control Plane 검사와
Linux Platform image build·container smoke를 수행한다.

Container image publish와 운영 배포를 담당하는 CI/CD pipeline은 현재 정의하지 않는다.
특정 CI provider, registry 또는 runner를 먼저 선택하지 않고도 같은 결과를 만들 수 있도록
검증·빌드·runtime lifecycle은 저장소의 canonical 명령으로 유지한다. 외부 automation은
transport/orchestration adapter이며 별도 remote deployment state machine을 소유하지 않는다.

## 9.1 책임 구분

| 책임 | 현재 진입점 | 기준 |
|---|---|---|
| Application·contract 검사 | `make check` | `pyproject.toml`, `uv.lock`, configs, specs, tests |
| Platform image build | `make build-image` | `Dockerfile`, `pyproject.toml`, `uv.lock` |
| Unified vLLM image build | `make build-vllm-unified-image` | `configs/vllm_unified_build.yaml`, runtime Dockerfile·patch |
| Release source package | `make package` | Git tracked source와 packaging exclusion |
| Target lifecycle | `make setup/build/prepare/up/status/down` | deployment target, `.env`, local Runtime convergence |
| Runtime / Main Model mutation | Control Plane Plan/Apply APIs | component-owned runtime state와 rollback |
| 외부 transport | Repository contract 아님 | SSH/Ansible/CI 등이 canonical lifecycle을 호출 |

GitHub Actions 같은 자동화 도구는 위 진입점을 호출하는 adapter다. Python dependency,
Docker build argument, runtime 기동 순서와 component rollback 정책을 workflow YAML에 다시
구현하지 않는다.

## 9.2 현재 검증 자동화

GitHub의 검증 workflow는 다음 경계를 독립적으로 확인한다.

- Ubuntu: Linux application·shell·contract 호환성
- macOS: 로컬 개발 환경의 application·contract 호환성
- Control Plane: frontend source/type/test와 checked-in bundle drift
- Platform image: `make build-image`로 Linux/amd64 Dockerfile build와 image 내부 app composition smoke

Ubuntu/Python 3.12와 macOS/Python 3.13은 같은 Platform `uv.lock`의 대표 호환 조합이다.
로컬 기본 patch는 `.python-version`, native runtime exact patch는 runtime 설정, Linux
Platform image의 exact Python patch와 base digest는 `Dockerfile`이 각각 소유한다.

이 workflow는 다음 작업을 수행하지 않는다.

- Platform image registry push/promotion
- Unified vLLM image build
- 모델 다운로드
- CUDA·NVIDIA GPU runtime 실행
- 운영 서버 배포
- 장시간 부하·성능 측정

Platform image job은 source 아래 Dockerfile·lock·package composition이 실제 runnable image를
만드는지 확인하는 verification gate다. 결과 image를 registry에 publish하거나 release candidate로
승격하지 않는다. 따라서 workflow 성공은 application/contract와 Platform image packaging 검증
결과이며 GPU runtime qualification을 대체하지 않는다.

## 9.3 Build, publish, lifecycle의 독립 경계

Image build와 registry publish는 다른 책임이다. Git repository는 source/configuration/build
contract의 authority이며 Docker/OCI registry 자체를 소유하지 않는다.

```text
Source + locked inputs
        ↓
Repository build script
        ↓
Local image
        ├─ local lifecycle에서 직접 사용
        └─ 선택된 외부 automation이 publish
                       ↓
              immutable name@sha256 digest
                       ↓
              host persistent image pin
                       ↓
              canonical target lifecycle
```

외부 registry digest는 `make build`가 다시 build하지 않고 보존한다. Publish 결과를 특정
host에서 사용하려면 해당 host의 image pin을 명시적으로 갱신하고 같은
`setup/build/prepare/up/status` lifecycle로 수렴시킨다.

SSH/Ansible/CI runner가 이 lifecycle을 다른 host에서 호출할 수는 있지만, repository는 source
전송, rolling/full mode, release symlink, remote automatic rollback을 별도 deployment protocol로
구현하지 않는다. 자세한 결정은
[ADR-0037](./adr/0037-local-lifecycle-deployment-authority.md)을 따른다.

## 9.4 자원 경계

정적 검증과 unit/contract test는 GPU runtime을 시작하지 않는다. `make check` 안에서
`validate`와 `test`는 순서대로 실행되며, OS matrix의 병렬 실행은 GPU VRAM과 무관하다.

향후 image publish·배포 자동화를 추가할 때는 다음 자원을 별도로 직렬화한다.

| 자원 | 직렬화할 작업 | 이유 |
|---|---|---|
| Linux image builder | 대형 Unified vLLM image build·push | base layer의 disk·memory·network 경합 방지 |
| GPU runtime target | lifecycle mutation과 live runtime qualification | 동시에 model을 load하거나 runtime state를 바꾸지 않도록 보장 |

Runtime 내부의 실제 VRAM 안전성은 CI stage가 아니라 `configs/gpu_budgets.yaml`, runtime
admission, prerequisite 순차 기동과 readiness/rollback 정책이 소유한다.

## 9.5 미래 자동화 추가 원칙

Platform image는 application source·lock·Dockerfile·runtime config가 하나의 배포 artifact로
조립되는 경계라 PR에서 build와 container smoke를 required gate로 검증한다. 이 검증은
`make build-image`를 그대로 호출하며 image publish나 운영 promotion 규칙을 소유하지 않는다.
추가 자동화를 넣을 때는 어떤 장애를 막는지, artifact invalidation 범위, cold/warm build 비용,
verification image와 release candidate의 구분을 먼저 확인한다.

1. 기존 명령으로 로컬에서 같은 작업을 먼저 수행할 수 있어야 한다.
2. Workflow는 provider adapter로 유지하고 동작을 중복 구현하지 않는다.
3. Build, publish, promote, deploy를 서로 다른 책임으로 유지하고 운영 결과는 immutable digest로 연결한다.
4. Platform Image와 Unified vLLM Image의 build/publish lifecycle을 분리한다.
5. 대형 image builder와 GPU deployment는 서로 다른 resource lock을 사용한다.
6. PR cache write 권한, registry credential과 publish 권한은 source verification 권한과 분리한다.
7. 오래된 검증 실행은 취소할 수 있지만 진행 중인 Runtime/Main Model operation은 새 automation 요청으로 중단하지 않는다.
8. Workflow 문법은 provider 자체 검증을 사용하며 `make validate`에 YAML parser를 넣지 않는다.
9. CI를 위해 테스트 전용 helper나 Source of Truth 복제 파일을 만들지 않는다.

Platform image의 build·smoke는 현재 required gate다. 반면 Unified vLLM artifact는 크기와
CUDA/runtime compatibility, GPU qualification을 함께 다루므로 일반 application PR의 Platform
image gate와 같은 경로로 취급하지 않는다. Unified vLLM 자동 검증을 추가할 때는 별도 builder와
qualification evidence를 전제로 manual/non-blocking 단계부터 시작한다.

## 9.6 관련 문서

- 로컬 개발과 image build: [7. 로컬 개발과 빌드](./07_local_dev_build.md)
- 테스트와 검증 범위: [8. 테스트와 검증](./08_testing_validation.md)
- Target lifecycle과 복구 authority: [10. 배포](./10_deployment.md)
- 변경 영향에 따른 확인 범위: [13. 변경 가이드](./13_change_guide.md)
