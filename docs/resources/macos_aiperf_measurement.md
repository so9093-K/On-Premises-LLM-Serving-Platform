# macOS AIPerf 초기 실측 기록

이 기록은 2026-10-19 Apple Silicon 한 대에서 수행한 수동 실험이다.
성능 Baseline·SLO·모델 Qualification 또는 Ubuntu/NVIDIA 지원 완료의 선언이 아니다.
실행 방법과 지표 정의는 [공통 측정 절차](../../ops/perf/README.md)를 따른다.

## 환경과 실행 계약

- 소스: `0a89584ece4f2d1773f291c35dd3565575e965b1` 기반, 측정 설정을 추가한 Working Tree.
- Apple M5, Unified Memory 32 GiB, macOS 27.0.1, arm64, Python 3.13.12.
- **배터리 전원**, Low Power Mode off. AC 전원 실측과 직접 비교하지 않는다.
  온도·다른 앱의 자원 사용은 통제·기록하지 않았으므로 반복 차이의 원인을 확정하지 않는다.
- `macos-metal-static`, Gemma 4 26B A4B QAT 4-bit, MLX-VLM 0.6.17.
- 모델 Revision `0e3cbab38ce568cf6e23543010d08d03b731910c`, Assistant Revision
  `bb94eae1b70a80dac16cbf959bb4b7d56bd1fb8c`.
- MTP on / block size 4, TurboQuant off, effective context 32,768,
  Gateway Admission 1 / Queue Timeout 90s, Native max_num_seqs 1.
- AIPerf 0.13.0, Worker 1개, seed 42, 합성 영어 Shakespeare continuation,
  고정 System Prompt, temperature 0, reasoning false. 출력은 상한이며 실제 토큰 수를 확인했다.
- 32개 Dataset, 각 실행의 Warmup 2건 + 측정 10건. Server usage 기반 토큰 수.
- APC disabled, Cache reset 없음, 동일 프로세스에서 순차 실행.
  실행 순서는 short-r1 → long-r1 → queue-c2-r1 → short-r2 → long-r2(중단)였다.
- Native JSON과 Gateway admission 지표는 1초 간격 관측. CLI 준비 시간과 Warmup은
  표의 측정 구간에 포함하지 않았다.

Workload SHA-256: `2b4716e6d6b5031ad6d5af27af0f627b9dac2b1f6e3d17c1566689b727857d79`

Tool lock SHA-256: `53a0dbfe604d8dfdcedee3851b3be067b5aa6ded23ccf95b435593b79f0619cf`

## 완료된 실행

아래 네 실행은 각 10건, HTTP/Stream 오류 0%, 완료 상태이며 Warmup 2건은 별도 Phase다.
각 측정 레코드의 요청 ID 10개를 Gateway 완료 로그와 연결해 Queue 대기와 토큰 usage를
확인했다. TTFO는 reasoning false인 이 표본에서 TTFT와 같았다.

| 실행 | 실제 입력 tokens | 실제 출력 tokens | TTFT 평균 ms | ITL 추정 평균 ms | E2E 평균 ms | 전체 출력 tokens/s | Gateway Queue 평균 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| short-r1 | 300–301 | 128–128 | 394.98 | 28.94 | 4070.91 | 31.42 | 0.03 |
| short-r2 | 300–301 | 128–128 | 415.50 | 32.26 | 4512.63 | 28.34 | 0.04 |
| long-r1 | 4140–4141 | 256–256 | 4168.18 | 34.78 | 13037.11 | 19.63 | 0.07 |
| queue-c2-r1 | 556–557 | 256–256 | 8554.05 | 32.12 | 16745.75 | 28.98 | 7913.00 |

Short 두 실행의 실제 길이는 같지만 지연·처리량에는 차이가 있었다. 이는 같은 조건에서
반복 기록이 가능함을 보여 주는 초기 표본이며, 원인을 특정하거나 회귀로 판정하지 않는다.
Long Prompt는 4,096 User tokens 목표에 System/Template overhead가 포함됐다.
Queue-c2는 Admission 한도 1을 넘는 별도 시험이다. 같은 512/256 입력·출력의
동시성 1 기준을 실행하지 않았으므로 c2에 의한 처리량 개선/악화 비율을 산출하지 않는다.

## Native 관측

| 실행 | 관측 Native in-flight 최대 | 관측 Native Queue 최대 | 완료 요청이 보고한 Peak 관측 범위 GiB | Native 최근 Decode 관측 범위 tokens/s |
|---|---:|---:|---:|---:|
| short-r1 | 1 | 0 | 15.49–15.61 | 31.36–36.98 |
| short-r2 | 1 | 0 | 18.06–18.06 | 26.02–35.06 |
| long-r1 | 1 | 0 | 17.05–18.06 | 25.90–31.43 |
| queue-c2-r1 | 1 | 0 | 18.06–18.06 | 29.59–34.42 |

Queue-c2에서 Gateway admission waiting은 1까지 관측됐고 Native Queue는 0이었다.
두 Queue를 합치거나 Native가 동시성 2로 실행했다고 해석하지 않는다.
위 메모리는 측정 시간 안의 최근 완료 요청 보고값을 GB에서 GiB로 변환한 관측 범위다.
1초 Sample 사이의 최대값·호스트 전체 메모리·독립된 요청별 할당량은 보장하지 않는다.
고정 Native 구현은 MLX Peak 값을 보고하므로 과거 할당의 영향도 배제하지 않는다.

기존 Exporter는 `peak_memory_gb`를 변환 없이 `_gib`에 노출했다. Native 구현의
`get_peak_memory() / 1e9`를 확인해 `GB * 1e9 / 2**30` 변환과 회귀 테스트를 추가했다.
이 기록의 메모리는 Native 원본에서 변환한 값이며, 측정 중 서비스 Image는 재빌드하지 않았다.

## 실패·중지와 범위

- 최초 준비 시험은 32토큰 출력으로 Gateway Streaming/완료/서버 usage를 확인했다.
  유휴 뒤 첫 Warmup TTFT 약 29.2초가 관측돼 정상 표본의 지연과 섞지 않았다.
- `HF_HUB_OFFLINE=1`에서 로컬 절대 Tokenizer 경로로 실행한 준비 시험은
  HFValidationError와 비정상 종료로 실패했다. 캐시된 Hub ID + 고정 Revision으로
  이후 완료된 실행이 동작했다. 실패를 느린 추론으로 기록하지 않았다.
- long-r2는 사용자 요청에 따라 부하 측정을 중지해 최종 정상 Summary가 없으며 비교에서
  제외했다. Long/Queue 반복과 Concurrent c1은 완료했다고 선언하지 않는다.
- `ACCESS=local`에서 측정했다. 인증 강제 배포·오디오·이미지·도구 호출·Reasoning on·
  장시간/최대 용량·Ubuntu NVIDIA 성능은 이번 표본의 검증 범위가 아니다.
- 일반 CI와 모델 Qualification은 이 숫자를 소비하거나 자동 승격하지 않는다.

원본 JSON/CSV/요청별 JSONL, 합성 inputs, 환경·버전·관측 로그는 Git에서 제외한
`reports/perf/2026-10-19-macos/`에 보관했다. 공유 문서에는 Prompt·응답·키를 싣지 않았다.

단위 확인 근거: [고정 MLX-VLM generation 구현](https://github.com/Blaizzy/mlx-vlm/blob/v0.6.17/mlx_vlm/server/generation.py).
