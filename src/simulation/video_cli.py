"""CLI entry point for rendering simulation replay videos.

Usage:
    python -m src.simulation.video_cli \
        --simulation-file simulation_output_sfo_100.json \
        --output video_output/sfo_100_replay.mp4

    python -m src.simulation.video_cli \
        --simulation-file simulation_output_sfo_100.json \
        --output video_output/sfo_morning.mp4 \
        --fps 30 --resolution 1920x1080 --start-hour 6 --end-hour 10

    # Estimate only (no rendering):
    python -m src.simulation.video_cli \
        --simulation-file simulation_output_sfo_100.json \
        --output /dev/null --estimate-only
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
        help="Simulation output filename (e.g., simulation_output_sfo_100.json)",
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
        help="Include full UI (header, sidebars) instead of cropping to map area",
    )
    parser.add_argument(
        "--view-mode",
        choices=["2d", "3d"],
        default="2d",
        help="Map view mode: 2d (Leaflet bird's eye) or 3d (Three.js). Default: 2d",
    )
    parser.add_argument(
        "--track-flight",
        default=None,
        help="Select and track a specific flight by icao24 ID (shows trajectory)",
    )
    parser.add_argument(
        "--estimate-only",
        action="store_true",
        help="Print size estimate and exit without rendering",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt and render immediately",
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
        view_mode=args.view_mode,
        track_flight=args.track_flight,
    )

    # Always compute and show the estimate first
    try:
        est = renderer.estimate()
    except FileNotFoundError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 56)
    print("  VIDEO RENDER ESTIMATE")
    print("=" * 56)
    print(est.summary())
    print("=" * 56)
    print(f"  Output: {args.output}")
    print("=" * 56)

    if est.captured_frames == 0:
        print("\nNo frames in the requested time window. Nothing to render.")
        sys.exit(0)

    if args.estimate_only:
        sys.exit(0)

    # Confirmation (unless --yes)
    if not args.yes:
        try:
            answer = input("\nProceed with rendering? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("Cancelled.")
            sys.exit(0)

    try:
        # skip_confirmation=True because we already confirmed above
        output = asyncio.run(renderer.render(skip_confirmation=True))
        size_mb = output.stat().st_size / (1024 * 1024)
        print(f"\nVideo saved: {output} ({size_mb:.1f} MB)")
    except RuntimeError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(130)


if __name__ == "__main__":
    main()
