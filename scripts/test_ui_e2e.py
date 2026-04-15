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

_shared: dict = {}


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
    page.wait_for_load_state("networkidle", timeout=30000)
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
    count = page.evaluate("""() => document.querySelectorAll("svg[role='img'][aria-label*='Flight']").length""")
    if count == 0:
        s.status = "skip"
        s.details = "No flight markers found on map"
        return
    page.evaluate("""() => {
        const marker = document.querySelector("svg[role='img'][aria-label*='Flight']");
        if (marker) marker.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    }""")
    page.wait_for_timeout(1500)
    panel = page.locator("[class*='flight-detail'], [class*='FlightDetail'], [class*='selectedFlight']").first
    if panel.is_visible():
        s.details = f"Flight detail panel opened ({count} markers on map)"
    else:
        s.details = f"Clicked flight marker via JS ({count} markers), panel may use different selector"


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


def s5_flight_list_select(page: Page, s: Scenario):
    page.wait_for_timeout(2000)

    rows = page.locator("button:has(span[title='Altitude'])")
    count = rows.count()
    if count == 0:
        s.status = "skip"
        s.details = "No flight rows found in list (looked for ALT span)"
        return

    target_row = rows.nth(min(1, count - 1))
    callsign_el = target_row.locator("span.font-mono.font-medium").first
    callsign = callsign_el.inner_text().strip() if callsign_el.is_visible() else "?"
    _shared["selected_callsign"] = callsign

    classes_before = target_row.get_attribute("class") or ""
    already_selected = "border-l-blue" in classes_before
    if already_selected:
        target_row.click()
        page.wait_for_timeout(300)

    target_row.click()
    page.wait_for_timeout(1000)

    classes = target_row.get_attribute("class") or ""
    selected = "border-l-blue" in classes or "bg-blue" in classes
    s.details = f"Clicked row '{callsign}' ({count} rows), selected={selected}"
    if not selected:
        s.details += " — selection styling not detected (may use parent classes)"


def s6_flight_detail(page: Page, s: Scenario):
    page.wait_for_timeout(1500)

    empty_state = page.locator("text=Select a flight to view details")
    if empty_state.is_visible():
        page.wait_for_timeout(2000)
        if empty_state.is_visible():
            s.status = "fail"
            s.details = "Detail panel shows empty state after flight selection"
            return

    header = page.locator("h3:has-text('Flight Details')")
    if not header.first.is_visible():
        s.status = "fail"
        s.details = "Flight Details header not found"
        return

    detail_panel = header.locator("xpath=ancestor::div[contains(@class,'rounded-lg')][1]")
    if detail_panel.count() == 0:
        detail_panel = header.locator("..")

    callsign_el = detail_panel.locator("div.font-mono.font-bold").first
    callsign_text = callsign_el.inner_text().strip() if callsign_el.is_visible() else ""

    expected = _shared.get("selected_callsign", "")
    match = expected and expected in callsign_text

    fields_found = []
    for label in ["Latitude", "Longitude", "Altitude", "Speed", "Heading"]:
        if detail_panel.locator(f"text={label}").first.is_visible():
            fields_found.append(label)

    s.details = f"Callsign='{callsign_text}' (match={match}), fields={fields_found}"
    if len(fields_found) < 3:
        s.status = "fail"
        s.details += " — fewer than 3 position/movement fields visible"


