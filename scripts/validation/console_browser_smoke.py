"""Chromium smoke against the compiled Control Plane, with deterministic mock API data.

This exercises DOM, focus transitions and 390/1440 layouts. It is not a GPU or
production Grafana validation. Server contracts stay owned by the regular tests.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

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
    "switch_preflight": {
        "status": "fits", "reason_code": None, "required_fraction": .65,
        "available_fraction": .93, "ceiling_fraction": .93, "stop": [],
    },
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
            candidate = dict(profile)
            if state.get("switch_in_progress"):
                candidate["switch_preflight"] = {
                    "status": "blocked", "reason_code": "MODEL_SWITCH_IN_PROGRESS",
                    "required_fraction": None, "available_fraction": None,
                    "ceiling_fraction": None, "stop": [],
                }
            return send(route, {"profiles": [active, candidate] if active else [candidate]})
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
    assert page.get_by_text("조회 결과 · 주의 없음").count() == 0, "Failed traffic must not look fully observed"
    page.screenshot(path=str(SCREENSHOTS / f"overview-failed-{width}.png"), full_page=True)
    state["traffic_failure"] = False
    page.get_by_role("button", name="새로고침").click()
    page.get_by_text("조회 결과 · 주의 없음").wait_for()
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
    # 내부 JSX 문구 존재가 아니라 사용자에게 노출되는 중단·복구 정보를 검증한다.
    summary.get_by_text("전환 중 일시 중단 가능").wait_for()
    page.get_by_text("전환 실패 시 이전 모델로 복구를 시도합니다.").wait_for()
    page.get_by_text("GPU 정책 비율").wait_for()
    assert summary.get_by_text("제거: 이미지").count() > 0
    assert summary.get_by_text("변경됨").count() > 0
    page.screenshot(path=str(SCREENSHOTS / f"main-switch-impact-{width}.png"), full_page=True)
    # 서버가 다른 전환 진행 중이라고 응답하면 그 이유는 보이되 재전환은 실행할 수 없다.
    state["switch_in_progress"] = True
    page.reload(wait_until="domcontentloaded")
    page.get_by_role("link", name="메인 모델", exact=True).click()
    page.get_by_role("button", name="전환 검토").click()
    page.get_by_text("다른 모델 전환 작업이 완료된 뒤 다시 검토하세요.").wait_for()
    assert page.get_by_role("button", name="전환 요청").is_disabled()
    viewport_check = page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    assert viewport_check, f"Body overflow at {width} px"
    assert errors == [], errors
    print(f"PASS Chromium {width}x{height}: Overview error/recovery, configuration Apply/focus/stale revision, first activation and capability regression")
    context.close()



def run_audio_example(browser, width, height):
    """Real Chromium and bundled WAV; mock public model/Chat API only."""
    context = browser.new_context(viewport={"width": width, "height": height})
    context.grant_permissions(["clipboard-read", "clipboard-write"])
    page = context.new_page()
    errors = []
    requests = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    state = {"traffic_failure": False, "revision": 7, "value": 300, "active_profile": False, "audio": False}
    bootstrap["deployment"]["features"] = ["chat"]
    install_routes(page, state)

    def handle_public(route):
        from urllib.parse import urlsplit
        path = urlsplit(route.request.url).path
        if path == "/v1/models":
            return send(route, {
                "object": "list",
                "data": [{
                    "id": "local-main",
                    "backend": "vllm-cuda",
                    "capabilities": ["chat.completions"],
                    "input_modalities": ["text", "audio"] if state["audio"] else ["text"],
                    "request_parameters": {"stream": {"type": "boolean"}},
                    "request_limits": {"audio": {"allowed_formats": ["wav"], "max_inputs": 1, "max_bytes": 250000}},
                }],
            })
        if path == "/v1/chat/completions":
            body = json.loads(route.request.post_data)
            requests.append(body)
            route.fulfill(
                status=200, content_type="text/event-stream",
                body='data: {"choices":[{"delta":{"content":"확인했습니다."}}]}\n\ndata: [DONE]\n\n',
            )
            return
        route.continue_()

    page.route("**/v1/models", handle_public)
    page.route("**/v1/chat/completions", handle_public)
    page.goto(URL, wait_until="domcontentloaded")
    page.get_by_role("link", name="Playground").click()
    if width <= 600:
        # 구현 문자열이 아니라 모바일 실제 앵커와 이동 대상을 확인한다.
        expect(page.locator("#chat-model-settings")).to_have_count(1)
        expect(page.locator("#chat-input")).to_have_count(1)
        # 모바일에서 설정 패널이 채팅 본문보다 먼저 배치되면 입력 흐름을 가린다.
        main_bounds = page.locator(".chat-main").bounding_box()
        settings_bounds = page.locator(".chat-side").bounding_box()
        assert main_bounds is not None and settings_bounds is not None
        assert settings_bounds["y"] >= main_bounds["y"] + main_bounds["height"] - 1, (
            "Mobile request settings must follow the conversation and composer"
        )
        page.get_by_role("link", name="요청 설정 ↓").click()
        page.wait_for_function("() => location.hash === '#chat-model-settings'")
        page.get_by_role("link", name="대화 입력으로 돌아가기 ↑").click()
        page.wait_for_function("() => location.hash === '#chat-input'")
    page.get_by_role("button", name="오디오 분석").click()
    page.get_by_text("현재 모델은 오디오 입력을 지원하지 않습니다.").first.wait_for()
    assert page.get_by_role("button", name="입력에 적용").is_disabled(), "Unsupported model must not apply audio"
    state["audio"] = True
    page.reload(wait_until="domcontentloaded")
    page.get_by_role("button", name="오디오 분석").click()
    audio = page.get_by_label("예제 한국어 음성 재생")
    audio.wait_for()
    page.wait_for_function("() => document.querySelector('.playground-example-audio')?.readyState >= 1")
    assert audio.evaluate("(el) => el.duration > 3.5 && el.duration < 15")
    assert not audio.evaluate("(el) => el.autoplay")
    page.get_by_text("음성 대본 보기").click()
    page.get_by_text("그들은 세시에 나갔어요. 그들은 세시간을 나갔다 왔어요.").wait_for()
    assert requests == [], "Sample selection and playback must not submit inference"
    page.get_by_role("button", name="입력에 적용").click()
    page.locator(".chat-attachment-list").get_by_text("sample-audio.wav").wait_for()
    page.get_by_text("오디오 분석 예제에서 시작 · 오디오 1개").wait_for()
    expect(page.get_by_label("메시지")).to_be_focused(timeout=3000)
    assert requests == [], "Applying fixture must not submit inference"
    page.screenshot(path=str(SCREENSHOTS / f"playground-audio-ready-{width}.png"), full_page=True)
    with page.expect_request("**/v1/chat/completions") as outgoing:
        page.get_by_role("button", name="보내기").click()
    page.wait_for_function("() => document.querySelectorAll('.chat-log li').length > 0")
    user = outgoing.value.post_data_json["messages"][-1]
    parts = user["content"]
    assert parts[-1]["type"] == "input_audio", parts
    assert parts[-1]["input_audio"]["format"] == "wav"
    assert parts[-1]["input_audio"]["data"].startswith("UklGR"), "Expected WAV RIFF Base64"
    assert not any("sample-audio.wav" in str(part) for part in parts), "File name not in model payload"

    # The same emitted multimodal request must be obtainable from the finished turn.
    import zipfile
    export = page.locator(".playground-export").last
    export.locator("summary").first.click()
    export.get_by_label("개발 언어").select_option("javascript")
    assert "readFile" in export.locator(".playground-export-code").first.inner_text()
    export.get_by_role("button", name="요청 JSON 복사").click()
    assert json.loads(page.evaluate("navigator.clipboard.readText()")) == outgoing.value.post_data_json
    with page.expect_download() as json_save:
        export.get_by_role("button", name="요청 JSON 받기").click()
    with open(json_save.value.path(), encoding="utf-8") as downloaded:
        assert json.load(downloaded) == outgoing.value.post_data_json
    with page.expect_download() as zip_save:
        export.get_by_role("button", name="전체 예제 ZIP 받기").click()
    with zipfile.ZipFile(zip_save.value.path()) as archive:
        assert archive.testzip() is None
        assert json.loads(archive.read("request.json")) == outgoing.value.post_data_json
        assert {"client.py", "client.mjs", "client.sh", "README.md"}.issubset(archive.namelist())
    assert errors == [], errors
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    print(f"PASS audio Chromium {width}x{height}: gating, local playback, no auto-send, validated WAV request")
    context.close()



def run_tool_result_roundtrip(browser, width, height):
    """컴포넌트 분리 뒤에도 도구 결과는 명시적인 사용자 제출로만 전송된다."""
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    errors = []
    requests = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    state = {"traffic_failure": False, "revision": 7, "value": 300, "active_profile": False}
    bootstrap["deployment"]["features"] = ["chat"]
    install_routes(page, state)

    def handle_public(route):
        from urllib.parse import urlsplit
        path = urlsplit(route.request.url).path
        if path == "/v1/models":
            return send(route, {
                "object": "list",
                "data": [{
                    "id": "local-main",
                    "backend": "vllm-cuda",
                    "capabilities": ["chat.completions", "chat.completions.tools"],
                    "input_modalities": ["text"],
                    "request_parameters": {
                        "stream": {"type": "boolean"},
                        "tools": {"type": "array", "min_items": 0, "max_items": 2},
                        "tool_choice": {"allowed": ["auto", "none"]},
                    },
                }],
            })
        if path == "/v1/chat/completions":
            body = json.loads(route.request.post_data)
            requests.append(body)
            if len(requests) == 1:
                chunk = {
                    "choices": [{
                        "delta": {"tool_calls": [{
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "lookup", "arguments": '{"q":"x"}'},
                        }]},
                        "finish_reason": "tool_calls",
                    }],
                }
            else:
                chunk = {"choices": [{"delta": {"content": "처리 완료"}, "finish_reason": "stop"}]}
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body="data: " + json.dumps(chunk, ensure_ascii=False) + "\n\ndata: [DONE]\n\n",
            )
            return
        route.continue_()

    page.route("**/v1/models", handle_public)
    page.route("**/v1/chat/completions", handle_public)
    page.goto(URL, wait_until="domcontentloaded")
    page.get_by_role("link", name="Playground").click()

    # 브라우저에서 실제 도구 정의를 저장해야 Gateway에 유효한 tools 요청이 간다.
    settings = page.locator(".chat-settings")
    if not settings.evaluate("(el) => el.open"):
        settings.locator("summary").first.click()
    tools_settings = page.locator(".chat-tool-settings")
    tools_settings.locator("summary").first.click()
    tools_settings.get_by_role("button", name="Function 추가").click()
    tools_settings.get_by_label("Function 이름").fill("lookup")
    schema = {"type": "object", "properties": {"q": {"type": "string"}}}
    tools_settings.get_by_label("Parameters JSON Schema").fill(json.dumps(schema))

    page.get_by_label("메시지").fill("조회해주세요")
    with page.expect_request("**/v1/chat/completions") as first_outgoing:
        page.get_by_role("button", name="보내기").click()
    first_body = first_outgoing.value.post_data_json
    assert first_body["tools"] == [{
        "type": "function",
        "function": {"name": "lookup", "parameters": schema},
    }], first_body
    assert first_body["messages"] == [{"role": "user", "content": "조회해주세요"}]

    form = page.locator(".chat-tool-result-form")
    form.wait_for()
    result_input = form.locator("textarea").first
    assert page.get_by_label("메시지").is_disabled(), "Pending result blocks unrelated turns"
    assert len(requests) == 1, "Model tool calls are not executed automatically"
    result_input.fill('{"temp":18}')
    assert len(requests) == 1, "Editing a result must not submit inference"
    with page.expect_request("**/v1/chat/completions") as outgoing:
        form.get_by_role("button", name="도구 결과 보내기").click()
    continuation = outgoing.value.post_data_json
    assert continuation["tools"] == first_body["tools"], continuation
    messages = continuation["messages"]
    assert [item["role"] for item in messages] == ["user", "assistant", "tool"], messages
    assert messages[-1] == {"role": "tool", "tool_call_id": "call_1", "content": '{"temp":18}'}
    page.get_by_text("처리 완료").wait_for()
    assert len(requests) == 2, requests
    assert errors == [], errors
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    print(f"PASS tool result Chromium {width}x{height}: manual submit, exact tool_call_id, no auto-send")
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
            run_audio_example(browser, 1440, 900)
            run_audio_example(browser, 390, 844)
            run_tool_result_roundtrip(browser, 1440, 900)
            run_tool_result_roundtrip(browser, 390, 844)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
