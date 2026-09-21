# 변경 이력

이 파일은 사용자와 운영자에게 의미 있는 버전별 릴리스 노트만 기록한다. 세부 내부 작업 이력은 Git commit history를 기준으로 확인한다.

## [Unreleased]

현재 0.1.0 이후의 미출시 변경이 없다.

## [0.1.0] - 2026-09-21

0.0.1 이후 누적된 개발 상태를 현재 운영 계약 기준으로 정리한 첫 Control Plane baseline이다. 중간 개발 단계에서 도입됐다가 제거되거나 의미가 바뀐 상태는 릴리스 노트에 재현하지 않고 최종 계약만 기록한다.

### Added

- OpenAI 호환 Gateway가 Chat Completions, Responses, Embeddings를 제공하고 Retrieval과 Risk Signal API를 함께 노출한다. Main Model profile의 capability에 따라 multimodal input, structured output, reasoning, tool calling 등 지원 표면을 명시적으로 제한한다.
- Linux/NVIDIA의 unified vLLM runtime과 macOS/Apple Silicon의 MLX-VLM static target을 포함한 target-aware local lifecycle(`make setup/build/prepare/up/status/down`)을 제공한다.
- Runtime, Main Model, Configuration 변경을 Plan → Review → Apply → Verify 흐름으로 제어하며 operation history와 rollback/recovery evidence를 보존한다.
- same-origin first-party Control Plane Console이 Overview, Runtime Control, Main Model switching, Configuration, Activity를 제공한다. Activity는 각 backend journal의 authority를 유지한 채 최근 operation을 시간순 read-only projection으로 통합한다.
- Main Model qualification evidence, stable qualification check registry, reviewed promotion과 immutable `qualified_run` provenance를 제공한다.
- Prometheus/Grafana/Loki 기반 운영 관측과 runtime validation, deterministic release package, Linux/macOS CI 검증을 제공한다.

### Changed

- Hardware admission은 GPU 제품 allowlist가 아니라 deployment/runtime compatibility, resource feasibility, profile contract와 post-apply runtime validation을 기준으로 한다. GPU 제품명·UUID·driver는 evidence provenance이며 새 GPU 관측만으로 profile requalification을 요구하지 않는다.
- Main Model `resource_variant`는 GPU 분류가 아니라 reference resource policy가 실제 host에 맞지 않을 때 선택하는 reviewed override로 제한한다. `configs/runtime_topology.yaml`의 composition constraint는 선택된 resource policy와 공존할 수 없는 non-main Model Runtime만 effective topology에서 제외한다.
- Prompt Injection Detector는 reference Main resource policy에서는 정상 Runtime Control 대상이며, `rtx4090-24gb` policy에서만 reviewed composition constraint로 unavailable하다. PII/Secret local detector와 aggregate Risk API는 해당 상태에서도 유지된다.
- Repository-owned deployment authority를 local lifecycle로 수렴하고 remote release transport, rolling/full release mode, release symlink와 중복 rollback state machine을 제거했다. Runtime/Main Model/Configuration rollback은 각 Control Plane component가 소유한다.
- vLLM engine/runtime artifact identity와 Docker image ref/image ID/distribution digest의 의미를 분리하고, qualification evidence가 실제 runtime provenance를 기록하도록 정리했다.
- Control Plane은 effective topology에서 unavailable한 Runtime을 숨기지 않고 resource-policy 상태와 이유를 설명하며, unavailable 항목을 제어 surface나 GPU support 판정으로 재해석하지 않는다.

### Security

- Access Profile(`local|private|edge`)과 Admin/internal service authentication 경계를 명시하고, Gateway에는 Docker socket을 제공하지 않는다. Runtime lifecycle 권한은 내부 Runtime Controller가 제한된 contract로 소유한다.
- 이미지·오디오·비디오 입력은 Gateway에서 scheme/format, decoded byte, image pixel, video frame/duration 등 profile-backed 한도를 검증한 뒤 upstream runtime으로 전달한다.
- vLLM security advisory exposure를 Gateway의 실제 request surface와 대조하는 posture 문서와 regression contract를 유지한다. Engine 버전 변경이나 security patch는 GPU 제품별 support matrix가 아니라 bounded runtime regression lane으로 검증한다.

## [0.0.1] - 2026-05-20

### Added

- Gateway 중심의 chat, embedding, retrieval, risk signal API 계약과 운영 문서 기준선을 제공한다.
- 모델 catalog, model cards, runtime config, OpenAPI/JSON Schema, monitoring projection 검증 흐름을 포함한다.
- Docker/GPU full-stack 운영을 위한 compose, Prometheus, Grafana, runtime validation report 생성 흐름을 제공한다.

### Changed

- CHANGELOG는 짧은 release history로 유지한다.

### Security

- 인증/인가 동작은 이 문서 재구조화에서 변경하지 않았다.
