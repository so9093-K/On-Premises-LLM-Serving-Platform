# Ubuntu/NVIDIA AIPerf 실측 기록

2026-10-20 RTX 4090 한 대의 활성 E4B 구성에서 수행한 수동 실험이다.
다른 GPU·모델·Target의 성능이나 전체 사용자 수·SLO를 정의하지 않는다.
설치·실행·지표 의미는 [공통 절차](../../ops/perf/README.md)를 따른다.

## 환경과 실행 조건

- Ubuntu 24.04.4 LTS, x86_64, AMD Ryzen 9 7900X3D, OS 관측 RAM 약 61.9 GiB.
  데스크톱 전원, CPU governor `powersave`(종료 후 조회), GPU 전력 상한 450 W.
  GPU clock·온도를 고정하지 않았고 다른 데스크톱 앱과 장비를 공유했다.
- NVIDIA GeForce RTX 4090, 관측 총 메모리 24,564 MiB, driver `580.178.04`.
  실제 Runtime은 PyTorch `2.13.0+cu130`, CUDA `13.0`, vLLM `0.30.0`, Transformers `5.17.0`.
- `linux-nvidia-dynamic`, `gemma4-e4b-it` / `rtx4090-24gb`.
  모델 `google/gemma-4-E4B-it`, Revision `ee0ef6023621cff504d758262d4e04895a5af4a2`.
- Gateway Admission 4 / Queue Timeout 90s. Engine context 65,000, max_num_seqs 4,
  max_num_batched_tokens 4,096, gpu_memory_utilization 0.76. Speculative decoding/MTP 설정 없음.
- Platform·Controller·Risk·Runtime의 image source는 `62a7940ac8893288ba8e92f54576006edd6b807d`.
  측정 중 Working Tree의 후속 변경은 문서였으며, 전후 container/image/command·활성 profile·
  Serving Envelope가 같음을 확인했다. 아래 값은 registry 승격 digest가 아닌 **로컬 image ID**다.
  - Platform: `sha256:4dcc764346040df10f61282c0fceed222c5711aa9cec118836da85b0fd9e599f`.
  - vLLM: `sha256:58ad17c26548de17febe4cec5f7c38446a90d527ecaa1775e5bd5f807a6bca97`.
- Python `3.13.12`, AIPerf `0.13.0`, 도구 측 Transformers `5.20.1`.
  별도 가상환경에서 기존 Docker host cache의 실제 Hub ID·고정 Revision을 오프라인으로 읽었다.
- 공통 YAML, 합성 Shakespeare 입력, Worker 1, pooled 연결, 도구 seed 42,
  temperature 0, reasoning false. 모델 요청 seed는 지정하지 않았다.
- 각 실행 Warmup 2건 + profiling 10건. 6개 조건을 r1 → r2 순서로 반복했다.
  각 반복 안에서는 Short → Long → Concurrent c1 → c2 → c4 → Queue c8 순서였다.
  실제 요청 구간은 **09:24:10–09:29:44 KST**다. CLI 준비·Warmup은 표의 AIPerf profiling 통계에서 제외된다.

Workload SHA-256: `2b4716e6d6b5031ad6d5af27af0f627b9dac2b1f6e3d17c1566689b727857d79`

Tool lock SHA-256: `53a0dbfe604d8dfdcedee3851b3be067b5aa6ded23ccf95b435593b79f0619cf`

## 실행 검증과 요청 무결성

`make up`으로 PR source의 이미지·준비 상태를 맞췄다. 처음 전체 Runtime 검증은
중지된 Embedding 2종 때문에 실패했다. Main을 중지하지 않는 admissible Plan을 확인해
보조 Runtime을 잠시 시작한 뒤 `make runtime-validate`가 **37 pass / 0 fail / 1 skip**이었다.
skip은 활성 profile이 허용하지 않는 named Tool choice다. 측정 전 Plan/Apply로 보조 Runtime을
원래 중지 상태로 복원했다. 이 준비 과정의 API 요청은 아래 성능 통계에 포함하지 않았다.

