"""Server-side headless video renderer for simulation replays.

Uses Playwright (headless Chromium with WebGL) to capture the 3D view
frame-by-frame, then ffmpeg to encode into MP4.

Install dependencies:
    uv pip install -e ".[video]"
    playwright install chromium
"""

import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Empirical estimate: H.264 CRF 23 at 1080p for 3D scene capture
# averages ~40-80 KB per output frame. We use 60 KB as middle ground.
_ESTIMATED_BYTES_PER_FRAME_1080P = 60_000
# PNG screenshots are ~2-4 MB each at 1080p; use 3 MB for temp disk estimate
_ESTIMATED_PNG_BYTES_PER_FRAME = 3_000_000

# Where to look for simulation files
_PROJECT_ROOT = Path(__file__).parent.parent.parent


def _find_simulation_file(filename: str) -> Path:
    """Resolve a simulation filename to an absolute path."""
    candidates = [
        _PROJECT_ROOT / filename,
        _PROJECT_ROOT / "simulation_output" / filename,
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"Simulation file not found: {filename}\n"
        f"Searched: {', '.join(str(c) for c in candidates)}"
    )


def _load_simulation_metadata(filepath: Path) -> dict:
    """Load just the metadata we need for estimation (without holding full data in memory)."""
    with open(filepath) as f:
        data = json.load(f)
    return data


def _count_frames_in_window(
    data: dict, start_hour: float, end_hour: float
) -> tuple[int, str | None, str | None]:
    """Count unique timestamps in the requested time window.

    Returns (frame_count, first_timestamp, last_timestamp).
    """
    config = data.get("config", {})
    snapshots = data.get("position_snapshots", [])

    if not snapshots:
        return 0, None, None

    # Collect unique timestamps
    all_times = sorted(set(s["time"] for s in snapshots))

    # Determine simulation start for hour-based windowing
    start_time_iso = config.get("start_time")
    if not start_time_iso:
        start_time_iso = all_times[0]

    if isinstance(start_time_iso, str):
        sim_start = datetime.fromisoformat(start_time_iso.replace("Z", "+00:00"))
    else:
        sim_start = start_time_iso

    window_start = sim_start + timedelta(hours=start_hour)
    window_end = sim_start + timedelta(hours=end_hour)
    window_start_iso = window_start.isoformat()
    window_end_iso = window_end.isoformat()

    windowed = [t for t in all_times if window_start_iso <= t <= window_end_iso]

    if not windowed:
        return 0, None, None
    return len(windowed), windowed[0], windowed[-1]


