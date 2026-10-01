# On-Premises LLM Serving Platform

온프레미스 AI 모델을 하나의 **OpenAI-compatible API와 운영 lifecycle**로 제공한다.
모델 실행·전환, Retrieval, Risk Detection, 접근 제어와 관측을 deployment target에 맞는
일관된 플랫폼 계약으로 관리하는 것이 이 프로젝트의 목적이다.

Linux/NVIDIA에서는 vLLM, Apple Silicon에서는 MLX-VLM을 사용하며 외부 애플리케이션은
runtime 차이와 관계없이 Gateway의 공통 API 계약을 사용한다.

## 주요 기능

- OpenAI-compatible Chat Completions / Responses / Embedding API
- 한국어 Retrieval
- PII·Secret 및 Prompt Injection Risk Detection
- Main Model lifecycle과 profile switching
- target-aware Runtime Control과 GPU resource admission
- Prometheus / Grafana / Loki 기반 관측
- 재현 가능한 application 검증, image build와 deployment lifecycle

제공 범위는 deployment target에 따라 달라진다. 현재 target과 실제 capability는
아래 표와 `configs/deployment_targets.yaml`에서 확인할 수 있다.

## 시스템 구성

Gateway를 중심으로 Model Runtime, Risk Signal Service, Runtime Controller와 관측 서비스가 연결된다.

![AI 모델 서빙 플랫폼 시스템 구성도](assets/ai_model_serving_system_architecture.svg)

전체 구성과 서비스별 역할은 [시스템 구성](docs/03_system_components.md)에서 설명한다.

## Control Plane

운영자용 Control Plane은 현재 상태와 설정을 설명하고, 같은 공개 API로 모델 응답을 직접 확인할 수 있는
self-hosted UI를 Gateway의 `/admin/console/`에서 제공한다.

![Control Plane 채팅 테스트](assets/screenshots/control_plane_chat_test.webp)

*채팅 테스트 화면에서 요청 설정과 모델 응답, 첫 토큰 시간·전체 시간·토큰 수·request_id를 함께 확인한다.*

---

## Deployment Target

| Target | Main runtime | 제공 범위 | 실행 환경 |
|---|---|---|---|
| `linux-nvidia-dynamic` | vLLM · Platform-managed | Chat / Responses, Embedding, Retrieval, PII·Secret·Prompt Risk, Model Control | Linux amd64, Python 3.12–3.13, NVIDIA GPU/driver/Container Toolkit, Docker, Bash 4+ |
| `linux-nvidia-static` | 외부 OpenAI-compatible runtime | Chat / Responses, PII·Secret Risk | Linux amd64, Python 3.12–3.13, Docker, 외부 Main endpoint |
| `macos-metal-static` | MLX-VLM · native runtime | Chat / Responses, PII·Secret Risk | Apple Silicon, Python 3.13.12, Docker |

모델별 GPU 자원 적용 가능성은 선택한 model profile과 resource policy로 판단한다.
실측 범위와 resource variant는 [모델 운영](docs/06_model_operations.md)에서 관리한다.

---

## 시작하기

첫 실행에서 target과 접근 범위를 선택하면 `make up`이 필요한 환경과 설정, image, model cache,
service startup을 준비하고 target에 맞는 readiness를 확인한다.

Linux/NVIDIA managed target:

```bash
make up TARGET=linux-nvidia-dynamic ACCESS=local
```

gated Hugging Face model에 token이 필요하면 같은 명령에 전달한다.

```bash
HF_TOKEN=hf_xxx make up TARGET=linux-nvidia-dynamic ACCESS=local
```

Apple Silicon:

```bash
make up TARGET=macos-metal-static ACCESS=local
```

외부 Main runtime을 사용하는 Linux static target:

```bash
make up TARGET=linux-nvidia-static MAIN_URL=http://127.0.0.1:8000/v1 ACCESS=local
```

`TARGET` 없이 처음 `make up`을 실행하면 사용할 수 있는 target과 이 host에서 감지한 추천 target을 보여 준다.
기동이 끝나면 Console, API 문서, Grafana 주소를 함께 출력한다.

이후에는 저장된 configuration을 기준으로 같은 명령으로 수렴한다.

```bash
make up
make status
make logs
make down
```

접근 범위는 `ACCESS=local|private|edge`로 선택한다. Main Model profile을 처음부터 바꾸려면
`MODEL=<profile-id>`를 함께 전달한다. 상세 로그 조회, reset/purge와 장애 대응은
[운영 관리 및 장애 대응](docs/12_operations.md)에서 설명한다.

---

## API 사용

