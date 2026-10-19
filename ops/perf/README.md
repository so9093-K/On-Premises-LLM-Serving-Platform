# 수동 추론 성능 측정

준비된 Gateway의 `/v1/chat/completions`를 AIPerf로 측정한다. 이 디렉터리는
독립된 측정 도구 환경과 공통 Workload만 소유한다. 플랫폼 기동은 `make up`,
성능 해석은 실제 장비에서 얻은 AIPerf 결과와 운영 지표가 각각 담당한다.

현재 실제 검증 범위는 **Apple Silicon / macos-metal-static**이다.
Linux x86_64는 같은 도구 lock의 해석 대상이지만 Ubuntu/NVIDIA 설치·추론·성능은
이 PR에서 실측하지 않았다. 두 OS의 지원 완료나 성능 동등성을 의미하지 않는다.
`make check`, Qualification 선언, Release Gate에 성능 측정을 추가하지 않는다.
설계 경계는 [ADR-0052](../../docs/adr/0052-manual-aiperf-measurement.md),
Mac 실측은 [측정 기록](../../docs/resources/macos_aiperf_measurement.md)을 따른다.

## 설치와 선행 조건

저장소 루트에서 실행한다. Platform·MLX와 다른 가상환경을 사용한다.
`uv.lock`은 AIPerf 0.13.0과 간접 의존성을 고정한다. 다른 Python minor·OS에서
lock이 해석되는 것과 그 환경의 실제 설치·측정 성공은 별개다.

```bash
UV_PROJECT_ENVIRONMENT="$PWD/.runtime/perf/venv" \
  uv sync --locked --project ops/perf --python 3.13.12
.runtime/perf/venv/bin/aiperf --version

make metal-doctor
make up TARGET=macos-metal-static ACCESS=local
make status
curl --fail http://127.0.0.1:9400/ready
curl --fail http://127.0.0.1:9400/admin/serving-envelope
curl --fail http://127.0.0.1:9400/v1/models
```

이미 다른 Deployment Target이 설정된 `.env`를 덮어쓰지 않는다. 인증된 배포는
해당 공개 API Key를 사용하고, Admin 정보 조회는 별도의 관리자 권한을 사용한다.
아래 기본 절차는 `ACCESS=local`에서 검증했다.

현재 Mac profile의 캐시된 Tokenizer ID와 Revision을 읽는다. 모델 가중치를
측정 도구에 다시 설치하거나 Tokenizer를 `local-main`이라는 공개 별칭으로 추측하지 않는다.

```bash
export PERF_TOKENIZER="$(.venv/bin/python -c 'import yaml; c=yaml.safe_load(open("configs/macos_mlx_runtime.yaml")); print(c["profiles"][c["default_profile"]]["model_id"])')"
export PERF_TOKENIZER_REVISION="$(.venv/bin/python -c 'import yaml; c=yaml.safe_load(open("configs/macos_mlx_runtime.yaml")); print(c["profiles"][c["default_profile"]]["revision"])')"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PERF_CHAT_URL=http://127.0.0.1:9400/v1/chat/completions
```

`HF_HUB_OFFLINE=1`은 먼저 모델·Tokenizer가 캐시된 상태에서 쓴다. AIPerf 0.13.0은
이 모드에서 로컬 절대 경로를 Hub ID로 해석해 실패하는 경우가 있어, 위처럼
**실제 Hub ID + 고정 Revision**을 사용한다. 캐시 누락 시 온라인으로 임의 Revision을
받는 대신 실패를 확인하고 `make up`의 캐시 준비 경로를 사용한다.

## 공통 Workload

`chat.yaml`은 AIPerf 자체 Schema 2.0을 사용한다. 합성 Shakespeare corpus,
고정 System Prompt, seed 42, temperature 0, reasoning false, Worker 1개,
요청 2건의 워밍업 + 측정 10건, pooled 연결을 모든 시나리오에서 동일하게 사용한다.
워밍업의 별도 Phase는 AIPerf의 측정 통계에서 제외된다.

| 이름 | 합성 User 입력 목표 | 출력 상한 | 클라이언트 동시성 | Mac 해석 |
|---|---:|---:|---:|---|
| Short Chat | 256 tokens | 128 tokens | 1 | 정상 단일 요청 |
| Long Prompt | 4,096 tokens | 256 tokens | 1 | Prefill·Context 영향 |
| Concurrent Chat 기준 | 512 tokens | 256 tokens | 1 | 현재 Admission 한도의 정상 부하 |
| Concurrent Chat Queue | 512 tokens | 256 tokens | 2 | 같은 입력으로 한도 1을 넘는 별도 실험 |

