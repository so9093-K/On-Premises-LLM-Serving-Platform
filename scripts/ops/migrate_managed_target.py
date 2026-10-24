"""폐기된 관리형 Linux Target을 명시적으로 종료한 뒤 공통 Controller로 전환한다.

plan-first, scope-limited: 인증·포트·모델 Cache를 건드리지 않는다.
복구가 필요한 이전 Main Model 상태는 전용 backup 폴더로 이동한다.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from scripts.config.setup_env import (  # noqa: E402
    deployment_target_values,
    parse_env_template,
    write_env,
)
from scripts.ops.compose_ownership import owned_container_ids  # noqa: E402
from ai_model_serving.main_model.state import read_main_model_state_file  # noqa: E402

REMOVED_MANAGED_TARGETS = frozenset({"linux-cpu-managed", "linux-adaptive"})
MANAGED_TARGET = "linux-nvidia-dynamic"
CPU_PROFILE = "cpu-gguf-text"
CPU_FIRST_POLICIES = frozenset({"cpu", "fallback", "automatic"})


def migration_plan(
    root: Path,
    *,
    policy: str,
    profile: str | None,
    projection: Callable[[str, str | None], dict[str, str]] = deployment_target_values,
) -> tuple[list[str], dict[str, str], dict[str, str], Path]:
    """허용한 이전 Target만 이전한다. 전체 reset/secret 재생성을 호출하지 않는다."""
    env_path = root / ".env"
    if not env_path.is_file() or env_path.is_symlink():
        raise ValueError("일반 파일 .env가 필요합니다")
    lines, existing = parse_env_template(env_path)
    previous = existing.get("DEPLOYMENT_TARGET")
    if previous not in REMOVED_MANAGED_TARGETS:
        raise ValueError("삭제된 관리형 Target만 명시적으로 전환할 수 있습니다")
    if existing.get("BUILD_PROFILE") != "compose":
        raise ValueError("Compose 배포에서만 이전할 수 있습니다")
    if policy not in CPU_FIRST_POLICIES | {"gpu"}:
        raise ValueError("실행 정책은 cpu, fallback, automatic, gpu 중 하나여야 합니다")
    chosen = profile or (CPU_PROFILE if policy in CPU_FIRST_POLICIES else None)
    if policy in CPU_FIRST_POLICIES and chosen != CPU_PROFILE:
        raise ValueError("CPU 시작 정책의 기준 프로필은 cpu-gguf-text여야 합니다")
    if not chosen:
        raise ValueError("GPU 고정 정책은 --profile GPU_PROFILE을 지정해야 합니다")
    if policy == "gpu" and chosen == CPU_PROFILE:
        raise ValueError("GPU 고정 정책에서는 CPU 프로필을 선택할 수 없습니다")
    projected = projection(MANAGED_TARGET, chosen)
    values = dict(existing)
    values["DEPLOYMENT_TARGET"] = MANAGED_TARGET
    values["MAIN_MODEL_BOOT_PROFILE"] = chosen
    values["MAIN_MODEL_BASE_URL"] = projected["MAIN_MODEL_BASE_URL"]
    values["MAIN_MODEL_EXECUTION_POLICY"] = policy
    # 이전 독립 CPU Compose에서만 쓰던 정적 프로필 선택값은 남기지 않는다.
    values.pop("MAIN_MODEL_STATIC_PROFILE", None)
    lines = [
        line for line in lines
        if line.strip().split("=", 1)[0] != "MAIN_MODEL_STATIC_PROFILE"
    ]
    state_path = root / ".runtime/main-model/main-model-state.json"
    if state_path.is_symlink():
        raise ValueError("Main Model 상태 파일은 symlink일 수 없습니다")
    if state_path.exists() and not state_path.is_file():
        raise ValueError("Main Model 상태 파일은 일반 파일이어야 합니다")
    if state_path.exists():
        read_main_model_state_file(state_path)
    return lines, existing, values, state_path


def migrate_environment(
    root: Path,
    *,
    policy: str,
    profile: str | None = None,
    confirmed: bool = False,
    ownership_check: Callable[[Path], list[str]] = owned_container_ids,
    projection: Callable[[str, str | None], dict[str, str]] = deployment_target_values,
) -> dict[str, str | bool]:
    lines, existing, values, state_path = migration_plan(
        root, policy=policy, profile=profile, projection=projection
    )
    result: dict[str, str | bool] = {
        "from": existing["DEPLOYMENT_TARGET"],
        "to": MANAGED_TARGET,
        "policy": policy,
        "profile": values["MAIN_MODEL_BOOT_PROFILE"],
        "state_reset": state_path.is_file(),
        "applied": False,
    }
    if not confirmed:
        return result

    # 실행/중지 명령은 소유권 검증을 완료한 별도 make down 작업이다.
    # 기존 컨테이너가 남아 있으면 인증/상태를 절대 변경하지 않는다.
    if ownership_check(root):
        raise RuntimeError(
            "이 checkout의 컨테이너가 남아 있습니다. 이전 버전에서 make down 후 다시 실행하세요"
        )
    env_path = root / ".env"
    backup_dir = root / ".runtime/migrations"
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_dir.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_env = backup_dir / f"{stamp}.env.bak"
    backup_state = backup_dir / f"{stamp}.main-model-state.json.bak"
    shutil.copy2(env_path, backup_env)
    backup_env.chmod(0o600)
    moved = False
    try:
        if state_path.is_file():
            state_path.rename(backup_state)
            backup_state.chmod(0o600)
            moved = True
        write_env(lines, values, env_path)
    except Exception:
        if moved:
            backup_state.rename(state_path)
        raise
    result["applied"] = True
    result["backup_env"] = str(backup_env)
    if moved:
        result["backup_state"] = str(backup_state)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, choices=["cpu", "fallback", "automatic", "gpu"])
    parser.add_argument("--profile", default=None)
    parser.add_argument("--confirm", choices=["migrate"], default=None)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        result = migrate_environment(
            args.root.resolve(), policy=args.policy, profile=args.profile,
            confirmed=args.confirm == "migrate",
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[managed-migration] 이전 거부: {exc}", file=sys.stderr)
        return 2
    print(f"[managed-migration] {result['from']} → {result['to']}")
    print(f"[managed-migration] policy={result['policy']} profile={result['profile']}")
    print(f"[managed-migration] Main state archive: {result['state_reset']}")
    if not result["applied"]:
        print("계획만 표시했습니다. 기존 배포 중지 후 --confirm migrate로 적용하세요.")
    else:
        print(f"[managed-migration] 설정 백업: {result['backup_env']}")
        if result.get("backup_state"):
            print(f"[managed-migration] Main 상태 백업: {result['backup_state']}")
        print("[managed-migration] 기존 secret/포트/모델 cache는 유지했습니다.")
        print("다음 단계: make up TARGET=linux-nvidia-dynamic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
