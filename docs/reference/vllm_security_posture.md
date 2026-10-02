# vLLM 보안 노출 경계

이 문서는 현재 project-owned vLLM runtime pin에 공개된 upstream request-surface security advisory를
**이 플랫폼의 실제 API/Exposure 계약에 투영**한다. upstream 취약점 목록을 복제하는 문서가 아니라,
어떤 입력이 Gateway를 통과해 runtime에 도달하는지와 어떤 경우 Gateway를 우회하는지를 기록한다.

> Security review contract: `engine=0.30.0`, `reviewed_at=2026-10-02`.

위 한 줄은 engine pin과 이 문서의 advisory reachability 검토가 같은 변경에서 갱신됐음을
`make validate`가 확인하는 machine-readable review boundary다. 단순 버전 문자열 동기화가
아니며, pin이 바뀌면 아래 Gateway/direct-runtime exposure를 다시 검토한 뒤 갱신한다.

검토 기준일은 **2026-10-02**이다. Unified vLLM build candidate는
`configs/vllm_unified_build.yaml`의 `vllm: 0.30.0`을 사용한다. 공식
`v0.30.0` CUDA 13.0 linux/amd64 manifest digest는
`sha256:5f5e535216848d0c52159c8c13a0af04be5f6fe1a84e79914300610796f76d40`이다.
이미지 내부에서 vLLM `0.30.0`, Transformers `5.17.0`, huggingface_hub `1.32.0`을
확인했다. 이 값은 base artifact의 검토 결과이며 derived image의 runtime canary와
운영 승격은 별도로 수행한다. Upstream advisory의
affected/patched range가 바뀌거나 runtime pin이 변경되면 이 문서의 reachability를 다시 검토한다.

## 보안 경계

일반 제품 경로는 Gateway가 request contract를 검증한 뒤 내부 Model Runtime을 호출하는 구조다.

```text
Client
  ↓
Gateway request validation
  ↓
Model Runtime
```

Canonical host boundary는 Gateway와 target의 Grafana만 host에 publish하고 vLLM runtime은
Compose network 안에 둔다. 이 경우 아래의 **Gateway 차단**은 실제 외부 request boundary다.

vLLM runtime port는 지원되는 host surface에 publish하지 않는다. 따라서 외부 client의
지원 경로는 Gateway 하나이며 아래 Gateway 차단이 실제 public request boundary다.
Compose 내부의 raw runtime 자체는 upstream engine이므로, 내부 주체가 직접 호출하거나
runtime이 침해된 경우에는 Gateway mitigation을 적용받지 않는다는 구분은 유지한다.

## 현재 request-surface advisory 투영

