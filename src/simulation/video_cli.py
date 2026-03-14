"""CLI entry point for rendering simulation replay videos.

Usage:
    python -m src.simulation.video_cli \
        --simulation-file simulation_output_sfo_50.json \
        --output video_output/sfo_50_replay.mp4

    python -m src.simulation.video_cli \
        --simulation-file simulation_output_sfo_50.json \
        --output video_output/sfo_50_replay.mp4 \
        --fps 30 --resolution 1920x1080 --start-hour 6 --end-hour 10
"""

import argparse
import asyncio
import logging
import sys


def parse_resolution(value: str) -> tuple[int, int]:
    """Parse 'WIDTHxHEIGHT' string into (width, height) tuple."""
    try:
        w, h = value.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        raise argparse.ArgumentTypeError(
            f"Invalid resolution '{value}'. Expected format: WIDTHxHEIGHT (e.g., 1920x1080)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render simulation replay to MP4 video using headless browser capture."
    )
    parser.add_argument(
        "--simulation-file",
        required=True,
        help="Simulation output filename (e.g., simulation_output_sfo_50.json)",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output MP4 file path (e.g., video_output/replay.mp4)",
    )
    parser.add_argument(
        "--app-url",
        default="http://localhost:3000",
        help="URL of the running app (default: http://localhost:3000)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=30,
        help="Output video framerate (default: 30)",
    )
    parser.add_argument(
        "--resolution",
        type=parse_resolution,
        default=(1920, 1080),
        help="Viewport resolution WIDTHxHEIGHT (default: 1920x1080)",
    )
    parser.add_argument(
        "--speed",
        type=int,
        default=1,
        help="Frame skip factor: 1 = every frame, 2 = every other, etc. (default: 1)",
    )
    parser.add_argument(
        "--start-hour",
        type=float,
        default=0,
        help="Start hour within simulation (default: 0)",
    )
    parser.add_argument(
        "--end-hour",
        type=float,
        default=24,
        help="End hour within simulation (default: 24)",
    )
    parser.add_argument(
        "--no-crop",
        action="store_true",
        help="Include full UI (header, sidebars) instead of cropping to 3D canvas",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from src.simulation.video_renderer import VideoRenderer

    width, height = args.resolution
    renderer = VideoRenderer(
        app_url=args.app_url,
        output_path=args.output,
        simulation_file=args.simulation_file,
        fps=args.fps,
        width=width,
        height=height,
        speed=args.speed,
        start_hour=args.start_hour,
        end_hour=args.end_hour,
        crop_to_canvas=not args.no_crop,
    )

    try:
        output = asyncio.run(renderer.render())
        print(f"\nVideo saved: {output}")
    except RuntimeError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)


if __name__ == "__main__":
    main()