실험은 공개 합성 입력으로만 수행하고 `--export-level raw`를 명시했다. **120개 측정 요청과
24개 Warmup** 모두 HTTP 200·finish reason·`[DONE]`·양수 서버 usage를 원본 SSE에서 확인했다.
요청 ID 144개를 Gateway 완료 로그와 연결했고, 입력·출력 토큰 수가 AIPerf 요청별 metric 및
Gateway 로그와 일치했다. 각 반복의 측정 요청 본문 집합도 같았다.
첫 요청부터 마지막 요청까지 Gateway 로그에서 다른 공개 API 요청은 발견되지 않았다.

별도의 loopback 인증 Gateway에서 익명 요청과 공개 API에 Admin Key를 사용한 요청은 401이었다.
AIPerf의 유효한 사용자 키 요청은 Warmup 1건·측정 2건 모두 200·`[DONE]`를 확인했다.
그때 생성한 키가 결과 파일에 남지 않았음을 확인하고 임시 Gateway·인증 파일을 제거했다.
이는 인증 호환성 시험이며 아래 성능 수치에는 포함하지 않았다.

## AIPerf profiling 결과

각 행은 10건이다. 오류율 0%, `is_complete=true`, `was_cancelled=false`였고 원본 종료를 별도로 확인했다.
TTFO는 reasoning false인 이 표본에서 TTFT와 같았다. p95는 AIPerf 정의의 작은 표본 통계다.
콘텐츠 지연은 `request_latency`이며 finish·usage·DONE 수신 완료 시간과 다르다.

| 실행 | 실제 입력 tokens | 실제 출력 tokens | TTFT 평균 / p95 ms | ITL 평균 ms | 콘텐츠 지연 평균 ms | 출력 tokens/s | Gateway Queue 평균 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| short-r1 | 296–297 | 128–128 | 33.14 / 36.25 | 11.27 | 1464.64 | 87.30 | 0.02 |
| long-r1 | 4136–4137 | 256–256 | 261.64 / 264.10 | 11.95 | 3309.47 | 77.31 | 0.02 |
| concurrent-c1-r1 | 552–553 | 256–256 | 34.64 / 36.22 | 11.29 | 2914.36 | 87.78 | 0.02 |
| concurrent-c2-r1 | 552–553 | 256–256 | 37.02 / 41.56 | 12.47 | 3217.67 | 158.92 | 0.02 |
| concurrent-c4-r1 | 552–553 | 256–256 | 42.91 / 48.88 | 12.28 | 3174.15 | 267.49 | 0.02 |
| queue-c8-r1 | 552–553 | 256–256 | 1940.05 / 3219.16 | 12.29 | 5073.00 | 268.21 | 1893.99 |
| short-r2 | 296–297 | 128–128 | 24.20 / 25.78 | 11.24 | 1452.22 | 88.04 | 0.02 |
| long-r2 | 4136–4137 | 256–256 | 36.38 / 40.80 | 11.97 | 3087.90 | 82.84 | 0.02 |
| concurrent-c1-r2 | 552–553 | 256–256 | 25.04 / 26.09 | 11.24 | 2891.96 | 88.46 | 0.02 |
| concurrent-c2-r2 | 552–553 | 256–256 | 37.32 / 44.92 | 12.44 | 3209.84 | 159.30 | 0.02 |
| concurrent-c4-r2 | 552–553 | 256–256 | 43.87 / 52.80 | 12.29 | 3176.84 | 267.63 | 0.02 |
| queue-c8-r2 | 552–553 | 256–256 | 1947.26 / 3232.98 | 12.33 | 5091.43 | 267.23 | 1901.31 |

### Cache 조건

vLLM의 `cache_config_info`에서 APC 활성화를 확인했다. Cache reset은 수행하지 않았다.
도구의 seed와 요청 본문이 같아도 첫 실행과 재사용 실행의 Cache 상태는 같지 않다.
Long의 첫 응답 지연 차이를 코드 변경에 따른 성능 개선이나 회귀로 부르지 않는다.

각 Long 실행 전후에 관측한 Prefix Cache counter 차이는 다음과 같다.
여기에는 Warmup도 포함한 12건이 들어가므로 profiling 10건만의 지표로 해석하지 않는다.

| 실행 | 조회 token counter 차이 | Hit token counter 차이 | 관측 비율 |
|---|---:|---:|---:|
| long-r1 | 49,633 | 3,456 | 6.96% |
| long-r2 | 49,633 | 49,536 | 99.80% |

