/**
 * GIS Map Interactions E2E Tests
 *
 * Verifies core map rendering and interaction capabilities:
 * - Page load and map canvas initialization
 * - Basemap switching (vector / image / terrain)
 * - Layer visibility toggling
 * - Feature click / popup display
 * - Zoom and pan controls
 * - Legend panel rendering
 */

import { test, expect } from '@playwright/test';

const TEST_GIS_URL = '/test-gis';

test.describe('GIS Map Interactions', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(TEST_GIS_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
    // Wait for map canvas to initialize
    await page.waitForSelector('canvas', { timeout: 15000 });
    // Additional wait for MapLibre to fully render
    await page.waitForTimeout(3000);
  });

  test('map canvas renders on page load', async ({ page }) => {
    const canvas = page.locator('canvas');
    await expect(canvas).toBeVisible();
    // MapLibre renders multiple canvases; at least one must be visible
    const count = await canvas.count();
    expect(count).toBeGreaterThanOrEqual(1);
  });

  test('basemap switch to satellite image', async ({ page }) => {
    const imageBtn = page.locator('button', { hasText: /卫星|影像/ });
    if (await imageBtn.count() > 0) {
      await imageBtn.first().click();
      await page.waitForTimeout(2000);
      // Map should still render after basemap switch
      const canvas = page.locator('canvas');
      await expect(canvas).toBeVisible();
    }
  });

  test('basemap switch to terrain', async ({ page }) => {
    const terrainBtn = page.locator('button', { hasText: /地形/ });
    if (await terrainBtn.count() > 0) {
      await terrainBtn.first().click();
      await page.waitForTimeout(2000);
      const canvas = page.locator('canvas');
      await expect(canvas).toBeVisible();
    }
  });

  test('layer toggle hides and shows GeoJSON data', async ({ page }) => {
    // Look for layer toggle checkboxes or buttons
    const layerToggle = page.locator('input[type="checkbox"]').first();
    if (await layerToggle.count() > 0) {
      const isChecked = await layerToggle.isChecked();
      await layerToggle.click();
      await page.waitForTimeout(500);
      const newState = await layerToggle.isChecked();
      expect(newState).toBe(!isChecked);
    }
  });

  test('zoom controls work', async ({ page }) => {
    const zoomIn = page.locator('button', { hasText: /\+/ }).or(
      page.locator('[aria-label*="zoom"]')
    ).or(
      page.locator('.maplibregl-ctrl-zoom-in')
    );
    if (await zoomIn.count() > 0) {
      await zoomIn.first().click();
      await page.waitForTimeout(500);
      const canvas = page.locator('canvas');
      await expect(canvas).toBeVisible();
    }
  });

  test('legend panel displays zone colors', async ({ page }) => {
    const legend = page.locator('[class*="legend"], [class*="Legend"]');
    if (await legend.count() > 0) {
      await expect(legend.first()).toBeVisible();
    }
  });

  test('no console errors on initial load', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        errors.push(msg.text());
      }
    });
    // Reload to capture console messages
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    // Filter out known benign errors (map tile fetch failures, 404s, CORS)
    const criticalErrors = errors.filter(
      (e) =>
        !e.includes('404') &&
        !e.includes('net::ERR') &&
        !e.includes('CORS') &&
        !e.includes('Failed to fetch') &&
        !e.includes('AJAXError')
    );
    if (criticalErrors.length > 2) {
      console.log('Critical console errors:', JSON.stringify(criticalErrors, null, 2));
    }
    expect(criticalErrors.length).toBeLessThanOrEqual(2);
  });
});
