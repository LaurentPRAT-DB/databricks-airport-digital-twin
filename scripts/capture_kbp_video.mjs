#!/usr/bin/env node
/**
 * Capture 3D view screenshots and video of KBP Easter Egg (fighter jets)
 *
 * Usage: node scripts/capture_kbp_video.mjs
 * Requires: backend on :8000, frontend on :3000, UKBB activated
 */

import puppeteer from '/opt/homebrew/lib/node_modules/@mermaid-js/mermaid-cli/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js';
import { mkdir } from 'fs/promises';
import path from 'path';

const OUTPUT_DIR = 'data/kbp_easter_egg';
const BASE_URL = 'http://localhost:3000';
const SCREENSHOT_INTERVAL_MS = 500;  // capture every 500ms
const VIDEO_DURATION_S = 30;         // 30 seconds of capture

async function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function main() {
  await mkdir(OUTPUT_DIR, { recursive: true });

  console.log('Launching browser...');
  const browser = await puppeteer.launch({
    headless: false,        // Show browser for debugging
    defaultViewport: null,
    args: ['--window-size=1920,1080', '--no-sandbox'],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080 });

  console.log('Loading airport digital twin...');
  await page.goto(BASE_URL, { waitUntil: 'networkidle0', timeout: 30000 });
  await delay(3000);

  // Take initial 2D view screenshot
  console.log('Capturing 2D overview...');
  await page.screenshot({ path: path.join(OUTPUT_DIR, 'kbp_2d_overview.png'), fullPage: false });

  // Switch to 3D view
  console.log('Switching to 3D view...');
  // Click the 3D toggle button
  const toggle3D = await page.$('[data-testid="view-toggle-3d"], button:has-text("3D"), [aria-label*="3D"]');
  if (toggle3D) {
    await toggle3D.click();
    await delay(5000);  // Wait for 3D scene to load
  } else {
    // Try finding button by text content
    const buttons = await page.$$('button');
    for (const btn of buttons) {
      const text = await page.evaluate(el => el.textContent, btn);
      if (text && text.includes('3D')) {
        await btn.click();
        console.log('  Clicked 3D button');
        await delay(5000);
        break;
      }
    }
  }

  // Take 3D view screenshots
  console.log('Capturing 3D view...');
  await page.screenshot({ path: path.join(OUTPUT_DIR, 'kbp_3d_overview.png'), fullPage: false });

  // Capture frame sequence for video
  console.log(`Capturing ${VIDEO_DURATION_S}s of frames...`);
  const totalFrames = Math.floor(VIDEO_DURATION_S * 1000 / SCREENSHOT_INTERVAL_MS);

  for (let i = 0; i < totalFrames; i++) {
    const frameNum = String(i).padStart(4, '0');
    await page.screenshot({
      path: path.join(OUTPUT_DIR, `frames/frame_${frameNum}.png`),
      fullPage: false
    });
    if (i % 10 === 0) {
      console.log(`  Frame ${i}/${totalFrames}`);
    }
    await delay(SCREENSHOT_INTERVAL_MS);
  }

  // Try to find and click on a fighter jet
  console.log('Looking for fighter jet aircraft...');
  // Take a few more targeted screenshots
  await page.screenshot({ path: path.join(OUTPUT_DIR, 'kbp_3d_final.png'), fullPage: false });

  console.log('Capture complete!');
  await browser.close();

  console.log(`\nOutput in ${OUTPUT_DIR}/`);
  console.log(`To create video from frames:\n  ffmpeg -framerate 2 -i ${OUTPUT_DIR}/frames/frame_%04d.png -c:v libx264 -pix_fmt yuv420p ${OUTPUT_DIR}/kbp_easter_egg.mp4`);
}

main().catch(console.error);
