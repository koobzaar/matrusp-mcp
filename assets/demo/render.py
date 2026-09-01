"""Render the deterministic MatrUSP HTML demo to an animated GIF.

Run with ``uv run --locked --with Pillow python assets/demo/render.py``.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

WIDTH = 1280
HEIGHT = 440
FPS = 24
DURATION = 16.2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("matrusp-demo.gif"),
        help="Destination GIF path.",
    )
    return parser.parse_args()


def find_browser() -> Path:
    explicit = os.environ.get("MATRUSP_BROWSER")
    candidates = [Path(explicit)] if explicit else []
    app_data = os.environ.get("LOCALAPPDATA")
    candidates.extend(
        [
            Path(os.environ.get("ProgramFiles(x86)", ""))
            / "Microsoft"
            / "Edge"
            / "Application"
            / "msedge.exe",
            Path(os.environ.get("ProgramFiles", ""))
            / "Microsoft"
            / "Edge"
            / "Application"
            / "msedge.exe",
            Path(os.environ.get("ProgramFiles", ""))
            / "Google"
            / "Chrome"
            / "Application"
            / "chrome.exe",
        ]
    )
    if app_data:
        candidates.extend(
            [
                *sorted(
                    Path(app_data).glob("ms-playwright/chromium-*/chrome-win*/chrome.exe"),
                    reverse=True,
                ),
                Path(app_data) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            ]
        )
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    raise FileNotFoundError("Chromium-compatible browser not found; set MATRUSP_BROWSER")


def encode_gif(frames: Path, output: Path) -> None:
    frame_paths = sorted(frames.glob("frame-*.png"))
    if not frame_paths:
        raise FileNotFoundError(f"No rendered frames found in {frames}")
    images = [Image.open(frame_path).convert("RGB") for frame_path in frame_paths]
    palette_frame = images[min(len(images) - 1, round(11.8 * FPS))]
    palette = palette_frame.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    indexed = [image.quantize(palette=palette, dither=Image.Dither.NONE) for image in images]
    indexed[0].save(
        output,
        save_all=True,
        append_images=indexed[1:],
        duration=round(1000 / FPS),
        loop=0,
        disposal=2,
        optimize=True,
    )
    for image in images:
        image.close()


def render() -> None:
    args = parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name("index.html").resolve()
    browser_executable = find_browser()
    frame_count = round(DURATION * FPS)

    with tempfile.TemporaryDirectory(prefix="matrusp-demo-") as temp_dir:
        frames = Path(temp_dir)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=str(browser_executable),
                headless=True,
            )
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
            page.goto(source.as_uri(), wait_until="load")
            page.evaluate("document.fonts && document.fonts.ready")
            for frame_number in range(frame_count):
                timestamp = frame_number / FPS
                page.evaluate("time => window.setDemoTime(time)", timestamp)
                page.screenshot(path=str(frames / f"frame-{frame_number:05d}.png"), animations="disabled")
            browser.close()
        encode_gif(frames, output)


if __name__ == "__main__":
    render()