| Advisory | Upstream 영향 | Gateway 경유 | Compose-internal raw runtime | 현재 계약 |
|---|---|---|---|---|
| [GHSA-25q3-v2hm-8vpf](https://github.com/vllm-project/vllm/security/advisories/GHSA-25q3-v2hm-8vpf) negative token ID embedding/pooling DoS | 0.28.0부터 패치 | **차단 유지** | 후보 버전에서 패치 | Public `/v1/embeddings`는 `str | list[str]`만 받고 token-id 배열을 거부한다. Gateway는 `/pooling`을 공개하지 않는다. |
| [GHSA-wpww-v874-ph2p](https://github.com/vllm-project/vllm/security/advisories/GHSA-wpww-v874-ph2p) unbounded `cache_salt` CPU DoS | 0.29.0부터 패치 | **차단 유지** | 후보 버전에서 패치 | Chat/Embedding request parameter allowlist와 Responses schema는 caller `cache_salt`를 거부한다. |
| [GHSA-p6g9-7v3x-m8mv](https://github.com/vllm-project/vllm/security/advisories/GHSA-p6g9-7v3x-m8mv) remote/inline media pre-limit materialization | 0.29.0 이하 영향, 0.30.0 후보는 패치 범위 | **remote fetch 차단, inline payload bounded 유지** | 후보 버전에서 패치 | Main Model은 image/video URL을 `data`로 제한하고 audio는 raw base64만 받는다. Gateway의 body, decoded media byte/item 상한도 유지한다. |
| [GHSA-jcq2-4gch-5qhf](https://github.com/vllm-project/vllm/security/advisories/GHSA-jcq2-4gch-5qhf) chat audio size limit gap | 0.29.0부터 패치 | **bounded 유지** | 후보 버전에서 패치 | Gateway는 `input_audio` 1개, decoded payload 25 MB, 전체 body 100 MB 상한을 적용한다. |
| [GHSA-85xf-c7hm-whqw](https://github.com/vllm-project/vllm/security/advisories/GHSA-85xf-c7hm-whqw) structured-output engine-fatal errors | 0.30.0부터 패치 | **schema 제한 유지** | 후보 버전에서 패치 | Gateway의 response format 계약과 잘못된 schema 거부를 회귀 검증한다. |
| [GHSA-x6mc-67gf-chw4](https://github.com/vllm-project/vllm/security/advisories/GHSA-x6mc-67gf-chw4) Qwen video sampler frame amplification | 0.30.0 tag의 Qwen2/3-VL sampler에 `max_frames`·`fps` 상한 확인 | **request-level sampler override 차단** | 후보 tag에서 해당 상한 확인 | Gateway는 `media_io_kwargs`를 거부하고 video byte/frame/duration 상한을 둔다. 권고의 affected range 표기(`>=0.24.0`)는 patched range(`>=0.30.0`)와 겹치므로 실제 tag 코드를 검토했다. |
| [GHSA-87x5-vmc3-756j](https://github.com/vllm-project/vllm/security/advisories/GHSA-87x5-vmc3-756j) completion prompt-list fanout | 후보 버전에서 패치 | **비노출 유지** | 후보 버전에서 패치 | Gateway는 legacy `/v1/completions`를 공개하지 않는다. |
| [GHSA-pr7f-p5mw-fc87](https://github.com/vllm-project/vllm/security/advisories/GHSA-pr7f-p5mw-fc87) concurrent `prompt_embeds` bypass | 후보 버전에서 패치 | **비노출 유지** | 후보 버전에서 패치 | Gateway는 `prompt_embeds`를 공개하지 않는다. |
| [GHSA-99f2-hwrc-gvq8](https://github.com/vllm-project/vllm/security/advisories/GHSA-99f2-hwrc-gvq8) speech-to-text duration bypass | 0.28.0부터 패치 | **비노출 유지** | 후보 버전에서 패치 | Gateway는 `/v1/audio/transcriptions`를 공개하지 않는다. |

2026-09-23 이후 공개된 권고 중 LMCache-MP `cache_salt`
([GHSA-2823-qmq8-rwvj](https://github.com/vllm-project/vllm/security/advisories/GHSA-2823-qmq8-rwvj)),
scale-out disaggregated multimodal transport
([GHSA-ph72-cqr5-qpp7](https://github.com/vllm-project/vllm/security/advisories/GHSA-ph72-cqr5-qpp7)),
Harmony tool continuation
([GHSA-935w-9g4m-p28p](https://github.com/vllm-project/vllm/security/advisories/GHSA-935w-9g4m-p28p))도
0.30.0 패치 범위로 기록돼 있다. 이 플랫폼은 LMCache-MP, scale-out, Harmony profile을
구성하지 않으며 Gateway는 caller `cache_salt`를 받지 않는다. Rust frontend metrics,
GLMGA sampler, Flash scoring 권고도 현재 배포 경로 밖이다. 새 profile이나 raw runtime
surface가 추가되면 이 판단을 다시 검토한다.

별도의 upstream [video `num_frames` ceiling PR](https://github.com/vllm-project/vllm/pull/51969)은
검토 시점에 열려 있다. 이 변경은 Qwen sampler의 `max_frames`/`fps` 상한과 다른 경로다.
Gateway는 `media_io_kwargs`를 전달하지 않지만 내부 raw runtime은 Gateway 경계 밖이므로
후속 upstream 상태와 직접 접근 가능성을 계속 확인한다.

## Regression invariant

현재 0.30.0 후보와 이후 pin을 유지하는 동안 다음 사실이 깨지면 upstream advisory reachability를 다시 평가해야 한다.

- Embedding API가 caller-supplied token ID 배열을 받지 않는다.
- Chat/Embedding parameter allowlist와 Responses top-level schema가 `cache_salt`를 upstream으로 전달하지 않는다.
- Chat/Responses schema가 `media_io_kwargs`를 upstream으로 전달하지 않는다.
- Main Model의 public image/video URL scheme은 `data` only다.
- Public audio input은 `input_audio.data` raw base64이며 remote `audio_url` surface를 만들지 않는다.
- Gateway request-body/media byte/item limit이 runtime 호출 전에 적용된다.
- Gateway가 `/v1/completions`, `/pooling`, `/v1/audio/transcriptions`를 public route로 추가하지 않는다.
- raw model runtime은 host에 publish하지 않으며, 내부 direct access는 Gateway mitigation 바깥의 Compose-internal boundary다.

`tests/unit/test_vllm_security_exposure.py`는 이 중 request-contract로 직접 고정할 수 있는
negative token ID, `cache_salt`, remote media URL 경계를 보호한다. Host-publish 집합은
`configs/services.yaml` service role과 target Compose `ports`의 정합성 검증이 authority다.

## Engine upgrade 판단

Gateway mitigation은 현재 public API의 blast radius를 줄이는 방어층이지 vulnerable upstream
engine을 patched 상태로 재분류하는 근거가 아니다. Raw runtime 자체에는 Gateway mitigation이
적용되지 않으므로 내부 경계와 engine upgrade 검토는 계속 별도로 유지한다.

따라서 vLLM 변경은 “새 GPU마다 다시 qualification”하는 방식이 아니라 다음 순서로 검토한다.

```text
upstream security/engine candidate
        ↓
advisory reachability 재평가
        ↓
Gateway contract + adversarial regression
        ↓
model parser / tool / structured-output compatibility
        ↓
bounded runtime canary
        ↓
runtime image pin 변경
```

Engine pin을 올릴 때는 단일 “latest” 버전 숫자만 보고 결정하지 않는다. candidate release가
현재 relevant advisory를 실제로 patch하는지와 project-specific Gemma/Qwen parser, structured
output, multimodal contract를 함께 확인한다.
