"""Capture screenshots of simulation replays for what-if scenario reports."""
import os
import time
from playwright.sync_api import sync_playwright

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
BASE_URL = "http://localhost:3000"

# Start with SFO (default airport, no switch needed), then JFK and DXB
SIMULATIONS = [
    {
        "file": "calibrated/simulation_sfo_1000_thunderstorm.json",
        "label": "sfo_thunderstorm",
        "airport": "KSFO",
        "seek_pcts": [40, 65, 80],  # pre-storm, peak storm, fog
        "start_hour": 8,
        "end_hour": 22,
    },
    {
        "file": "calibrated/simulation_jfk_1000_winter_storm.json",
        "label": "jfk_winter_storm",
        "airport": "KJFK",
        "seek_pcts": [20, 40, 70],  # pre-storm, severe snow, recovery
        "start_hour": 4,
        "end_hour": 18,
    },
    {
        "file": "calibrated/simulation_dxb_1000_sandstorm.json",
        "label": "dxb_sandstorm",
        "airport": "OMDB",
        "seek_pcts": [15, 35, 60],  # dust onset, peak sandstorm, recovery
        "start_hour": 0,
        "end_hour": 14,
    },
]


def wait_no_loading(page, timeout=120):
    """Wait until no loading spinners or overlays are visible.

    Uses getBoundingClientRect() instead of offsetParent because offsetParent
    returns null for elements inside position:fixed containers (like the
    full-screen airport switch overlay).
    """
    start = time.time()
    while time.time() - start < timeout:
        has_loading = page.evaluate("""() => {
            // Check for visible animate-spin elements
            const spinners = document.querySelectorAll('.animate-spin');
            for (const s of spinners) {
                const rect = s.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) return true;
            }
            // Check for full-screen loading overlays (position:fixed inset-0)
            const overlays = document.querySelectorAll('[class*="fixed"][class*="inset-0"]');
            for (const o of overlays) {
                if (o.getBoundingClientRect().width > 0) return true;
            }
            return false;
        }""")
        if not has_loading:
            return True
        time.sleep(2)
    return False


def wait_airport_ready(page, expected_icao, timeout=120):
    """Wait until the expected airport is loaded and all overlays are gone."""
    print(f"  Waiting for airport {expected_icao} to be ready...")
    start = time.time()
    while time.time() - start < timeout:
        ready = page.evaluate("""(expected) => {
            if (!window.__airportControl) return false;
            const current = window.__airportControl.getCurrentAirport();
            return current === expected;
        }""", expected_icao)
        if ready:
            # Airport matched — now wait for overlays to clear
            if wait_no_loading(page, timeout=10):
                return True
        time.sleep(2)
    return False


def switch_airport(page, icao_code, timeout=120):
    """Explicitly switch airport via __airportControl and wait for readiness."""
    current = page.evaluate("""() => {
        return window.__airportControl
            ? window.__airportControl.getCurrentAirport()
            : null;
    }""")
    if current == icao_code:
        print(f"  Already on {icao_code}")
        return True

    print(f"  Switching airport from {current} to {icao_code}...")
    page.evaluate("""async (icao) => {
        let tries = 0;
        while (!window.__airportControl && tries < 50) {
            await new Promise(r => setTimeout(r, 200));
            tries++;
        }
        if (window.__airportControl) {
            await window.__airportControl.loadAirport(icao);
        }
    }""", icao_code)

    return wait_airport_ready(page, icao_code, timeout)


def capture_simulation(page, sim, first_run=False):
    label = sim["label"]
    airport = sim["airport"]
    print(f"\n=== Capturing {label} ({airport}) ===")

    # Switch airport first (explicit, reliable)
    if not switch_airport(page, airport):
        print(f"  WARNING: Airport {airport} not ready after timeout, continuing anyway")

    # Load simulation
    print(f"  Loading file (hours {sim['start_hour']}-{sim['end_hour']})...")
    result = page.evaluate(
        """async ([filename, startHour, endHour]) => {
            let tries = 0;
            while (!window.__simControl && tries < 100) {
                await new Promise(r => setTimeout(r, 200));
                tries++;
            }
            if (!window.__simControl) return {error: 'simControl not available'};
            try {
                await window.__simControl.loadFile(filename, startHour, endHour);
                await new Promise(r => setTimeout(r, 500));
                return window.__simControl.getInfo();
            } catch(e) {
                return {error: e.message};
            }
        }""",
        [sim["file"], sim["start_hour"], sim["end_hour"]],
    )
    print(f"  Load result: {result}")
    if isinstance(result, dict) and result.get("error"):
        print(f"  FAILED: {result['error']}")
        return

    total = result.get("totalFrames", 0)

    # Wait for any remaining loading to settle
    time.sleep(3)
    wait_no_loading(page, timeout=30)
    time.sleep(2)

    # Take screenshots at multiple seek positions
    for i, pct in enumerate(sim["seek_pcts"]):
        target = int(total * pct / 100)
        print(f"  Seeking to frame {target}/{total} ({pct}%)")
        page.evaluate("(frame) => window.__simControl.seekTo(frame)", target)
        time.sleep(2)

        suffix = ["pre", "peak", "post"][i] if i < 3 else str(i)
        path_2d = os.path.join(SCREENSHOTS_DIR, f"{label}_{suffix}_2d.png")
        page.screenshot(path=path_2d)
        print(f"  Saved {label}_{suffix}_2d.png")

    # 3D screenshot at peak (middle seek position)
    peak_target = int(total * sim["seek_pcts"][1] / 100)
    page.evaluate("(frame) => window.__simControl.seekTo(frame)", peak_target)
    time.sleep(1)

    switched = page.evaluate("""() => {
        const buttons = Array.from(document.querySelectorAll('button'));
        const btn = buttons.find(b => b.textContent && b.textContent.trim() === '3D');
        if (btn) { btn.click(); return true; }
        return false;
    }""")

    if switched:
        print("  Switched to 3D, waiting for scene to render...")
        time.sleep(5)
        wait_no_loading(page, timeout=60)
        time.sleep(3)

        path_3d = os.path.join(SCREENSHOTS_DIR, f"{label}_peak_3d.png")
        page.screenshot(path=path_3d)
        print(f"  Saved {label}_peak_3d.png")

        # Switch back to 2D
        page.evaluate("""() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            const btn = buttons.find(b => b.textContent && b.textContent.trim() === '2D');
            if (btn) btn.click();
        }""")
        time.sleep(3)


def main():
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        print("Navigating to app...")
        page.goto(BASE_URL, wait_until="load", timeout=60000)

        # Wait for initial SFO airport to load
        print("Waiting for initial airport load...")
        time.sleep(10)
        wait_no_loading(page, timeout=90)
        time.sleep(5)

        page.screenshot(path=os.path.join(SCREENSHOTS_DIR, "app_initial.png"))
        print("Saved app_initial.png")

        # First sim is SFO (no airport switch needed)
        for i, sim in enumerate(SIMULATIONS):
            try:
                capture_simulation(page, sim, first_run=(i == 0))
            except Exception as e:
                print(f"  ERROR capturing {sim['label']}: {e}")

        browser.close()
        print("\nDone!")


if __name__ == "__main__":
    main()
