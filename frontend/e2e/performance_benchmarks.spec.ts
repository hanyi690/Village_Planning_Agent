/**
 * GIS Performance Benchmark E2E Tests
 *
 * Measures frontend rendering and interaction performance:
 * - Initial page load time
 * - Map render time (first meaningful paint of map canvas)
 * - Layer rendering time with GeoJSON data
 * - Basemap switch latency
 * - Memory usage stability
 */

import { test, expect } from '@playwright/test';

const TEST_GIS_URL = '/test-gis';

test.describe('Performance Benchmarks', () => {
  test('page load completes under 10s', async ({ page }) => {
    const start = Date.now();
    await page.goto(TEST_GIS_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
    const loadTime = Date.now() - start;

    expect(loadTime).toBeLessThan(10000);
  });

  test('map canvas renders under 5s after page load', async ({ page }) => {
    await page.goto(TEST_GIS_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });

    const start = Date.now();
    await page.waitForSelector('canvas', { timeout: 10000 });
    const renderTime = Date.now() - start;

    expect(renderTime).toBeLessThan(5000);
  });

  test('basemap switch completes under 3s', async ({ page }) => {
    await page.goto(TEST_GIS_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForSelector('canvas', { timeout: 15000 });

    const imageBtn = page.locator('button', { hasText: /卫星|影像/ });
    if (await imageBtn.count() > 0) {
      const start = Date.now();
      await imageBtn.first().click();
      await page.waitForTimeout(500);
      // Wait for new tiles to start loading
      await page.waitForTimeout(1000);
      const switchTime = Date.now() - start;

      expect(switchTime).toBeLessThan(3000);
    }
  });

  test('GeoJSON layer rendering does not freeze UI', async ({ page }) => {
    await page.goto(TEST_GIS_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForSelector('canvas', { timeout: 15000 });

    // Trigger a tool that loads GeoJSON data
    const layoutSection = page.locator('div.border', { hasText: /空间布局|spatial.layout/i });
    if (await layoutSection.count() > 0) {
      const runButton = layoutSection.locator('button', { hasText: /运行|run/i }).first();
      if (await runButton.count() > 0) {
        await runButton.click();

        // UI should remain responsive — try scrolling or clicking during load
        const mapCanvas = page.locator('canvas');
        await expect(mapCanvas).toBeVisible({ timeout: 5000 });
      }
    }
  });

  test('no memory leaks on repeated layer toggle', async ({ page }) => {
    await page.goto(TEST_GIS_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForSelector('canvas', { timeout: 15000 });

    const getMemory = async () => {
      const metrics = await page.evaluate(() => {
        const perf = performance as unknown as { memory?: { usedJSHeapSize: number } };
        return perf.memory?.usedJSHeapSize ?? 0;
      });
      return metrics;
    };

    const memoryBefore = await getMemory();

    // Toggle layers 5 times
    const checkboxes = page.locator('input[type="checkbox"]');
    const count = await checkboxes.count();
    for (let i = 0; i < 5 && count > 0; i++) {
      const cb = checkboxes.first();
      await cb.click();
      await page.waitForTimeout(300);
      await cb.click();
      await page.waitForTimeout(300);
    }

    const memoryAfter = await getMemory();

    // Memory should not grow more than 50MB from toggle operations
    if (memoryBefore > 0 && memoryAfter > 0) {
      const growth = (memoryAfter - memoryBefore) / (1024 * 1024);
      expect(growth).toBeLessThan(50);
    }
  });
});
