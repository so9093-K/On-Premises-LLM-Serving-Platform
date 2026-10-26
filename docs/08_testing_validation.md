# 테스트·검증 실행 체계

테스트 실행은 플랫폼 운영 Lifecycle과 분리한다. 공통 CLI는 Suite를 선택하고 Native Runner를 실행하며 결과 코드를 전달한다. 개별 Assertion과 테스트 결과의 권위는 pytest·Vitest·Playwright가 소유한다.

## 사전 준비

Python 3.12~3.13, 저장소의 uv 및 Node/npm 지정 버전을 사용한다.

```bash
make setup-dev
npm --prefix ui/control-plane ci  # Control Plane 타입·빌드 도구
```

Vitest·Playwright가 필요할 때 `make setup-test-runners`를 실행한다. Control Plane 의존성을 `npm ci`로 설치한 뒤 테스트 전용 Runner는 `scripts/quality/node_modules`에 독립적으로 설치하고 Console에는 실행 연결만 생성한다. 배포 의존성을 변경하지 않는다. 배포용 `package-lock.json`과 프로덕션 의존성에는 테스트 Runner를 추가하지 않는다. 테스트 Runner의 정확한 직접·하위 의존성은 `scripts/quality/package.json` 및 `scripts/quality/package-lock.json`이 소유하며, `npm ci`는 불일치 시 설치를 중단한다. 테스트 Runner 버전을 변경할 때는 `npm --prefix scripts/quality install --package-lock-only --ignore-scripts --no-audit --no-fund`로 전용 Lockfile만 갱신한다. Playwright는 기본 4173 포트에 전용 Preview를 시작하며 기존 서버를 재사용하지 않는다. 브라우저 테스트용 Vite 빌드는 `ui/control-plane/node_modules/.cache/playwright-preview/`에 별도로 생성하며 추적된 제품 정적 자산을 덮어쓰지 않는다. 해당 포트를 이미 사용 중이라면 다른 서비스를 대상으로 테스트하지 않고 오류로 종료한다. Chromium이 필요하면 `npm --prefix ui/control-plane exec -- playwright install chromium`을 별도로 실행한다.

## 실행 명령

```bash
make test            # pytest
make validate        # Ruff + 생성 산출물 Drift
make console-check   # Vitest + Control Plane 타입·빌드 검사
make check           # 빠른 정적 검사: Ruff + 생성 산출물 Drift + Control Plane 타입
make browser-test    # Playwright Test (Chromium)
```

같은 진입점은 CI에서도 호출할 수 있다.

```bash
python scripts/quality_cli.py run python
python scripts/quality_cli.py run frontend
python scripts/quality_cli.py run browser
python scripts/quality_cli.py run all --junit-dir /tmp/quality-junit
python scripts/quality_cli.py check
```

`--junit-dir`는 요청한 경우에만 Native Runner의 JUnit XML 출력을 활성화한다. 공통 CLI는 결과 저장소, 실행 증빙 이력 또는 벤치마크 판정기를 만들지 않는다.

평소에는 `make check`와 변경한 기능의 실행 확인을 사용한다. 기능 회귀가 우려될 때 해당 테스트를 선택하고, 브라우저·이미지 검사는 필요한 변경에서 별도로 실행한다. PR CI는 Python·프런트엔드 검사만 자동 실행하며, 이미지 빌드·HTTP 검사는 `main` 반영 후에도 실행한다. Chromium을 포함한 전체 CI는 Actions의 **Run workflow**로 실행한다.

## Source of Truth

- Python 테스트: `tests/python/` 및 `pyproject.toml`
- 프런트엔드 테스트: `ui/control-plane/tests/unit/`
- 브라우저 테스트: `ui/control-plane/tests/browser/`
- Suite 선택과 실행 명령: `scripts/quality_cli.py`
- 프런트엔드 테스트 Runner 직접·하위 의존성: `scripts/quality/package.json`과 `scripts/quality/package-lock.json`
- CI: 위 명령을 호출하는 Thin Adapter

운영 중 기동·상태 확인 및 요청 Readiness는 플랫폼의 운영 명령이 소유하며 품질 CLI에서 수행하지 않는다. 이미지 빌드·배포·운영 상태는 테스트 통과의 파생 상태가 아니다.
