#!/usr/bin/env node
/**
 * Capture simulation replay video with Playwright + ffmpeg.
 *
 * Usage:
 *   node scripts/capture_video.js \
 *     --sim simulation_output_sfo_100.json \
 *     --output video_output/landing.mp4 \
 *     --start-hour 14.5 --end-hour 15.0 \
 *     --track-flight sim00056 \
 *     --view-mode 2d \
 *     --fps 30 --speed 1
 */

const path = require('path');
const fs = require('fs');
const os = require('os');
const { execSync } = require('child_process');
// Resolve playwright from the frontend node_modules
const { chromium } = require(path.join(__dirname, '..', 'app/frontend/node_modules/playwright'));

// Parse CLI args
function parseArgs() {
  const args = process.argv.slice(2);
  const opts = {
    sim: null,
    output: null,
    appUrl: 'http://localhost:3000',
    fps: 30,
    width: 1920,
    height: 1080,
    speed: 1,
    startHour: 0,
    endHour: 24,
    viewMode: '2d',
    trackFlight: null,
    noCrop: false,
  };

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--sim': opts.sim = args[++i]; break;
      case '--output': case '-o': opts.output = args[++i]; break;
      case '--app-url': opts.appUrl = args[++i]; break;
      case '--fps': opts.fps = parseInt(args[++i]); break;
      case '--resolution': {
        const [w, h] = args[++i].split('x').map(Number);
        opts.width = w; opts.height = h; break;
      }
      case '--speed': opts.speed = parseInt(args[++i]); break;
      case '--start-hour': opts.startHour = parseFloat(args[++i]); break;
      case '--end-hour': opts.endHour = parseFloat(args[++i]); break;
      case '--view-mode': opts.viewMode = args[++i]; break;
      case '--track-flight': opts.trackFlight = args[++i]; break;
      case '--no-crop': opts.noCrop = true; break;
    }
  }

  if (!opts.sim || !opts.output) {
    console.error('Usage: node capture_video.js --sim <file> --output <mp4> [options]');
    console.error('  --start-hour N  --end-hour N  --track-flight <icao24>  --view-mode 2d|3d');
    process.exit(1);
  }
  return opts;
}

async function waitForBackend(page) {
  for (let i = 0; i < 60; i++) {
    const ready = await page.evaluate(async () => {
      try {
        const r = await fetch('/api/ready');
        const d = await r.json();
        return d.ready === true;
      } catch { return false; }
    });
    if (ready) { console.log('Backend ready'); return; }
    await page.waitForTimeout(1000);
  }
  throw new Error('Backend did not become ready within 60s');
}

async function waitForSimLoaded(page) {
  for (let i = 0; i < 120; i++) {
    const info = await page.evaluate(() => window.__simControl?.getInfo());
    if (info && info.isActive && !info.isLoading) return;
    await page.waitForTimeout(500);
  }
  throw new Error('Simulation did not load within 60s');
}

async function getCanvasClip(page, viewMode) {
  const selector = viewMode === '2d' ? '.leaflet-container' : 'canvas';
  const clip = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
  }, selector);
  if (clip && clip.width > 0 && clip.height > 0) {
    // Ensure even dimensions for H.264
    clip.width = clip.width - (clip.width % 2);
    clip.height = clip.height - (clip.height % 2);
    return clip;
  }
  return null;
}

