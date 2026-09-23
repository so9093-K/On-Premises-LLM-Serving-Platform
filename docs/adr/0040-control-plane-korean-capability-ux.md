# ADR-0040: Control Plane은 한국어 우선 vocabulary와 capability 기반 UI를 사용한다

## Status

Accepted

## Context

Control Plane Console은 Linux/NVIDIA managed target과 Linux/macOS static target을 하나의
first-party operator UI로 제공한다. Deployment Target마다 실제 제어 capability는 다르지만
동일한 제품 안에서 운영자가 상태를 이해하고 다음 행동을 결정해야 한다.

초기 Console은 backend contract를 정확하게 노출하는 데 집중하면서
`Operator status`, `Current control state`, `Profile evidence`,
`effective topology`, `Observed container` 같은 implementation vocabulary와 한국어 설명이
한 화면에 혼재했다. 이 방식은 진단 정보는 풍부하지만 정상 운영자가 먼저 답해야 하는
"지금 정상인가", "왜 이 기능이 없는가", "현재 가능한 행동은 무엇인가"를 빠르게 읽기 어렵다.

또한 `macos-metal-static`과 `linux-nvidia-static`은 Main runtime lifecycle을 external owner가
관리하므로 `runtime_control`, `model_switching`, `gpu_admission` capability가 없다.
메뉴가 사라지는 것만으로 표현하면 사용자는 기능 미구현, 권한 부족, 장애, target의 의도적
ownership 차이를 구분하기 어렵다.

## Decision

### 1. 기본 operator language는 한국어다

Control Plane의 navigation, page heading, 상태, action, 도움말과 empty state는
`ko-KR`을 기본으로 한다.

번역은 raw backend 용어의 일대일 치환이 아니라 operator intent를 우선한다.

| Backend / internal concept | Operator 표현 |
|---|---|
| desired state | 원하는 상태 |
| observed state | 실제 상태 |
| profile evidence | 검증 근거 |
| GPU admission | GPU 실행 가능성 |
| lifecycle owner | 관리 주체 |
| resource policy | 리소스 정책 |
| unavailable by composition policy | 정책상 제외 |
| operation | 작업 |

API, GPU, Grafana, Docker, vLLM, MLX 같은 고유 기술명과 service key, profile ID, error code,
revision, digest, request/operation ID는 번역하지 않는다. 사람이 읽는 label을 먼저 표시하고
raw identifier는 secondary text 또는 상세 evidence에서 보존한다.

### 2. 문자열은 semantic presentation layer를 통한다

Console source는 `uiText.ts`에 기본 locale과 공통 vocabulary/presentation helper를 둔다.
현재 제품은 language selector를 추가하지 않지만 `ko-KR` 기본값과 `en-US` fallback을
구조적으로 분리한다.

새 i18n framework나 runtime locale dependency를 지금 추가하지 않는다. 실제 다국어 전환
요구가 생기면 semantic key를 유지한 채 catalog loader를 확장한다.

### 3. target별 UI composition의 authority는 server capability다

Frontend는 OS, hostname, browser user agent 또는 target 이름으로 feature availability를
추론하지 않는다.

```text
Deployment Target
      ↓
Control Plane Bootstrap
      ↓
deployment.features / lifecycle_owner
      ↓
navigation + available actions + explanation
```

`Runtimes`는 `runtime_control`, Main Model control page는 `model_switching` capability가
있을 때만 navigation에 나타난다. Linux/macOS를 이유로 별도 application shell이나 별도 IA를
만들지 않는다.

### 4. capability가 없는 이유를 Overview에서 설명한다

숨긴 action을 무조건 disabled 상태로 복제하지 않는다.

- capability가 실제 제공됨 → **사용 가능**
- external lifecycle owner가 제어하는 runtime/model lifecycle capability → **외부 관리**
- 현재 target의 serving capability에 포함되지 않음 → **제공하지 않음**

따라서 macOS/static target에서 Runtimes/Main Model 메뉴가 없는 것은 기능 미구현이나
권한 오류처럼 보이지 않는다. Overview의 지원 기능과 ownership 설명이 현재 target의
제품 경계를 명시한다.

### 5. 정상 화면은 조용하고 예외를 우선한다

Overview는 정상 상태에서 하나의 운영 상태를 우선 보여준다. 실제 attention signal이 있을
때만 별도 확인 필요 영역을 강조한다. policy/informational state는 장애와 분리한다.

Activity와 Configuration History는 기록이 없을 때 0-count filter/table을 먼저 보여주지 않고
무엇이 기록될 영역인지 설명하는 empty state를 사용한다.

### 6. 기본 화면과 diagnostic evidence의 계층을 분리한다

GPU budget은 percentage와 상한/여유를 먼저 보여주고 raw fraction은 필요한 경우 상세
evidence에서 확인한다. Configuration은 동기화 여부와 current revision을 먼저 보여주며
store/resolver/runtime revision은 상세 영역으로 내린다.

Main Model의 compatibility, qualification evidence, resource policy는 서로 다른 축으로
유지하지만 operator label을 사용한다. service key, profile ID, revision, operation/request ID,
plan digest와 raw verification JSON은 삭제하지 않고 secondary/detail 영역에 유지한다.

## Consequences

| Positive | Negative |
|---|---|
| 한국어 운영자가 화면마다 영어/한국어 mental context를 전환하는 비용이 줄어든다. | 공통 vocabulary와 presentation mapping을 지속적으로 관리해야 한다. |
| macOS/Linux capability 차이가 다른 제품처럼 보이지 않는다. | capability가 추가될 때 Overview 설명과 action mapping도 함께 검토해야 한다. |
| 정상 상태는 간결하고 장애·정책 상태의 우선순위가 분명해진다. | raw backend field를 바로 노출하는 것보다 UI presentation 코드가 늘어난다. |
| API identifier와 diagnostic evidence는 그대로 남아 운영 추적성을 잃지 않는다. | 동일 개념에 operator label과 raw identifier 두 표현을 유지해야 한다. |
| 향후 다국어 지원을 component 전체 재작성 없이 확장할 수 있다. | 현재는 실제 language selector가 없으므로 en-US catalog는 fallback 구조일 뿐 완전 번역을 보장하지 않는다. |

## Operational impact

운영자는 target이 달라도 동일한 navigation vocabulary와 Overview mental model을 사용한다.
static/external target의 메뉴 감소는 Overview의 지원 기능에서 이유를 확인할 수 있다.

UI 문구 변경은 API schema, persisted state, Runtime Controller 또는 Main Model control
semantics를 변경하지 않는다.

## Migration notes

- 기존 English-first page/navigation label은 한국어 operator label로 교체한다.
- raw API/service/profile identifier는 번역하지 않는다.
- 새 UI action은 `deployment.features`를 기준으로만 노출한다.
- OS별 component fork를 만들지 않는다.
- 새 operator-facing 용어를 추가할 때는 `uiText.ts`의 기존 vocabulary와
  `docs/reference/terminology.md`의 canonical technical identifier를 함께 확인한다.

## Related

- [ADR-0020](0020-runtime-control-and-deployment-targets.md)
- [ADR-0027](0027-control-plane-runtime-configuration-and-console-boundary.md)
- [ADR-0035](0035-capability-based-hardware-admission-and-transparent-operations.md)
- [ADR-0039](0039-operator-intent-lifecycle-and-diagnostics.md)
- [용어집](../reference/terminology.md)