## Gateway·엔진·GPU 관측

Gateway `/metrics`, 내부 vLLM·DCGM Exporter 및 `nvidia-smi`를 1초 간격으로 읽고,
profiling 요청의 시간 구간에 해당하는 표본을 확인했다. 아래 최대는 **관측 표본의 최대**이며
표본 사이의 순간 최대나 안전한 메모리 여유를 보장하지 않는다.
DCGM Framebuffer 값은 전체 장치의 MiB이며 Main 전용 할당량이나 MLX 최근 요청 Peak와 다르다.

| 실행 | Gateway in-flight / waiting 최대 | vLLM running / waiting 최대 | KV 사용 비율 최대 % | DCGM used MiB | DCGM free MiB | GPU 온도 °C |
|---|---:|---:|---:|---:|---:|---:|
| short-r1 | 1 / 0 | 1 / 0 | 1.04 | 19647–19694 | 4383–4430 | 48–52 |
| long-r1 | 1 / 0 | 1 / 0 | 4.11 | 19694–19845 | 4232–4383 | 52–65 |
| concurrent-c1-r1 | 1 / 0 | 1 / 0 | 1.55 | 19844–19853 | 4224–4233 | 57–61 |
| concurrent-c2-r1 | 2 / 0 | 2 / 0 | 3.06 | 19836–19853 | 4224–4241 | 57–58 |
| concurrent-c4-r1 | 4 / 0 | 4 / 0 | 6.06 | 19836–19836 | 4241–4241 | 58–58 |
| queue-c8-r1 | 4 / 4 | 4 / 0 | 6.15 | 19836–19836 | 4241–4241 | 58–58 |
| short-r2 | 1 / 0 | 1 / 0 | 1.11 | 19836–19846 | 4231–4241 | 60–62 |
| long-r2 | 1 / 0 | 1 / 0 | 4.11 | 19846–19846 | 4231–4231 | 59–63 |
| concurrent-c1-r2 | 1 / 0 | 1 / 0 | 1.55 | 19846–19852 | 4225–4231 | 62–64 |
| concurrent-c2-r2 | 2 / 0 | 2 / 0 | 3.08 | 19851–19851 | 4226–4226 | 59–60 |
| concurrent-c4-r2 | 4 / 0 | 4 / 0 | 6.10 | 19851–19864 | 4213–4226 | 59–60 |
| queue-c8-r2 | 4 / 4 | 4 / 0 | 5.96 | 19864–19864 | 4213–4213 | 59–62 |

한도 4를 넘는 c8에서는 Gateway waiting 4와 요청별 Queue 대기를 관측했다.
같은 구간 vLLM waiting은 0이었다. 두 Queue를 합산하거나 c8을 엔진 동시 실행 8로 해석하지 않는다.
표의 전체 출력 처리량도 단일 사용자 Decode 속도·장시간 최대 용량이 아니다.

## 범위와 원본

- 설치·Tokenizer·Stream/usage 검증 실패는 느린 추론과 별도로 취급했다.
  로컬 도구 오류 주입에서 AIPerf 0.13.0이 DONE/finish·usage 누락을 정상으로 집계할 수 있음을
  확인했으며, 실제 GPU 응답의 지연·오류율에 그 가짜 응답을 섞지 않았다.
- 온도와 Cache 이력이 달라진 반복을 자동 회귀로 판정하지 않는다. 모델·Tokenizer·Runtime과
  전원·배치·입력이 다른 [Mac 수치](macos_aiperf_measurement.md)와도 직접 비교하지 않는다.
- `linux-nvidia-static`, 다른 모델·Resource Variant·GPU, 멀티 GPU, 부하 중 모델 전환·
  최대 Context·장시간 포화·성능 Release Gate는 이 실험의 검증 범위가 아니다.
- 원본 JSON/CSV/요청별 JSONL·SSE·관측·전후 API/이미지 snapshot은 Git 제외 경로
  `reports/perf/2026-10-20-linux/`에 보관했다. 공개 문서에는 요청·응답·키·내부 IP를 싣지 않았다.
  성능 비교기·Result Schema·Baseline 승격·자동 재측정은 추가하지 않았다.
