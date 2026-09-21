# vLLM 보안 노출 경계

이 문서는 현재 project-owned vLLM runtime pin에 공개된 upstream request-surface security advisory를
**이 플랫폼의 실제 API/Exposure 계약에 투영**한다. upstream 취약점 목록을 복제하는 문서가 아니라,
어떤 입력이 Gateway를 통과해 runtime에 도달하는지와 어떤 경우 Gateway를 우회하는지를 기록한다.

검토 기준일은 **2026-09-21**이다. 현재 Unified vLLM build input은
`configs/vllm_unified_build.yaml`의 `vllm: 0.25.1`을 사용한다. Upstream advisory의
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

`private_network` exposure mode는 Gateway와 Grafana만 host에 publish하고 vLLM runtime은
Compose network 안에 둔다. 이 경우 아래의 **Gateway 차단**은 실제 외부 request boundary다.

`master_open`은 진단용으로 vLLM runtime port까지 host에 publish한다. 이 경로의 직접 호출은
Gateway의 parameter allowlist, media scheme/size validation, public endpoint 축소를 거치지 않는다.
따라서 아래 표에서 Gateway가 막는 advisory라도 **direct runtime access에는 그 mitigation이 적용되지 않는다**.
`master_open`은 신뢰된 네트워크에서만 사용한다.

## 현재 request-surface advisory 투영

| Advisory | Upstream 영향 | Gateway 경유 | Direct runtime (`master_open`) | 현재 계약 |
|---|---|---|---|---|
| [GHSA-25q3-v2hm-8vpf](https://github.com/vllm-project/vllm/security/advisories/GHSA-25q3-v2hm-8vpf) negative token ID embedding/pooling DoS | vLLM의 token-id input이 음수 ID를 GPU까지 전달할 수 있는 버전이 영향 대상 | **차단** | upstream pin의 영향 그대로 받음 | Public `/v1/embeddings`는 `str | list[str]`만 받고 token-id 배열을 거부한다. Gateway는 `/pooling`을 공개하지 않는다. |
| [GHSA-wpww-v874-ph2p](https://github.com/vllm-project/vllm/security/advisories/GHSA-wpww-v874-ph2p) unbounded `cache_salt` CPU DoS | `<0.29.0` 영향 | **차단** | 0.25.1 direct API에는 upstream 영향이 남음 | Chat/Embedding request parameter allowlist에 `cache_salt`가 없고 Responses도 unknown top-level field를 거부한다. |
| [GHSA-p6g9-7v3x-m8mv](https://github.com/vllm-project/vllm/security/advisories/GHSA-p6g9-7v3x-m8mv) remote/inline media pre-limit materialization | 0.25.1에서 확인된 media acquisition resource exhaustion | **remote fetch 차단, inline payload bounded** | upstream 영향 그대로 받음 | Main Model profile은 image/video URL scheme을 `data`로 제한하고 audio는 raw base64 `input_audio`만 받는다. Gateway는 request body, decoded image/audio/video bytes와 item count를 제한한다. 이 제한은 upstream decoder 자체의 안전성을 대체하지 않는다. |
| [GHSA-jcq2-4gch-5qhf](https://github.com/vllm-project/vllm/security/advisories/GHSA-jcq2-4gch-5qhf) multimodal chat audio compressed-size enforcement gap | chat audio path의 upstream size control이 acquisition/decode 전에 완전하지 않은 버전이 영향 대상 | **bounded** | upstream 영향 그대로 받음 | Gateway가 `input_audio`를 최대 1개, decoded compressed payload 25 MB 이하로 제한하며 전체 request body도 100 MB로 제한한다. Gateway도 base64를 검증하기 위해 bounded payload를 메모리에 materialize하므로 “zero allocation” 방어는 아니다. |
| [GHSA-87x5-vmc3-756j](https://github.com/vllm-project/vllm/security/advisories/GHSA-87x5-vmc3-756j) completion prompt-list fanout | `>=0.19.0,<0.26.0` 영향 | **비노출** | 0.25.1 direct `/v1/completions`에는 upstream 영향이 남음 | Gateway는 legacy `/v1/completions`를 공개하지 않는다. |
| [GHSA-pr7f-p5mw-fc87](https://github.com/vllm-project/vllm/security/advisories/GHSA-pr7f-p5mw-fc87) concurrent `prompt_embeds` validation bypass | `>=0.21.0,<0.26.0` 영향 | **비노출** | 0.25.1 direct API에는 upstream 영향 가능 | Gateway chat/Responses content contract는 `prompt_embeds`를 공개하지 않는다. |
| [GHSA-99f2-hwrc-gvq8](https://github.com/vllm-project/vllm/security/advisories/GHSA-99f2-hwrc-gvq8) speech-to-text decode duration bypass | `<0.28.0`의 transcription-capable endpoint가 영향 대상 | **비노출** | 해당 model/runtime이 transcription route를 mount하면 upstream 영향 가능 | Gateway는 `/v1/audio/transcriptions`를 공개하지 않는다. Main Model의 audio는 Chat content part로만 공개한다. |

## Regression invariant

현재 0.25.1 pin을 유지하는 동안 다음 사실이 깨지면 upstream advisory reachability를 다시 평가해야 한다.

- Embedding API가 caller-supplied token ID 배열을 받지 않는다.
- Chat/Embedding parameter allowlist와 Responses top-level schema가 `cache_salt`를 upstream으로 전달하지 않는다.
- Main Model의 public image/video URL scheme은 `data` only다.
- Public audio input은 `input_audio.data` raw base64이며 remote `audio_url` surface를 만들지 않는다.
- Gateway request-body/media byte/item limit이 runtime 호출 전에 적용된다.
- Gateway가 `/v1/completions`, `/pooling`, `/v1/audio/transcriptions`를 public route로 추가하지 않는다.
- `master_open`의 direct model runtime access는 Gateway mitigation 바깥의 trusted diagnostic boundary다.

`tests/unit/test_vllm_security_exposure.py`는 이 중 request-contract로 직접 고정할 수 있는
negative token ID, `cache_salt`, remote media URL 경계를 보호한다. Exposure topology의
host-publish 집합은 `configs/exposure_profiles.yaml`이 계속 authority다.

## Engine upgrade 판단

Gateway mitigation은 현재 public API의 blast radius를 줄이는 방어층이지 vulnerable upstream
engine을 patched 상태로 재분류하는 근거가 아니다. 특히 `master_open`처럼 runtime을 직접
publish하는 mode에는 적용되지 않는다.

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
