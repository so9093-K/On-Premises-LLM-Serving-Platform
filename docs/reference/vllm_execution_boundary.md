# vLLM execution boundary 재평가 (#195)

2026-10-03, vLLM 0.30.0 기준 조사. 현재 managed Docker 계약과 external lifecycle의
native 실행 가능성을 구분한다. 단발 실험의 원시 로그는 로컬 `reports/runtime/`에 두고,
재현 조건·결과·한계는 이 문서와 PR에 기록한다. ADR-0042의 방침대로 별도
machine-readable qualification evidence나 성능 benchmark 체계는 만들지 않는다.

## Docker 기준선

- source: main `94c1fe5a`에 #221/#222의 runtime별 persistent compile cache 반영.
- host: RTX 4090 24 GiB, NVIDIA driver 580.178.04, Docker 29.8.1.
- model: `google/gemma-4-E4B-it`, revision `ee0ef6023621cff504d758262d4e04895a5af4a2`.
- profile: `gemma4-e4b-it`, `rtx4090-24gb`; max length 65000, sequences 4,
  batched tokens 4096, GPU utilization 0.76, canonical template/parser/structured-output 설정.
- artifact: Unified image `sha256:a52fc4ea3d140bc7e712a6dee79a0204d5ec6122bdb415e41a568bba0f207c4e`.
- upstream base: `vllm/vllm-openai@sha256:5f5e535216848d0c52159c8c13a0af04be5f6fe1a84e79914300610796f76d40`.
- 재조회한 package metadata: vLLM 0.30.0, Transformers 5.17.0, Hub 1.32.0,
  Torch 2.13.0+cu130, torchvision 0.28.0+cu130.

| 실행 | container 시작→health (s) | 첫 text (s) | 첫 schema (s) | torch.compile (s) | startup device peak (MiB) |
|---|---:|---:|---:|---:|---:|
| compile cache empty | 151.799 | 0.813 | 0.711 | 39.26 | 19364 |
| down/up, cache 유지 | 101.039 | 0.042 | 0.689 | 0.91 | 19531 |
| same-profile backend replace | 102.535 | 0.058 | 0.858 | 0.64 | 19416 |
| 실패 candidate 후 template 복구 | 100.024 | 0.045 | 0.694 | 0.62 | 19425 |

HF model은 이미 cached였으며 OS page cache는 통제하지 않았다. cache-cold 1회와 서로 다른
warm lifecycle 3회의 관찰이다. warm마다 같은 경로의 `Directly load AOT compilation`을
확인했지만 startup 차이 전체를 compile cache 효과로 돌리거나 throughput 향상을 주장하지 않는다.
VRAM은 1초 간격 device 전체 표본으로 desktop을 포함한다. 실행 후 19,315–19,483 MiB,
전체 stop 후 약 1.1 GiB로 돌아왔고 vLLM process는 남지 않았다.

실패 실험은 잘못된 CLI flag로 종료된 candidate를 제거한 뒤 같은 backend의 저장된 creation
template로 복구한 것이다. 실제 cross-profile switch나 Gateway journal 자동 rollback 증거는 아니다.
현재 4090 variant가 허용하는 Main profile은 E4B 하나다.

Gateway validation은 37 pass / 0 fail / 1 unsupported named-tool-choice skip였다.
text/image/audio/video/streaming/reasoning/schema/tool-auto, 두 embeddings, health/metrics를 포함한다.
raw Runtime의 HostPortBindings는 비어 있고 내부 bridge 주소로만 호출했다.
프로비저닝은 이미 존재하는 image/model cache를 사용했으므로 최초 다운로드·image build 시간은
이 startup 표에 포함하지 않는다. Docker inspect/logs/health, image ID/digest, compile volume으로
artifact와 lifecycle을 연결할 수 있다.

## stock / thin overlay와 패치

동일 digest의 **수정하지 않은** upstream image를 새 disposable container에서 확인했다.

| 항목 | 0.30.0 확인 결과 | 판단 |
|---|---|---|
| media dependencies | 공식 base의 `soundfile` package metadata 없음 | audio/video workload에 curated media overlay 유지 |
| Gemma4 unified vision | 기존 `quant_config=quant_config` patch anchor 존재 | 12B vision 수정 유지; source audit만으로 제거 불가 |
| Gemma4 unified audio | `fft_length` 추가 patch 적용됨 | audio warmup 수정 유지 |
| streaming reasoning 시작 상태 | patch script가 `reasoning_fix=upstream` 판정 | 이미 upstream 동작 확인만 수행; 중복 backport 없음 |
| streaming `<turn\|>` | `turn_end=applied` | local terminal 흡수 수정 유지 |
| Kanana head_dim | stock `LlamaConfig(hidden_size=1792, num_attention_heads=24, head_dim=128)`가 validation error | guard 유지 |
| Kanana BnB | 별도 `vllm-bnb-plugin==0.0.3`, `bitsandbytes==0.49.2` 경계 | hash-pinned plugin overlay 유지 |