Gateway 기본 주소는 `http://127.0.0.1:9400`이다. 인증이 적용된 환경에서는 해당 profile의
Bearer token을 함께 사용한다. 브라우저 API Reference는 `/docs`, OpenAPI 명세는
`/openapi.json`에서 제공한다.

대표적인 Chat Completions 요청:

```bash
curl -s http://127.0.0.1:9400/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "local-main",
    "messages": [
      {"role": "user", "content": "안녕하세요"}
    ],
    "max_tokens": 128
  }'
```

Responses, Embedding, Retrieval, Risk Detection, Streaming, 인증 방식과 전체 요청·응답 계약은
[API 인터페이스](docs/reference/api_reference.md)에서 확인한다.

![Scalar API Reference](assets/screenshots/scalar_api_reference.jpg)

---

## 개발과 검증

Gateway와 Risk Signal Service의 application 개발은 로컬 Python 환경에서 독립적으로 준비하고 검증할 수 있다.

```bash
make setup-dev
make app-check
```

저장소 전체 변경은 Control Plane source/build까지 포함해 다음 명령으로 확인한다.

```bash
make check
```

live Runtime qualification은 일반 application check와 분리되어 있다. 개발 환경, image build와
검증 범위는 [로컬 개발과 빌드](docs/07_local_dev_build.md)와
[테스트와 검증](docs/08_testing_validation.md)을 따른다.

---

## 주요 명령

| 목적 | 명령 |
|---|---|
| 시작 / 현재 configuration으로 수렴 | `make up [TARGET=<id>] [ACCESS=<profile>]` |
| 현재 상태 | `make status` |
| 운영 이벤트와 오류 확인 | `make logs` |
| 실행 리소스 정지 | `make down` |
| Application 변경 검증 | `make app-check` |
| 저장소 전체 변경 검증 | `make check` |

reset/purge, raw service log, Runtime qualification과 복구 절차는
[운영 문서](docs/12_operations.md)와 [테스트와 검증](docs/08_testing_validation.md)에 둔다.

---

## 프로젝트 구조

```text
src/        애플리케이션 코드
configs/    서비스·모델·GPU 설정
specs/      JSON Schema·OpenAPI
ops/        Compose·Runtime Image·모니터링
scripts/    Build·검증·배포·운영 도구
ui/         Control Plane source
docs/       프로젝트 문서
assets/     아키텍처·문서 이미지
```

변경 영역과 함께 확인할 설정·검증·배포 범위는 [변경 가이드](docs/13_change_guide.md)에서 정리한다.

---

## 문서

| 문서 | 내용 |
|---|---|
| [문서 안내](docs/README.md) | 전체 문서 구성과 읽기 순서 |
| [API 인터페이스](docs/reference/api_reference.md) | API 계약, 요청·응답, 인증과 예제 |
| [실행 환경과 모드](docs/04_runtime_modes.md) | Deployment Target과 lifecycle |
| [설정 체계](docs/05_configuration.md) | 설정 구조와 Source of Truth |
| [모델 운영](docs/06_model_operations.md) | Main Model / Runtime 운영과 resource policy |
| [배포](docs/10_deployment.md) | Release 적용과 복구 |
| [관측성](docs/11_observability.md) | 요청, Runtime, GPU와 로그 관측 |
| [운영 관리 및 장애 대응](docs/12_operations.md) | 상태 확인, 진단과 복구 |
| [변경 가이드](docs/13_change_guide.md) | 변경 영향과 검증·배포 범위 |

개발 변경과 Pull Request 기준은 [CONTRIBUTING](CONTRIBUTING.md)을 따른다.

## 버전과 변경 이력

현재 버전은 [`VERSION`](VERSION)을 기준으로 관리한다. 변경 이력은 [CHANGELOG](CHANGELOG.md)에서 확인한다.

## AI Assistance

- **Codex (OpenAI)** — AI-assisted 프로젝트 검토, 구현 및 검증 지원
- **Claude (Anthropic)** — AI-assisted 프로젝트 검토, 구현 및 검증 지원

## License

이 프로젝트에서 직접 작성한 소스 코드, 문서 및 설정은 별도 표시가 없는 한
[Apache License 2.0](LICENSE)을 따른다.

제3자 소프트웨어와 모델은 각 upstream의 라이선스 및 이용 약관을 따른다. 모델 가중치와 upstream에서
가져오거나 수정한 자료도 이 프로젝트의 Apache-2.0 라이선스 대상에 포함되지 않는다.

자세한 출처와 제3자 고지 사항은 [NOTICE](NOTICE)에서 확인한다.
