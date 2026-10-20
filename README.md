# On-Premises LLM Serving Platform

자체 인프라의 AI 모델을 **OpenAI 호환 API**로 제공하고 **Control Plane**에서 운영하는 플랫폼입니다.

**Self-hosted · Linux/NVIDIA · Apple Silicon**

[빠른 시작](#quick-start) · [사용자 가이드](docs/guides/user-guide.md) · [API 연동](docs/guides/api-integration.md) · [원격 접속](docs/guides/remote-access.md) · [개발자 가이드](docs/guides/developer-guide.md)

## 외부에서 이용하기 (서버 설치 불필요)

서버 운영자가 이미 LLM 플랫폼과 Tailnet 접근을 준비했다면, **이 저장소를 내려받거나 서버의 `make` 명령을 실행하지 않습니다.**

- **외부 관리자:** 본인의 기기에서 Tailscale에 연결한 뒤 운영자가 알려 준 `https://<실제-서버-tailnet-이름>/admin/console/` 주소를 브라우저에서 열고 Admin Key로 인증합니다. [외부 관리자 접속](docs/guides/remote-access.md#external-admin)
- **외부 API 사용자:** Tailscale 연결 후 운영자가 전달한 HTTPS 8443 **API Base URL**과 **사용자 API Key**로 SDK 또는 **허용된 모델 API 경로**로 요청합니다. 팀원 진입점은 `GET /v1/models`, `POST /v1/chat/completions`·`/v1/responses`·`/v1/embeddings`만 전달합니다. 팀원 API에서는 관리자 Console을 제공하지 않습니다. [외부 API 연동](docs/guides/api-integration.md#remote-api)

URL과 권한은 운영자가 실제 Tailnet에서 확인해 전달합니다. 이 절차는 일반 인터넷 공개가 아니며, 인증 키를 URL에 포함하지 않습니다.

<a id="quick-start"></a>

## 빠른 시작 (서버 설치자)

Git, Python·uv, Docker 및 해당 환경의 모델 실행 자원이 필요합니다. [환경별 설치 조건](docs/guides/getting-started.md)

```bash
git clone https://github.com/so9093-K/On-Premises-LLM-Serving-Platform.git
cd On-Premises-LLM-Serving-Platform
```

**Linux / NVIDIA** — vLLM Runtime 및 GPU 관리

```bash
make up TARGET=linux-nvidia-dynamic ACCESS=local
```

**Apple Silicon** — 외부에서 관리하는 MLX-VLM Main Runtime

```bash
make up TARGET=macos-metal-static ACCESS=local
```

모델 접근 승인·`HF_TOKEN`·GPU 메모리 및 Resource Variant 설정은 [빠른 시작 가이드](docs/guides/getting-started.md)를 참고하세요.

실행 후 `make status`로 플랫폼 준비 상태를 확인합니다. **다른 기기에서의 접근 가능 여부는 별도 검증**해야 합니다.

- **Control Plane:** `http://127.0.0.1:9400/admin/console/`
- **Gateway:** `http://127.0.0.1:9400`

모델 요청이 준비된 경우, 로컬 기본 인증 설정에서 다음과 같이 호출할 수 있습니다.

```bash
curl --fail-with-body -sS http://127.0.0.1:9400/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "local-main",
    "messages": [{"role": "user", "content": "안녕하세요"}],
    "max_tokens": 128
  }'
```

인증이 활성화된 경우 사용자 API Key가 필요합니다. `ACCESS=local`은 동일 호스트의 Loopback 접속입니다. **서버 운영자만** 기존 `make up ACCESS=edge`의 계획·승인 계약과 [원격 접속 Host 구성](docs/guides/remote-access.md#operator-setup)을 사용합니다. `make status`는 플랫폼 준비 상태이며 실제 외부 기기의 네트워크 접근 성공 여부는 별도로 확인해야 합니다.

```bash
make up
make status
make logs
make down
```

## 시스템 구성

![Gateway, 모델 Runtime, Control Plane 및 관측 서비스의 구조](assets/ai_model_serving_system_architecture.png)

애플리케이션은 Gateway를 통해 모델 API를 호출합니다. Linux/NVIDIA의 Managed Runtime은 모델 실행·전환과 GPU 자원 제어를 제공하며, Static Target의 Main Runtime은 외부에서 관리합니다.

[시스템 구성](docs/03_system_components.md) · [OpenAI 호환 범위](docs/reference/openai_compatibility.md)

## Control Plane

![메인 모델, Runtime 및 최근 요청을 보여주는 운영 개요](assets/screenshots/showcase/overview.png)

*운영 개요*

![Playground에서 실행한 모델 응답](assets/screenshots/guides/playground-after.png)

*Playground · 모델 응답*

모델 상태·요청 지표를 조회하고, Playground에서 모델 요청과 코드 내보내기를 수행할 수 있습니다. 지원되는 Managed Target에서는 Runtime 제어와 모델 전환 영향 검토도 제공합니다.

[Control Plane 사용법](docs/guides/user-guide.md) · [모델 운영](docs/06_model_operations.md)

## 기능 데모

![Playground 이미지 분석 데모](assets/demos/image-analysis.gif)

*이미지 분석 · 그래프의 최대·최소값*

[이미지 분석](docs/reference/feature_demos.md#image-analysis) · [OCR](docs/reference/feature_demos.md#ocr) · [시스템 프롬프트 입력](docs/reference/feature_demos.md#system-prompt) · [임베딩·유사도](docs/reference/feature_demos.md#embedding)

## Scalar API Reference

![Scalar API Reference에서 API 목록과 요청 예제를 확인하는 화면](assets/screenshots/scalar_api_reference.jpg)

*Scalar API Reference*

Gateway의 `/docs`에서 API 요청 스키마·예제·테스트 요청을 확인할 수 있습니다. 문서 화면의 제공 여부는 접근 설정에 따릅니다.

[API Reference](docs/reference/api_reference.md) · [OpenAPI 계약](specs/openapi.gateway.yaml)

<a id="deployment-targets"></a>

## 배포 환경

| Target | 모델 실행 | 지원 기능 | 운영 주체 |
|---|---|---|---|
| `linux-nvidia-dynamic` | vLLM | Chat·Responses, Embedding·Retrieval, Risk | 플랫폼 관리 · 모델 전환·GPU 제어 |
| `linux-nvidia-static` | 외부 vLLM | Chat·Responses, PII·Secret Risk | 외부 Main Runtime |
| `macos-metal-static` | MLX-VLM | Chat·Responses, PII·Secret Risk | 외부 Main Runtime |

기능별 지원·검증 상태와 모델 자원 조건은 [Deployment Target](configs/deployment_targets.yaml) 및 [모델 운영](docs/06_model_operations.md)을 참고하세요.

## 문서

[가이드 목차](docs/guides/README.md) · [기술 문서](docs/README.md) · [기여 안내](CONTRIBUTING.md) · [변경 이력](CHANGELOG.md)

## 라이선스

직접 작성한 소스 코드·문서·설정은 별도 표시가 없는 한 [Apache License 2.0](LICENSE)을 따릅니다. 제3자 소프트웨어와 모델 가중치는 각 원저작자의 라이선스 및 이용 약관을 따릅니다. [제3자 고지](NOTICE)