입력 목표는 합성 User 문장의 길이다. System Prompt·Chat Template를 포함한
실제 `usage.prompt_tokens`는 더 길 수 있다. 출력은 **상한**이며 강제 길이가 아니다.
현재 MLX profile에 없는 `ignore_eos`·`min_tokens`를 넣어 길이를 강제하지 않는다.
결과의 실제 입력·출력 토큰 분포와 오류·중단 상태를 반드시 함께 읽는다.

```bash
export PERF_ARTIFACT_DIR="$PWD/reports/perf/mac-local/short-r1"
.runtime/perf/venv/bin/aiperf config validate --config-file ops/perf/chat.yaml
.runtime/perf/venv/bin/aiperf profile --config ops/perf/chat.yaml

PERF_ISL=4096 PERF_OSL=256 PERF_CONCURRENCY=1 \
  PERF_ARTIFACT_DIR="$PWD/reports/perf/mac-local/long-r1" \
  .runtime/perf/venv/bin/aiperf profile --config ops/perf/chat.yaml

PERF_ISL=512 PERF_OSL=256 PERF_CONCURRENCY=2 \
  PERF_ARTIFACT_DIR="$PWD/reports/perf/mac-local/queue-c2-r1" \
  .runtime/perf/venv/bin/aiperf profile --config ops/perf/chat.yaml
```

Concurrent Chat의 정상 기준도 `PERF_ISL=512 PERF_OSL=256 PERF_CONCURRENCY=1`로
`concurrent-c1-r1` 같은 별도 경로에 측정한다. 입력·출력이 다른 Short/Long 수치만으로
동시성 2의 Queue 효과를 추정하지 않는다.

각 Workload를 같은 조건에서 `r2`처럼 새 결과 경로로 반복한다. 기존 경로를 덮어쓰지
않는다. 비교하려는 실행에서는 전원 공급·저전력 모드·온도·다른 부하·요청 순서·관측
주기까지 기록한다. 장시간 유휴 뒤 첫 요청은 워밍업과 별도로 확인한다.
위 세 시나리오의 Cache reset은 수행하지 않는다. 실행 시점의 APC 활성화 여부와
기존 Prefix Cache 조건을 기록하며, Cache가 다른 실행을 같은 조건이라고 간주하지 않는다.

인증이 필요한 공개 API는 `PERF_API_KEY`를 프로세스 환경으로 전달할 수 있다.
설정 파일에 실제 키를 적거나 shell trace를 켜지 않는다. AIPerf의 JSON Export는
키를 마스킹하지만, 결과 디렉터리 전체의 안전성을 가정하지 말고 공유 전에 확인한다.

## 지표와 관측

| 결과 필드 | 의미와 한계 |
|---|---|
| `time_to_first_token` | Client 요청 시작부터 첫 비어 있지 않은 생성 Chunk까지. Reasoning Chunk도 포함한다. Network·Gateway Queue·Prefill이 함께 포함된다. |
| `time_to_first_output_token` | 첫 일반 Output까지. Reasoning을 켜면 TTFT와 다를 수 있다. 현재 Workload는 reasoning false다. |
| `inter_token_latency` | AIPerf 0.13.0의 요청별 `(E2E-TTFT)/(실제 출력 토큰-첫 Chunk 토큰)` 추정값. per-chunk usage가 없으면 첫 Chunk를 1 token으로 가정한다. MTP가 여러 token을 묶어 보내므로 물리적인 token 간격으로 해석하지 않는다. |
| `inter_chunk_latency` | 실제 수신 Chunk 사이 간격. 위 ITL/TPOT 추정값과 구분한다. |
| `request_latency` | 요청 완료까지의 Client E2E. Warmup·Tokenizer 준비·CLI 시작 시간은 별도다. |
| `output_token_throughput` | 관측 구간 전체의 실제 출력 tokens/sec. 단일 사용자 Decode 속도와 다르다. |
| `output_token_throughput_per_user` | 요청별 ITL 역수 추정값. Native MLX의 `decode_tok_s`와 별도로 해석한다. |
| `usage_*`, `input_sequence_length`, `output_sequence_length` | `useServerTokenCount`로 받은 서버 토큰 수. usage가 누락되면 Client Tokenizer 수로 조용히 대체하지 않는다. |

