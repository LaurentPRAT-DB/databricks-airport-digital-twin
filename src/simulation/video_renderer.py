"""Server-side headless video renderer for simulation replays.

Uses Playwright (headless Chromium with WebGL) to capture the 3D view
frame-by-frame, then ffmpeg to encode into MP4.

Install dependencies:
    uv pip install -e ".[video]"
    playwright install chromium
"""

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class VideoRenderer:
    """Renders a simulation replay to an MP4 video file."""

    def __init__(
        self,
        app_url: str,
        output_path: str,
        simulation_file: str,
        fps: int = 30,
        width: int = 1920,
        height: int = 1080,
        speed: int = 1,
        start_hour: float = 0,
        end_hour: float = 24,
        crop_to_canvas: bool = True,
    ):
        self.app_url = app_url.rstrip("/")
        self.output_path = Path(output_path)
        self.simulation_file = simulation_file
        self.fps = fps
        self.width = width
        self.height = height
        self.speed = max(1, speed)
        self.start_hour = start_hour
        self.end_hour = end_hour
        self.crop_to_canvas = crop_to_canvas

    async def render(self) -> Path:
        """Run the full render pipeline: capture frames then encode to MP4."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is required for video rendering. Install with:\n"
                "  uv pip install -e '.[video]'\n"
                "  playwright install chromium"
            )

        if not shutil.which("ffmpeg"):
            raise RuntimeError(
                "ffmpeg is required for video encoding. Install with:\n"
                "  brew install ffmpeg  (macOS)\n"
                "  apt install ffmpeg   (Linux)"
            )

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix="sim_video_"))
        logger.info("Temporary frame directory: %s", tmp_dir)

        try:
            frame_count = await self._capture_frames(async_playwright, tmp_dir)
            if frame_count == 0:
                raise RuntimeError("No frames were captured")
            self._encode_video(tmp_dir, frame_count)
            logger.info("Video saved to %s", self.output_path)
            return self.output_path
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    async def _capture_frames(self, async_playwright, tmp_dir: Path) -> int:
        """Launch headless browser, step through simulation, screenshot each frame."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--enable-webgl",
                    "--use-gl=angle",
                    "--enable-gpu-rasterization",
                    "--ignore-gpu-blocklist",
                    "--disable-software-rasterizer",
                ],
            )
            context = await browser.new_context(
                viewport={"width": self.width, "height": self.height},
                device_scale_factor=1,
            )
            page = await context.new_page()

            # Navigate and wait for backend ready
            logger.info("Navigating to %s", self.app_url)
            await page.goto(self.app_url, wait_until="networkidle")
            await self._wait_for_backend(page)

            # Switch to 3D view
            logger.info("Switching to 3D view")
            await page.evaluate("window.__viewControl.setViewMode('3d')")
            # Wait for 3D canvas to appear
            await page.wait_for_selector("canvas", timeout=30000)
            # Give Three.js a moment to initialize
            await page.wait_for_timeout(2000)

            # Load simulation file
            logger.info("Loading simulation file: %s", self.simulation_file)
            await page.evaluate(
                """([filename, startHour, endHour]) =>
                    window.__simControl.loadFile(filename, startHour, endHour)""",
                [self.simulation_file, self.start_hour, self.end_hour],
            )
            # Wait for loading to complete
            await self._wait_for_sim_loaded(page)

            # Get total frames
            info = await page.evaluate("window.__simControl.getInfo()")
            total_frames = info["totalFrames"]
            logger.info("Simulation loaded: %d total frames", total_frames)

            if total_frames == 0:
                await browser.close()
                return 0

            # Determine which frames to capture based on speed setting
            frame_indices = list(range(0, total_frames, self.speed))
            captured = 0

            # Determine screenshot region
            clip = None
            if self.crop_to_canvas:
                clip = await self._get_canvas_clip(page)

            for i, frame_idx in enumerate(frame_indices):
                # Seek to frame
                await page.evaluate(
                    "idx => window.__simControl.seekTo(idx)", frame_idx
                )
                # Wait for a render cycle
                await page.evaluate(
                    "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
                )

                # Screenshot
                screenshot_path = tmp_dir / f"frame_{captured:05d}.png"
                if clip:
                    await page.screenshot(path=str(screenshot_path), clip=clip)
                else:
                    await page.screenshot(path=str(screenshot_path))
                captured += 1

                if (i + 1) % 100 == 0 or i == len(frame_indices) - 1:
                    logger.info(
                        "Captured frame %d/%d (sim frame %d/%d)",
                        captured,
                        len(frame_indices),
                        frame_idx + 1,
                        total_frames,
                    )

            await browser.close()
            logger.info("Captured %d frames", captured)
            return captured

    async def _wait_for_backend(self, page) -> None:
        """Poll until the app's backend readiness check passes."""
        for _ in range(60):
            ready = await page.evaluate(
                """async () => {
                    try {
                        const r = await fetch('/api/ready');
                        const d = await r.json();
                        return d.ready === true;
                    } catch { return false; }
                }"""
            )
            if ready:
                logger.info("Backend is ready")
                return
            await page.wait_for_timeout(1000)
        raise RuntimeError("Backend did not become ready within 60 seconds")

    async def _wait_for_sim_loaded(self, page) -> None:
        """Wait until simulation data is fully loaded."""
        for _ in range(120):
            info = await page.evaluate("window.__simControl.getInfo()")
            if info["isActive"] and not info["isLoading"]:
                return
            await page.wait_for_timeout(500)
        raise RuntimeError("Simulation file did not load within 60 seconds")

    async def _get_canvas_clip(self, page) -> dict | None:
        """Get bounding box of the 3D canvas for cropping."""
        clip = await page.evaluate(
            """() => {
                const canvas = document.querySelector('canvas');
                if (!canvas) return null;
                const rect = canvas.getBoundingClientRect();
                return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
            }"""
        )
        if clip and clip["width"] > 0 and clip["height"] > 0:
            # Ensure even dimensions for H.264
            clip["width"] = clip["width"] - (clip["width"] % 2)
            clip["height"] = clip["height"] - (clip["height"] % 2)
            return clip
        return None

    def _encode_video(self, frames_dir: Path, frame_count: int) -> None:
        """Use ffmpeg to encode PNG frames into MP4."""
        input_pattern = str(frames_dir / "frame_%05d.png")
        cmd = [
            "ffmpeg",
            "-y",
            "-framerate", str(self.fps),
            "-i", input_pattern,
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(self.output_path),
        ]
        logger.info("Encoding video: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")
        size_mb = self.output_path.stat().st_size / (1024 * 1024)
        logger.info(
            "Encoded %d frames → %s (%.1f MB)", frame_count, self.output_path, size_mb
        )
