# ADR-0062: 실행 입력과 배포 출처를 분리한다

## Status

Accepted. ADR-0060의 이미지 재사용 조건을 대체한다.

## Context

문서·라이선스 수정이나 Git 상태만으로 실행 내용이 같은 이미지를 다시 빌드하면
기동 시간과 네트워크 의존성이 증가한다. Platform 소스 변경 때문에 별개 vLLM
이미지까지 빌드되는 결합도 제거해야 한다.

## Decision

1. 공통 입력 목록은 이미지별 Docker COPY 입력과 빌드 제어 파일을 소유한다.
   Platform과 vLLM은 각각 `ai_model_serving.runtime_digest`를 기록하고,
   기동은 artifact 종류와 실행 해시가 일치하는 로컬 이미지를 재사용한다.
   코드·설정·스키마·의존성·패치·실제 build override는 해당 이미지의 실행 입력이다.
2. README·LICENSE·NOTICE는 실행 해시에서 제외한다. Git revision과 clean/dirty/local은
   빌드 당시의 출처 표기이며 재사용 조건이 아니다. 배포 파일까지 포함한
   `ai_model_serving.source_digest`는 실행 해시와 별도로 기록한다.
3. 명시적인 이미지 빌드는 존재하는 README·LICENSE·NOTICE를 패키징한다.
   로컬 복사본에서 해당 파일이 없어도 이미지 생성과 기동을 허용한다.
   원본 LICENSE·NOTICE와 Apache-2.0 표기는 저장소에 유지한다.
4. 기동은 실행 입력이 달라진 이미지만 빌드한다. 외부 registry digest는 배포자가
   지정한 불변 입력이며 로컬 소스 비교의 대상이 아니다.
5. HTTP Smoke 스크립트는 실행 이미지 생성·재사용의 필수 입력이 아니라 독립 검증 도구다.
   빌드 출처의 `source_digest`에는 그 스크립트를 포함하되, 재사용에 쓰는
   `runtime_digest`에서는 제외한다. 이미지 생성과 이미지 Smoke도 독립 단계로 실행한다.

## Consequences

문서만 갱신하면 기존 이미지 안의 문서·라이선스는 빌드 당시 내용으로 유지된다.
이를 갱신한 배포물을 만들 때는 명시적으로 빌드한다. 로컬 실행 가능 여부와
재배포 시 필요한 파일의 완전성은 서로 다른 계약이다.

새 실행 해시 라벨이 없는 이전 로컬 이미지는 다음 기동에 한 번 캐시를 활용해
갱신한다. 내용 해시는 소스 일치를 판단하며 릴리스 서명이나 배포 권한을 증명하지 않는다.
