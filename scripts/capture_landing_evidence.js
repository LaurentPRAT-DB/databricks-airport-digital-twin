#!/usr/bin/env node
/**
 * Capture 2D screenshots at key approach/landing moments using simulation replay.
 * Loads the simulation file, seeks to frames where flights are approaching/landing,
 * and takes screenshots with the flight selected to show trajectory lines.
 *
 * Usage:
 *   node scripts/capture_landing_evidence.js --sim simulation_output.json
 */
const path = require('path');
const fs = require('fs');
const { chromium } = require(path.join(__dirname, '..', 'app/frontend/node_modules/playwright'));

const APP_URL = 'http://localhost:3000';
const OUT_DIR = path.resolve(__dirname, '..', 'screenshots');

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function waitForBackend(page) {
  for (let i = 0; i < 60; i++) {
    const ready = await page.evaluate(async () => {
      try { const r = await fetch('/api/ready'); const d = await r.json(); return d.ready === true; }
      catch { return false; }
    });
    if (ready) return;
    await sleep(1000);
  }
  throw new Error('Backend not ready');
}

async function waitForSimLoaded(page) {
  for (let i = 0; i < 120; i++) {
    const info = await page.evaluate(() => window.__simControl?.getInfo());
    if (info && info.isActive && !info.isLoading) return;
    await sleep(500);
  }
  throw new Error('Simulation did not load');
}