기본 출력은 `profile_export_aiperf.json`/CSV와 요청별 `profile_export.jsonl`이다.
요청별 레코드의 `metadata.phase_kind`로 warmup/profiling을 구분한다. percentile은
AIPerf의 정의를 따르며 Gateway 최근 트래픽의 nearest-rank 규칙과 섞지 않는다.
10개 표본의 p95는 참고값이며 장시간 성능이나 SLO의 증거가 아니다.

실행 전후의 `/admin/serving-envelope`, `/v1/models`, Python·AIPerf·Runtime 버전,
`ops/perf/uv.lock`/Workload의 SHA-256, 소스 Commit 및 dirty 여부를 결과 경로에 보관한다.
이 저장소에 별도의 Manifest/Result Schema나 승격 도구를 만들지 않는다.

Mac에서는 Native `http://127.0.0.1:9401/metrics`의 `summary`, `latest`, `server`와
Prometheus의 MLX Exporter를 함께 확인한다. 측정 중 1초 간격으로 Native Queue와
Gateway `/metrics`의 `upstream_admission_waiting`/`inflight`를 관측했다.
관측 주기는 Sample 사이의 순간적인 최대값을 보장하지 않는다.
`mlx_runtime_latest_peak_memory_gib`는 **최근 완료 요청이 보고한** 값이다. Native
`peak_memory_gb`는 십진 GB이므로 GiB와 비교할 때 `GB * 1e9 / 2**30`으로 변환한다.
시간 구간의 최대값이나 호스트 전체 메모리로 부르지 않는다. Native `decode_tok_s`도 최근 요청 기준이다.
Gateway Admission Queue와 Runtime Queue는 별개의 관측값이다.

Ubuntu에서는 실제 Active Profile·Resource Variant·Image Digest·vLLM/Driver·GPU ID와
VRAM을 별도로 확인해야 한다. vLLM Scheduler·DCGM과 MLX 최근 요청 Peak Memory를
직접 같은 지표로 비교하지 않는다. `make runtime-validate`는 Linux Runtime 기능 검증이며
Mac 성능 측정을 대신하지 않는다.

## 실패와 비교

`aiperf profile`의 종료 코드는 도구 실행 성공 여부다. 0만으로 정상 표본이라고 판정하지
않고 `is_complete`, `was_cancelled`, `request_count`, `completed_request_count`,
`request_error_rate`, `error_summary` 및 누락된 usage를 확인한다. 설치·설정·Tokenizer
실패, 잘린 Stream, Timeout·HTTP 오류가 있는 실행은 정상 성능 비교 대상에서 제외한다.
유효한 반복 실행에서 지연이 늘어난 경우는 실행 실패와 구분하며 자동 차단하지 않는다.

모델/Tokenizer와 Revision, Target·장비·OS·전원, Runtime·MTP·동시성/Admission,
입출력 분포, seed·System Prompt·Reasoning·Warmup·Cache, Tool/lock 버전과 관측 조건이
같을 때만 같은 필드의 원본 요약을 나란히 비교한다. 결과가 다르면 원인을 조사하며,
단일 수치로 성능 회귀를 선언하거나 모델 간 tokens/sec를 등가로 취급하지 않는다.
AIPerf의 JSON/CSV와 `aiperf plot`이 비교 입력을 소유한다. 별도 비교기는 만들지 않는다.

`reports/perf/`는 Git에서 제외된다. raw/HTTP trace/생성 응답 Export는 기본적으로
끄지만 AIPerf는 `inputs.json`에 합성 입력을 저장할 수 있다. 사내 Prompt·이미지·키를
측정 Dataset에 넣지 않는다. 공유할 때는 확인한 숫자·조건·제약만 선별해 문서에 기록한다.

## 공식 참고 자료

- [AIPerf 0.13.0 배포](https://pypi.org/project/aiperf/0.13.0/)
- [YAML 설정](https://github.com/ai-dynamo/aiperf/blob/v0.13.0/docs/tutorials/yaml-config.md)
- [지표 정의](https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference)
- [JSON Export](https://docs.nvidia.com/aiperf/reference/json-export-schema)
