# ADR-0066: Runtime Controller 관리형 Main Model의 서버 토큰 한도 변경

Status: Accepted

## Context

기존 Main Model Catalog는 프로필 ID를 기준으로 실행 엔진의 argv와 Gateway 요청 정책을 함께 소유한다. Console에서 임의 숫자를 입력만 할 수 있게 만들면 Runtime·Gateway 불일치, 재시작 설정 유실, 실패 뒤 잘못된 Gate 개방으로 이어질 수 있다.

## Decision

- 이미지·모델 ID·Revision·기본 GPU 예약 등 신원/자원 정책은 선언된 기준 프로필이 계속 소유한다.
- 운영자는 서버 `context_tokens`와 `max_output_tokens`만 요청한다. CPU는 동일 GGUF의 최대 선언 프리셋 이하, GPU는 기준 프로필의 문맥 이하에서만 변경한다. 미검증 설정은 명시적인 확인이 필요하다.
- Runtime Controller는 기준 프로필과 숫자 한도에서 결정적 파생 프로필 ID, 실행 argv, Gateway admission 정책을 생성한다. 그 내용을 기존 Main Model state의 `runtime_limit_profiles`에 저장하고 재시작에 재구성해 신원·한도 무결성을 다시 검사한다.
- 같은 기준 프로필과 한도 조합은 결정적 ID로 재사용한다. 파생 설정의 영속 기록은 현재 활성·마지막 정상·직전 정상 실행과, 재검증 또는 Rollback 실패로 관측 신원을 확정할 수 없는 현재 작업에 필요한 것만 남긴다. 과거 성공·실패 작업은 `operations` 이력으로 별도 조회하며, 이를 보존하려고 실행 프로필을 무한히 누적하거나 개수 기반 GC를 운영하지 않는다. 실제 Runtime을 확정하지 못하면 파생 신원을 보존하고 Gate를 닫는다.
- 변경은 기존 MainModelManager의 Gate/Drain/Replace/Canary/Commit/Rollback 작업으로만 수행한다. Compose·Docker 제어 권한은 Gateway에 추가하지 않는다.
- 새 관리형 CPU 전용 설치는 공통 `linux-nvidia-dynamic POLICY=cpu`를 사용하며, CPU/GPU의 실행 변경은 Runtime Controller가 소유한다. `linux-cpu-managed`·`linux-adaptive`는 기존 설치의 명시적 이전을 기다리는 호환 Target이다. 기존 Compose CPU에는 Controller API를 지원하는 척하지 않으며, Static·external도 읽기 전용이다.
- `cpu-gguf-text-compact`와 `cpu-gguf-text-extended` 식별자는 기존 활성/저장 프로필 복원을 위해 유지한다. 신규 직접 편집은 동일 GGUF의 파생 실행 구성으로 구현하고 원본 모델 가중치는 중복 설치하지 않는다.
- 직접 토큰 한도 편집은 명시적 CPU 고정·GPU 고정 정책에서 제공한다. GPU 우선·CPU 복구(`fallback`)와 자동 복귀(`automatic`)의 실행 후보 및 복구 의미는 기존 정책이 계속 소유한다.
- OpenAPI는 고정 프로필의 출력을 초과하는 관리형 사용자 한도를 허용할 수 있으므로, 동적 환경에서는 정적 최대 출력값을 보증하지 않는다. 활성 프로필의 정확한 요청 제한은 `GET /v1/models`가 제공하고 Gateway가 적용 시 검증한다.
- Runtime 변경 가능 여부와 실제 하드웨어의 충분한 성능은 다르다. 과거 검증 결과를 새로운 한도 설정의 성능 보증으로 사용하지 않는다.

## Consequences

새 설정으로의 모델 적재 실패 또는 Canary 실패 시 이전 정상 프로필의 실행 인자·요청 한도까지 복원을 시도한다. 복구 검증에 실패하면 Gate를 닫고 해당 파생 실행 기록을 보존한다. 불변 ID와 지속 상태는 기존 Controller state의 일부이며 별도 저장소를 추가하지 않는다. GPU 문맥 상향은 별도 자원 admission 계약 전까지 허용하지 않는다.
