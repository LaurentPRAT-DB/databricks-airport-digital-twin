"""Capture trajectory screenshots v2 — wider zoom, force sim speed, select airborne flights."""

import json
import os
import subprocess
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
    print("Launching browser...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=2,
        )
        page = context.new_page()
        context.set_extra_http_headers({"Authorization": f"Bearer {token}"})

        print("Navigating to app...")
        page.goto(APP_URL, wait_until="networkidle", timeout=60000)
        time.sleep(5)

        # Reset simulation to get fresh flights
        print("Resetting simulation speed...")
        # Click speed buttons to get 30x or 60x
        try:
            # Try clicking the speed buttons in the bottom playback bar
            speed_btns = page.locator('button:has-text("30x"), button:has-text("60x")')
            if speed_btns.count() > 0:
                speed_btns.first.click()
                print("Set simulation speed")
                time.sleep(2)
        except Exception as e:
            print(f"Speed button: {e}")

        # Zoom out significantly to see approach/departure paths
        print("Zooming out to see trajectories...")
        try:
            # Use Leaflet zoom out button
            zoom_out = page.locator('.leaflet-control-zoom-out, button[title="Zoom out"], a.leaflet-control-zoom-out')
            for _ in range(8):
                if zoom_out.count() > 0:
                    zoom_out.first.click()
                    time.sleep(0.3)
        except Exception as e:
            print(f"Zoom: {e}")

        time.sleep(3)

        # Screenshot 1: Wide view showing approach/departure corridors
        path1 = os.path.join(OUTPUT_DIR, "10_wide_approach_corridors.png")
        page.screenshot(path=path1, full_page=False)
        print(f"Saved: {path1}")

        # Now let's try to click on airborne flights from the flight list
        # The flight list shows flights on the left panel
        # Find approaching/enroute flights
        print("Looking for airborne flights in the list...")

        # Try filtering to approaching flights
        try:
            # Look for phase filter dropdown or search
            search = page.locator('input[placeholder*="Search"], input[placeholder*="search"], input[type="search"]')
            if search.count() > 0:
                search.first.fill("")
                time.sleep(0.5)
        except Exception:
            pass

        # Scroll flight list to find approaching flights
        try:
            flight_items = page.locator('[class*="flight-item"], [class*="FlightItem"], li:has-text("approaching"), li:has-text("enroute")')
            print(f"Found {flight_items.count()} flight items with approaching/enroute")

            # Also try to find any flight list items
            all_items = page.locator('.flight-list-item, [class*="flightList"] li, [class*="flight-list"] > div')
            print(f"Total flight list items: {all_items.count()}")
        except Exception as e:
            print(f"Flight list: {e}")

        # Use JavaScript to zoom the map to show a wider area
        try:
            page.evaluate("""() => {
                // Try to access the Leaflet map instance
                const maps = document.querySelectorAll('.leaflet-container');
                if (maps.length > 0) {
                    // Find the map instance through Leaflet internals
                    for (const key in maps[0]) {
                        if (key.startsWith('_leaflet_id')) {
                            break;
                        }
                    }
                }
                return true;
            }""")
        except Exception:
            pass

        # Try programmatic zoom via keyboard
        print("Programmatic zoom out...")
        page.keyboard.press("Minus")
        page.keyboard.press("Minus")
        page.keyboard.press("Minus")
        time.sleep(2)

        path2 = os.path.join(OUTPUT_DIR, "11_zoomed_out_more.png")
        page.screenshot(path=path2, full_page=False)
        print(f"Saved: {path2}")

        # Try to select flights from the left panel — click on different flights
        try:
            # The flight list panel shows flights - look for expandable items
            flight_entries = page.locator('[class*="accordion"], [class*="Accordion"], details, [role="button"]')
            fcount = flight_entries.count()
            print(f"Found {fcount} expandable entries")

            # Also try direct text matching for approaching flights
            app_flights = page.locator('text=/approaching|APP|enroute|ENR/')
            print(f"Found {app_flights.count()} text matches for airborne phases")

            if app_flights.count() > 0:
                app_flights.first.click()
                time.sleep(2)
                path_sel = os.path.join(OUTPUT_DIR, "12_selected_airborne.png")
                page.screenshot(path=path_sel, full_page=False)
                print(f"Saved: {path_sel}")
        except Exception as e:
            print(f"Flight selection: {e}")

        # Try to find the flight list items directly
        try:
            # Look at what's in the flight list sidebar
            sidebar_html = page.locator('[class*="sidebar"], [class*="panel"], [class*="list"]').first.inner_html()
            print(f"Sidebar HTML (first 500): {sidebar_html[:500]}")
        except Exception as e:
            print(f"Sidebar: {e}")

        # Let sim run at faster speed to get more trajectory data
        print("Running simulation for trajectory accumulation...")

        # Click 60x speed if available
        try:
            btn = page.locator('button:has-text("60x")')
            if btn.count() > 0:
                btn.first.click()
                print("Set 60x speed")
        except Exception:
            pass

        time.sleep(10)

        # Screenshot after more time
        path3 = os.path.join(OUTPUT_DIR, "13_after_sim_advance.png")
        page.screenshot(path=path3, full_page=False)
        print(f"Saved: {path3}")

        # Zoom back in to medium level to see individual trajectory lines
        print("Zooming to medium level...")
        try:
            zoom_in = page.locator('.leaflet-control-zoom-in, button[title="Zoom in"], a.leaflet-control-zoom-in')
            for _ in range(4):
                if zoom_in.count() > 0:
                    zoom_in.first.click()
                    time.sleep(0.3)
        except Exception:
            pass

        time.sleep(2)
        path4 = os.path.join(OUTPUT_DIR, "14_medium_zoom_trajectories.png")
        page.screenshot(path=path4, full_page=False)
        print(f"Saved: {path4}")

        # Try to click various flights from the left list
        try:
            # Get all clickable flight items
            items = page.locator('div[class*="cursor-pointer"], div[role="button"]')
            icount = items.count()
            print(f"Clickable items: {icount}")
            for i in range(min(icount, 5)):
                try:
                    text = items.nth(i).text_content()
                    if text and any(kw in text.lower() for kw in ['app', 'enr', 'approach', 'depart']):
                        items.nth(i).click()
                        time.sleep(2)
                        path_f = os.path.join(OUTPUT_DIR, f"15_flight_{i}.png")
                        page.screenshot(path=path_f, full_page=False)
                        print(f"Saved: {path_f} (clicked: {text[:50]})")
                        break
                except Exception:
                    continue
        except Exception as e:
            print(f"Individual flight: {e}")

        # Get trajectory SVG paths from the page
        try:
            svg_info = page.evaluate("""() => {
                const paths = document.querySelectorAll('svg path');
                const results = [];
                for (const p of paths) {
                    const d = p.getAttribute('d');
                    const stroke = p.getAttribute('stroke') || window.getComputedStyle(p).stroke;
                    const cls = p.className?.baseVal || '';
                    if (d && d.length > 100) {  // Only long paths (trajectory lines)
                        results.push({
                            d_length: d.length,
                            stroke: stroke,
                            class: cls,
                            d_start: d.substring(0, 100),
                        });
                    }
                }
                return results;
            }""")
            print(f"\nLong SVG paths (likely trajectories): {len(svg_info)}")
            for s in svg_info[:5]:
                print(f"  stroke={s['stroke']}, d_len={s['d_length']}, class={s['class']}")
        except Exception as e:
            print(f"SVG analysis: {e}")

        # Final comprehensive screenshot
        path_final = os.path.join(OUTPUT_DIR, "16_final_comprehensive.png")
        page.screenshot(path=path_final, full_page=False)
        print(f"Saved: {path_final}")

        browser.close()

    print(f"\nDone! All screenshots in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