패치 적용 성공은 해당 upstream source가 여전히 미수정이라는 증거다. 각 패치의 완전한
unpatched GPU A/B를 새로 수행했다는 의미는 아니다. #210의 실제 workload qualification과
이번 stock config 실패/source audit를 함께 사용하며, 패치 제거를 승인하지 않는다.

현재 image는 pinned official image 위에 media/BnB와 현재 제거를 승인할 근거가 없는 compatibility patch set을 올리는 제한된 overlay다.
Docker inspect의 image size는 base 30,729,512,364 bytes, Unified 31,557,039,874 bytes
(차이 827,527,510 bytes). 이는 Docker가 보고한 크기이며 전송 압축 크기나 실제 공유 disk 사용량은 아니다.
"thin"이라는 이름만 바꾸면 유지해야 할 코드·dependencies가 줄어들지는 않는다.

## Supporting Runtime Sleep/Wake

동일 Unified image, 별도 disposable container, published port 없음,
`--enable-sleep-mode`, `VLLM_SERVER_DEV_MODE=1`, `POST /sleep?level=1` 후 전체 wake를 사용했다.
각 runtime은 단독 실행했고 baseline desktop VRAM은 약 1050 MiB였다.

| Runtime | boot (s) | active / asleep / stopped device MiB | sleep / wake (s) | 복귀 응답 |
|---|---:|---|---|---|
| embeddinggemma | 48.44 | 2595 / 1968 / 1056 | 0.387 / 0.039 | 동일 vector, max abs diff 0 |
| Korean embedding | 41.11 | 2727 / 1596 / 1053 | 0.647 / 0.070 | 동일 vector, max abs diff 0 |
| Kanana | 39.19 | 4840 / 1562 / 1045 | 0.878 / 0.102 | 전후 `<UNSAFE-A1>` |

embedding은 canonical CLI, Kanana는 단독 GPU 초기화를 위해 utilization 0.16을 사용했다
(canonical 0.065와 다름). Kanana 입력은 system prompt/credentials 유출 지시,
`temperature=0`, `max_tokens=1`, logprobs 켬. 각 1회이며 장시간 반복·동시 요청·OOM 복구는 검증하지 않았다.

셋 모두 asleep 상태에서 `/is_sleeping=true`이고 `/health=200`이었다. sleep은 stop과 달리
CUDA context 등 VRAM을 남긴다. 따라서 현재 readiness/container running 관찰만으로는
serving 가능 여부를 판정할 수 없고, stop처럼 GPU 전량 회수를 가정할 수도 없다.

**현재 stop/start 대체는 채택하지 않는다.** 기능은 동작하지만 production 도입에는 request drain/gate,
잠든 상태·wake 실패 reconciliation, 남은 GPU/CPU memory admission, controller 전용 제어 접근이 필요하다.
개발 endpoint 전체를 활성화하는 비용도 있다. 기존 controller API에 단순히 sleep 호출을 끼우면
운영 계약이 맞지 않는다. Level 2는 weight reload까지 필요해 이번 빠른 idle 복귀 비교에서 제외했다.

## Native Main spike

기존 `linux-nvidia-static` external lifecycle을 그대로 사용했다. Gateway/Risk Signal Service는
Docker static stack, Main Runtime만 host의 dedicated venv(Python 3.12.3, `uv`)에서 실행했다.
command는 현재 profile renderer 출력에서 host/port/template 경로만 바꿨다. 같은 model revision과
HF cache(`HF_HUB_OFFLINE=1`)를 사용했고 별도 `VLLM_CACHE_ROOT`를 두었다.

### 환경 준비

