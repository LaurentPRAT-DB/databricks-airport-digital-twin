#!/usr/bin/env node
/**
 * Capture screenshots of KBP Easter Egg (fighter jets + commercial aircraft)
 * Uses Puppeteer from mermaid-cli global install
 */

const puppeteer = await import('/opt/homebrew/lib/node_modules/@mermaid-js/mermaid-cli/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js');
const { mkdir } = await import('fs/promises');
const path = await import('path');

const OUTPUT_DIR = 'data/kbp_easter_egg';
const BASE_URL = 'http://localhost:3000';

function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

async function main() {
  await mkdir(path.join(OUTPUT_DIR, 'frames'), { recursive: true });

  console.log('Launching headless browser...');
  const browser = await puppeteer.default.launch({
    headless: 'new',
    defaultViewport: { width: 1920, height: 1080 },
    args: ['--no-sandbox', '--disable-gpu', '--disable-software-rasterizer'],
  });

  const page = await browser.newPage();

  console.log('Loading app...');
  await page.goto(BASE_URL, { waitUntil: 'networkidle0', timeout: 30000 });
  await delay(3000);

  // Screenshot 1: 2D overview
  console.log('1. 2D overview...');
  await page.screenshot({ path: path.join(OUTPUT_DIR, 'kbp_2d_overview.png') });

  // Find and click 3D toggle
  console.log('2. Switching to 3D...');
  try {
    // Try various selectors for the 3D button
    const clicked = await page.evaluate(() => {
      const buttons = document.querySelectorAll('button');
      for (const btn of buttons) {
        if (btn.textContent.includes('3D') || btn.getAttribute('aria-label')?.includes('3D')) {
          btn.click();
          return true;
        }
      }
      // Try tab-like elements
      const tabs = document.querySelectorAll('[role="tab"], [data-view="3d"]');
      for (const tab of tabs) {
        if (tab.textContent.includes('3D')) {
          tab.click();
          return true;
        }
      }
      return false;
    });

    if (clicked) {
      console.log('  Clicked 3D button, waiting for scene...');
      await delay(8000);
    } else {
      console.log('  Could not find 3D button');
    }
  } catch (e) {
    console.log('  Error switching to 3D:', e.message);
  }

  // Screenshot 2: 3D view
  console.log('3. 3D overview...');
  await page.screenshot({ path: path.join(OUTPUT_DIR, 'kbp_3d_overview.png') });

  // Capture frame sequence (2fps for 15 seconds = 30 frames)
  console.log('4. Capturing frame sequence (30 frames)...');
  for (let i = 0; i < 30; i++) {
    const num = String(i).padStart(4, '0');
    await page.screenshot({ path: path.join(OUTPUT_DIR, `frames/frame_${num}.png`) });
    if (i % 5 === 0) console.log(`   Frame ${i}/30`);
    await delay(500);
  }

  // Screenshot: page HTML for debugging
  const html = await page.content();
  const hasCanvas = html.includes('<canvas');
  const hasThree = html.includes('three') || html.includes('Three');
  console.log(`\nPage analysis: canvas=${hasCanvas}, three.js references=${hasThree}`);

  // Get flight info from the page
  const flightInfo = await page.evaluate(() => {
    const els = document.querySelectorAll('[class*="flight"], [class*="aircraft"], [data-callsign]');
    return Array.from(els).slice(0, 10).map(el => ({
      text: el.textContent?.substring(0, 100),
      className: el.className
    }));
  });
  console.log('Flight UI elements found:', flightInfo.length);

  console.log('\n5. Final screenshot...');
  await page.screenshot({ path: path.join(OUTPUT_DIR, 'kbp_3d_final.png') });

  await browser.close();

  console.log(`\nDone! Screenshots saved to ${OUTPUT_DIR}/`);
  console.log(`\nTo create video:`);
  console.log(`  ffmpeg -framerate 2 -i ${OUTPUT_DIR}/frames/frame_%04d.png -c:v libx264 -pix_fmt yuv420p -vf "scale=1920:1080" ${OUTPUT_DIR}/kbp_easter_egg.mp4`);
}

main().catch(e => { console.error(e); process.exit(1); });
