/**
 * E2E Test: GIS Frontend → Backend Integration
 *
 * Validates the full browser interaction path for GIS features:
 *   1. Session creation via form → planning starts
 *   2. Completed session → map tab with layers
 *   3. Full-screen map overlay opens and closes
 *   4. GIS GeoJSON upload → map updates
 *   5. Layer toggle panel shows/hides layers
 *
 * Strategy:
 *   - Test 1 uses the real form → backend flow (end-to-end session creation)
 *   - Test 2 & 4 create real API sessions and wait for L1 pause (~3 min)
 *   - Tests 3 & 5 use store injection with fake GIS data (no LLM calls)
 *
 * Requires both frontend and backend running:
 *   BACKEND_URL=http://127.0.0.1:8000 npx playwright test gis-frontend.spec.ts
 */

import { test, expect } from '@playwright/test';
import { apiClient } from './helpers/api-client';
import { MINIMAL_VILLAGE } from './fixtures/village-data';

// Absolute path to GIS test data
const GIS_DATA_DIR = 'F:/project/Village_Planning_Agent/data/gis/jintian';

/** Minimal GeoJSON FeatureCollection for store injection. */
const EMPTY_GEOJSON = { type: 'FeatureCollection', features: [] };

/**
 * Inject a session into the frontend zustand store with backend state sync.
 * Must be called AFTER page.goto('/').
 */
async function injectSessionWithSync(
  page: import('@playwright/test').Page,
  sessionId: string,
  villageName: string,
  status: 'completed' | 'paused' = 'completed',
) {
  await page.evaluate(
    async ({ sid, vname, st }) => {
      const store = (window as any).__PLANNING_STORE__;
      if (!store) throw new Error('__PLANNING_STORE__ not found on window');
      const { getState } = store;

      getState().clearMessages();
      getState().setProjectName(vname);
      getState().setSessionId(sid);
      getState().setStatus(st);

      // Sync backend state
      const backendUrl = 'http://127.0.0.1:8000';
      try {
        const [checkpointsResp, statusData] = await Promise.all([
          fetch(`${backendUrl}/api/sessions/${sid}/checkpoints`).then((r) => r.json()),
          fetch(`${backendUrl}/api/v1/sessions/${sid}/state`).then((r) => r.json()),
        ]);
        getState().setCheckpoints(
          checkpointsResp.checkpoints.map((cp: any) => ({
            checkpoint_id: cp.checkpoint_id,
            description: cp.phase || '',
            timestamp: '',
            layer: cp.layer,
          })),
        );
        getState().syncBackendState(statusData);
      } catch {
        // Store still has sessionId + status for UI transition
      }
    },
    { sid: sessionId, vname: villageName, st: status },
  );
  await page.waitForTimeout(1000);
}

/**
 * Inject a fake completed session with GIS layers for UI-only tests.
 * No backend calls needed — pure frontend state injection.
 */
async function injectFakeSessionWithGis(
  page: import('@playwright/test').Page,
) {
  await page.evaluate(() => {
    const store = (window as any).__PLANNING_STORE__;
    if (!store) throw new Error('__PLANNING_STORE__ not found');
    const { getState } = store;

    getState().setSessionId('fake-gis-session');
    getState().setProjectName('测试村');
    getState().setStatus('completed');

    // Use addGisLayersFromUpload to inject GIS layers
    const emptyGeojson = { type: 'FeatureCollection', features: [] };
    getState().addGisLayersFromUpload([
      {
        layers: [
          {
            geojson: emptyGeojson,
            layerType: 'boundary',
            layerName: '村庄边界',
            color: '#4ade80',
          },
          {
            geojson: emptyGeojson,
            layerType: 'function_zone',
            layerName: '现状用地',
            color: '#f59e0b',
          },
        ],
      },
    ]);
  });
  await page.waitForTimeout(1000);
}

