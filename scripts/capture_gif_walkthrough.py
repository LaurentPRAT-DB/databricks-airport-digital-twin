"""Capture a GIF walkthrough of the Airport Digital Twin app."""

import json
import os
import subprocess
import time
from pathlib import Path

import imageio.v3 as iio
from PIL import Image
from playwright.sync_api import sync_playwright

APP_URL = "https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com"
DB_PROFILE = "FEVM_SERVERLESS_STABLE"
OUTPUT_DIR = Path("test-results")
GIF_PATH = OUTPUT_DIR / "app_walkthrough.gif"


def get_token(profile: str) -> str:
    result = subprocess.run(
        ["databricks", "auth", "token", "--profile", profile],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Auth failed: {result.stderr}")
    return json.loads(result.stdout)["access_token"]


def capture_walkthrough():
    OUTPUT_DIR.mkdir(exist_ok=True)
    token = get_token(DB_PROFILE)
    frames: list[Path] = []
    frame_idx = 0

    def screenshot(page, label: str, delay: float = 1.0):
        nonlocal frame_idx
        time.sleep(delay)
        path = OUTPUT_DIR / f"frame_{frame_idx:03d}_{label}.png"
        page.screenshot(path=str(path))
        frames.append(path)
        frame_idx += 1
        print(f"  [{frame_idx}] {label}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={"Authorization": f"Bearer {token}"},
        )
        page = context.new_page()

        # 1. Load app
        print("Loading app...")
        page.goto(APP_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)
        screenshot(page, "01_map_loaded", delay=2)

        # 2. Click on a flight (aircraft icon on the map)
        print("Clicking a flight...")
        # Wait for flights to appear — they're SVG/canvas markers
        page.wait_for_timeout(3000)
        # Try clicking an aircraft marker — leaflet markers or custom divs
        flight_marker = page.locator('[class*="aircraft"], [class*="flight-marker"], .leaflet-marker-icon, [data-flight]').first
        if flight_marker.is_visible(timeout=5000):
            flight_marker.click()
            screenshot(page, "02_flight_clicked", delay=2)
        else:
            # Fallback: click somewhere on the map where flights typically are
            page.mouse.click(960, 540)
            screenshot(page, "02_map_clicked", delay=2)

        # 3. Scroll right panel to show flight details
        print("Scrolling right panel...")
        right_panel = page.locator('[class*="panel"], [class*="sidebar"], [class*="flight-info"], aside').first
        if right_panel.is_visible(timeout=3000):
            right_panel.evaluate("el => el.scrollTop = el.scrollHeight / 2")
            screenshot(page, "03_panel_scrolled", delay=1.5)
            right_panel.evaluate("el => el.scrollTop = el.scrollHeight")
            screenshot(page, "04_panel_bottom", delay=1.5)

        # Helper: close modal overlay
        def close_modal(page, label: str = ""):
            time.sleep(0.5)
            # Try aria-label close buttons first
            close = page.locator(f'[aria-label="Close {label}"], [aria-label="Close"], button:has-text("✕")').first
            if close.is_visible(timeout=2000):
                close.click(force=True)
                time.sleep(0.5)
                return
            # Fallback: Escape key
            page.keyboard.press("Escape")
            time.sleep(1)

        # 4. Click FIDS tab
        print("Opening FIDS...")
        fids_btn = page.locator('button:has-text("FIDS"), [data-tab="fids"], a:has-text("FIDS"), [aria-label*="FIDS"]').first
        if fids_btn.is_visible(timeout=3000):
            fids_btn.click()
            screenshot(page, "05_fids_open", delay=2)
            close_modal(page, "FIDS")
            screenshot(page, "06_fids_closed", delay=1)

        # 5. Click KPI / Data Ops tab
        print("Opening KPI...")
        kpi_btn = page.locator('button:has-text("KPI"), button:has-text("Data Ops"), [data-tab="kpi"], a:has-text("KPI")').first
        if kpi_btn.is_visible(timeout=3000):
            kpi_btn.click()
            screenshot(page, "07_kpi_open", delay=2)
            close_modal(page, "Data Ops")
            screenshot(page, "08_kpi_closed", delay=1)

        # 6. Click Report tab
        print("Opening Report...")
        # Dismiss any lingering overlays first
        page.evaluate("document.querySelectorAll('[class*=\"inset-0\"][class*=\"bg-black\"]').forEach(e => e.remove())")
        time.sleep(0.5)
        report_btn = page.locator('button:has-text("Report"), [data-tab="report"], a:has-text("Report")').first
        if report_btn.is_visible(timeout=3000):
            report_btn.click(force=True)
            screenshot(page, "09_report_open", delay=2)
            close_modal(page, "Report")

        # 7. Click Platform links
        print("Opening Platform links...")
        page.evaluate("document.querySelectorAll('[class*=\"inset-0\"][class*=\"bg-black\"]').forEach(e => e.remove())")
        time.sleep(0.5)
        platform_btn = page.locator('button:has-text("Platform"), a:has-text("Platform"), [data-tab="platform"]').first
        if platform_btn.is_visible(timeout=3000):
            platform_btn.click(force=True)
            screenshot(page, "10_platform_links", delay=2)

        # Final state
        screenshot(page, "11_final", delay=1)

        browser.close()

    # Build GIF from frames
    print(f"\nBuilding GIF from {len(frames)} frames...")
    images = []
    for fpath in frames:
        img = Image.open(fpath)
        # Resize to 960x540 for reasonable GIF size
        img = img.resize((960, 540), Image.LANCZOS)
        images.append(img)

    # Save as GIF with 2s per frame
    if images:
        images[0].save(
            str(GIF_PATH),
            save_all=True,
            append_images=images[1:],
            duration=2000,  # 2s per frame
            loop=0,
        )
        size_mb = GIF_PATH.stat().st_size / 1024 / 1024
        print(f"✓ GIF saved: {GIF_PATH} ({size_mb:.1f} MB, {len(frames)} frames)")
    else:
        print("✗ No frames captured")


if __name__ == "__main__":
    capture_walkthrough()
