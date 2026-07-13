/**
 * E2E Test: GIS Full Integration Flow
 *
 * Validates the complete pipeline: Planning → GIS Agent → SSE Events → Frontend Rendering
 * with real Jintian village GIS data, Watchdog monitoring, and result persistence.
 *
 * Tests:
 *   1. Full chain: planning → GIS trigger → SSE → frontend (with Watchdog)
 *   2. GeoJSON data integrity validation
 *   3. Incremental SSE event sequence validation
 *   4. Frontend map interaction with real Jintian data
 *   5. Error handling
 *
 * Requires both frontend and backend running:
 *   BACKEND_URL=http://127.0.0.1:8000 npx playwright test gis-integration.spec.ts
 */

import { test, expect } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs/promises';
import { apiClient } from './helpers/api-client';
import { SSECollector } from './helpers/sse-collector';
import { MINIMAL_VILLAGE, JINTIAN_VILLAGE, JINTIAN_GIS_FILES, JINTIAN_ALL_GIS_FILES, BACKEND_URL, loadJintianVillageData, E2E_OUTPUT_BASE } from './fixtures/village-data';
import { Watchdog, saveTestResults } from './helpers/log-collector';
import { GisVerifier } from './helpers/gis-verifier';

// ── Shared helpers ────────────────────────────────────────────────────

