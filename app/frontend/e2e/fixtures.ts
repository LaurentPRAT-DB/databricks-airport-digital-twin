import { test as base, expect } from '@playwright/test';

export const test = base.extend<{ appReady: void }>({
  appReady: async ({ page }, use) => {
    await page.goto('/');
    await page.locator('text=Initializing').waitFor({ state: 'hidden', timeout: 45_000 });
    await page.waitForSelector('[data-testid="flight-list"] button', { timeout: 15_000 }).catch(() =>
      page.waitForSelector('button:has-text("UAL")', { timeout: 10_000 })
    );
    await use();
  },
});

export { expect };
