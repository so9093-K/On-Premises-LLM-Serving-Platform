# Version Reference

이 문서는 project version, Python package version, API contract version, container image tag와 config schema version의 역할을 구분한다. 실제 값은 `VERSION`, `pyproject.toml`, OpenAPI와 image 설정이 소유한다.

---

## Version의 역할

| 구분 | 기준 | `make reset-version` 반영 |
|---|---|:---:|
| Project version | `VERSION` | 예 |
| Python package version | `pyproject.toml` | 예. prerelease는 PEP 440 표기 사용 |
| API contract version | `specs/openapi.*.yaml` | 예 |
| Platform / Unified vLLM 로컬 기본 image tag | `.env.compose.example`, `configs/recommended_images.yaml` | 예 |
| Third-party upstream image digest | `configs/recommended_images.yaml` | 아니오 |
| Config schema version | 각 `configs/*.yaml`의 `version` | 아니오 |
| Published project image identity | registry가 반환한 immutable digest | 아니오 |

`VERSION`은 project와 project-built image의 사람이 읽는 기준선이다. 운영에서 실제 image 내용을 식별하는 값은 registry publish 결과의 immutable digest이고, third-party upstream image는 `configs/recommended_images.yaml`의 pinned manifest digest가 소유한다. Config schema version은 project version과 독립적이며 해당 config 구조가 바뀔 때만 변경한다.

Git source 자체의 identity는 commit/tree가 소유한다. 저장소는 별도의 source ZIP, release manifest 또는 release provenance format을 플랫폼 계약으로 만들지 않는다.

---

## VERSION을 올리는 시점

다음 중 하나에 해당할 때 새 project version을 만든다.

- 공개 API 계약 또는 OpenAPI schema가 바뀜
- 환경변수의 이름·의미·기본 동작이 바뀜
- 운영자가 image 또는 배포 기준선을 새로운 버전으로 구분해야 함
- 공유된 기준선의 실제 버그를 수정함
- GPU/vLLM 검증 결과를 반영해 새 운영 기준선을 만듦

다음만으로는 올리지 않는다.

- 문서 문구·오탈자·설명 보강
- 코드 동작을 바꾸지 않는 리팩터링
- 테스트 구조 변경 또는 내부 report 정리
- config schema version만 변경하는 경우

---

## Version 변경

```bash
make reset-version NEW_VERSION=<x.y.z 또는 x.y.z-rc.n>
make validate
```

`make reset-version`은 다음 version reference를 하나의 선언(`scripts/lib/version_refs.py`)에서 갱신한다.

- `VERSION`
- `pyproject.toml`의 Python package version
- Gateway / Risk Signal Service checked-in OpenAPI `info.version`
- `.env.compose.example`의 project-built Platform / Unified vLLM 기본 image tag
- `configs/recommended_images.yaml`의 project-built Platform / Unified vLLM 기본 image tag

Third-party upstream digest, config schema version, publish 결과 digest와 실행 중 runtime state는 version reset 대상이 아니다.

Source archive가 필요하면 Git commit/tree를 기준으로 사용하는 source-control 또는 외부 배포 자동화가 transport를 소유한다. Repository가 소유하는 배포 경계는 [9. 자동화 경계](../09_cicd.md), [10. 배포](../10_deployment.md), image build와 digest 정책은 [7. 로컬 개발과 빌드](../07_local_dev_build.md)를 따른다.