async function main() {
  // Parse --sim argument
  const args = process.argv.slice(2);
  let simFile = 'simulation_output.json';
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--sim') simFile = args[++i];
  }

  fs.mkdirSync(OUT_DIR, { recursive: true });

  // Load simulation data to find key moments
  const simData = JSON.parse(fs.readFileSync(simFile, 'utf8'));
  const transitions = simData.phase_transitions;
  const snapshots = simData.position_snapshots;
  const arrivals = new Set(simData.schedule.filter(s => s.flight_type === 'arrival').map(s => s.flight_number));

  // Find key approach→landing and landing→taxi transitions
  const approachToLanding = transitions.filter(t => t.from_phase === 'approaching' && t.to_phase === 'landing');
  const landingToTaxi = transitions.filter(t => t.from_phase === 'landing' && t.to_phase === 'taxi_to_gate');

  console.log(`Simulation: ${simFile}`);
  console.log(`Arrivals: ${arrivals.size}, approach→landing: ${approachToLanding.length}, landing→taxi: ${landingToTaxi.length}`);

  // Pick a few representative flights to track
  // Choose the first 3 flights that have complete approach→landing→taxi sequences
  const flightsToTrack = [];
  for (const a2l of approachToLanding) {
    const l2t = landingToTaxi.find(t => t.callsign === a2l.callsign);
    if (l2t && flightsToTrack.length < 3) {
      flightsToTrack.push({
        callsign: a2l.callsign,
        icao24: a2l.icao24,
        approachTime: a2l.time,
        approachAlt: a2l.altitude,
        landingTime: l2t.time,
      });
    }
  }

  console.log(`\nFlights to capture:`);
  flightsToTrack.forEach(f => console.log(`  ${f.callsign} (${f.icao24}): approach→landing at ${f.approachAlt}ft`));

  // Find snapshot times for each flight during approach (mid-approach and near-landing)
  const capturePoints = [];
  for (const flight of flightsToTrack) {
    const flightSnaps = snapshots.filter(s => s.icao24 === flight.icao24);
    const approachSnaps = flightSnaps.filter(s => s.phase === 'approaching');
    const landingSnaps = flightSnaps.filter(s => s.phase === 'landing');
    const taxiSnaps = flightSnaps.filter(s => s.phase === 'taxi_to_gate');

    if (approachSnaps.length > 2) {
      // Mid-approach: aircraft descending with altitude
      const midIdx = Math.floor(approachSnaps.length / 2);
      capturePoints.push({
        label: `approach_mid_${flight.callsign}`,
        description: `${flight.callsign} mid-approach at ${Math.round(approachSnaps[midIdx].altitude)}ft`,
        time: approachSnaps[midIdx].time,
        icao24: flight.icao24,
      });
      // Late approach: just before transition
      const lateIdx = approachSnaps.length - 1;
      capturePoints.push({
        label: `approach_late_${flight.callsign}`,
        description: `${flight.callsign} late approach at ${Math.round(approachSnaps[lateIdx].altitude)}ft`,
        time: approachSnaps[lateIdx].time,
        icao24: flight.icao24,
      });
    }

    if (landingSnaps.length > 0) {
      capturePoints.push({
        label: `landing_${flight.callsign}`,
        description: `${flight.callsign} landing rollout at ${Math.round(landingSnaps[0].altitude)}ft, ${Math.round(landingSnaps[0].velocity)}kts`,
        time: landingSnaps[0].time,
        icao24: flight.icao24,
      });
    }

    if (taxiSnaps.length > 0) {
      capturePoints.push({
        label: `taxi_start_${flight.callsign}`,
        description: `${flight.callsign} taxi start after landing`,
        time: taxiSnaps[0].time,
        icao24: flight.icao24,
      });
    }
  }

  console.log(`\nCapture points: ${capturePoints.length}`);
  capturePoints.forEach(p => console.log(`  [${p.label}] ${p.description} @ ${p.time}`));

  // Launch browser
  const browser = await chromium.launch({
    headless: true,
    args: ['--enable-webgl', '--use-gl=angle', '--enable-gpu-rasterization', '--ignore-gpu-blocklist'],
  });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

  console.log('\nNavigating to app...');
  await page.goto(APP_URL, { waitUntil: 'load', timeout: 60000 });
  await waitForBackend(page);
  await page.waitForSelector('.leaflet-container', { timeout: 30000 });
  await sleep(3000);

  // Load simulation replay
  console.log(`Loading simulation: ${simFile}...`);
  await page.evaluate(
    ([filename]) => window.__simControl.loadFile(filename, 0, 24),
    [simFile]
  );
  await waitForSimLoaded(page);

  const info = await page.evaluate(() => window.__simControl.getInfo());
  console.log(`Simulation loaded: ${info.totalFrames} frames`);

  // Get all snapshot times to map capture-point times to frame indices
  const allTimes = snapshots.map(s => s.time);
  const uniqueTimes = [...new Set(allTimes)].sort();

  // Capture each point
  let shotIdx = 1;
  for (const point of capturePoints) {
    console.log(`\n[${shotIdx}/${capturePoints.length}] ${point.description}`);

    // Find the frame index closest to this time
    const timeIdx = uniqueTimes.findIndex(t => t >= point.time);
    const frameIdx = Math.max(0, Math.min(timeIdx, info.totalFrames - 1));

    // Seek to frame
    await page.evaluate((idx) => window.__simControl.seekTo(idx), frameIdx);
    await sleep(200);

    // Select the flight
    await page.evaluate((icao24) => window.__flightControl?.selectFlight(icao24), point.icao24);
    await sleep(500);

    // Center map on flight
    const pos = await page.evaluate(() => window.__flightControl?.getSelectedFlightPosition());
    if (pos) {
      const zoom = pos.alt > 2000 ? 12 : pos.alt > 500 ? 13 : 14;
      await page.evaluate(
        ([lat, lon, z]) => window.__mapControl?.setView(lat, lon, z),
        [pos.lat, pos.lon, zoom]
      );
      await sleep(500);
    }

    // Take screenshot
    const filename = `landing_${String(shotIdx).padStart(2, '0')}_${point.label}.png`;
    await page.screenshot({ path: path.join(OUT_DIR, filename) });
    console.log(`  Saved: ${filename}`);
    shotIdx++;
  }

  // Also take an overview shot with a flight fully visible (approach trajectory)
  console.log('\nCapturing overview with full approach trajectory...');
  const firstFlight = flightsToTrack[0];
  if (firstFlight) {
    // Seek to just after landing
    const taxiTrans = landingToTaxi.find(t => t.callsign === firstFlight.callsign);
    if (taxiTrans) {
      const timeIdx = uniqueTimes.findIndex(t => t >= taxiTrans.time);
      const frameIdx = Math.min(timeIdx + 5, info.totalFrames - 1); // A few frames after taxi start
      await page.evaluate((idx) => window.__simControl.seekTo(idx), frameIdx);
      await sleep(200);
      await page.evaluate((icao24) => window.__flightControl?.selectFlight(icao24), firstFlight.icao24);
      await sleep(1000);

      // Zoom out to see full approach + landing + taxi trajectory
      await page.evaluate(([lat, lon]) => window.__mapControl?.setView(lat, lon, 12), [37.615, -122.30]);
      await sleep(1000);

      await page.screenshot({ path: path.join(OUT_DIR, 'landing_overview_trajectory.png') });
      console.log('  Saved: landing_overview_trajectory.png');
    }
  }

  await browser.close();

  // Print summary
  console.log('\n' + '='.repeat(70));
  console.log('SCREENSHOTS CAPTURED');
  console.log('='.repeat(70));
  const shots = fs.readdirSync(OUT_DIR).filter(f => f.startsWith('landing_'));
  shots.forEach(f => console.log(`  ${OUT_DIR}/${f}`));
  console.log(`\nTotal: ${shots.length} screenshots in ${OUT_DIR}/`);
}

main().catch(err => {
  console.error('Error:', err.message);
  process.exit(1);
});