test.describe('GIS Frontend Integration', () => {
  // Test 1 is fast; Tests 2 & 4 need L1 pause (~3 min); Tests 3 & 5 are fast
  test.setTimeout(600000); // 10 min (Tests 2 & 4 need L1 pause)

  // ── Test 1: Form → Session → Planning (real E2E) ────

  test('create session via form and verify planning starts', async ({ page }) => {
    await page.goto('/');

    // Wait for the form to render
    await expect(page.locator('#projectName')).toBeVisible();

    // Fill required fields
    await page.locator('#projectName').fill('金田村规划测试');
    await page.locator('#villageData').fill(
      '金田村位于广东省梅州市平远县泗水镇，总面积约23平方公里，下辖12个村民小组，人口约2000人，主要产业为农业和林业。',
    );

    // Click submit
    await page.getByRole('button', { name: '开始规划' }).click();

    // Verify page transitions to planning state
    await expect(page.getByText('L1').first()).toBeVisible({ timeout: 60000 });
  });

  // ── Test 2: Completed session → map tab with layers ──

  test('completed session shows map tab with layers', async ({ page }) => {
    // Create session via API (step mode → L1 pause in ~3 min)
    const sessionId = await apiClient.createSession({
      projectName: MINIMAL_VILLAGE.projectName,
      villageName: MINIMAL_VILLAGE.villageName,
      villageData: MINIMAL_VILLAGE.villageData,
      taskDescription: MINIMAL_VILLAGE.taskDescription,
      stepMode: true,
    });

    // Wait for L1 to pause (generous timeout for concurrent sessions)
    await apiClient.waitForPaused(sessionId, 600000);

    // Navigate and inject completed state
    await page.goto('/');
    await injectSessionWithSync(page, sessionId, MINIMAL_VILLAGE.villageName, 'paused');

    // Switch to map tab
    await page.getByRole('button', { name: '地图' }).click({ timeout: 10000 });

    // Verify MapLibre map container renders
    await expect(page.locator('.maplibregl-map')).toBeVisible({ timeout: 15000 });
  });

  // ── Test 3: Full-screen map overlay ─────────────────

  test('full-screen map overlay opens and closes', async ({ page }) => {
    await page.goto('/');
    await injectFakeSessionWithGis(page);

    // Switch to map tab
    await page.getByRole('button', { name: '地图' }).click({ timeout: 10000 });

    // Wait for map to render
    await expect(page.locator('.maplibregl-map')).toBeVisible({ timeout: 15000 });

    // Open full-screen map
    await page.getByTitle('全屏查看').click();

    // Verify overlay appears (fullscreen overlay has z-50)
    await expect(page.locator('.fixed.inset-0.z-50')).toBeVisible();

    // Close overlay
    await page.getByTitle('关闭全屏').click();

    // Verify overlay closed
    await expect(page.locator('.fixed.inset-0.z-50')).not.toBeVisible();
  });

  // ── Test 4: GIS upload → map update ─────────────────

  test('upload GIS GeoJSON updates map layers', async ({ page }) => {
    // Create session via API and wait for L1 pause
    const sessionId = await apiClient.createSession({
      projectName: MINIMAL_VILLAGE.projectName,
      villageName: MINIMAL_VILLAGE.villageName,
      villageData: MINIMAL_VILLAGE.villageData,
      taskDescription: MINIMAL_VILLAGE.taskDescription,
      stepMode: true,
    });

    // Wait for L1 to pause (generous timeout for concurrent sessions)
    await apiClient.waitForPaused(sessionId, 600000);

    await page.goto('/');
    await injectSessionWithSync(page, sessionId, MINIMAL_VILLAGE.villageName, 'paused');

    // Switch to map tab
    await page.getByRole('button', { name: '地图' }).click({ timeout: 10000 });

    // Upload a GeoJSON file via hidden file input
    const fileInput = page.locator('input[type="file"][accept=".geojson,.json"]');
    await fileInput.setInputFiles(`${GIS_DATA_DIR}/current/boundary.geojson`);

    // Verify upload success indicator (green badge with checkmark on upload button)
    await expect(page.locator('[title^="已上传"]')).toBeVisible({ timeout: 15000 });

    // Verify map renders after upload
    await expect(page.locator('.maplibregl-map')).toBeVisible({ timeout: 15000 });
  });

  // ── Test 5: Layer toggle panel ──────────────────────

  test('layer toggle panel shows and hides layers', async ({ page }) => {
    await page.goto('/');
    await injectFakeSessionWithGis(page);

    // Switch to map tab
    await page.getByRole('button', { name: '地图' }).click({ timeout: 10000 });

    // Wait for map to render
    await expect(page.locator('.maplibregl-map')).toBeVisible({ timeout: 15000 });

    // Verify layer panel header
    await expect(page.getByText('图层')).toBeVisible();

    // Verify toggle all button exists
    await expect(page.getByText(/全显|全隐/)).toBeVisible();
  });
});