| 단계 | 결과 |
|---|---|
| `uv pip install vllm==0.30.0` | 198 packages, 다운로드·준비 11분 39초, venv 8.2 GiB |
| media/BnB lock과 세 patch script | Docker build와 같은 결과(`patch_dense`+`fft_length`, `reasoning_fix=upstream turn_end=applied`, head_dim `applied`), `pip check` 통과 |
| 첫 기동 | **실패**. warmup sampling에서 FlashInfer가 kernel JIT를 시도했고 `ninja`가 없어 `FileNotFoundError` |
| 원인 | 공식 image에는 `flashinfer-cubin`, `flashinfer-jit-cache 0.6.18.post1+cu130`, `ninja`, CUDA 13.0 `nvcc`가 있다. PyPI `vllm` 의존성에는 이것들이 없고 host toolkit은 CUDA 11.8이라 JIT fallback도 맞지 않는다 |
| 복구 | FlashInfer GitHub release의 두 wheel(합계 약 2.5 GiB, sha256 기록)을 `--no-deps` 설치. jit-cache hash는 FlashInfer index 값과 일치. `flashinfer-cubin 0.6.18.post1`은 PyPI에 없다 |

복구 후에도 package set은 image와 같지 않다. 정규화한 freeze 기준 image 281개, native 215개이며
공통 213개 중 44개 버전이 다르다(예: `cuda-bindings` 13.4.2→13.4.3, `nvidia-nccl-cu13`
2.30.7→2.29.7, `xgrammar` 0.2.7→0.2.8, `numpy` 2.2.6→2.3.5). vLLM wheel도 image는 build 산출물,
native는 PyPI wheel이다. 따라서 "같은 vLLM 0.30.0"이라도 native는 별도로 lock·qualify해야 하는
두 번째 runtime artifact다.

### 실행 결과

| 실행 | process 시작→health (s) | 첫 text (s) | 첫 schema (s) | torch.compile (s) | startup device peak (MiB) | stop 후 (MiB) |
|---|---:|---:|---:|---:|---:|---:|
| compile cache empty | 102.117 | 0.797 | 0.626 | 36.13 | 19319 | 1027 |
| restart, cache 유지 | 55.057 | 0.042 | 0.603 | 0.58 (AOT direct load) | 19318 | 1031 |

KV cache(2.13 GiB, 104,289 tokens)와 steady VRAM은 Docker와 같았다. native 측정은 직전 cold 실행으로
page cache가 데워진 상태였고 Docker와 같은 날 같은 조건으로 번갈아 측정하지 않았다. 각 1회이므로
startup 차이를 execution 방식의 고유 이점으로 보지 않는다. 로그상 Docker warm은 engine process
spawn/import(36s 대 23s), model load(9.5s 대 3.6s), profiling 구간이 길었다. 이 차이는 execution 경계가 아니라
Docker 실행 안에서 원인을 확인할 대상이다.

Gateway validation(같은 script): **26 pass / 7 fail / 1 skip**. Main의 text/image/audio/video/streaming/
reasoning/schema/logprobs/tool-auto와 main metrics는 모두 통과했다. 실패 7개 중 6개는 static stack에
embedding Runtime과 Prometheus/Grafana가 없어서 생긴 범위 차이다. 나머지 1개 `main runtime artifact`는
controller observed state의 image ID/digest를 요구하는 provenance 계약이며, native에는 대응 identity가
없어 실패한다. 이는 static stack 범위 문제가 아니라 계약 공백이다.

### Network와 supervision 관찰

- Runtime을 `issue195-native` bridge gateway 주소(`172.18.0.1:19401`)에만 bind했다. LAN 주소와 loopback에서는
  연결되지 않았고 Gateway container에서는 연결됐다.
- 그러나 **무관한 default bridge container에서도 `/health` 200**이었다. host 주소 bind는 해당 host에서
  route 가능한 모든 container에 열린다. Docker Main은 Compose internal network 구성원만 접근한다.
  같은 경계를 유지하려면 host firewall 규칙 또는 UDS와 Gateway transport 변경을 추가로 소유해야 한다.
- API server(PID)만 `SIGKILL`하자 `VLLM::EngineCore`와 helper process가 user systemd로 재부모화됐다.
  70초 이상 18.8 GiB를 계속 점유하고 port는 닫혔다. process group 전체 `SIGTERM` 후 1026 MiB로 회수됐다.
  managed native라면 PID가 아니라 process group/cgroup 단위의 소유, crash 후 잔여 VRAM 탐지, 재시작
  전 회수가 필수다. Docker에서는 container 종료가 이 범위를 정의한다.

## 운영 경계 비교

