"""외부 자산 없이 Playground용 무음 도형 영상을 만든다. PyAV와 NumPy가 필요하다."""

from __future__ import annotations

import argparse
from pathlib import Path

import av
import numpy as np


def generate(destination: Path) -> None:
    """8초 동안 빨간 정사각형이 이동하고 파란 원이 추가되는 합성 WebM을 만든다."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    width, height, fps = 640, 360, 6
    y, x = np.ogrid[:height, :width]
    with av.open(str(destination), mode="w", format="webm", options={"fflags": "+bitexact"}) as container:
        stream = container.add_stream("libvpx-vp9", rate=fps)
        stream.width, stream.height = width, height
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "30", "b": "0", "threads": "1", "deadline": "good", "cpu-used": "4"}
        for index in range(8 * fps):
            seconds = index / fps
            pixels = np.full((height, width, 3), (242, 245, 249), dtype=np.uint8)
            center_x = round(100 + 240 * min(seconds / 3, 1))
            center_y = round(140 + 120 * max((seconds - 5) / 3, 0))
            pixels[center_y - 36:center_y + 36, center_x - 36:center_x + 36] = (220, 40, 45)
            if seconds >= 3:
                pixels[(x - 520) ** 2 + (y - 140) ** 2 <= 42 ** 2] = (35, 95, 220)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    generate(parser.parse_args().destination)