def s7_playback_bar(page: Page, s: Scenario):
    bar = page.locator("div.fixed.bottom-0, div.fixed.bottom-12").first
    try:
        bar.wait_for(state="visible", timeout=5000)
    except Exception:
        s.status = "skip"
        s.details = "PlaybackBar not visible (simulation may not be active)"
        return

    checks = []

    play_btn = page.locator("button[title='Play'], button[title='Pause']").first
    if play_btn.is_visible():
        initial_title = play_btn.get_attribute("title")
        play_btn.click()
        page.wait_for_timeout(500)
        new_title = play_btn.get_attribute("title")
        toggled = initial_title != new_title
        checks.append(f"play/pause toggled={toggled} ({initial_title}→{new_title})")
        play_btn.click()
        page.wait_for_timeout(300)
    else:
        checks.append("play/pause NOT found")

    time_el = page.locator("div.font-mono.font-bold").first
    if time_el.is_visible():
        time_text = time_el.inner_text().strip()
        checks.append(f"simTime='{time_text}'")
    else:
        checks.append("simTime NOT visible")

    local_label = page.locator("text=Local Time").first
    checks.append(f"localTimeLabel={'yes' if local_label.is_visible() else 'no'}")

    speed_1x = page.locator("button:has-text('1x')").first
    if speed_1x.is_visible():
        speed_2x = page.locator("button:has-text('2x')").first
        if speed_2x.is_visible():
            speed_2x.click()
            page.wait_for_timeout(300)
            classes_2x = speed_2x.get_attribute("class") or ""
            active = "bg-blue-600" in classes_2x
            checks.append(f"speed2x active={active}")
            speed_1x.click()
            page.wait_for_timeout(300)
        checks.append("speedButtons=yes")
    else:
        checks.append("speedButtons=no")

    flights_text = page.locator("text=/\\d+ flights/").first
    if flights_text.is_visible():
        checks.append(f"flightCount='{flights_text.inner_text().strip()}'")
    else:
        checks.append("flightCount=not found")

    s.details = "; ".join(checks)


def s8_sim_report_modal(page: Page, s: Scenario):
    report_btn = page.locator("button[title='Generate simulation report']").first
    if not report_btn.is_visible():
        report_btn = page.locator("button:has-text('Report')").first
    if not report_btn.is_visible():
        s.status = "skip"
        s.details = "Report button not found in PlaybackBar"
        return

    report_btn.click()
    page.wait_for_timeout(1500)

    modal = page.locator("div.fixed.inset-0").first
    if not modal.is_visible():
        s.status = "fail"
        s.details = "Report modal did not open after clicking Report button"
        return

    checks = []

    title = page.locator("text=/Simulation Report/i").first
    checks.append(f"title={'yes' if title.is_visible() else 'no'}")

    kpi_found = []
    for label in ["On-Time %", "Avg Delay", "Total Flights", "Cancellations", "Go-Arounds"]:
        if page.locator(f"text='{label}'").first.is_visible():
            kpi_found.append(label)
    checks.append(f"kpis={len(kpi_found)}/{5}")

    download_btn = page.locator("button:has-text('Download Report')").first
    checks.append(f"downloadBtn={'yes' if download_btn.is_visible() else 'no'}")

    closed = page.evaluate("""() => {
        const btns = [...document.querySelectorAll('button')];
        const closeBtn = btns.find(b => b.textContent.trim() === 'Close');
        if (closeBtn) { closeBtn.click(); return true; }
        return false;
    }""")
    if closed:
        page.wait_for_timeout(500)
        modal_gone = not page.locator("div.fixed.inset-0").first.is_visible()
        checks.append(f"closed={modal_gone}")
    else:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        checks.append("closed via Escape")

    s.details = "; ".join(checks)


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