| 책임 | 현재 Docker + 필수 overlay | managed native를 선택할 때 필요한 것 |
|---|---|---|
| private network | raw port publish 없음, internal service DNS | loopback은 Docker Gateway에서 바로 못 씀; 전용 bridge bind 또는 공유 UDS와 transport 설정 필요 |
| provenance | digest/image ID, source labels, inspect, patch metadata | Python executable/환경 경로, wheel/dependency lock, patch·template hash, system CUDA/OS 의존성과 실행 argv 묶기 |
| process identity | container ID와 Compose ownership label | PID 재사용 방지, process group/cgroup 소유권, worker·자식 process까지 회수 |
| supervision | restart policy, health, logs, controller reconcile | systemd 등 supervisor와 controller observed state의 일관된 소유 경계 |
| replace / rollback | creation template, immutable image, volume 보존 | 이전 immutable environment/config 보존, atomic 선택, validation 실패 복구 |
| GPU admission | controller의 기존 runtime state와 start/stop 계약 | 외부 process와 crash 잔여 VRAM 탐지까지 결합; native 자체가 GPU 메모리를 덜 쓰는 것은 아님 |
| logs / metrics | container logs + 기존 scrape 경로 | journald/file rotation, process identity별 log projection, endpoint health/metrics 유지 |
| authority | controller의 Docker socket은 강한 host authority(ADR-0031) | socket 제거 가능하지만 supervisor 제어 권한, runtime user, 모델 코드의 host 파일 접근을 새로 제한해야 함 |
| isolation | container filesystem/mount/network boundary; GPU·host kernel 공유 | venv는 dependency 분리일 뿐 보안 sandbox가 아님; `trust_remote_code`는 실행 user 권한으로 동작 |

현재 Gateway RuntimeClient는 일반 HTTP client를 생성하며 Runtime UDS transport를 설정하는
경로가 없다. vLLM의 `--uds` 제공만으로 현재 Gateway 연결이 자동 전환되지는 않는다.
UDS를 채택하려면 socket directory의 uid/gid/mode, mount, stale socket cleanup, 재시작 시
client 재연결까지 소유해야 한다. native 단독 실행 성공을 managed lifecycle 동등성으로 보지 않는다.

## 결정

**Docker 유지.** 현재 pinned official image + 검증된 overlay(media, BnB plugin, compatibility patch set) 구조를 유지하고,
managed native와 Sleep/Wake 기반 lifecycle은 채택하지 않는다. 이번 조사는 기존 patch의 완전한 unpatched GPU A/B가 아니므로
overlay가 절대 최소라고 단정하지 않고, 현재 제거를 승인할 근거가 없다는 결론으로 제한한다.

| 후보 | 판단 | 근거 |
|---|---|---|
| Docker 유지 | 채택 | 37/0 validation, digest 기반 provenance, internal network, container 단위 회수, compile cache로 warm 재시작 단축(#222) |
| thin Docker | 별도 전환 안 함 | stock image는 media dependency와 Kanana head_dim에서 실패. 이번 조사에서는 기존 overlay 제거를 승인할 근거가 없어 현재 제한된 overlay를 유지 |
| managed native | 기각 | Issue 판단 기준 중 private boundary 약화, provenance 계약 공백, custom supervisor 소유, image와 다른 dependency set 네 가지에 해당 |
| Sleep/Wake | 보류 | 기능은 동작하지만 VRAM 일부 잔존, `/health` 의미 변화, dev endpoint 필요. 현 stop/start 계약 대체 불가 |

native는 Docker가 제공하던 책임(artifact 조립, network 격리, process tree 회수, identity)을 project 코드와
host 설정으로 옮길 뿐 전체 소유 complexity를 줄이지 않는다. Docker socket authority 제거라는 이점은
supervisor 제어 권한과 host 파일 접근 제한을 새로 소유하는 비용보다 작다.

현재 구조와 ADR-0031이 그대로 유지되므로 새 ADR은 작성하지 않는다. 다음 조건이 생기면 재평가한다.

- 대상 host에서 Docker를 사용할 수 없거나, Docker 자체가 측정 가능한 병목으로 확인됨
- upstream이 FlashInfer prebuilt kernel을 포함한 재현 가능한 lock 경로를 제공하고, project patch가 upstream에 흡수됨
- Gateway가 Runtime 전용 UDS transport를 이미 필요로 하는 경우

## 관련 자료

- [Issue #195](https://github.com/so9093-K/On-Premises-LLM-Serving-Platform/issues/195)
- [Docker compile-cache 실측 #222](https://github.com/so9093-K/On-Premises-LLM-Serving-Platform/pull/222)
- [vLLM Sleep Mode](https://docs.vllm.ai/en/latest/features/sleep_mode/)
- [vLLM GPU installation](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)
- [ADR-0031 Docker authority](../adr/0031-runtime-controller-docker-authority-boundary.md)
- [FlashInfer v0.6.18.post1 release](https://github.com/flashinfer-ai/flashinfer/releases/tag/v0.6.18.post1)
