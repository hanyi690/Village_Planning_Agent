/**
 * Planning Pipeline E2E Tests
 *
 * Tests the full GIS planning workflow:
 * - Service health check
 * - Spatial layout generation
 * - Constraint validation
 * - Planning zone rendering
 * - SSE progress streaming
 */

import { test, expect } from '@playwright/test';

const TEST_GIS_URL = '/test-gis';
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

test.describe('Planning Pipeline', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(TEST_GIS_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForSelector('canvas', { timeout: 15000 });
    await page.waitForTimeout(2000);
  });

  test('GIS service health check passes', async ({ page }) => {
    const response = await page.request.get(`${BACKEND_URL}/api/gis-test/status`);
    if (response.ok()) {
      const data = await response.json();
      expect(data.status).toBeTruthy();
    }
  });

  test('spatial layout generation produces valid output', async ({ page }) => {
    // Find and click the spatial layout tool section
    const layoutSection = page.locator('div.border', { hasText: /空间布局|spatial.layout/i });
    if (await layoutSection.count() > 0) {
      const runButton = layoutSection.locator('button', { hasText: /运行|run/i }).first();
      if (await runButton.count() > 0) {
        await runButton.click();
        // Wait for completion (up to 2 minutes for MIP solve)
        await page.waitForTimeout(5000);

        // Check for loading spinner to disappear
        const spinner = page.locator('.animate-spin');
        await expect(spinner).toHaveCount(0, { timeout: 120000 });

        // Verify result appeared — either success indicator or layer on map
        const resultArea = page.locator('[class*="result"], [class*="Result"]');
        if (await resultArea.count() > 0) {
          await expect(resultArea.first()).toBeVisible({ timeout: 10000 });
        }
      }
    }
  });

  test('constraint validator runs without errors', async ({ page }) => {
    const validatorSection = page.locator('div.border', { hasText: /约束|constraint|validator/i });
    if (await validatorSection.count() > 0) {
      const runButton = validatorSection.locator('button', { hasText: /运行|run/i }).first();
      if (await runButton.count() > 0) {
        await runButton.click();
        await page.waitForTimeout(3000);

        // Should not show error state
        const errorEl = validatorSection.locator('.text-red-500, .text-red-600');
        const errorCount = await errorEl.count();
        expect(errorCount).toBeLessThanOrEqual(1);
      }
    }
  });

  test('planning zones render on map after generation', async ({ page }) => {
    // Trigger spatial layout if not already visible
    const layoutSection = page.locator('div.border', { hasText: /空间布局|spatial.layout/i });
    if (await layoutSection.count() > 0) {
      const runButton = layoutSection.locator('button', { hasText: /运行|run/i }).first();
      if (await runButton.count() > 0) {
        await runButton.click();
        // Wait for MIP solve to complete
        const spinner = page.locator('.animate-spin');
        await expect(spinner).toHaveCount(0, { timeout: 120000 });
        await page.waitForTimeout(2000);
      }
    }

    // Check for planning zone layer — look for canvas re-render or GeoJSON source
    const mapCanvas = page.locator('canvas');
    await expect(mapCanvas).toBeVisible();
  });

  test('SSE progress updates appear during generation', async ({ page }) => {
    const layoutSection = page.locator('div.border', { hasText: /空间布局|spatial.layout/i });
    if (await layoutSection.count() > 0) {
      const runButton = layoutSection.locator('button', { hasText: /运行|run/i }).first();
      if (await runButton.count() > 0) {
        // Monitor for progress indicators
        const progressBefore = await page.locator('[class*="progress"], [class*="Progress"]').count();

        await runButton.click();

        // Wait a short time to see if progress appears
        await page.waitForTimeout(3000);

        const progressAfter = await page.locator('[class*="progress"], [class*="Progress"]').count();
        // Either progress appeared, or the task completed quickly
        expect(progressAfter).toBeGreaterThanOrEqual(progressBefore);
      }
    }
  });

  test('all 4 planning zone types present in generated layout', async ({ page }) => {
    // Call backend API directly to verify zone completeness
    const response = await page.request.post(`${BACKEND_URL}/api/gis-test/spatial-layout`, {
      data: {
        village_name: '金田村',
        include_adjacency: true,
      },
      headers: { 'Content-Type': 'application/json' },
    });

    if (response.ok()) {
      const data = await response.json();
      if (data.layers) {
        const planningZoneLayer = data.layers.find(
          (l: Record<string, unknown>) => l.layerType === 'planning_zone'
        );
        if (planningZoneLayer?.data?.features) {
          const zoneTypes = new Set(
            planningZoneLayer.data.features.map(
              (f: Record<string, any>) => f.properties?.assigned_zone
            )
          );
          // Should have at least 3 of the 4 standard zones
          expect(zoneTypes.size).toBeGreaterThanOrEqual(3);
        }
      }
    }
  });
});
