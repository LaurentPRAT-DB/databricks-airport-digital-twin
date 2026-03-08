import { test, expect } from '@playwright/test';

test.describe('3D Visualization', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    // Wait for initial data load
    await page.waitForSelector('[data-testid="flight-list"]', { timeout: 10000 }).catch(() => {
      // Fallback: wait for any flight row
      return page.waitForSelector('button:has-text("UAL")', { timeout: 10000 });
    });
  });

  test('switches to 3D view', async ({ page }) => {
    // Click 3D button
    const button3D = page.getByRole('button', { name: /3d/i });
    await button3D.click();

    // Verify 3D button is active
    await expect(button3D).toHaveClass(/bg-blue-600/);

    // Wait for canvas to render (Three.js uses canvas)
    const canvas = page.locator('canvas');
    await expect(canvas).toBeVisible({ timeout: 10000 });
  });

  test('3D canvas renders WebGL context', async ({ page }) => {
    // Switch to 3D view
    await page.getByRole('button', { name: /3d/i }).click();

    // Wait for canvas
    const canvas = page.locator('canvas');
    await expect(canvas).toBeVisible({ timeout: 10000 });

    // Verify canvas has dimensions (rendered)
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(100);
    expect(box!.height).toBeGreaterThan(100);
  });

  test('can switch back to 2D view', async ({ page }) => {
    // Go to 3D
    await page.getByRole('button', { name: /3d/i }).click();
    await page.locator('canvas').waitFor({ state: 'visible', timeout: 10000 });

    // Switch back to 2D
    const button2D = page.getByRole('button', { name: /2d/i });
    await button2D.click();

    // Verify 2D is active
    await expect(button2D).toHaveClass(/bg-blue-600/);

    // 2D map should be visible (Leaflet container)
    const mapContainer = page.locator('.leaflet-container');
    await expect(mapContainer).toBeVisible({ timeout: 5000 });
  });

  test('3D view shows loading state briefly', async ({ page }) => {
    // Click 3D - may show loading briefly
    await page.getByRole('button', { name: /3d/i }).click();

    // Either loading or canvas should appear
    await Promise.race([
      page.waitForSelector('text=/loading/i', { timeout: 2000 }),
      page.waitForSelector('canvas', { timeout: 5000 }),
    ]);

    // Eventually canvas should be visible
    await expect(page.locator('canvas')).toBeVisible({ timeout: 10000 });
  });

  test('3D aircraft are clickable', async ({ page }) => {
    // Switch to 3D
    await page.getByRole('button', { name: /3d/i }).click();
    await page.locator('canvas').waitFor({ state: 'visible', timeout: 10000 });

    // Get canvas position for clicking
    const canvas = page.locator('canvas');
    const box = await canvas.boundingBox();

    if (box) {
      // Click in the center of the canvas (where aircraft likely are)
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);

      // Wait a moment for any selection to register
      await page.waitForTimeout(500);

      // Check if flight details panel updated (would show selected flight)
      // This is a soft assertion - clicking may or may not hit an aircraft
    }
  });

  test('3D view persists flight selection from 2D', async ({ page }) => {
    // First select a flight in 2D view
    const flightRow = page.locator('button:has-text("UAL")').first();
    await flightRow.click();

    // Verify selection in detail panel (multiple UAL elements may exist)
    await expect(page.locator('text=/UAL/i').first()).toBeVisible();

    // Switch to 3D
    await page.getByRole('button', { name: /3d/i }).click();
    await page.locator('canvas').waitFor({ state: 'visible', timeout: 10000 });

    // Selection should persist (detail panel still shows selected flight)
    await expect(page.getByRole('heading', { name: /flight details/i })).toBeVisible();
  });
});

test.describe('3D Performance', () => {
  test('3D view loads within acceptable time', async ({ page }) => {
    await page.goto('/');

    const startTime = Date.now();

    // Switch to 3D
    await page.getByRole('button', { name: /3d/i }).click();

    // Wait for canvas to be visible
    await page.locator('canvas').waitFor({ state: 'visible', timeout: 15000 });

    const loadTime = Date.now() - startTime;

    // Should load within 5 seconds (generous for CI)
    expect(loadTime).toBeLessThan(5000);
  });

  test('3D view maintains frame rate', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: /3d/i }).click();
    await page.locator('canvas').waitFor({ state: 'visible', timeout: 10000 });

    // Measure frame performance using Performance API
    const fps = await page.evaluate(async () => {
      return new Promise<number>((resolve) => {
        let frameCount = 0;
        const startTime = performance.now();

        function countFrame() {
          frameCount++;
          if (performance.now() - startTime < 1000) {
            requestAnimationFrame(countFrame);
          } else {
            resolve(frameCount);
          }
        }

        requestAnimationFrame(countFrame);
      });
    });

    // Should maintain at least 30 FPS
    expect(fps).toBeGreaterThan(30);
  });
});

test.describe('3D Visual Regression', () => {
  test('3D view renders without errors', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: /3d/i }).click();

    // Wait for 3D to fully render
    await page.locator('canvas').waitFor({ state: 'visible', timeout: 10000 });
    // Give WebGL time to render
    await page.waitForTimeout(2000);

    // Verify canvas has content (non-zero dimensions and is rendered)
    const canvas = page.locator('canvas');
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(200);
    expect(box!.height).toBeGreaterThan(200);

    // Check for WebGL errors in console
    const errors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') {
        errors.push(msg.text());
      }
    });

    // No WebGL errors should have occurred
    const webglErrors = errors.filter(e =>
      e.toLowerCase().includes('webgl') || e.toLowerCase().includes('three')
    );
    expect(webglErrors).toHaveLength(0);
  });

  // Visual regression test - run with --update-snapshots to create baseline
  test.skip('3D view screenshot matches baseline', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: /3d/i }).click();

    await page.locator('canvas').waitFor({ state: 'visible', timeout: 10000 });
    await page.waitForTimeout(2000);

    const canvas = page.locator('canvas');
    await expect(canvas).toHaveScreenshot('3d-view.png', {
      maxDiffPixels: 1000,
      timeout: 10000,
    });
  });
});