async function main() {
  const opts = parseArgs();
  console.log(`\nCapture settings:`);
  console.log(`  Simulation: ${opts.sim}`);
  console.log(`  Output: ${opts.output}`);
  console.log(`  Time window: hour ${opts.startHour} - ${opts.endHour}`);
  console.log(`  View mode: ${opts.viewMode}`);
  console.log(`  Track flight: ${opts.trackFlight || 'none'}`);
  console.log(`  FPS: ${opts.fps}, Speed: ${opts.speed}x`);
  console.log(`  Resolution: ${opts.width}x${opts.height}`);

  const browser = await chromium.launch({
    headless: true,
    args: [
      '--enable-webgl',
      '--use-gl=angle',
      '--enable-gpu-rasterization',
      '--ignore-gpu-blocklist',
      '--disable-software-rasterizer',
    ],
  });

  const context = await browser.newContext({
    viewport: { width: opts.width, height: opts.height },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  // Navigate and wait
  console.log(`\nNavigating to ${opts.appUrl}...`);
  await page.goto(opts.appUrl, { waitUntil: 'load', timeout: 60000 });
  await waitForBackend(page);

  // Switch to view mode
  console.log(`Switching to ${opts.viewMode.toUpperCase()} view...`);
  await page.evaluate((mode) => window.__viewControl?.setViewMode(mode), opts.viewMode);

  if (opts.viewMode === '3d') {
    await page.waitForSelector('canvas', { timeout: 30000 });
    await page.waitForTimeout(2000);
  } else {
    await page.waitForSelector('.leaflet-container', { timeout: 30000 });
    await page.waitForTimeout(3000);
  }

  // Load simulation file
  console.log(`Loading simulation: ${opts.sim}...`);
  await page.evaluate(
    ([filename, startHour, endHour]) => window.__simControl.loadFile(filename, startHour, endHour),
    [opts.sim, opts.startHour, opts.endHour]
  );
  await waitForSimLoaded(page);

  const info = await page.evaluate(() => window.__simControl.getInfo());
  console.log(`Simulation loaded: ${info.totalFrames} frames`);

  if (info.totalFrames === 0) {
    console.log('No frames in time window. Exiting.');
    await browser.close();
    return;
  }

  // Create temp directory for frames
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sim_video_'));
  console.log(`Temp frames dir: ${tmpDir}`);

  // Get crop region
  const clip = opts.noCrop ? null : await getCanvasClip(page, opts.viewMode);
  if (clip) console.log(`Crop region: ${clip.width}x${clip.height} at (${clip.x}, ${clip.y})`);

  // Capture frames
  const frameIndices = [];
  for (let i = 0; i < info.totalFrames; i += opts.speed) frameIndices.push(i);
  console.log(`\nCapturing ${frameIndices.length} frames...`);

  let flightSelected = false;

  for (let i = 0; i < frameIndices.length; i++) {
    const frameIdx = frameIndices[i];

    // Seek
    await page.evaluate((idx) => window.__simControl.seekTo(idx), frameIdx);

    // Wait for render
    if (opts.viewMode === '2d') {
      await page.evaluate(() => new Promise(r => setTimeout(r, 50)));
    } else {
      await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
    }

    // Select tracked flight and center map on it
    if (opts.trackFlight) {
      await page.evaluate(
        (icao24) => window.__flightControl?.selectFlight(icao24),
        opts.trackFlight
      );

      // Center the map on the tracked flight's position
      if (opts.viewMode === '2d') {
        const pos = await page.evaluate(() => window.__flightControl?.getSelectedFlightPosition());
        if (pos) {
          // Pick zoom based on altitude: zoomed in for ground, zoomed out for airborne
          const zoom = pos.alt > 2000 ? 12 : pos.alt > 500 ? 13 : 14;
          await page.evaluate(
            ([lat, lon, z]) => window.__mapControl?.setView(lat, lon, z),
            [pos.lat, pos.lon, zoom]
          );
          // Wait for map tiles to load after panning
          await page.evaluate(() => new Promise(r => setTimeout(r, 150)));
        }
      }

      if (!flightSelected) {
        // Extra wait for trajectory to render on first selection
        await page.evaluate(() => new Promise(r => setTimeout(r, 500)));
        flightSelected = true;
      }
    }

    // Screenshot
    const framePath = path.join(tmpDir, `frame_${String(i).padStart(5, '0')}.png`);
    const screenshotOpts = { path: framePath };
    if (clip) screenshotOpts.clip = clip;
    await page.screenshot(screenshotOpts);

    if ((i + 1) % 50 === 0 || i === frameIndices.length - 1) {
      console.log(`  Captured ${i + 1}/${frameIndices.length} (sim frame ${frameIdx + 1}/${info.totalFrames})`);
    }
  }

  await browser.close();
  console.log(`\nCaptured ${frameIndices.length} frames`);

  // Encode with ffmpeg
  const outputDir = path.dirname(opts.output);
  if (outputDir) fs.mkdirSync(outputDir, { recursive: true });

  const inputPattern = path.join(tmpDir, 'frame_%05d.png');
  const ffmpegCmd = [
    'ffmpeg', '-y',
    '-framerate', String(opts.fps),
    '-i', inputPattern,
    '-c:v', 'libx264',
    '-preset', 'medium',
    '-crf', '23',
    '-pix_fmt', 'yuv420p',
    '-movflags', '+faststart',
    opts.output,
  ].join(' ');

  console.log(`Encoding video...`);
  try {
    execSync(ffmpegCmd, { stdio: 'pipe' });
  } catch (err) {
    console.error('ffmpeg failed:', err.stderr?.toString());
    process.exit(1);
  }

  // Report size
  const stats = fs.statSync(opts.output);
  const sizeMB = (stats.size / (1024 * 1024)).toFixed(1);
  console.log(`\nVideo saved: ${opts.output} (${sizeMB} MB)`);

  // Cleanup temp frames
  fs.rmSync(tmpDir, { recursive: true, force: true });
  console.log('Temp frames cleaned up.');
}

main().catch(err => {
  console.error('Error:', err);
  process.exit(1);
});
