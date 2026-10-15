# On-Premises LLM Serving Platform

**Your models. Your infrastructure. One serving platform.**

Run, serve, and operate AI models on your infrastructure.

다양한 환경에서 AI 모델을 실행하고, 하나의 API로 연결하고,
Control Plane에서 상태·모델·리소스를 운영하세요.

**OpenAI-compatible API · Model Lifecycle · GPU Resource Control · Observability**

Linux / NVIDIA · Apple Silicon · Self-hosted — 제공 기능과 운영 권한은 [Deployment Target](#deployment-targets)에 따라 다릅니다.

![Control Plane 운영 개요에서 모델·런타임 상태와 최근 실제 API 요청을 확인하는 화면](assets/screenshots/showcase/overview.png)

*Linux/NVIDIA managed 환경의 실제 운영 화면입니다. 상태 조회와 모델 추론 성공은 별도로 확인합니다.*

[시작하기](#quick-start) · [API Reference](docs/reference/api_reference.md) · [운영 가이드](docs/06_model_operations.md) · [전체 문서](docs/README.md)

## 01. What can you do?

### 모델과 서비스 상태를 한눈에

운영 개요에서 현재 모델과 Runtime 상태, 최근 요청을 확인하고 필요한 작업으로 이동하세요.
Runtime 제어와 GPU 자원 검토, 설정 변경, 운영 활동을 하나의 Control Plane에서 연결합니다.

[화면별 운영 흐름](docs/reference/control_plane_operator_ux.md) · [런타임과 GPU 화면](assets/screenshots/showcase/runtimes.png)

### 실제 모델 응답을 테스트

Playground에서 공개 API를 호출하고, 응답과 요청 당시 설정·첫 토큰 시간·토큰 수를 함께 확인하세요.
이미지·오디오·도구·구조화 출력 등은 현재 모델이 제공하는 기능에 맞춰 사용할 수 있습니다.

![Playground에서 공개용 한국어 질문에 실제 모델이 응답하고 요청 지표를 표시한 화면](assets/screenshots/showcase/playground.png)

*공개용 예시 입력에 대한 실제 Gemma 4 E4B 응답입니다. 화면의 지연·생성 속도는 이 요청의 관찰값입니다.*

[Playground 사용과 기능 경계](docs/reference/control_plane_chat_playground.md)

### 영향을 검토하고 모델을 변경

Linux/NVIDIA managed target에서는 현재 모델과 후보의 기능·자원 영향을 검토하고 전환 결과를 추적할 수 있습니다.
모델 교체에는 서비스 중단이나 복구가 필요할 수 있습니다. 성공한 전환 뒤에는 별도의 API 요청으로 응답을 확인하세요.

![메인 모델 전환 전 현재 E4B와 12B 후보의 기능·자원 정책 변화를 검토하는 화면](assets/screenshots/showcase/model-review.png)

*실제 프로필 조회 화면이며, 다른 모델로의 전환 성공을 시연한 이미지는 아닙니다. 호스트별 적용 가능성은 별도 확인합니다.*

[모델 전환과 검증·복구](docs/06_model_operations.md) · [설정 화면](assets/screenshots/showcase/configuration.png) · [실제 설정 변경 기록](assets/screenshots/showcase/operations.png)

## 02. See it in action

입력 이미지를 첨부하고 실제 모델 응답을 확인하는 짧은 GIF입니다.

![공개용 예시 그래프를 첨부하고 최대·최소 요청 수를 읽는 실제 Playground GIF](assets/demos/image-analysis.gif)

*첫 3초는 촬영용 입력 이미지입니다. 이어 실제 요청·응답 화면을 재생합니다.*
[정지 화면](assets/demos/image-analysis-poster.png) · [입력 이미지](assets/demos/inputs/sample-chart.png)

| 더 볼 수 있는 데모 | 실제 실행 내용 |
|---|---|
| [이미지 분석](docs/reference/feature_demos.md#image-analysis) | 그래프에서 최대·최소값 읽기 |
| [OCR](docs/reference/feature_demos.md#ocr) | 가상 주문서의 항목을 텍스트로 추출 |
| [시스템 프롬프트와 인젝션 입력](docs/reference/feature_demos.md#system-prompt) | 역할 변경·프롬프트 공개 요구에 대한 모델 응답 |
| [임베딩과 문장 유사도](docs/reference/feature_demos.md#embedding) | 실제 벡터 생성과 cosine similarity 정렬 |

각 데모의 입력·결과·실행 조건을 함께 공개합니다. 인젝션 장면은 모델 응답 예시이고,
임베딩 장면은 촬영용 API 뷰어입니다.

실제 화면에서 다음 흐름으로 플랫폼을 사용합니다.

1. **운영 개요**에서 현재 모델과 요청 가능 상태를 확인합니다.
2. **Playground**에서 질문을 보내 실제 응답을 확인합니다.
3. **메인 모델**에서 후보의 기능과 자원 영향을 검토합니다. 전환은 지원되는 환경에서 수행합니다.
4. **운영 활동**에서 변경 결과를 확인하고, 전환 성공 후 Playground에서 새 응답을 검증합니다.

[화면 촬영 환경과 실제 실행 범위](assets/screenshots/showcase/README.md)에서 예시의 조건을 확인할 수 있습니다.

Runtime/GPU 화면의 비율은 **정책상 예약값**입니다. GPU 실측 사용량과 시간대별 서비스 지표는
[관측성 가이드](docs/11_observability.md)의 Grafana·로그 탐색 경로에서 확인하세요.

## 03. How it works

외부 애플리케이션은 **Gateway**의 공통 API를 호출하고, **Model Runtime**이 추론을 수행합니다.
**Control Plane**은 Gateway가 제공하는 운영 UI입니다. Linux managed target의 Runtime Controller가
모델 lifecycle과 GPU admission을 담당하며, static target의 Main lifecycle은 외부에서 관리합니다.

![Gateway와 모델 Runtime, 운영·관측 서비스의 관계를 보여 주는 시스템 구성도](assets/ai_model_serving_system_architecture.png)

Linux/NVIDIA는 vLLM, Apple Silicon은 MLX-VLM을 사용합니다.
Chat Completions / Responses를 공통 진입점으로 제공하고, managed target은 Embedding·한국어 Retrieval·
Prompt Injection 탐지까지 지원합니다. PII·Secret 탐지는 static target에서도 제공합니다.

[시스템 구성](docs/03_system_components.md) · [설정과 Source of Truth](docs/05_configuration.md) · [OpenAI 호환 범위](docs/reference/openai_compatibility.md)

<a id="quick-start"></a>

## 04. Quick Start

저장소 루트에서 실행합니다. 최초 실행은 image build와 model download를 포함하므로 네트워크·장비에 따라 시간이 걸립니다.
모델 접근 권한, GPU 메모리와 환경별 설치 조건은 [실행 환경](docs/04_runtime_modes.md)을 먼저 확인하세요.

**Linux / NVIDIA managed** — Linux amd64, Python 3.12–3.13, Docker, NVIDIA GPU/driver/Container Toolkit, Bash 4+:

```bash
make up TARGET=linux-nvidia-dynamic ACCESS=local
```

**Apple Silicon** — Python 3.13.12, Docker, 모델에 충분한 unified memory:

```bash
make up TARGET=macos-metal-static ACCESS=local
```

Gated Hugging Face 모델은 접근 승인과 `HF_TOKEN`이 필요합니다. 키 설정 및 외부 Main Runtime을 연결하는
Linux static target은 [실행 모드](docs/04_runtime_modes.md)에서 확인하세요.

기동이 완료되면 출력되는 주소로 접속합니다. 기본 Gateway 주소는 `http://127.0.0.1:9400`입니다.

- **Control Plane:** `/admin/console/` — 관리자 인증이 요구되면 설정한 관리자 키를 사용합니다.
- **API 문서:** `/docs` · **OpenAPI:** `/openapi.json`

첫 요청 (`ACCESS=local` 기본 설정 기준):

```bash
curl -s http://127.0.0.1:9400/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "local-main",
    "messages": [{"role": "user", "content": "안녕하세요"}],
    "max_tokens": 128
  }'
```

인증이 적용된 환경에서는 사용자 API Bearer token을 함께 전달합니다.
Responses, Embedding, Retrieval, Risk, Streaming 예제는 [API Reference](docs/reference/api_reference.md)를 참고하세요.

이후에는 저장된 설정을 사용합니다.

```bash
make up
make status
make logs
make down
```

접근 범위는 `ACCESS=local|private|edge`, 최초 Main profile은 `MODEL=<profile-id>`로 선택합니다.
접근 변경·진단·복구는 [운영 가이드](docs/12_operations.md)를 따릅니다. raw Model Runtime은 public API로 노출하지 않습니다.

<a id="deployment-targets"></a>

## 05. Deployment Targets & Capabilities

| Target | Main runtime / lifecycle | 제공 기능 | Console의 모델·Runtime 제어 |
|---|---|---|---|
| `linux-nvidia-dynamic` | vLLM / 플랫폼 관리 | Chat·Responses, Embedding, Retrieval, PII·Secret·Prompt Risk | 모델 전환, 시작·중지, GPU admission |
| `linux-nvidia-static` | 외부 vLLM / 외부 관리 | Chat·Responses, PII·Secret Risk | 외부 lifecycle |
| `macos-metal-static` | native MLX-VLM / 외부 관리 | Chat·Responses, PII·Secret Risk | 외부 lifecycle |

현재 target qualification은 Linux managed와 macOS가 `verified`, Linux static은 `unverified`입니다.
모든 모델·장비 조합을 검증했다는 의미는 아닙니다. 모델별 기능과 GPU 적용 가능성은 선택한 profile과 resource policy로 판단합니다.

[Target 선언](configs/deployment_targets.yaml) · [모델과 resource variant](docs/06_model_operations.md) · [보안 노출 경계](docs/reference/vllm_security_posture.md)

## 06. Documentation & Development

| 목적 | 문서 |
|---|---|
| 전체 안내와 읽기 순서 | [문서 목차](docs/README.md) |
| API·인증·요청 예제 | [API Reference](docs/reference/api_reference.md) |
| 구성·설정·적용값 | [설정과 Source of Truth](docs/05_configuration.md) |
| 모델·GPU·전환·복구 | [모델 운영](docs/06_model_operations.md) |
| 지표·Grafana·로그 | [관측성](docs/11_observability.md) |
| 배포·장애 대응 | [배포](docs/10_deployment.md) · [운영 관리](docs/12_operations.md) |
| 개발·검증·기여 | [로컬 개발](docs/07_local_dev_build.md) · [테스트](docs/08_testing_validation.md) · [기여 안내](CONTRIBUTING.md) |
| 변경 영역과 검증 범위 | [변경 가이드](docs/13_change_guide.md) |

```bash
make setup-dev
make app-check   # Application 검증
make check       # Control Plane source/build를 포함한 전체 변경 검증
```

실제 GPU 추론과 live Runtime qualification은 application check와 별도로 수행합니다.
소스는 `src/`, UI는 `ui/`, 설정은 `configs/`, 계약은 `specs/`, 배포 자산은 `ops/`에서 관리합니다.

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