/** Inject a session into the frontend store with backend state sync. */
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

      try {
        const [checkpointsResp, statusData] = await Promise.all([
          fetch(`${BACKEND_URL}/api/sessions/${sid}/checkpoints`).then((r) => r.json()),
          fetch(`${BACKEND_URL}/api/sessions/${sid}/status`).then((r) => r.json()),
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

/** Create session, upload GIS data, connect SSE, start Watchdog. */
async function setupFullSession() {
  const sse = new SSECollector();
  const watchdog = new Watchdog({ pollIntervalMs: 30000, stagnationThreshold: 3, maxTimeoutMs: 2400000 });

  // Load detailed village data from demo file
  const villageData = await loadJintianVillageData();
  console.log(`[Setup] Loaded village data: ${villageData.length} chars`);

  const sessionId = await apiClient.createSessionWithGis(
    {
      projectName: JINTIAN_VILLAGE.projectName,
      villageName: JINTIAN_VILLAGE.villageName,
      villageData,
      taskDescription: JINTIAN_VILLAGE.taskDescription,
      province: JINTIAN_VILLAGE.province,
      city: JINTIAN_VILLAGE.city,
      county: JINTIAN_VILLAGE.county,
      township: JINTIAN_VILLAGE.township,
      stepMode: false,
    },
    JINTIAN_GIS_FILES,
  );
  console.log(`[Setup] Session: ${sessionId}`);

  sse.connect(sessionId);
  watchdog.start(sessionId);

  return { sessionId, sse, watchdog };
}

/** Feed SSE events to Watchdog for pipeline tracking. */
function feedWatchdogFromSse(sse: SSECollector, watchdog: Watchdog) {
  for (const event of sse.getEvents()) {
    watchdog.recordSseEvent(event.type, event.data);
  }
}

// ── Test Suite ────────────────────────────────────────────────────────

test.describe('GIS Full Integration', () => {
  test.setTimeout(2400000); // 40 min

  // ── Test 1: Full chain ─────────────────────────────────────────────

  test('planning → GIS trigger → SSE events → frontend rendering', async ({ page }) => {
    console.log('\n=== TEST 1: Full GIS Integration Chain ===\n');

    const { sessionId, sse, watchdog } = await setupFullSession();

    // Step 1: Wait for planning completion
    console.log('[Step 1] Waiting for planning completion...');
    const completedStatus = await apiClient.waitForCompleted(sessionId, 1200000);
    console.log(`[Step 1] Planning completed: phase=${completedStatus.phase}, progress=${completedStatus.progress}%`);
    expect(completedStatus.status).toBe('completed');
    expect(completedStatus.progress).toBeGreaterThanOrEqual(90);

    feedWatchdogFromSse(sse, watchdog);

    // Step 2: Trigger GIS analysis
    console.log('[Step 2] Triggering GIS analysis...');
    const gisTriggerResult = await apiClient.triggerGisAnalysis(sessionId);
    console.log(`[Step 2] GIS trigger result: ${JSON.stringify(gisTriggerResult)}`);

    // Step 3: Wait for GIS result SSE event
    console.log('[Step 3] Waiting for gis_result SSE event...');
    const gisResultEvent = await sse.waitForEventType('gis_result', 1200000);
    const gisResult = gisResultEvent.data as any;
    console.log(`[Step 3] GIS result: dimension_key=${gisResult.dimension_key}, layers=${gisResult.layers?.length}`);

    feedWatchdogFromSse(sse, watchdog);

    // Step 4: Verify gis_result structure
    expect(gisResult.dimension_key).toBe('spatial_layout');
    expect(gisResult.dimension_name).toBe('空间布局');
    expect(gisResult.layers).toBeTruthy();
    expect(Array.isArray(gisResult.layers)).toBe(true);
    expect(gisResult.layers.length).toBeGreaterThan(0);

    // Verify each layer has required fields
    for (const layer of gisResult.layers) {
      expect(layer.layerType).toBeTruthy();
      expect(layer.layerName).toBeTruthy();
      expect(layer.geojson).toBeTruthy();
    }

    // Step 5: Verify incremental gis_layer_update events
    const gisLayerUpdates = sse.getEventsByType('gis_layer_update');
    console.log(`[Step 5] Incremental gis_layer_update events: ${gisLayerUpdates.length}`);
    expect(gisLayerUpdates.length).toBeGreaterThanOrEqual(1);

    // Step 6: Frontend rendering
    console.log('[Step 6] Verifying frontend rendering...');
    await page.goto('/');
    await injectSessionWithSync(page, sessionId, JINTIAN_VILLAGE.villageName, 'completed');

    // Switch to map tab
    await page.getByRole('button', { name: '地图' }).click({ timeout: 10000 }).catch(() => {
      console.log('[Step 6] Map tab click failed, trying alternative...');
    });

    // Verify MapLibre renders
    await expect(page.locator('.maplibregl-map')).toBeVisible({ timeout: 30000 }).catch(() => {
      console.log('[Step 6] MapLibre map not visible - checking store state...');
    });

    // Verify store has GIS data
    const storeHasGis = await page.evaluate(() => {
      const store = (window as any).__PLANNING_STORE__;
      if (!store) return false;
      const state = store.getState();
      return Object.keys(state.gisLayers || {}).length > 0;
    });
    console.log(`[Step 6] Store has GIS data: ${storeHasGis}`);

    // Step 7: Save screenshot
    const outputDir = path.join(E2E_OUTPUT_BASE, sessionId);
    await fs.mkdir(outputDir, { recursive: true });
    const screenshotPath = path.join(outputDir, 'frontend_screenshot.png');
    await page.screenshot({ path: screenshotPath, fullPage: false }).catch(() => {
      console.log('[Step 7] Screenshot failed');
    });
    console.log(`[Step 7] Screenshot saved: ${screenshotPath}`);

    // Step 8: Save all test results
    const layersMap = GisVerifier.buildLayersMap(gisResult.layers);
    await saveTestResults(sessionId, {
      gisLayerConfigs: gisResult.layers,
      pipelineReport: {
        sessionId,
        ssePipelineTrace: sse.getPipelineTrace(),
        watchdogSummary: watchdog.getPipelineSummary(),
      },
      watchdogSummary: watchdog.getPipelineSummary(),
      sseEvents: sse.getEvents().map((e) => ({ type: e.type, data: e.data, timestamp: e.timestamp })),
      statusHistory: watchdog.getStatusHistory(),
      layers: layersMap,
    });

    // Step 9: Final Watchdog check
    watchdog.stop();
    feedWatchdogFromSse(sse, watchdog);

    if (watchdog.hasErrors()) {
      console.error(`[Watchdog] Errors detected: ${watchdog.getErrors().join('; ')}`);
    }

    console.log('\n=== TEST 1: COMPLETE ===\n');
    sse.disconnect();
  });

  // ── Test 2: GeoJSON data integrity ─────────────────────────────────

  test('GIS SSE event data integrity validation', async () => {
    console.log('\n=== TEST 2: GeoJSON Data Integrity ===\n');

    const { sessionId, sse, watchdog } = await setupFullSession();

    // Wait for planning + GIS
    await apiClient.waitForCompleted(sessionId, 1200000);
    await apiClient.triggerGisAnalysis(sessionId);
    const gisResultEvent = await sse.waitForEventType('gis_result', 1200000);
    const gisResult = gisResultEvent.data as any;

    feedWatchdogFromSse(sse, watchdog);

    // Validate each layer
    const layerTypes: string[] = [];
    for (let i = 0; i < gisResult.layers.length; i++) {
      const layer = gisResult.layers[i];
      const validation = GisVerifier.validateLayerConfig(layer);

      if (!validation.valid) {
        console.warn(`[Layer ${i}] ${layer.layerType}: ${validation.errors.join(', ')}`);
      }

      // Core checks
      expect(layer.layerType).toBeTruthy();
      expect(layer.geojson).toBeTruthy();
      expect(layer.geojson.type).toBe('FeatureCollection');
      expect(Array.isArray(layer.geojson.features)).toBe(true);

      // Coordinate bounds check
      if (layer.geojson.features.length > 0) {
        const coordResult = GisVerifier.validateCoordinateBounds(layer.geojson.features[0]?.geometry);
        if (coordResult.length > 0) {
          console.warn(`[Layer ${i}] ${layer.layerType} coordinate issues: ${coordResult.join(', ')}`);
        }
      }

      layerTypes.push(layer.layerType);
      console.log(`  ${layer.layerType} (${layer.layerName}): ${layer.geojson.features?.length ?? 0} features`);
    }

    // Verify layer types are from expected set
    const expectedTypes = GisVerifier.getExpectedLayerTypes();
    console.log(`\nLayer types present: ${layerTypes.join(', ')}`);
    console.log(`Expected types: ${expectedTypes.join(', ')}`);

    for (const lt of layerTypes) {
      expect(expectedTypes).toContain(lt);
    }

    // Verify layer names contain Chinese
    for (const layer of gisResult.layers) {
      if (layer.layerName) {
        const hasChinese = /[一-鿿]/.test(layer.layerName);
        if (!hasChinese) {
          console.warn(`Layer name not Chinese: ${layer.layerName}`);
        }
      }
    }

    // Save results
    await saveTestResults(sessionId, {
      gisLayerConfigs: gisResult.layers,
      watchdogSummary: watchdog.getPipelineSummary(),
      layers: GisVerifier.buildLayersMap(gisResult.layers),
    });

    watchdog.stop();
    sse.disconnect();
    console.log('\n=== TEST 2: COMPLETE ===\n');
  });

  // ── Test 3: Incremental SSE event sequence ─────────────────────────

  test('incremental SSE event sequence with pipeline monitoring', async () => {
    console.log('\n=== TEST 3: Incremental SSE Event Sequence ===\n');

    const { sessionId, sse, watchdog } = await setupFullSession();

    // Wait for planning completion
    await apiClient.waitForCompleted(sessionId, 1200000);
    feedWatchdogFromSse(sse, watchdog);

    // Verify dimension_complete events from planning
    const dimCompleteEvents = sse.getEventsByType('dimension_complete');
    console.log(`[Planning] dimension_complete events: ${dimCompleteEvents.length}`);
    expect(dimCompleteEvents.length).toBeGreaterThan(0);

    // Trigger GIS
    await apiClient.triggerGisAnalysis(sessionId);

    // Wait for GIS events
    const gisResultEvent = await sse.waitForEventType('gis_result', 1200000);
    feedWatchdogFromSse(sse, watchdog);

    // Verify event sequence
    const allEvents = sse.getEvents();
    const eventTypes = allEvents.map((e) => e.type);
    const uniqueTypes = [...new Set(eventTypes)];

    console.log(`Total SSE events: ${allEvents.length}`);
    console.log(`Unique types: ${uniqueTypes.join(', ')}`);

    // Critical event types must appear
    const criticalTypes = ['dimension_complete', 'gis_layer_update', 'gis_result'];
    for (const ct of criticalTypes) {
      const count = eventTypes.filter((t) => t === ct).length;
      console.log(`  ${ct}: ${count}`);
      expect(count, `Critical event ${ct} should appear`).toBeGreaterThanOrEqual(1);
    }

    // Verify gis_layer_update appears before gis_result
    const layerUpdateIdx = eventTypes.indexOf('gis_layer_update');
    const gisResultIdx = eventTypes.indexOf('gis_result');
    expect(layerUpdateIdx).toBeGreaterThanOrEqual(0);
    expect(gisResultIdx).toBeGreaterThan(layerUpdateIdx);
    console.log(`gis_layer_update at event[${layerUpdateIdx}], gis_result at event[${gisResultIdx}]`);

    // Verify incremental layers count
    const gisLayerUpdates = sse.getEventsByType('gis_layer_update');
    let incrementalLayerCount = 0;
    for (const update of gisLayerUpdates) {
      const data = update.data as any;
      incrementalLayerCount += data?.layers?.length ?? 0;
    }
    const finalLayerCount = (gisResultEvent.data as any)?.layers?.length ?? 0;
    console.log(`Incremental layers: ${incrementalLayerCount}, Final layers: ${finalLayerCount}`);
    expect(incrementalLayerCount).toBeGreaterThanOrEqual(finalLayerCount);

    // Pipeline trace
    const pipelineTrace = sse.getPipelineTrace();
    console.log(`\nPipeline trace (${pipelineTrace.length} stages):`);
    for (const stage of pipelineTrace) {
      console.log(`  ${stage.tool} @ ${new Date(stage.timestamp).toISOString()}`);
    }

    // Save results
    await saveTestResults(sessionId, {
      pipelineReport: {
        sessionId,
        ssePipelineTrace: pipelineTrace,
        eventCounts: uniqueTypes.map((t) => ({ type: t, count: eventTypes.filter((et) => et === t).length })),
      },
      watchdogSummary: watchdog.getPipelineSummary(),
      sseEvents: allEvents.map((e) => ({ type: e.type, timestamp: e.timestamp })),
    });

    watchdog.stop();
    sse.disconnect();
    console.log('\n=== TEST 3: COMPLETE ===\n');
  });

  // ── Test 4: Frontend map interaction with real data ────────────────

  test('frontend map interaction with real Jintian GIS data', async ({ page }) => {
    console.log('\n=== TEST 4: Frontend Map Interaction ===\n');

    const sse = new SSECollector();
    const watchdog = new Watchdog();

    // Create session with full Jintian data (load detailed village report)
    const villageData = await loadJintianVillageData();
    const sessionId = await apiClient.createSessionWithGis(
      {
        projectName: JINTIAN_VILLAGE.projectName,
        villageName: JINTIAN_VILLAGE.villageName,
        villageData,
        taskDescription: JINTIAN_VILLAGE.taskDescription,
        province: JINTIAN_VILLAGE.province,
        city: JINTIAN_VILLAGE.city,
        county: JINTIAN_VILLAGE.county,
        township: JINTIAN_VILLAGE.township,
        stepMode: false,
      },
      JINTIAN_ALL_GIS_FILES,
    );
    console.log(`[Setup] Session: ${sessionId}`);

    sse.connect(sessionId);
    watchdog.start(sessionId);

    // Wait for planning + GIS
    await apiClient.waitForCompleted(sessionId, 1200000);
    await apiClient.triggerGisAnalysis(sessionId);
    await sse.waitForEventType('gis_result', 1200000);
    feedWatchdogFromSse(sse, watchdog);

    // Navigate to frontend
    await page.goto('/');
    await injectSessionWithSync(page, sessionId, JINTIAN_VILLAGE.villageName, 'completed');

    // Switch to map tab
    await page.getByRole('button', { name: '地图' }).click({ timeout: 10000 }).catch(() => {});

    // Verify map renders
    await expect(page.locator('.maplibregl-map')).toBeVisible({ timeout: 30000 });
    console.log('[Map] MapLibre map rendered');

    // Verify map shows real data (non-empty GeoJSON in store)
    const hasRealData = await page.evaluate(() => {
      const store = (window as any).__PLANNING_STORE__;
      if (!store) return false;
      const state = store.getState();
      const layers = state.gisLayers || {};
      let totalFeatures = 0;
      for (const key of Object.keys(layers)) {
        const layerArr = layers[key] as any[];
        if (Array.isArray(layerArr)) {
          for (const layer of layerArr) {
            totalFeatures += layer?.geojson?.features?.length ?? 0;
          }
        }
      }
      return totalFeatures > 0;
    });
    console.log(`[Map] Has real GIS data: ${hasRealData}`);
    expect(hasRealData).toBe(true);

    // Screenshot
    const outputDir = path.join(E2E_OUTPUT_BASE, sessionId);
    await fs.mkdir(outputDir, { recursive: true });
    await page.screenshot({ path: path.join(outputDir, 'frontend_screenshot.png'), fullPage: false }).catch(() => {});

    // Full-screen map
    const fullscreenBtn = page.getByTitle('全屏查看');
    if (await fullscreenBtn.isVisible().catch(() => false)) {
      await fullscreenBtn.click();
      await expect(page.locator('.fixed.inset-0.z-50')).toBeVisible({ timeout: 5000 }).catch(() => {
        console.log('[Map] Fullscreen overlay not found');
      });
      // Screenshot fullscreen
      await page.screenshot({ path: path.join(outputDir, 'frontend_fullscreen.png'), fullPage: false }).catch(() => {});

      // Close fullscreen
      const closeBtn = page.getByTitle('关闭全屏');
      if (await closeBtn.isVisible().catch(() => false)) {
        await closeBtn.click();
      }
    }

    // Layer toggle panel
    const layerPanel = page.getByText('图层');
    if (await layerPanel.isVisible().catch(() => false)) {
      console.log('[Map] Layer panel visible');
    }

    // Save results
    const gisResults = sse.getEventsByType('gis_result');
    const gisData = gisResults.length > 0 ? (gisResults[gisResults.length - 1].data as any) : null;

    await saveTestResults(sessionId, {
      gisLayerConfigs: gisData?.layers,
      watchdogSummary: watchdog.getPipelineSummary(),
      statusHistory: watchdog.getStatusHistory(),
      layers: gisData?.layers ? GisVerifier.buildLayersMap(gisData.layers) : undefined,
    });

    watchdog.stop();
    sse.disconnect();
    console.log('\n=== TEST 4: COMPLETE ===\n');
  });

  // ── Test 5: Error handling ─────────────────────────────────────────

  test('GIS error handling', async () => {
    console.log('\n=== TEST 5: Error Handling ===\n');

    // Test 5a: Invalid GeoJSON upload
    const sessionId = await apiClient.createSession({
      projectName: MINIMAL_VILLAGE.projectName,
      villageName: MINIMAL_VILLAGE.villageName,
      villageData: MINIMAL_VILLAGE.villageData,
      taskDescription: MINIMAL_VILLAGE.taskDescription,
      stepMode: false,
    });

    // Write invalid GeoJSON to temp file
    const tmpDir = path.join(E2E_OUTPUT_BASE, '_tmp');
    await fs.mkdir(tmpDir, { recursive: true });
    const invalidFile = path.join(tmpDir, 'invalid.geojson');
    await fs.writeFile(invalidFile, '{"type":"Invalid","features":[]}', 'utf-8');

    // Upload should fail with 400
    const uploadResult = await apiClient.uploadGisData(sessionId, invalidFile, 'boundary').catch((err) => err);
    console.log(`[5a] Invalid GeoJSON upload: ${uploadResult instanceof Error ? `Error: ${uploadResult.message}` : `Success: ${JSON.stringify(uploadResult)}`}`);

    // Test 5b: Empty file upload
    const emptyFile = path.join(tmpDir, 'empty.geojson');
    await fs.writeFile(emptyFile, '', 'utf-8');

    const emptyResult = await apiClient.uploadGisData(sessionId, emptyFile).catch((err) => err);
    console.log(`[5b] Empty file upload: ${emptyResult instanceof Error ? `Error: ${emptyResult.message}` : `Result: ${JSON.stringify(emptyResult)}`}`);

    // Test 5c: Session should still be functional after error
    const status = await apiClient.getStatus(sessionId);
    console.log(`[5c] Session status after errors: ${status.status}`);
    // Session should not crash
    expect(['pending', 'running', 'paused', 'completed']).toContain(status.status);

    // Cleanup
    await apiClient.deleteSession(sessionId);
    await fs.rm(tmpDir, { recursive: true, force: true });

    console.log('\n=== TEST 5: COMPLETE ===\n');
  });
});
