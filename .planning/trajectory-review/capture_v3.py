"""Capture trajectory screenshots v3 — proper auth, multiple zoom levels."""

import json
import os
import time

from playwright.sync_api import sync_playwright

APP_URL = "https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com"
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

token = open("/tmp/db_token.txt").read().strip()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        device_scale_factor=2,
    )
    page = context.new_page()
    context.set_extra_http_headers({"Authorization": f"Bearer {token}"})

    print("Loading app...")
    page.goto(APP_URL, wait_until="networkidle", timeout=60000)
    time.sleep(8)
    print(f"Title: {page.title()}, URL: {page.url}")

    # Screenshot 1: Default view
    page.screenshot(path=f"{OUTPUT_DIR}/30_default.png")
    print("30_default.png")

    # Zoom out 4x to see approach corridors
    zoom_out = page.locator("a.leaflet-control-zoom-out")
    for _ in range(4):
        try:
            zoom_out.click(timeout=2000)
            time.sleep(0.4)
        except Exception:
            break
    time.sleep(3)
    page.screenshot(path=f"{OUTPUT_DIR}/31_zoomed_out_4x.png")
    print("31_zoomed_out_4x.png")

    # Zoom out 3 more
    for _ in range(3):
        try:
            zoom_out.click(timeout=2000)
            time.sleep(0.4)
        except Exception:
            break
    time.sleep(3)
    page.screenshot(path=f"{OUTPUT_DIR}/32_zoomed_out_7x.png")
    print("32_zoomed_out_7x.png")

    # Zoom back in to medium (approach path visible)
    zoom_in = page.locator("a.leaflet-control-zoom-in")
    for _ in range(5):
        try:
            zoom_in.click(timeout=2000)
            time.sleep(0.4)
        except Exception:
            break
    time.sleep(3)
    page.screenshot(path=f"{OUTPUT_DIR}/33_medium_zoom.png")
    print("33_medium_zoom.png")

    # Try to click on an approaching flight from list
    # First let's look at how flights appear in the DOM
    flight_info = page.evaluate("""() => {
        // Get all elements with 'APP' or 'ENR' text (phase badges)
        const all = document.body.querySelectorAll('*');
        const matches = [];
        for (const el of all) {
            const text = el.textContent?.trim() || '';
            if ((text.includes('APP') || text.includes('ENR') || text.includes('DEP'))
                && text.length < 200
                && el.children.length < 5) {
                matches.push({
                    tag: el.tagName,
                    text: text.substring(0, 80),
                    cls: (el.className || '').substring(0, 60),
                    clickable: el.style?.cursor === 'pointer' || el.closest('[role="button"]') !== null
                });
            }
        }
        return matches.slice(0, 15);
    }""")
    print(f"\nPhase elements found: {len(flight_info)}")
    for fi in flight_info[:5]:
        print(f"  {fi['tag']}.{fi['cls'][:30]} -> {fi['text'][:60]}")

    # Try clicking a flight with trajectory toggle
    # Look for list items that are expandable
    clicked_flight = False
    try:
        # Click on the first flight entry that contains APP or ENR
        for fi in flight_info:
            if 'APP' in fi['text'] or 'ENR' in fi['text']:
                # Find and click this element
                selector = f"text=/{fi['text'][:20].replace('(', '.').replace(')', '.')}/"
                try:
                    el = page.locator(selector).first
                    el.click(timeout=3000)
                    time.sleep(2)
                    clicked_flight = True
                    print(f"Clicked: {fi['text'][:40]}")
                    break
                except Exception:
                    continue
    except Exception as e:
        print(f"Click error: {e}")

    page.screenshot(path=f"{OUTPUT_DIR}/34_clicked_flight.png")
    print("34_clicked_flight.png")

    # Enable trajectory display: look for Show Trajectory toggle
    try:
        traj_toggle = page.locator('text="Show Trajectory"').first
        traj_toggle.click(timeout=3000)
        time.sleep(2)
        print("Toggled trajectory display")
    except Exception:
        print("No trajectory toggle found")

    page.screenshot(path=f"{OUTPUT_DIR}/35_trajectory_toggled.png")
    print("35_trajectory_toggled.png")

    # Now try clicking directly on aircraft icons on the map
    try:
        # SVG aircraft icons or markers
        markers = page.locator("img.leaflet-marker-icon")
        mc = markers.count()
        print(f"\nLeaflet markers: {mc}")
        if mc > 0:
            markers.first.click(timeout=3000)
            time.sleep(2)
            page.screenshot(path=f"{OUTPUT_DIR}/36_marker_clicked.png")
            print("36_marker_clicked.png")
    except Exception as e:
        print(f"Marker click: {e}")

    # Zoom in slightly on current view
    for _ in range(2):
        try:
            zoom_in.click(timeout=2000)
            time.sleep(0.4)
        except Exception:
            break
    time.sleep(2)
    page.screenshot(path=f"{OUTPUT_DIR}/37_closer_zoom.png")
    print("37_closer_zoom.png")

    # Try scrolling the flight list to find airborne flights and click them
    try:
        # Find the flight list container
        list_items = page.evaluate("""() => {
            const items = document.querySelectorAll('[class*="accordion"], [class*="Accordion"]');
            return Array.from(items).map(i => ({
                text: i.textContent?.substring(0, 100),
                id: i.id
            })).slice(0, 10);
        }""")
        print(f"\nAccordion items: {len(list_items)}")
        for li in list_items[:3]:
            print(f"  {li['text'][:60]}")
    except Exception:
        pass

    # Final: zoom back to default and get a clean overview
    page.goto(APP_URL, wait_until="networkidle", timeout=60000)
    time.sleep(5)

    # Zoom out 3x for good overview
    for _ in range(3):
        try:
            page.locator("a.leaflet-control-zoom-out").click(timeout=2000)
            time.sleep(0.4)
        except Exception:
            break
    time.sleep(3)
    page.screenshot(path=f"{OUTPUT_DIR}/38_final_overview.png")
    print("38_final_overview.png")

    browser.close()

print("\nDone!")
