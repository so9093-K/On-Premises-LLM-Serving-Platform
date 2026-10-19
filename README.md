# On-Premises LLM Serving Platform

**Your models. Your infrastructure. One serving platform.**

자체 인프라에서 AI 모델을 실행하고 API로 제공하며, 하나의 Control Plane에서 운영합니다.

**OpenAI-compatible API · Model Lifecycle · GPU Resource Control · Observability**

Linux/NVIDIA · Apple Silicon · Self-hosted — [환경별 지원 기능](#deployment-targets)

[빠른 시작](#quick-start) · [사용자 가이드](docs/guides/user-guide.md) · [원격 접속](docs/guides/remote-access.md) · [API 연동](docs/guides/api-integration.md) · [개발자 가이드](docs/guides/developer-guide.md)

## 01. 시스템 구성

![Gateway와 모델 Runtime, 운영·관측 서비스의 관계를 보여 주는 시스템 구성도](assets/ai_model_serving_system_architecture.png)

*Gateway · Model Runtime · Runtime Controller · Observability*

외부 애플리케이션은 **Gateway**의 공통 API를 호출하고, **Model Runtime**이 추론을 수행합니다.
**Control Plane**은 Gateway가 제공하는 운영 UI입니다. Linux managed target의 Runtime Controller가
모델 lifecycle과 GPU admission을 담당하며, static target의 Main lifecycle은 외부에서 관리합니다.

Linux/NVIDIA는 vLLM, Apple Silicon은 MLX-VLM을 사용합니다.
Chat Completions / Responses를 공통 진입점으로 제공하고, managed target은 Embedding·한국어 Retrieval·
Prompt Injection 탐지까지 지원합니다. PII·Secret 탐지는 static target에서도 제공합니다.

[시스템 구성](docs/03_system_components.md) · [설정과 Source of Truth](docs/05_configuration.md) · [OpenAI 호환 범위](docs/reference/openai_compatibility.md)


<a id="quick-start"></a>

## 02. 빠른 시작

**사전 준비:** [실행 환경](docs/04_runtime_modes.md) · GPU 메모리 · 모델 접근 권한

최초 실행에 이미지 빌드와 모델 다운로드가 포함됩니다.

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


## 03. Control Plane

![모델·런타임 상태와 최근 요청을 보여주는 Control Plane 운영 개요](assets/screenshots/showcase/overview.png)

*Linux/NVIDIA · Control Plane 운영 개요*

### 서비스 운영

모델 상태, Runtime, 최근 요청, 운영 작업을 Control Plane에서 확인합니다.

[운영 화면 안내](docs/reference/control_plane_operator_ux.md) · [런타임과 GPU](assets/screenshots/showcase/runtimes.png)

### 모델 응답

Playground에서 모델 응답을 확인하고 요청 코드를 내보낼 수 있습니다.

![현재 Playground에서 한국어 요약 요청과 실제 모델 응답](assets/screenshots/guides/playground-after.png)

*Playground · 모델 응답*

[Playground 사용법](docs/guides/user-guide.md) · [요청 재현](docs/reference/playground_integration.md)

### 모델 전환 영향

모델 전환 전에 입력 기능과 GPU 리소스 정책의 변화를 확인합니다.

![현재 E4B 프로필과 12B 후보의 모델 전환 영향 비교](assets/screenshots/showcase/model-review.png)

*E4B → 12B 후보 · 전환 전 영향 검토*

[모델 전환과 복구](docs/06_model_operations.md) · [설정](assets/screenshots/showcase/configuration.png) · [운영 활동](assets/screenshots/showcase/operations.png)

## 04. 기능 데모

**이미지 분석 · 그래프의 최대·최소 요청 수**

![예시 그래프를 Playground에 첨부해 최대·최소값을 읽는 모델 응답 GIF](assets/demos/image-analysis.gif)

[정지 화면](assets/demos/image-analysis-poster.png) · [입력 그래프](assets/demos/inputs/sample-chart.png)

| 데모 | 기능 |
|---|---|
| [이미지 분석](docs/reference/feature_demos.md#image-analysis) | 그래프 값 분석 |
| [이미지 텍스트 읽기 (OCR)](docs/reference/feature_demos.md#ocr) | 가상 주문서 정보 추출 |
| [시스템 프롬프트 입력 사례](docs/reference/feature_demos.md#system-prompt) | 역할 변경 요구에 대한 모델 응답 |
| [임베딩·문장 유사도](docs/reference/feature_demos.md#embedding) | API 실행 뷰어 · 벡터 생성과 검색 |

[데모 입력·응답 및 촬영 정보](docs/reference/feature_demos.md) · [운영 화면 촬영 정보](assets/screenshots/showcase/README.md)

## 05. API 문서

실행 중인 Gateway의 Scalar 화면에서 API 목록과 요청 스키마를 확인할 수 있습니다. 문서 화면은 배포 설정에 따라 비활성화될 수 있습니다.

[API 연동 가이드](docs/guides/api-integration.md) · [API Reference](docs/reference/api_reference.md) · [OpenAPI 계약](specs/openapi.gateway.yaml)

<a id="deployment-targets"></a>

## 06. 배포 환경과 지원 기능

| Target | Main runtime / lifecycle | 제공 기능 | Console의 모델·Runtime 제어 |
|---|---|---|---|
| `linux-nvidia-dynamic` | vLLM / 플랫폼 관리 | Chat·Responses, Embedding, Retrieval, PII·Secret·Prompt Risk | 모델 전환, 시작·중지, GPU admission |
| `linux-nvidia-static` | 외부 vLLM / 외부 관리 | Chat·Responses, PII·Secret Risk | 외부 lifecycle |
| `macos-metal-static` | native MLX-VLM / 외부 관리 | Chat·Responses, PII·Secret Risk | 외부 lifecycle |

**Target 검증:** Linux managed·macOS `verified`, Linux static `unverified`.
모델별 지원 기능·GPU 조건은 활성 프로필과 리소스 정책을 따릅니다.

[Target 선언](configs/deployment_targets.yaml) · [모델과 resource variant](docs/06_model_operations.md) · [보안 노출 경계](docs/reference/vllm_security_posture.md)

## 07. 문서

[가이드 목차](docs/guides/README.md) · [전체 기술 문서](docs/README.md) · [기여 안내](CONTRIBUTING.md)

설정과 Source of Truth, 모델 운영, 관측성 및 테스트 기준은 [기술 문서](docs/README.md)에서 확인할 수 있습니다.

## 버전과 변경 이력

[버전](VERSION) · [변경 이력](CHANGELOG.md)

## License

이 프로젝트에서 직접 작성한 소스 코드, 문서 및 설정은 별도 표시가 없는 한
[Apache License 2.0](LICENSE)을 따른다.

제3자 소프트웨어와 모델은 각 upstream의 라이선스 및 이용 약관을 따른다. 모델 가중치와 upstream에서
가져오거나 수정한 자료도 이 프로젝트의 Apache-2.0 라이선스 대상에 포함되지 않는다.

자세한 출처와 제3자 고지 사항은 [NOTICE](NOTICE)에서 확인한다.
