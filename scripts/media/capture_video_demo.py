"""실제 Playground 영상 예제의 재생·전송·응답을 GIF와 포스터로 기록한다.

별도 도구 환경의 Playwright·Pillow를 사용한다. 인증 키를 읽거나 API 응답을 Mock하지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import urlsplit

from PIL import Image
from playwright.async_api import async_playwright


async def capture(url: str, output: Path, evidence: Path) -> None:
    if evidence.exists() and any(evidence.iterdir()):
        raise FileExistsError("Choose an empty evidence directory to preserve previous captures")
    evidence.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    frames: list[tuple[Path, float]] = []
    responses: list[dict] = []
    errors: list[str] = []
    finished = asyncio.Event()
    recorded = asyncio.Event()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        browser_version = browser.version
        page = await browser.new_page(viewport={"width": 1440, "height": 1100},
                                      device_scale_factor=1, locale="ko-KR", timezone_id="Asia/Seoul")
        page.on("pageerror", lambda error: errors.append(str(error)))

        async def record(response):
            if urlsplit(response.url).path == "/v1/chat/completions" and response.request.method == "POST":
                responses.append({"status": response.status, "request": response.request.post_data_json,
                                  "sse": (await response.body()).decode(),
                                  "request_id": response.headers.get("x-request-id")})
                recorded.set()

        page.on("response", record)
        await page.goto(url, wait_until="networkidle")
        console_bundle = await page.locator('script[type="module"]').get_attribute("src")
        await page.get_by_label("최대 출력 토큰", exact=True).fill("256")
        await page.get_by_text("고급 생성 설정", exact=True).click()
        await page.get_by_label("온도", exact=True).fill("0")
        await page.get_by_text("고급 생성 설정", exact=True).click()
        await page.get_by_role("button", name="영상 분석", exact=False).click()
        await page.locator(".playground-example-preview").evaluate("el => el.scrollIntoView({block: 'start'})")
        video = page.get_by_label("예제 영상 재생", exact=True)
        await page.wait_for_function("() => document.querySelector('video')?.readyState >= 2")
        assert await video.evaluate("el => el.duration === 8 && el.playbackRate === 1")

        async def sample():
            start = time.monotonic()
            while not finished.is_set():
                path = evidence / f"frame-{len(frames):04d}.png"
                await page.screenshot(path=str(path))
                frames.append((path, time.monotonic() - start))
                await asyncio.sleep(0.25)

        sampler = asyncio.create_task(sample())
        try:
            await asyncio.sleep(0.75)
            await video.evaluate("el => el.play()")
            await page.wait_for_function("() => document.querySelector('video')?.ended", timeout=15000)
            await asyncio.sleep(0.5)
            video_frame = len(frames) - 1
            await page.get_by_role("button", name="입력에 적용", exact=True).click()
            await page.get_by_label("메시지", exact=True).wait_for()
            await asyncio.sleep(1.25)
            await page.get_by_role("button", name="보내기", exact=True).click()
            await page.locator('.chat-message-assistant[aria-busy="false"] .chat-text').wait_for(timeout=120000)
            await asyncio.wait_for(recorded.wait(), timeout=10)
            await page.locator(".chat-exchange").evaluate("el => el.scrollIntoView({block: 'nearest'})")
            answer = await page.locator(".chat-message-assistant .chat-text").inner_text()
            await asyncio.sleep(4)
            assert len(responses) == 1 and responses[0]["status"] == 200
            assert "data: [DONE]" in responses[0]["sse"] and answer.strip()
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors, errors
        finally:
            finished.set()
            await sampler
            await browser.close()

    shutil.copyfile(frames[-1][0], output / "video-analysis-poster.png")
    # Include the colored input and response UI when selecting the GIF palette.
    sheet = Image.new("RGB", (1440 * 3, 1100))
    for index, frame in enumerate((frames[0][0], frames[video_frame][0], frames[-1][0])):
        with Image.open(frame) as image:
            sheet.paste(image.convert("RGB"), (index * 1440, 0))
    palette = sheet.quantize(colors=128)
    images = []
    for path, _ in frames:
        with Image.open(path) as image:
            images.append(image.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE))
    durations = [max(10, round((right[1] - left[1]) * 100) * 10)
                 for left, right in zip(frames, frames[1:])]
    durations.append(250)
    gif = output / "video-analysis.gif"
    images[0].save(gif, save_all=True, append_images=images[1:], duration=durations,
                   loop=0, optimize=True, disposal=1)
    duration = 0
    with Image.open(gif) as image:
        for index in range(image.n_frames):
            image.seek(index)
            duration += image.info.get("duration", 0)
    metadata = {
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "console_bundle": console_bundle,
        "browser": "Chromium " + browser_version, "viewport": [1440, 1100],
        "sample_sha256": hashlib.sha256(Path("assets/demos/inputs/sample-video.webm").read_bytes()).hexdigest(),
        "sampled_frames": len(frames), "gif_duration_ms": duration, "gif_bytes": gif.stat().st_size,
        "response_text": answer, "requests": responses,
    }
    (evidence / "capture.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in metadata.items() if k != "requests"}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", type=Path, default=Path("assets/demos"))
    parser.add_argument("--evidence", type=Path, default=Path("reports/validation/video-demo"))
    args = parser.parse_args()
    asyncio.run(capture(args.url, args.output, args.evidence))
