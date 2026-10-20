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
from ai_model_serving.settings_parts.dotenv_parser import parse_env_file  # noqa: E402
from ai_model_serving.settings_parts.env import is_default_secret  # noqa: E402

PORT = 9400
TEAM_PORT = 9480


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
        errors.append("제공된 Nginx 설정은 Gateway 9400번 포트만 지원합니다.")
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


def _purpose_title(purpose: str) -> str:
    return "내 기기에서 관리자 접속" if purpose == "personal" else "팀원에게 모델 API 공유"


def _show_plan(purpose: str, issues: list[str]) -> None:
    print(f"원격 접속 목적: {_purpose_title(purpose)}")
    if issues:
        print("접근 정책: 조치 필요 (다음 안내는 변경을 실행하지 않습니다)")
        for issue in issues:
            print(f"  - {issue}")
        print("먼저: make up ACCESS=edge")
        print("변경 계획 확인 뒤: make up ACCESS=edge CONFIRM=access")
        print("인증 키는 일반 API/Admin/내부 호출별로 구분하고 로그·명령 인자에 노출하지 않습니다.")
    else:
        print("접근 정책: 설정 파일 검사 통과 (실제 Host·Tailnet 연결은 별도 확인)")
    print("1. Tailscale 설치·로그인 후 서버를 Tailnet에 등록합니다.")
    print("2. Tailnet 전체 Grants/ACL을 확인하고 관리자만 HTTPS 443에 접근하도록 제한합니다.")
    print("   실제 정책은 Tailscale Admin Console에서 검토·테스트합니다.")
    print("3. tailscale serve status  # 기존 Serve 대상·포트 충돌 확인")
    print("4. tailscale funnel status # 공개 인터넷 노출이 없는지 확인")
    if purpose == "team":
        print("5. Nginx 팀원 전용 설정을 검토합니다: ops/access/team-api.nginx.conf")
        print("   sudo nginx -t && sudo systemctl reload nginx")
        print("   팀원은 HTTPS 8443만 허용하고 443/Admin 접근을 차단합니다.")
        print("6. tailscale serve --bg --https=443 http://127.0.0.1:9400")
        print("7. tailscale serve --bg --https=8443 http://127.0.0.1:9480")
    else:
        print("5. tailscale serve --bg --https=443 http://127.0.0.1:9400")
        print("   개인 접속에는 Nginx나 팀원용 8443이 필요하지 않습니다.")
    print("기존 Serve 설정은 자동 변경하지 않습니다. tailscale serve reset / funnel 사용 금지.")
    print("적용 뒤: make access-status PURPOSE=" + purpose)
    print("최종 확인: 실제 외부 기기에서 접속·인증·Tailnet 접근 제한을 검증합니다.")


def _tailscale_command(*parts: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(["tailscale", *parts], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None


def _serve_proxy_observed(output: str, port: int, upstream: str) -> bool:
    """Serve가 보여 준 HTTPS endpoint와 Loopback Proxy가 같은 블록에 있는지만 확인한다."""
    import re
    current_port: int | None = None
    for line in output.splitlines():
        match = re.search(r"https://[a-zA-Z0-9.-]+(?::([0-9]+))?(?:/|\s|$)", line)
        if match:
            current_port = int(match.group(1) or 443)
        if current_port == port and upstream in line and ("proxy" in line or "-->" in line):
            return True
    return False


def _show_status(purpose: str, issues: list[str]) -> int:
    print(f"원격 접속 상태: {_purpose_title(purpose)}")
    if issues:
        print("접근 정책: 조치 필요")
        for issue in issues:
            print(f"  - {issue}")
        print("다음: make access PURPOSE=" + purpose)
        return 2
    print("접근 정책: 설정 파일 검사 통과 (실제 Host bind는 확인하지 않음)")
    state = _tailscale_command("status", "--json")
    if state is None:
        print("Tailscale: 설치되지 않았거나 PATH에서 찾을 수 없음")
        return 1
    if state.returncode:
        print("Tailscale: 상태 조회 실패 — tailscale status로 로그인·네트워크 상태 확인")
        return 1
    import json
    try:
        details = json.loads(state.stdout)
    except (ValueError, TypeError):
        print("Tailscale: 상태 응답을 해석할 수 없음")
        return 1
    if not isinstance(details, dict) or details.get("BackendState") != "Running":
        print("Tailscale: 연결되지 않음 — tailscale status로 확인")
        return 1
    print("Tailscale: 이 서버의 Tailnet 연결 관측됨")
    raw_dns = details.get("Self")
    dns = raw_dns.get("DNSName", "") if isinstance(raw_dns, dict) else ""
    dns = dns.rstrip(".") if isinstance(dns, str) else ""
    if dns.endswith(".ts.net") and all(c.isascii() and (c.isalnum() or c in ".-") for c in dns):
        suffix = "/admin/console/" if purpose == "personal" else ":8443/v1/models"
        print(f"후보 접속 주소(미검증): https://{dns}{suffix}")
    serve = _tailscale_command("serve", "status")
    if serve is None or serve.returncode:
        print("Serve: 조회 불가 — tailscale serve status와 443/8443 목적지 확인")
        return 1
    expected = [(443, "http://127.0.0.1:9400")]
    if purpose == "team":
        expected.append((8443, "http://127.0.0.1:9480"))
    for port, upstream in expected:
        mapped = _serve_proxy_observed(serve.stdout, port, upstream)
        print(f"Serve HTTPS {port} → {upstream}: " + ("표시된 설정에서 관측됨" if mapped else "확인 필요"))
    funnel = _tailscale_command("funnel", "status")
    if funnel is None or funnel.returncode:
        print("Funnel: 조회 불가 — tailscale funnel status에서 공개 여부 확인")
        return 1
    if "https://" in funnel.stdout:
        print("Funnel: 공개 URL이 표시됨 — 의도하지 않은 인터넷 노출 여부 확인 필요")
    else:
        print("Funnel: 명령 조회됨 — 공개 비활성 여부는 출력과 설정에서 직접 확인")
    if purpose == "team":
        print("Nginx 팀원 API 경로·메서드 제한 및 관리자 경로 차단: 실제 Host 검증 필요")
    print("Tailnet 사용자별 Grants·외부 기기 연결·TLS 및 인증: 별도 확인 필요")
    print("원격 접속 완료 여부: 미검증 (서버 내부 조회 결과는 외부 접근 보증이 아님)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="비공개 원격 접속의 목적별 계획 및 읽기 전용 상태 진단")
    parser.add_argument("command", choices=("preflight", "plan", "status"))
    parser.add_argument("--purpose", choices=("personal", "team"), default="personal")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    issues = preflight(args.env_file)
    if args.command == "preflight":
        for issue in issues:
            print("[원격 접근 사전 점검 실패] " + issue, file=sys.stderr)
        if not issues:
            print("ACCESS=edge, Loopback, API/Admin 인증 및 키 분리: 설정 파일 확인")
        return 2 if issues else 0
    if args.command == "plan":
        _show_plan(args.purpose, issues)
        return 2 if issues else 0
    return _show_status(args.purpose, issues)


if __name__ == "__main__":
    raise SystemExit(main())
