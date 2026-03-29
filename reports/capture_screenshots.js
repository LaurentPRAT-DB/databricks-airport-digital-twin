const { chromium } = require('playwright');
const path = require('path');

const SCREENSHOTS_DIR = path.join(__dirname, 'screenshots');
const BASE_URL = 'http://localhost:3000';

const SIMULATIONS = [
  { file: 'calibrated/simulation_sfo_1000_thunderstorm.json', label: 'SFO_Thunderstorm', airport: 'KSFO', seekPercent: 65 },
  { file: 'calibrated/simulation_jfk_1000_winter_storm.json', label: 'JFK_Winter_Storm', airport: 'KJFK', seekPercent: 35 },
  { file: 'calibrated/simulation_dxb_1000_sandstorm.json', label: 'DXB_Sandstorm', airport: 'OMDB', seekPercent: 20 },
];

/**
 * Wait until no loading spinners or overlays are visible.
 * Uses getBoundingClientRect() instead of offsetParent because offsetParent
 * returns null for elements inside position:fixed containers.
 */
async function waitNoLoading(page, timeout = 120000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const hasLoading = await page.evaluate(() => {
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
    });
    if (!hasLoading) return true;
    await page.waitForTimeout(2000);
  }
  return false;
}

/**
 * Switch airport via __airportControl and wait for readiness.
 */
async function switchAirport(page, icaoCode, timeout = 120000) {
  const current = await page.evaluate(() => {
    return window.__airportControl
      ? window.__airportControl.getCurrentAirport()
      : null;
  });

  if (current === icaoCode) {
    console.log(`  Already on ${icaoCode}`);
    return true;
  }

  console.log(`  Switching airport from ${current} to ${icaoCode}...`);
  await page.evaluate(async (icao) => {
    let tries = 0;
    while (!window.__airportControl && tries < 50) {
      await new Promise(r => setTimeout(r, 200));
      tries++;
    }
    if (window.__airportControl) {
      await window.__airportControl.loadAirport(icao);
    }
  }, icaoCode);

  // Wait for airport to be ready
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const ready = await page.evaluate((expected) => {
      if (!window.__airportControl) return false;
      return window.__airportControl.getCurrentAirport() === expected;
    }, icaoCode);
    if (ready && await waitNoLoading(page, 10000)) return true;
    await page.waitForTimeout(2000);
  }
  return false;
}

async function captureSimulation(page, sim) {
  console.log(`\n=== Capturing ${sim.label} (${sim.airport}) ===`);

  // Switch airport first
  if (!await switchAirport(page, sim.airport)) {
    console.log(`  WARNING: Airport ${sim.airport} not ready after timeout`);
  }

  // Load the simulation
  console.log(`Loading ${sim.file}...`);
  const loaded = await page.evaluate(async (filename) => {
    let tries = 0;
    while (!window.__simControl && tries < 50) {
      await new Promise(r => setTimeout(r, 200));
      tries++;
    }
    if (!window.__simControl) return { error: 'simControl not available' };
    try {
      await window.__simControl.loadFile(filename, 0, 24);
      return window.__simControl.getInfo();
    } catch (e) {
      return { error: e.message };
    }
  }, sim.file);

  console.log('Load result:', JSON.stringify(loaded));
  if (loaded.error) {
    console.log(`Failed to load ${sim.label}: ${loaded.error}`);
    return;
  }

  // Wait for loading to settle
  await page.waitForTimeout(3000);
  await waitNoLoading(page, 30000);
  await page.waitForTimeout(2000);

  // Seek to the target percentage
  const targetFrame = Math.floor(loaded.totalFrames * sim.seekPercent / 100);
  console.log(`Seeking to frame ${targetFrame} / ${loaded.totalFrames} (${sim.seekPercent}%)`);
  await page.evaluate((frame) => { window.__simControl.seekTo(frame); }, targetFrame);
  await page.waitForTimeout(2000);

  // Capture 2D view
  const filename2D = `${sim.label.toLowerCase().replace(/\s+/g, '_')}_2d.png`;
  await page.screenshot({ path: path.join(SCREENSHOTS_DIR, filename2D), fullPage: false });
  console.log(`Saved ${filename2D}`);

  // Switch to 3D view
  const has3D = await page.evaluate(() => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const btn3d = buttons.find(b => b.textContent?.trim() === '3D');
    if (btn3d) { btn3d.click(); return true; }
    return false;
  });

  if (has3D) {
    console.log('  Switched to 3D, waiting for scene to render...');
    await page.waitForTimeout(5000);
    await waitNoLoading(page, 60000);
    await page.waitForTimeout(3000);

    const filename3D = `${sim.label.toLowerCase().replace(/\s+/g, '_')}_3d.png`;
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, filename3D), fullPage: false });
    console.log(`Saved ${filename3D}`);

    // Switch back to 2D
    await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll('button'));
      const btn2d = buttons.find(b => b.textContent?.trim() === '2D');
      if (btn2d) btn2d.click();
    });
    await page.waitForTimeout(2000);
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  const page = await context.newPage();

  console.log('Navigating to app...');
  await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(5000);
  await waitNoLoading(page, 90000);
  await page.waitForTimeout(3000);

  await page.screenshot({ path: path.join(SCREENSHOTS_DIR, 'app_initial.png'), fullPage: false });
  console.log('Saved app_initial.png');

  for (const sim of SIMULATIONS) {
    try {
      await captureSimulation(page, sim);
    } catch (e) {
      console.log(`  ERROR capturing ${sim.label}: ${e.message}`);
    }
  }

  await browser.close();
  console.log('\nDone! Screenshots saved to reports/screenshots/');
})();
