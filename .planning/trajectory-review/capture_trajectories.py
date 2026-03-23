"""Capture trajectory screenshots and flight data for ATC review.

Uses Playwright to authenticate via Databricks OAuth and capture
map screenshots with trajectory lines visible.
"""

import json
import os
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

APP_URL = "https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com"
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


def get_token():
    result = subprocess.run(
        ["databricks", "auth", "token", "--profile", "FEVM_SERVERLESS_STABLE"],
        capture_output=True, text=True, timeout=15,
    )
    return json.loads(result.stdout)["access_token"]


def main():
    token = get_token()
    print(f"Got auth token, launching browser...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=2,
        )
        page = context.new_page()

        # Set auth cookie/header before navigation
        # Databricks Apps use Bearer token auth
        context.set_extra_http_headers({
            "Authorization": f"Bearer {token}"
        })

        print("Navigating to app...")
        page.goto(APP_URL, wait_until="networkidle", timeout=60000)
        time.sleep(3)

        # Check if we landed on the app or a login page
        title = page.title()
        url = page.url
        print(f"Page title: {title}")
        print(f"Page URL: {url}")

        # Wait for map tiles to load
        print("Waiting for map to render...")
        time.sleep(8)

        # Screenshot 1: Full overview
        path1 = os.path.join(OUTPUT_DIR, "01_full_overview.png")
        page.screenshot(path=path1, full_page=False)
        print(f"Saved: {path1}")

        # Try to start/ensure simulation is running
        # Click play button if visible
        try:
            play_btn = page.locator('button:has-text("Play"), button[aria-label*="play"], button[title*="Play"]')
            if play_btn.count() > 0:
                play_btn.first.click()
                print("Clicked play button")
                time.sleep(5)
        except Exception as e:
            print(f"No play button found: {e}")

        # Wait more for trajectories to appear
        time.sleep(5)

        # Screenshot 2: After simulation runs a bit
        path2 = os.path.join(OUTPUT_DIR, "02_simulation_running.png")
        page.screenshot(path=path2, full_page=False)
        print(f"Saved: {path2}")

        # Try to click on an aircraft to show its trajectory
        try:
            # Look for aircraft markers (SVG or canvas elements on map)
            markers = page.locator('.leaflet-marker-icon, .aircraft-marker, [class*="aircraft"], [class*="flight"]')
            marker_count = markers.count()
            print(f"Found {marker_count} aircraft markers")
            if marker_count > 0:
                # Click the first visible marker
                for i in range(min(marker_count, 10)):
                    try:
                        m = markers.nth(i)
                        if m.is_visible():
                            m.click()
                            print(f"Clicked marker {i}")
                            time.sleep(2)
                            break
                    except Exception:
                        continue
        except Exception as e:
            print(f"Marker click failed: {e}")

        # Screenshot 3: With selected aircraft
        path3 = os.path.join(OUTPUT_DIR, "03_selected_aircraft.png")
        page.screenshot(path=path3, full_page=False)
        print(f"Saved: {path3}")

        # Try zooming in on the airport area
        try:
            # Zoom in using keyboard
            for _ in range(3):
                page.keyboard.press("Equal")  # Zoom in
                time.sleep(0.5)
            time.sleep(2)
        except Exception:
            pass

        # Screenshot 4: Zoomed in on airport
        path4 = os.path.join(OUTPUT_DIR, "04_zoomed_airport.png")
        page.screenshot(path=path4, full_page=False)
        print(f"Saved: {path4}")

        # Zoom back out
        try:
            for _ in range(6):
                page.keyboard.press("Minus")
                time.sleep(0.5)
            time.sleep(2)
        except Exception:
            pass

        # Screenshot 5: Wide view showing approach paths
        path5 = os.path.join(OUTPUT_DIR, "05_wide_approach_view.png")
        page.screenshot(path=path5, full_page=False)
        print(f"Saved: {path5}")

        # Let simulation advance more
        time.sleep(10)

        # Screenshot 6: Updated positions
        path6 = os.path.join(OUTPUT_DIR, "06_updated_positions.png")
        page.screenshot(path=path6, full_page=False)
        print(f"Saved: {path6}")

        # Try to get console logs for trajectory data
        console_messages = []
        page.on("console", lambda msg: console_messages.append(msg.text))

        # Check for any error overlays
        errors = page.locator('[class*="error"], [class*="Error"]')
        if errors.count() > 0:
            print(f"Found {errors.count()} error elements on page")

        # Screenshot 7: Get the flight info panel if visible
        try:
            panel = page.locator('[class*="panel"], [class*="sidebar"], [class*="info"]')
            if panel.count() > 0:
                print(f"Found {panel.count()} panel elements")
        except Exception:
            pass

        path7 = os.path.join(OUTPUT_DIR, "07_final_state.png")
        page.screenshot(path=path7, full_page=False)
        print(f"Saved: {path7}")

        # Get page HTML structure for debugging
        html_summary = page.evaluate("""() => {
            const map = document.querySelector('.leaflet-container');
            const svgPaths = document.querySelectorAll('path');
            const polylines = document.querySelectorAll('polyline');
            const markers = document.querySelectorAll('.leaflet-marker-icon');
            return {
                hasMap: !!map,
                svgPathCount: svgPaths.length,
                polylineCount: polylines.length,
                markerCount: markers.length,
                bodyClasses: document.body.className,
                title: document.title,
            };
        }""")
        print(f"\nPage structure: {json.dumps(html_summary, indent=2)}")

        browser.close()

    print(f"\nAll screenshots saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
