# ADR-0066: Runtime Controller 관리형 Main Model의 서버 토큰 한도 변경

Status: Accepted

## Context

기존 Main Model Catalog는 프로필 ID를 기준으로 실행 엔진의 argv와 Gateway 요청 정책을 함께 소유한다. Console에서 임의 숫자를 입력만 할 수 있게 만들면 Runtime·Gateway 불일치, 재시작 설정 유실, 실패 뒤 잘못된 Gate 개방으로 이어질 수 있다.

## Decision

- 이미지·모델 ID·Revision·기본 GPU 예약 등 신원/자원 정책은 선언된 기준 프로필이 계속 소유한다.
- 운영자는 서버 `context_tokens`와 `max_output_tokens`만 요청한다. CPU는 동일 GGUF의 최대 선언 프리셋 이하, GPU는 기준 프로필의 문맥 이하에서만 변경한다. 미검증 설정은 명시적인 확인이 필요하다.
- Runtime Controller는 기준 프로필과 숫자 한도에서 결정적 파생 프로필 ID, 실행 argv, Gateway admission 정책을 생성한다. 그 내용을 기존 Main Model state의 `runtime_limit_profiles`에 저장하고 재시작에 재구성해 신원·한도 무결성을 다시 검사한다.
- 같은 기준 프로필과 한도 조합은 기존 파생 ID를 재사용한다. 지속 상태는 최대 32개를 유지하며 초과 시 가장 오래된 비활성 변형부터 제거한다. 현재 활성·마지막 정상·직전 정상 프로필과 진행 중인 전환 대상은 복구를 위해 보존한다. 이 정리는 실행 중인 컨테이너를 변경하지 않는다.
- 변경은 기존 MainModelManager의 Gate/Drain/Replace/Canary/Commit/Rollback 작업으로만 수행한다. Compose·Docker 제어 권한은 Gateway에 추가하지 않는다.
- `linux-cpu-managed`는 별도 Compose 수명주기 소유권을 유지하므로 Runtime Controller 전환 API가 직접 제어하지 않는다. Static·external도 읽기 전용으로 둔다.
- Runtime 변경 가능 여부와 실제 하드웨어의 충분한 성능은 다르다. 과거 검증 결과를 새로운 한도 설정의 성능 보증으로 사용하지 않는다.

## Consequences

새 설정으로의 모델 적재 실패 또는 Canary 실패 시 이전 정상 프로필의 실행 인자·요청 한도까지 복원한다. 불변 ID와 지속 상태는 기존 Controller state의 일부이며 별도 저장소를 추가하지 않는다. GPU 문맥 상향은 별도 자원 admission 계약 전까지 허용하지 않는다.