@dataclass
class VideoEstimate:
    """Pre-render estimate of video output."""

    simulation_file: str
    airport: str
    total_sim_frames: int
    windowed_frames: int
    captured_frames: int  # after speed skip
    video_duration_seconds: float
    estimated_mp4_size_mb: float
    estimated_temp_disk_mb: float
    resolution: tuple[int, int]
    fps: int
    speed: int
    start_hour: float
    end_hour: float
    first_timestamp: str | None
    last_timestamp: str | None
    total_flights: int
    scenario_name: str | None

    def summary(self) -> str:
        """Human-readable summary for confirmation prompt."""
        lines = [
            f"Simulation: {self.simulation_file}",
            f"Airport:    {self.airport}",
            f"Flights:    {self.total_flights}",
        ]
        if self.scenario_name:
            lines.append(f"Scenario:   {self.scenario_name}")
        lines.extend([
            f"",
            f"Time window: hour {self.start_hour} - {self.end_hour}",
            f"  First frame: {self.first_timestamp or 'N/A'}",
            f"  Last frame:  {self.last_timestamp or 'N/A'}",
            f"  Frames in window: {self.windowed_frames}",
            f"",
            f"Render settings:",
            f"  Resolution: {self.resolution[0]}x{self.resolution[1]}",
            f"  FPS: {self.fps}",
            f"  Speed: {self.speed}x (capture every {self.speed} frame{'s' if self.speed > 1 else ''})",
            f"  Frames to capture: {self.captured_frames}",
            f"",
            f"Output estimate:",
            f"  Video duration: {self._format_duration(self.video_duration_seconds)}",
            f"  MP4 file size:  ~{self.estimated_mp4_size_mb:.1f} MB",
            f"  Temp disk (PNG frames): ~{self.estimated_temp_disk_mb:.0f} MB",
        ])
        return "\n".join(lines)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}h {m}m {s}s"
        elif m > 0:
            return f"{m}m {s}s"
        return f"{s}s"


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
        view_mode: str = "2d",
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
        self.view_mode = view_mode

    def estimate(self) -> VideoEstimate:
        """Read the simulation file and estimate output size without rendering.

        This reads the JSON directly — no browser or running app needed.
        """
        filepath = _find_simulation_file(self.simulation_file)
        data = _load_simulation_metadata(filepath)

        config = data.get("config", {})
        summary = data.get("summary", {})

        # Count all frames and windowed frames
        all_times = sorted(set(s["time"] for s in data.get("position_snapshots", [])))
        total_sim_frames = len(all_times)

        windowed_frames, first_ts, last_ts = _count_frames_in_window(
            data, self.start_hour, self.end_hour
        )

        # After speed skip
        captured_frames = len(range(0, windowed_frames, self.speed))

        # Video duration = captured frames / fps
        video_duration = captured_frames / self.fps if self.fps > 0 else 0

        # Scale size estimate by resolution relative to 1080p
        resolution_scale = (self.width * self.height) / (1920 * 1080)
        estimated_mp4_bytes = (
            captured_frames * _ESTIMATED_BYTES_PER_FRAME_1080P * resolution_scale
        )
        estimated_temp_bytes = (
            captured_frames * _ESTIMATED_PNG_BYTES_PER_FRAME * resolution_scale
        )

        return VideoEstimate(
            simulation_file=self.simulation_file,
            airport=config.get("airport", "?"),
            total_sim_frames=total_sim_frames,
            windowed_frames=windowed_frames,
            captured_frames=captured_frames,
            video_duration_seconds=video_duration,
            estimated_mp4_size_mb=estimated_mp4_bytes / (1024 * 1024),
            estimated_temp_disk_mb=estimated_temp_bytes / (1024 * 1024),
            resolution=(self.width, self.height),
            fps=self.fps,
            speed=self.speed,
            start_hour=self.start_hour,
            end_hour=self.end_hour,
            first_timestamp=first_ts,
            last_timestamp=last_ts,
            total_flights=summary.get("total_flights", 0),
            scenario_name=summary.get("scenario_name"),
        )

    async def render(self, skip_confirmation: bool = False) -> Path:
        """Run the full render pipeline: estimate, confirm, capture, encode.

        Args:
            skip_confirmation: If True, skip the interactive confirmation prompt.
        """
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

        # Estimate and optionally confirm
        est = self.estimate()
        if est.captured_frames == 0:
            raise RuntimeError(
                f"No frames found in time window {self.start_hour}-{self.end_hour}h"
            )

        if not skip_confirmation:
            print("\n" + "=" * 56)
            print("  VIDEO RENDER ESTIMATE")
            print("=" * 56)
            print(est.summary())
            print("=" * 56)
            print(f"  Output: {self.output_path}")
            print("=" * 56 + "\n")
            answer = input("Proceed with rendering? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                print("Cancelled.")
                raise KeyboardInterrupt("User cancelled render")

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
            await page.goto(self.app_url, wait_until="load", timeout=60000)
            await self._wait_for_backend(page)

            # Switch to the correct airport for this simulation
            await self._switch_airport(page)

            # Switch to the requested view mode
            logger.info("Switching to %s view", self.view_mode.upper())
            await page.evaluate(
                "mode => window.__viewControl.setViewMode(mode)", self.view_mode
            )

            if self.view_mode == "3d":
                # Wait for 3D canvas to appear
                await page.wait_for_selector("canvas", timeout=30000)
                # Give Three.js a moment to initialize
                await page.wait_for_timeout(2000)
            else:
                # Wait for Leaflet map tiles to load
                await page.wait_for_selector(".leaflet-container", timeout=30000)
                await page.wait_for_timeout(3000)

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
                # Wait for render: 2D needs Leaflet marker update, 3D needs RAF
                if self.view_mode == "2d":
                    # Leaflet updates markers synchronously on state change,
                    # but give React + DOM a tick to settle
                    await page.evaluate(
                        "() => new Promise(r => setTimeout(r, 50))"
                    )
                else:
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

    # Map IATA codes used in simulation configs to ICAO codes for airport loading
    _IATA_TO_ICAO = {
        "SFO": "KSFO", "JFK": "KJFK", "LAX": "KLAX", "ORD": "KORD",
        "ATL": "KATL", "DFW": "KDFW", "DEN": "KDEN", "SEA": "KSEA",
        "LHR": "EGLL", "DXB": "OMDB", "NRT": "RJAA", "HND": "RJTT",
        "CDG": "LFPG", "FRA": "EDDF", "AMS": "EHAM", "SIN": "WSSS",
        "HKG": "VHHH", "ICN": "RKSI", "SYD": "YSSY", "GRU": "SBGR",
    }

    async def _switch_airport(self, page) -> None:
        """Switch the app to the airport used in the simulation file."""
        filepath = _find_simulation_file(self.simulation_file)
        with open(filepath) as f:
            data = json.load(f)
        iata = data.get("config", {}).get("airport", "")
        icao = self._IATA_TO_ICAO.get(iata, f"K{iata}")  # default: prepend K

        current = await page.evaluate(
            "() => window.__airportControl?.getCurrentAirport()"
        )
        if current and current.upper() == icao.upper():
            logger.info("Already on airport %s", icao)
            return

        logger.info("Switching airport to %s (from sim config: %s)", icao, iata)
        await page.evaluate(
            "code => window.__airportControl.loadAirport(code)", icao
        )
        # Wait for airport to finish loading (OSM data fetch + render)
        for _ in range(60):
            cur = await page.evaluate(
                "() => window.__airportControl?.getCurrentAirport()"
            )
            if cur and cur.upper() == icao.upper():
                logger.info("Airport switched to %s", icao)
                # Give map tiles time to load
                await page.wait_for_timeout(3000)
                return
            await page.wait_for_timeout(1000)
        logger.warning("Airport switch to %s may not have completed", icao)

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
        """Get bounding box of the map area for cropping (2D or 3D)."""
        # In 2D mode, crop to .leaflet-container; in 3D, crop to canvas
        selector = ".leaflet-container" if self.view_mode == "2d" else "canvas"
        clip = await page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
            }""",
            selector,
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
            "Encoded %d frames -> %s (%.1f MB)", frame_count, self.output_path, size_mb
        )
