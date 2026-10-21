"""실제 Playground의 Embedding·Retrieval 실행 화면을 GIF와 포스터로 기록한다.

별도 도구 환경에 Playwright와 Pillow가 필요하다. 대상 Console은 같은 출처의 실제
Gateway API에 연결되어야 한다. 공개 합성 입력만 사용하며 API 키는 읽거나 기록하지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from playwright.async_api import async_playwright


async def capture(url: str, model: str, output: Path, evidence: Path) -> None:
    evidence.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    frames: list[tuple[Path, float]] = []
    responses: list[dict] = []
    errors: list[str] = []
    finished = asyncio.Event()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        browser_version = browser.version
        page = await browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        page.on("pageerror", lambda error: errors.append(str(error)))

        async def record(response):
            path = urlsplit(response.url).path
            if path in {"/v1/embeddings", "/v1/retrieval/rerank"} and response.request.method == "POST":
                responses.append({"path": path, "status": response.status,
                                  "request": response.request.post_data_json, "response": await response.json(),
                                  "request_id": response.headers.get("x-request-id")})

        page.on("response", record)
        await page.goto(url, wait_until="networkidle")
        await page.get_by_label("Embedding 모델", exact=True).select_option(model)
        await page.get_by_role("radio", name="텍스트 변환", exact=True).check()
        await page.get_by_label("텍스트", exact=True).fill("GPU 메모리가 부족해 모델 로딩이 실패했습니다.")
        assert await page.get_by_role("radio", name="문서 관련도 순위").is_enabled()

        async def sample():
            start = time.monotonic()
            while not finished.is_set():
                path = evidence / f"frame-{len(frames):04d}.png"
                await page.screenshot(path=str(path))
                frames.append((path, time.monotonic() - start))
                await asyncio.sleep(0.25)

        sampler = asyncio.create_task(sample())
        try:
            await asyncio.sleep(1)
            await page.get_by_role("button", name="벡터 생성", exact=True).click()
            await page.get_by_role("region", name="Embedding 결과").wait_for()
            await asyncio.sleep(2)
            await page.get_by_role("radio", name="문서 관련도 순위").check()
            await asyncio.sleep(0.6)
            await page.get_by_label("검색 질문", exact=True).fill("GPU 메모리 부족 원인")
            await asyncio.sleep(0.5)
            documents = ["CUDA out of memory가 발생했습니다.", "서비스 인증 토큰을 갱신했습니다.", "KV cache 사용량이 증가했습니다."]
            for index, text in enumerate(documents):
                await page.get_by_label(f"문서 {index + 1}", exact=True).fill(text)
                await asyncio.sleep(0.4)
            await page.get_by_label("상위 결과 개수").fill("2")
            await asyncio.sleep(0.5)
            await page.get_by_role("button", name="관련도 순위 확인").click()
            await page.get_by_role("region", name="문서 관련도 결과").wait_for()
            await asyncio.sleep(3)
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors, errors
            assert [r["path"] for r in responses] == ["/v1/embeddings", "/v1/retrieval/rerank"]
            assert all(r["status"] == 200 for r in responses), responses
        finally:
            finished.set()
            await sampler
            await browser.close()

    poster = output / "embedding-poster.png"
    shutil.copyfile(frames[-1][0], poster)
    with Image.open(poster) as last:
        palette = last.convert("RGB").quantize(colors=96)
    images = []
    for path, _ in frames:
        with Image.open(path) as image:
            images.append(image.convert("RGB").quantize(palette=palette))
    durations = [max(10, round((right[1] - left[1]) * 100) * 10) for left, right in zip(frames, frames[1:])]
    durations.append(250)
    gif = output / "embedding.gif"
    images[0].save(gif, save_all=True, append_images=images[1:], duration=durations, loop=0, optimize=True, disposal=1)
    actual_duration = 0
    with Image.open(gif) as image:
        for index in range(image.n_frames):
            image.seek(index)
            actual_duration += image.info.get("duration", 0)
    metadata = {"frontend_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "browser": "Chromium " + browser_version,
                "viewport": [1440, 1100], "sampled_frames": len(frames),
                "gif_duration_ms": actual_duration, "gif_bytes": gif.stat().st_size,
                "requests": responses}
    (evidence / "capture.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in metadata.items() if k != "requests"}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--model", default="local-embed-ko")
    parser.add_argument("--output", type=Path, default=Path("assets/demos"))
    parser.add_argument("--evidence", type=Path, default=Path("reports/validation/embedding-demo"))
    args = parser.parse_args()
    asyncio.run(capture(args.url, args.model, args.output, args.evidence))