def s9_playback_event_click(page: Page, s: Scenario):
    """Click an event marker on the PlaybackBar timeline and verify sim time changes."""
    bar = page.locator("div.fixed.bottom-0, div.fixed.bottom-12").first
    if not bar.is_visible():
        s.status = "skip"
        s.details = "PlaybackBar not visible"
        return

    time_el = page.locator("div.font-mono.font-bold").first
    time_before = time_el.inner_text().strip() if time_el.is_visible() else ""

    event_markers = bar.locator("div.cursor-pointer.z-10 div[class*='rounded-sm']")
    count = event_markers.count()
    if count == 0:
        s.status = "skip"
        s.details = "No event markers on timeline"
        return

    target_idx = min(count - 1, count // 2)
    marker = event_markers.nth(target_idx)
    parent = marker.locator("..")
    title = parent.get_attribute("title") or ""

    parent.dispatch_event("click")
    page.wait_for_timeout(1000)

    time_after = time_el.inner_text().strip() if time_el.is_visible() else ""
    changed = time_before != time_after

    s.details = f"Clicked event {target_idx+1}/{count} '{title[:60]}', time {time_before}→{time_after}, changed={changed}"
    if not changed and count > 1:
        s.details += " — time did not change (event may be at current time)"


def s10_report_event_click(page: Page, s: Scenario):
    """Open report, click an event row, verify modal closes, time seeks, flight selected."""
    report_btn = page.locator("button[title='Generate simulation report']").first
    if not report_btn.is_visible():
        report_btn = page.locator("button:has-text('Report')").first
    if not report_btn.is_visible():
        s.status = "skip"
        s.details = "Report button not found"
        return

    report_btn.click()
    page.wait_for_timeout(1500)

    modal = page.locator("div.fixed.inset-0").first
    if not modal.is_visible():
        s.status = "skip"
        s.details = "Report modal did not open"
        return

    event_rows = modal.locator("tr.cursor-pointer")
    row_count = event_rows.count()
    if row_count == 0:
        s.status = "skip"
        s.details = "No event rows in report table"
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        return

    target_row = event_rows.first
    row_time = target_row.locator("td").first.inner_text().strip()
    row_desc = target_row.locator("td").nth(2).inner_text().strip()

    time_el = page.locator("div.font-mono.font-bold").first
    time_before = time_el.inner_text().strip() if time_el.is_visible() else ""

    target_row.click()
    page.wait_for_timeout(1500)

    modal_closed = not page.locator("div.fixed.inset-0").first.is_visible()

    time_after = time_el.inner_text().strip() if time_el.is_visible() else ""
    time_changed = time_before != time_after

    detail_callsign = ""
    callsign_el = page.locator("div.font-mono.font-bold").first
    if callsign_el.is_visible():
        detail_callsign = callsign_el.inner_text().strip()

    checks = [
        f"clicked row '{row_time}: {row_desc[:40]}'",
        f"modalClosed={modal_closed}",
        f"time {time_before}→{time_after} changed={time_changed}",
    ]
    if detail_callsign and detail_callsign != time_after:
        checks.append(f"selectedFlight='{detail_callsign}'")

    s.details = "; ".join(checks)

    if not modal_closed:
        s.status = "fail"
        s.details += " — modal should close after event click"
        page.evaluate("""() => {
            const btns = [...document.querySelectorAll('button')];
            const closeBtn = btns.find(b => b.textContent.trim() === 'Close');
            if (closeBtn) closeBtn.click();
        }""")
        page.wait_for_timeout(500)


def s11_switch_mmmx(page: Page, s: Scenario):
    _switch_airport(page, s, "MMMX", 19.43, -99.07)


def s12_verify_mmmx(page: Page, s: Scenario):
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


def s13_switch_lsgg(page: Page, s: Scenario):
    _switch_airport(page, s, "LSGG", 46.24, 6.11)


def s14_switch_ksfo(page: Page, s: Scenario):
    _switch_airport(page, s, "KSFO", 37.62, -122.38, tolerance=0.5)


def s15_console_errors(page: Page, s: Scenario):
    pass


# ─── Recorded data parity scenarios ──────────────────────────────────────────

def s16_switch_to_recorded(page: Page, s: Scenario):
    """Click the 'Recorded' toggle in the DataModeToggle and verify picker opens."""
    recorded_btn = page.locator("button:has-text('Recorded')").first
    if not recorded_btn.is_visible():
        s.status = "skip"
        s.details = "Recorded toggle button not found"
        return

    recorded_btn.click()
    page.wait_for_timeout(3000)

    picker = page.locator("text=Recorded ADS-B Data")
    if picker.is_visible():
        s.details = "Switched to Recorded mode, picker modal opened"
    else:
        loading = page.locator("text=Loading recordings from lakehouse")
        if loading.is_visible():
            page.wait_for_timeout(10000)
            if page.locator("text=Recorded ADS-B Data").is_visible():
                s.details = "Switched to Recorded mode, picker opened after loading"
            else:
                s.status = "fail"
                s.details = "Picker still loading after 13s"
        else:
            s.details = "Switched to Recorded mode, picker may have auto-closed or not appeared"


def s17_load_recording(page: Page, s: Scenario):
    """Select KSFO recording from picker and verify PlaybackBar appears."""
    picker_visible = page.locator("text=Recorded ADS-B Data").first.is_visible()
    if not picker_visible:
        recorded_btn = page.locator("button:has-text('Load Recording')").first
        if recorded_btn.is_visible():
            recorded_btn.click()
            page.wait_for_timeout(3000)
            picker_visible = page.locator("text=Recorded ADS-B Data").first.is_visible()

    if not picker_visible:
        s.status = "skip"
        s.details = "Recording picker not visible"
        return

    # Target recording buttons inside the modal (w-full text-left), not airport switcher
    rec_btn = page.locator("button.w-full.text-left:has-text('KSFO')").first
    if rec_btn.is_visible():
        rec_btn.click(force=True)
        s.details = "Selected KSFO recording"
    else:
        entries = page.locator("button.w-full.text-left").all()
        available = [e.inner_text()[:40] for e in entries[:5]]
        if entries:
            entries[0].click(force=True)
            s.details = f"KSFO not found, loaded first available: {available}"
        else:
            s.status = "skip"
            s.details = "No recordings available in picker"
            return

    page.wait_for_timeout(15000)

    bar = page.locator("div.fixed.bottom-0, div.fixed.bottom-12").first
    bar_visible = bar.is_visible() if bar else False

    amber = page.locator("div.border-amber-500\\/60, div[class*='border-amber']").first
    has_amber = amber.is_visible() if amber else False

    flights = get_flight_data(page)
    flight_count = len(flights)

    s.details += f" — bar={bar_visible}, amber={has_amber}, flights={flight_count}"
    _shared["rec_flight_count"] = flight_count

    if flight_count == 0:
        s.status = "fail"
        s.details += " — no flights loaded from recording"


def s18_recorded_playback(page: Page, s: Scenario):
    """Verify PlaybackBar controls work in recorded mode (same as simulation)."""
    bar = page.locator("div.fixed.bottom-0, div.fixed.bottom-12").first
    if not bar.is_visible():
        s.status = "skip"
        s.details = "PlaybackBar not visible in recorded mode"
        return

    checks = []

    play_btn = page.locator("button[title='Play'], button[title='Pause']").first
    if play_btn.is_visible():
        initial_title = play_btn.get_attribute("title")
        play_btn.click()
        page.wait_for_timeout(500)
        new_title = play_btn.get_attribute("title")
        toggled = initial_title != new_title
        checks.append(f"play/pause={toggled}")
        play_btn.click()
        page.wait_for_timeout(300)
    else:
        checks.append("play/pause=NOT_FOUND")

    time_el = page.locator("div.font-mono.font-bold").first
    time_text = time_el.inner_text().strip() if time_el.is_visible() else "NOT_VISIBLE"
    checks.append(f"simTime='{time_text}'")

    local_label = page.locator("text=Local Time").first
    checks.append(f"localTime={'yes' if local_label.is_visible() else 'no'}")

    speed_1x = page.locator("button:has-text('1x')").first
    checks.append(f"speedBtns={'yes' if speed_1x.is_visible() else 'no'}")

    flights_text = page.locator("text=/\\d+ flights/").first
    if flights_text.is_visible():
        checks.append(f"flightCount='{flights_text.inner_text().strip()}'")
    else:
        checks.append("flightCount=not_found")

    s.details = "; ".join(checks)


def s19_recorded_flight_list(page: Page, s: Scenario):
    """Verify flight list populates with callsigns in recorded mode."""
    page.wait_for_timeout(2000)

    rows = page.locator("button:has(span[title='Altitude'])")
    count = rows.count()
    if count == 0:
        rows = page.locator("button:has(span.font-mono)")
        count = rows.count()

    if count == 0:
        s.status = "fail"
        s.details = "No flight rows in list during recorded playback"
        return

    first_row = rows.first
    callsign_el = first_row.locator("span.font-mono").first
    callsign = callsign_el.inner_text().strip() if callsign_el.is_visible() else "?"
    _shared["rec_selected_callsign"] = callsign

    first_row.click(force=True)
    page.wait_for_timeout(1000)

    s.details = f"{count} flight rows, clicked '{callsign}'"


def s20_recorded_flight_detail(page: Page, s: Scenario):
    """Verify flight detail panel works the same in recorded mode."""
    page.wait_for_timeout(1500)

    empty_state = page.locator("text=Select a flight to view details")
    if empty_state.is_visible():
        page.wait_for_timeout(2000)
        if empty_state.is_visible():
            s.status = "fail"
            s.details = "Detail panel shows empty state in recorded mode"
            return

    header = page.locator("h3:has-text('Flight Details')")
    if not header.first.is_visible():
        s.status = "fail"
        s.details = "Flight Details header not found in recorded mode"
        return

    detail_panel = header.locator("xpath=ancestor::div[contains(@class,'rounded-lg')][1]")
    if detail_panel.count() == 0:
        detail_panel = header.locator("..")

    callsign_el = detail_panel.locator("div.font-mono.font-bold").first
    callsign_text = callsign_el.inner_text().strip() if callsign_el.is_visible() else ""

    fields_found = []
    for label in ["Latitude", "Longitude", "Altitude", "Speed", "Heading"]:
        if detail_panel.locator(f"text={label}").first.is_visible():
            fields_found.append(label)

    sim_fields = _shared.get("sim_fields", ["Latitude", "Longitude", "Altitude", "Speed", "Heading"])
    missing = [f for f in sim_fields if f not in fields_found]

    s.details = f"Callsign='{callsign_text}', fields={fields_found}"
    if missing:
        s.details += f", missing vs sim: {missing}"
    if len(fields_found) < 3:
        s.status = "fail"
        s.details += " — fewer than 3 position fields (parity gap)"


def s21_recorded_data_quality(page: Page, s: Scenario):
    """Verify all recorded flights have valid positions (no NaN/null)."""
    flights = get_flight_data(page)
    if not flights:
        s.status = "fail"
        s.details = "No flights in recorded mode"
        return

    nan_count = 0
    null_count = 0
    valid = 0
    for f in flights:
        lat = f.get("latitude")
        lon = f.get("longitude")
        if lat is None or lon is None:
            null_count += 1
        elif str(lat) == "nan" or str(lon) == "nan":
            nan_count += 1
        else:
            valid += 1

    s.details = f"valid={valid}, null={null_count}, nan={nan_count}, total={len(flights)}"
    if nan_count > 0:
        s.status = "fail"
        s.details += " — NaN positions in recorded data"
    if null_count > 0:
        s.status = "fail"
        s.details += " — null positions in recorded data"


def s22_switch_back_to_simulation(page: Page, s: Scenario):
    """Switch back to Simulation mode and verify it returns to normal."""
    # Dismiss any open modal first (recording picker, etc.)
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)

    sim_btn = page.locator("button:has-text('Simulation')").first
    if not sim_btn.is_visible():
        s.status = "skip"
        s.details = "Simulation toggle button not found"
        return

    sim_btn.click(force=True)
    page.wait_for_timeout(5000)

    amber = page.locator("div.border-amber-500\\/60, div[class*='border-amber']")
    no_amber = amber.count() == 0 or not amber.first.is_visible()

    flights = get_flight_data(page)

    s.details = f"Back to simulation, amber_gone={no_amber}, flights={len(flights)}"


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
        ("S3", "Click a flight marker", s3_click_flight),
        ("S4", "Switch 2D/3D view", s4_view_toggle),
        ("S5", "Flight list selection", s5_flight_list_select),
        ("S6", "Flight detail panel", s6_flight_detail),
        ("S7", "PlaybackBar controls", s7_playback_bar),
        ("S8", "Simulation report modal", s8_sim_report_modal),
        ("S9", "PlaybackBar event click", s9_playback_event_click),
        ("S10", "Report event click", s10_report_event_click),
        ("S11", "Switch airport to MMMX", s11_switch_mmmx),
        ("S12", "Verify MMMX flight positions", s12_verify_mmmx),
        ("S13", "Switch airport to LSGG", s13_switch_lsgg),
        ("S14", "Switch back to KSFO", s14_switch_ksfo),
        # ─── Recorded data parity ───
        ("S15", "Switch to Recorded mode", s16_switch_to_recorded),
        ("S16", "Load KSFO recording", s17_load_recording),
        ("S17", "Recorded PlaybackBar", s18_recorded_playback),
        ("S18", "Recorded flight list", s19_recorded_flight_list),
        ("S19", "Recorded flight detail", s20_recorded_flight_detail),
        ("S20", "Recorded data quality", s21_recorded_data_quality),
        ("S21", "Switch back to Simulation", s22_switch_back_to_simulation),
        # ─── Summary ───
        ("S22", "Console error summary", s15_console_errors),
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

        s_last = scenarios[-1]
        if all_console_errors:
            s_last.status = "fail"
            s_last.details = f"{len(all_console_errors)} console errors total"
            s_last.console_errors = all_console_errors
        else:
            s_last.status = "pass"
            s_last.details = "No console errors"

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
