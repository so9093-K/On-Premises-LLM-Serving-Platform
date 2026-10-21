#!/usr/bin/env python3
"""사설 원격 접속 설정을 검토한다. Tailnet 설정·키·Host Firewall은 변경하지 않는다."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ai_model_serving.access_profile import access_profile_mismatches  # noqa: E402
from ai_model_serving.configuration import load_yaml_mapping  # noqa: E402
from ai_model_serving.settings_parts.dotenv_parser import parse_env_file  # noqa: E402
from ai_model_serving.settings_parts.env import is_default_secret  # noqa: E402

PORT = int(load_yaml_mapping(ROOT / 'configs/services.yaml')['services']['gateway']['default_host_port'])


def preflight(env_file: Path) -> list[str]:
    if not env_file.is_file():
        return ["설정 파일이 없습니다. 먼저 make up으로 초기화하세요."]
    result = parse_env_file(env_file)
    if result.errors:
        return ["설정 문법 오류: " + error for error in result.errors]
    values = result.values
    # 접근/인증 Profile의 최종 계약은 YAML에 소유권이 있다.
    # API 문서, 내부 서비스 인증, 운영 경로 보안, Host bind도 함께 검증한다.
    errors = [
        "ACCESS=edge 정책 불일치: " + mismatch
        for mismatch in access_profile_mismatches("edge", values)
    ]
    if values.get("GATEWAY_PORT", str(PORT)) != str(PORT):
        errors.append("제공된 Nginx 설정은 Gateway 현재 포트와 일치해야 합니다.")
    if is_default_secret(values.get("INTERNAL_SERVICE_TOKEN", "")):
        errors.append("내부 서비스 인증 토큰도 기본값일 수 없습니다.")
    for name in ("API_KEYS", "ADMIN_API_KEYS"):
        secrets = [key.strip() for key in values.get(name, "").split(",")]
        if not secrets or any(is_default_secret(key) for key in secrets):
            errors.append(f"{name}에 생성된 비기본 키가 필요합니다.")
    api = {key.strip() for key in values.get("API_KEYS", "").split(",") if key.strip()}
    admin = {key.strip() for key in values.get("ADMIN_API_KEYS", "").split(",") if key.strip()}
    if api & admin:
        errors.append("일반 API Key와 관리자 Key는 공유하면 안 됩니다.")
    for singular, allowed in (("API_KEY", api), ("ADMIN_API_KEY", admin)):
        alias = values.get(singular, "").strip()
        if alias and (is_default_secret(alias) or alias not in allowed):
            errors.append(f"{singular}는 활성 키 목록과 일치해야 합니다.")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Tailscale 비공개 원격 접근 사전 검증")
    parser.add_argument("command", choices=("preflight", "status"))
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()

    if args.command == "status":
        for cmd in (["tailscale", "status"], ["tailscale", "serve", "status"], ["tailscale", "funnel", "status"]):
            print("$ " + " ".join(cmd), flush=True)
            try:
                result = subprocess.run(cmd, check=False)
            except FileNotFoundError:
                print("tailscale 명령이 없습니다.", file=sys.stderr)
                return 127
            if result.returncode:
                return result.returncode
        return 0

    issues = preflight(args.env_file)
    if issues:
        for issue in issues:
            print("[원격 접근 사전 점검 실패] " + issue, file=sys.stderr)
        return 2
    print("ACCESS=edge, Loopback, API/Admin 인증 및 키 분리: 확인")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
