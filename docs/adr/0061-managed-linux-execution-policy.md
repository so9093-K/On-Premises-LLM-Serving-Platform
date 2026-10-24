# ADR-0061: 관리형 Linux의 실행 정책과 배포 기능을 분리한다

## Status

Accepted. ADR-0054의 자동 전환 계약을 공통 Runtime Controller로 확장한다.
기본 정책과 정책 미지정 설치의 승계 규칙은 [ADR-0063](0063-gpu-preferred-cpu-recovery.md)이 대체한다.

## Context

자동 CPU/GPU 전환을 위해 다른 Target을 설치하면 Supporting Runtime과 관측 기능까지
달라졌다. 실행 정책을 바꾸기 위해 인증·포트·캐시를 다시 초기화할 이유는 없다.

## Decision

1. `linux-nvidia-dynamic`을 유일한 관리형 Linux Target으로 사용한다. 최초 `TARGET=auto`는 이 구성의 자동 정책을 선택한다. 기존 독립 CPU Compose와 Adaptive Target은 중복 권한을 만들므로 제거한다. 외부 Runtime과 macOS는 기존 생명주기 소유권을 유지한다.
2. Main 실행 정책은 `automatic`·`cpu`·`gpu`다. Console은 모델과 지원 입력 변경을 검토한 뒤
   기존 Main 전환 API로 정책을 적용한다. 자동 정책은 Qwen CPU부터 검증하고 Gemma GPU를
   안정 관측·Admission·Drain·Canary 뒤 선택한다. 고정 정책은 다른 엔진으로 자동 전환하지 않는다.
3. 정책의 Source of Truth는 Main 상태 저장소다. `.env`의 `MAIN_MODEL_EXECUTION_POLICY`는
   최초 seed이며 Console 선택을 덮어쓰지 않는다. 기존 배포는 활성 프로필의 엔진을 고정 정책으로
   승계한다. 중지 의도·진행 중 요청·실패 시 Gate·Rollback 계약은 Main Manager가 소유한다.
4. 자동 선택과 Supporting Runtime 시작은 공통 GPU 예산 잠금과 Admission을 사용한다.
   Main 전환 진행 중에는 다른 Runtime 전환을 거부한다. 다른 GPU 작업을 자동 종료하지 않는다.
   기능 제공 여부는 Target·자원 정책·개별 Runtime 준비 상태가 소유한다.
5. CPU 우선 기동은 Main 템플릿만 생성하고 실제 시작·교체는 Controller가 수행한다.
   GPU 이미지·드라이버·관측 준비 실패는 Core·CPU·관측 서비스의 기동 실패로 전파하지 않는다.
   반복 `make up`은 실행 중 Main을 CPU로 덮어쓰지 않는다.
6. 관리형 Linux Target 이전은 이전 버전에서 Checkout 소유 컨테이너를 종료한 뒤 수행한다.
   인증값·포트·모델 캐시는 유지한다. 삭제된 Target·CPU 프리셋 ID가 기록된 Main 상태는
   새 Controller가 호환성을 가장하지 않으며, 운영자가 지원되는 기준 프로필로 명시적으로
   초기화한 뒤 새 관리형 구성을 시작한다.

## Consequences

같은 공개 모델 이름에서 CPU/GPU 선택에 따라 실제 모델·답변·입력 한도가 바뀐다.
자동 정책의 확인 화면은 이 차이와 미검증 프로필을 명시한다. Main의 CPU 실행은
GPU 기반 Embedding·Detector의 실행 가능성을 증명하지 않는다. 장치별 Qualification은 별도다.
