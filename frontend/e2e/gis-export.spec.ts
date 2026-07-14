/**
 * E2E Test: GIS Export Verification
 *
 * Validates that the GIS pipeline produces complete output:
 *   1. Complete planning flow
 *   2. Verify gis_layer_update SSE events contain required layers
 *   3. Verify gis_result event contains valid layer data
 *
 * Backend must be running on BACKEND_URL.
 * Run: BACKEND_URL=http://127.0.0.1:8000 npx playwright test gis-export.spec.ts
 */
import { test, expect } from '@playwright/test';
import { apiClient } from './helpers/api-client';
import { SSECollector } from './helpers/sse-collector';
import { TEST_VILLAGE } from './fixtures/village-data';

test.describe('GIS Export', () => {
  test.setTimeout(600000);

  test('planning completion produces >=3 GIS layer update events', async () => {
    const sse = new SSECollector();

    const sessionId = await apiClient.createSession({
      projectName: TEST_VILLAGE.projectName,
      villageName: TEST_VILLAGE.villageName,
      villageData: TEST_VILLAGE.villageData,
      taskDescription: TEST_VILLAGE.taskDescription,
      stepMode: false,
    });
    console.log(`[Test] Session: ${sessionId}`);

    sse.connect(sessionId);
    await apiClient.waitForCompleted(sessionId);

    const gisLayerUpdates = sse.getEventsByType('gis_layer_update');
    console.log(`[Test] gis_layer_update: ${gisLayerUpdates.length}`);

    expect(gisLayerUpdates.length).toBeGreaterThanOrEqual(3);

    const layerTypes = gisLayerUpdates.map(e => (e.data as Record<string, unknown>).layerType);
    console.log(`[Test] Layer types: ${layerTypes}`);
    expect(layerTypes).toContain('function_zone');
    expect(layerTypes).toContain('planning_zone');
  });

  test('GIS result event contains valid layer data', async () => {
    const sse = new SSECollector();

    const sessionId = await apiClient.createSession({
      projectName: TEST_VILLAGE.projectName,
      villageName: TEST_VILLAGE.villageName,
      villageData: TEST_VILLAGE.villageData,
      taskDescription: TEST_VILLAGE.taskDescription,
      stepMode: false,
    });

    sse.connect(sessionId);
    await apiClient.waitForCompleted(sessionId);

    const gisResults = sse.getEventsByType('gis_result');
    expect(gisResults.length).toBeGreaterThan(0);

    const lastResult = gisResults[gisResults.length - 1].data as Record<string, unknown>;
    expect(lastResult).toHaveProperty('layers');
    const layers = lastResult.layers as Array<Record<string, unknown>>;
    expect(layers.length).toBeGreaterThanOrEqual(3);

    for (const layer of layers) {
      expect(layer).toHaveProperty('geojson');
      const geojson = layer.geojson as Record<string, unknown>;
      expect(geojson).toHaveProperty('features');
      expect(Array.isArray(geojson.features)).toBe(true);
    }
  });
});
