"""Chromium smoke against the compiled Control Plane, with deterministic mock API data.

This exercises DOM, focus transitions and 390/1440 layouts. It is not a GPU or
production Grafana validation. Server contracts stay owned by the regular tests.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:4173/admin/console/"
SCREENSHOTS = Path(os.environ.get("UX_SCREENSHOTS", "/tmp/operator-ux-browser"))
SCREENSHOTS.mkdir(parents=True, exist_ok=True)

bootstrap = {
    "bootstrap_version": 4,
    "access": {"admin_auth_required": False, "profile": "local"},
    "deployment": {
        "features": ["chat"],
        "target": "linux-nvidia-managed",
        "display_name": "Chromium UX Test",
        "runtime_backend": "vllm-cuda",
        "lifecycle_owner": "managed",
        "control_mode": "managed",
        "implementation_status": "implemented",
        "qualification_status": "verified",
    },
    "configuration": {"write_available": True, "revision": 7},
    "platform": {"version": "test-build"},
    "monitoring": {"grafana_available": True, "available": True},
    "links": {"grafana": "http://127.0.0.1:9411", "docs": None},
}
schema = {
    "version": 2,
    "items": [{
        "key": "streaming.max_duration_seconds",
        "label": "스트리밍 최대 시간",
        "meaning": "테스트 대상 설정",
        "help": "설정 검증을 위한 예제",
        "group": "streaming",
        "owner": "gateway",
        "control_surface": "configuration",
        "type": "integer",
        "editable": True,
        "unit": "seconds",
        "risk": "low",
        "apply_mode": "live",
        "minimum": 60,
        "maximum": 900,
        "applicability": {"features": []},
    }],
}
profile = {
    "id": "test-main-profile",
    "display_name": "테스트 모델",
    "upstream_model_id": "model-test",
    "revision": "rev1",
    "runtime_image": "test-image",
    "active": False,
    "compatibility": {"status": "compatible"},
    "qualification": {"status": "verified"},
    "capabilities": {"deployed_input": ["text"]},
    "resource_variant": None,
    "vram_fraction": .65,
    "gateway_policy": {"request_limits": {"max_model_len": 4096}, "max_output_tokens": 512},
}


def send(route, data, status=200, headers=None):
    route.fulfill(
        status=status, content_type="application/json",
        headers=headers or {}, body=json.dumps(data, ensure_ascii=False),
    )


def install_routes(page, state):
    def handle(route):
        url = route.request.url
        from urllib.parse import urlsplit
        path = urlsplit(url).path
        if path == "/admin/control-plane/bootstrap":
            return send(route, bootstrap)
        if path == "/admin/traffic/recent":
            if state["traffic_failure"]:
                return send(route, {"error": {"code": "TRAFFIC_QUERY_FAILED", "message": "지표 조회 실패"}}, 503)
            return send(route, {
                "window_seconds": 900, "observed_seconds": 900,
                "minimum_samples": {"p50": 3, "p95": 20},
                "requests": {"total": 24, "client_errors": 1, "server_errors": 0},
                "completion_latency_seconds": {"samples": 24, "p50": .2, "p95": .7},
                "time_to_first_chunk_seconds": {"samples": 24, "p50": .1, "p95": .3},
            })
        if path == "/admin/main-model":
            active = ({**profile, "active": True,
                       "resource_variant": "gpu-high",
                       "capabilities": {"deployed_input": ["text", "image"]},
                       "vram_fraction": .85} if state["active_profile"] else None)
            return send(route, {
                "public_model": "local-main", "gate": "open" if active else "closed",
                "runtime_state": "active" if active else "stopped",
                "boot_profile": None, "active_profile": active, "profile_locked": False,
                "state_recovery_error": None, "observed_runtime": None,
                "last_operation": None,
            })
        if path == "/admin/main-model/profiles":
            active = ({**profile, "id": "active-profile", "display_name": "활성 모델",
                       "active": True, "resource_variant": "gpu-high",
                       "capabilities": {"deployed_input": ["text", "image"]},
                       "vram_fraction": .85} if state["active_profile"] else None)
            return send(route, {"profiles": [active, profile] if active else [profile]})
        if path == "/admin/config/schema":
            return send(route, schema)
        if path == "/admin/config/effective":
            return send(route, {
                "version": 2, "revision": state["revision"],
                "items": [{
                    "key": "streaming.max_duration_seconds", "effective_value": state["value"],
                    "operator_value": state["value"], "effective_source": "operator",
                    "configured": True, "sensitive": False,
                    "operator_override_shadowed": False,
                }],
                "write_status": {
                    "available": True, "synchronized": True,
                    "store_revision": state["revision"], "resolver_revision": state["revision"],
                    "runtime_revision": state["revision"], "pending_operations": 0, "reason": None,
                },
            }, headers={"ETag": f'"cfg-{state["revision"]}"'})
        if path == "/admin/config/history":
            return send(route, {"items": [], "next_cursor": None})
        if path == "/admin/config/plans":
            assert route.request.method == "POST"
            proposed = json.loads(route.request.post_data)["changes"][0]["value"]
            return send(route, {
                "base_revision": state["revision"], "candidate_revision": state["revision"] + 1,
                "would_change": True, "plan_digest": "a" * 64,
                "changes": [{
                    "key": "streaming.max_duration_seconds", "operation": "set",
                    "effective_before": state["value"], "effective_after": proposed,
                    "effective_source_after": "operator",
                    "operator_override_shadowed_after": False, "risk": "low",
                }],
            })
        if path == "/admin/config" and route.request.method == "PATCH":
            assert route.request.headers.get("if-match") == f'"cfg-{state["revision"]}"'
            state["revision"] += 1
            state["value"] = 240
            return send(route, {
                "operation_id": "cfg-test", "status": "verified", "changed": True,
                "revision": state["revision"], "verification": {
                    "store_revision": state["revision"],
                    "resolver_revision": state["revision"],
                    "runtime_revision": state["revision"], "synchronized": True,
                },
            })
        route.continue_()
    page.route("**/*", handle)


def run_one(browser, width, height):
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda exception: errors.append(str(exception)))
    bootstrap["deployment"]["features"] = ["chat"]
    state = {"traffic_failure": True, "revision": 7, "value": 300, "active_profile": False}
    install_routes(page, state)
    page.goto(URL, wait_until="domcontentloaded")
    page.get_by_text("최근 요청 지표를 조회하지 못했습니다.").wait_for()
    assert page.get_by_text("조회된 주의 항목 없음").count() == 0, "Failed traffic must not look fully observed"
    page.screenshot(path=str(SCREENSHOTS / f"overview-failed-{width}.png"), full_page=True)
    state["traffic_failure"] = False
    page.get_by_role("button", name="새로고침").click()
    page.get_by_text("조회된 주의 항목 없음").wait_for()
    assert page.get_by_text("24건").count() > 0
    page.screenshot(path=str(SCREENSHOTS / f"overview-recovered-{width}.png"), full_page=True)
    page.get_by_role("link", name="설정", exact=True).click()
    page.get_by_role("button", name="편집").first.click()
    page.locator("#configuration-value").fill("240")
    page.get_by_role("button", name="변경 내용 검토").click()
    page.get_by_role("button", name="검토한 변경 적용").click()
    result = page.get_by_role("region", name="설정 적용 결과")
    result.wait_for()
    assert result.get_by_text("검증 완료").count() > 0
    assert result.get_by_text("4분").count() > 0
    assert result.get_by_text("5분").count() > 0
    assert result.evaluate("(el) => el === document.activeElement"), "Result focus not handed off"
    assert result.locator("details").count() == 1
    # The configuration table horizontally scrolls to the action on mobile.
    # Its identity column remains in the viewport when editing from the far right.
    if width <= 600:
        identity = page.locator(".configuration-table-scroll tbody tr:first-child td:first-child")
        assert identity.evaluate("(el) => { const r=el.getBoundingClientRect(); return r.left >= 0 && r.right <= window.innerWidth; }")
    page.screenshot(path=str(SCREENSHOTS / f"configuration-applied-{width}.png"), full_page=True)
    # A later rollback or another operator's change must not leave a stale
    # "verified" Apply card that appears to describe the current revision.
    state["revision"] = 9
    state["value"] = 180
    page.get_by_role("button", name="새로고침").click()
    result.wait_for(state="detached")
    assert page.get_by_text("revision 9").count() > 0
    bootstrap["deployment"]["features"] = ["chat", "model_switching"]
    page.goto(URL, wait_until="domcontentloaded")
    page.get_by_role("link", name="메인 모델", exact=True).click()
    page.get_by_role("button", name="전환 검토").click()
    page.get_by_text("첫 활성화 · 현재 프로필 없음").wait_for()
    page.get_by_text("첫 활성화에는 복구할 이전 모델이 없습니다.").wait_for()
    page.screenshot(path=str(SCREENSHOTS / f"main-first-activation-{width}.png"), full_page=True)
    state["active_profile"] = True
    page.reload(wait_until="domcontentloaded")
    page.get_by_role("link", name="메인 모델", exact=True).click()
    page.get_by_role("button", name="전환 검토").click()
    summary = page.get_by_role("group", name="전환 핵심 영향")
    summary.wait_for()
    assert summary.get_by_text("제거: 이미지").count() > 0
    assert summary.get_by_text("변경됨").count() > 0
    page.screenshot(path=str(SCREENSHOTS / f"main-switch-impact-{width}.png"), full_page=True)
    viewport_check = page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    assert viewport_check, f"Body overflow at {width} px"
    assert errors == [], errors
    print(f"PASS Chromium {width}x{height}: Overview error/recovery, configuration Apply/focus/stale revision, first activation and capability regression")
    context.close()


def main():
    for _ in range(40):
        try:
            with urlopen(URL, timeout=2) as response:
                if response.status == 200:
                    break
        except Exception:
            pass
        import time
        time.sleep(1)
    else:
        raise RuntimeError("Vite preview did not start")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            run_one(browser, 1440, 900)
            run_one(browser, 390, 844)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
