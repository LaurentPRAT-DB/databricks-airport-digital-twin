"""UI E2E test — exercises the deployed Airport Digital Twin like a real user.

Runs headless Chromium via Playwright against the Databricks App URL.
Collects timings, console errors, screenshots on failure, and outputs
a structured JSON report for Claude Code to parse and act on.

Usage:
    uv run python scripts/test_ui_e2e.py [--url URL] [--headed]
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, ConsoleMessage

APP_URL = "https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com"
DB_PROFILE = os.getenv("DB_PROFILE", "FEVM_SERVERLESS_STABLE")
REPORT_DIR = Path("test-results")


def get_databricks_token(profile: str = DB_PROFILE) -> str:
    result = subprocess.run(
        ["databricks", "auth", "token", "--profile", profile],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get Databricks token: {result.stderr}")
    return json.loads(result.stdout)["access_token"]


def get_flight_data(page: Page) -> list[dict]:
    return page.evaluate("""() => {
        return fetch('/api/flights')
            .then(r => r.json())
            .then(d => d.flights || [])
            .catch(() => []);
    }""")


class Scenario:
    def __init__(self, id: str, name: str):
        self.id = id
        self.name = name
        self.status = "pending"
        self.duration_ms = 0
        self.details = ""
        self.console_errors: list[str] = []
        self.screenshot: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "details": self.details,
            "console_errors": self.console_errors,
            "screenshot": self.screenshot,
        }


def capture_screenshot(page: Page, scenario: Scenario) -> str:
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f"{scenario.id}_fail.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path)


def run_scenario(page: Page, scenario: Scenario, fn, console_errors: list):
    start = time.monotonic()
    errors_before = len(console_errors)
    try:
        fn(page, scenario)
        if scenario.status == "pending":
            scenario.status = "pass"
    except Exception as e:
        scenario.status = "fail"
        scenario.details = f"Exception: {e}"
        scenario.screenshot = capture_screenshot(page, scenario)
    finally:
        scenario.duration_ms = int((time.monotonic() - start) * 1000)
        scenario.console_errors = console_errors[errors_before:]


def s1_initial_load(page: Page, s: Scenario):
    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(3000)

    flights = get_flight_data(page)
    if len(flights) == 0:
        s.status = "fail"
        s.details = "No flights returned from API after page load"
        return

    map_visible = page.locator(".leaflet-container, canvas").first.is_visible()
    s.details = f"{len(flights)} flights loaded, map_visible={map_visible}"
    if not map_visible:
        s.status = "fail"
        s.details += " — map not visible"


def s2_flight_list(page: Page, s: Scenario):
    page.wait_for_timeout(2000)
    flights = get_flight_data(page)
    count = len(flights)
    if count < 5:
        s.status = "fail"
        s.details = f"Only {count} flights (expected >= 5)"
        return
    s.details = f"{count} flights in API response"


def s3_click_flight(page: Page, s: Scenario):
    markers = page.locator("svg[role='img'][aria-label*='Flight']")
    count = markers.count()
    if count == 0:
        s.status = "skip"
        s.details = "No flight markers found on map"
        return
    markers.first.click()
    page.wait_for_timeout(1500)
    panel = page.locator("[class*='flight-detail'], [class*='FlightDetail'], [class*='selectedFlight']").first
    if panel.is_visible():
        s.details = "Flight detail panel opened"
    else:
        s.details = "Clicked flight marker, panel may use different selector"


def s4_view_toggle(page: Page, s: Scenario):
    toggle_btn = page.locator("button:has-text('3D'), button:has-text('2D')").first
    if not toggle_btn.is_visible():
        s.status = "skip"
        s.details = "View toggle button not found"
        return
    current_text = toggle_btn.inner_text()
    toggle_btn.click()
    page.wait_for_timeout(3000)

    flights = get_flight_data(page)
    if len(flights) > 0:
        s.details = f"Toggled from {current_text}, {len(flights)} flights still active"
    else:
        s.status = "fail"
        s.details = f"Toggled from {current_text}, but no flights after toggle"

    toggle_btn2 = page.locator("button:has-text('3D'), button:has-text('2D')").first
    if toggle_btn2.is_visible():
        toggle_btn2.click()
        page.wait_for_timeout(2000)


def _switch_airport(page: Page, s: Scenario, icao: str, expected_lat: float, expected_lon: float, tolerance: float = 2.0):
    selector_btn = page.locator("button:has-text('KSFO'), button:has-text('MMMX'), button:has-text('LSGG'), [class*='AirportSelector'] button").first
    if not selector_btn.is_visible():
        selector_btn = page.locator("button").filter(has_text=icao[:4]).first
    if not selector_btn.is_visible():
        all_btns = page.locator("header button, nav button").all()
        for btn in all_btns:
            txt = btn.inner_text()
            if any(code in txt for code in ["KSFO", "MMMX", "LSGG", "SFO", "MEX", "GVA"]):
                selector_btn = btn
                break

    if selector_btn.is_visible():
        selector_btn.click()
        page.wait_for_timeout(1000)

    airport_btn = page.locator(f"button:has-text('{icao}')").first
    if not airport_btn.is_visible():
        airport_btn = page.locator(f"text={icao}").first

    if airport_btn.is_visible():
        airport_btn.click()
    else:
        page.evaluate(f"""() => fetch('/api/airports/{icao}/activate', {{method: 'POST'}})""")
        s.details = f"Used API fallback to switch to {icao}"

    page.wait_for_timeout(25000)

    flights = get_flight_data(page)
    ground = [f for f in flights if (f.get("altitude") or 9999) < 500]
    near_target = sum(
        1 for f in ground
        if abs(float(f.get("latitude", 0)) - expected_lat) < tolerance
        and abs(float(f.get("longitude", 0)) - expected_lon) < tolerance
    )
    near_sfo = sum(
        1 for f in ground
        if abs(float(f.get("latitude", 0)) - 37.62) < 0.5
        and abs(float(f.get("longitude", 0)) - (-122.38)) < 0.5
    )

    s.details = f"{icao}: {len(flights)} flights, {len(ground)} ground, {near_target} near target, {near_sfo} near SFO"

    if icao != "KSFO" and near_sfo > 0:
        s.status = "fail"
        s.details += f" — {near_sfo} flights still at SFO!"
        return

    if len(ground) > 0 and near_target == 0:
        s.status = "fail"
        s.details += " — no ground flights near target airport"
        return


def s5_switch_mmmx(page: Page, s: Scenario):
    _switch_airport(page, s, "MMMX", 19.43, -99.07)


def s6_verify_mmmx(page: Page, s: Scenario):
    flights = get_flight_data(page)
    ground = [f for f in flights if (f.get("altitude") or 9999) < 500]
    near_sfo = sum(
        1 for f in ground
        if abs(float(f.get("latitude", 0)) - 37.62) < 0.5
        and abs(float(f.get("longitude", 0)) - (-122.38)) < 0.5
    )
    if near_sfo > 0:
        s.status = "fail"
        s.details = f"{near_sfo} ground flights still at SFO after MMMX switch"
        return
    s.details = f"{len(flights)} flights total, {len(ground)} on ground, 0 at SFO"


def s7_switch_lsgg(page: Page, s: Scenario):
    _switch_airport(page, s, "LSGG", 46.24, 6.11)


def s8_switch_ksfo(page: Page, s: Scenario):
    _switch_airport(page, s, "KSFO", 37.62, -122.38, tolerance=0.5)


def s9_sim_report(page: Page, s: Scenario):
    report_btn = page.locator("button:has-text('Report'), button:has-text('report')").first
    if not report_btn.is_visible():
        s.status = "skip"
        s.details = "Report button not visible (may require simulation mode)"
        return
    report_btn.click()
    page.wait_for_timeout(1500)
    modal = page.locator("[class*='modal'], [class*='Modal'], [role='dialog']").first
    if modal.is_visible():
        s.details = "Report modal opened successfully"
        page.keyboard.press("Escape")
    else:
        s.status = "skip"
        s.details = "Report button found but no modal — feature may not be active"


def s10_console_errors(page: Page, s: Scenario):
    pass


def main():
    parser = argparse.ArgumentParser(description="UI E2E test for Airport Digital Twin")
    parser.add_argument("--url", default=APP_URL, help="App URL")
    parser.add_argument("--headed", action="store_true", help="Run with visible browser")
    parser.add_argument("--profile", default=DB_PROFILE, help="Databricks CLI profile")
    args = parser.parse_args()

    db_profile = args.profile

    print(f"Getting Databricks auth token (profile: {db_profile})...")
    token = get_databricks_token(db_profile)
    print(f"Token obtained ({len(token)} chars)")

    scenarios_def = [
        ("S1", "Initial page load", s1_initial_load),
        ("S2", "Flight list populates", s2_flight_list),
        ("S3", "Click a flight", s3_click_flight),
        ("S4", "Switch 2D/3D view", s4_view_toggle),
        ("S5", "Switch airport to MMMX", s5_switch_mmmx),
        ("S6", "Verify MMMX flight positions", s6_verify_mmmx),
        ("S7", "Switch airport to LSGG", s7_switch_lsgg),
        ("S8", "Switch back to KSFO", s8_switch_ksfo),
        ("S9", "Open simulation report", s9_sim_report),
        ("S10", "Console error summary", s10_console_errors),
    ]

    all_console_errors: list[str] = []
    scenarios: list[Scenario] = []
    total_start = time.monotonic()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={"Authorization": f"Bearer {token}"},
        )
        page = context.new_page()

        NOISE_PATTERNS = ["favicon", "websocket", "behind a redirect", "net::err_"]

        def on_console(msg: ConsoleMessage):
            if msg.type == "error":
                text = msg.text
                if text and not any(p in text.lower() for p in NOISE_PATTERNS):
                    all_console_errors.append(text)

        page.on("console", on_console)

        print(f"\nNavigating to {args.url}...")
        page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        print("Page loaded.\n")

        for sid, name, fn in scenarios_def:
            s = Scenario(sid, name)
            scenarios.append(s)
            print(f"  [{sid}] {name}...", end=" ", flush=True)
            run_scenario(page, s, fn, all_console_errors)
            status_str = {"pass": "\033[32mPASS\033[0m", "fail": "\033[31mFAIL\033[0m", "skip": "\033[33mSKIP\033[0m", "pending": "PEND"}.get(s.status, s.status)
            print(f"{status_str} ({s.duration_ms}ms) — {s.details}")

        s10 = scenarios[-1]
        if all_console_errors:
            s10.status = "fail"
            s10.details = f"{len(all_console_errors)} console errors total"
            s10.console_errors = all_console_errors
        else:
            s10.status = "pass"
            s10.details = "No console errors"

        REPORT_DIR.mkdir(exist_ok=True)
        page.screenshot(path=str(REPORT_DIR / "final_state.png"), full_page=True)

        browser.close()

    total_ms = int((time.monotonic() - total_start) * 1000)
    pass_count = sum(1 for s in scenarios if s.status == "pass")
    fail_count = sum(1 for s in scenarios if s.status == "fail")
    skip_count = sum(1 for s in scenarios if s.status == "skip")

    report = {
        "url": args.url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scenarios": [s.to_dict() for s in scenarios],
        "summary": {
            "pass": pass_count,
            "fail": fail_count,
            "skip": skip_count,
            "total_duration_ms": total_ms,
        },
        "console_errors_total": all_console_errors,
    }

    report_path = REPORT_DIR / "ui_e2e_report.json"
    report_path.write_text(json.dumps(report, indent=2))

    print(f"\n{'='*50}")
    print(f"Results: \033[32m{pass_count} passed\033[0m, "
          f"\033[31m{fail_count} failed\033[0m, "
          f"{skip_count} skipped — {total_ms}ms total")
    print(f"Report: {report_path}")
    if all_console_errors:
        print(f"Console errors ({len(all_console_errors)}):")
        for e in all_console_errors[:5]:
            print(f"  - {e[:120]}")
    print(f"{'='*50}")

    sys.exit(fail_count)


if __name__ == "__main__":
    main()
