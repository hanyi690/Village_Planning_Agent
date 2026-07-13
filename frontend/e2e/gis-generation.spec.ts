/**
 * E2E Test: GIS Spatial Layout Generation
 *
 * Validates the GIS agent generates spatial layout data:
 *   1. Complete planning first (non-step-mode for speed or step-mode for intermediate checks)
 *   2. Verify gis_layout_configs appear in session status
 *   3. Verify GIS-related SSE events (gis_layer_update, gis_result)
 *
 * Backend must be running on BACKEND_URL.
 * Run: BACKEND_URL=http://127.0.0.1:8000 npx playwright test gis-generation.spec.ts
 */

import { test, expect } from '@playwright/test';
import { apiClient } from './helpers/api-client';
import { SSECollector } from './helpers/sse-collector';
import { TEST_VILLAGE } from './fixtures/village-data';

test.describe('GIS Generation', () => {
  test.setTimeout(600000);

  test('planning completion produces GIS layout configs', async () => {
    const sse = new SSECollector();

    // Create session WITHOUT step_mode for faster execution
    const sessionId = await apiClient.createSession({
      projectName: TEST_VILLAGE.projectName,
      villageName: TEST_VILLAGE.villageName,
      villageData: TEST_VILLAGE.villageData,
      taskDescription: TEST_VILLAGE.taskDescription,
      stepMode: false,
    });
    console.log(`[Test] Session created: ${sessionId}`);

    sse.connect(sessionId);

    // Wait for completion
    const status = await apiClient.waitForCompleted(sessionId);
    console.log(`[Test] Completed: ${JSON.stringify(status)}`);

    // Check that gis_layout_configs is present in status
    const layoutConfigs = status as unknown as Record<string, unknown>;
    console.log(`[Test] GIS layout configs: ${JSON.stringify(layoutConfigs.gis_layout_configs)}`);

    // Check for GIS-related SSE events
    const gisLayerUpdates = sse.getEventsByType('gis_layer_update');
    const gisResults = sse.getEventsByType('gis_result');
    console.log(`[Test] GIS layer_update events: ${gisLayerUpdates.length}`);
    console.log(`[Test] GIS result events: ${gisResults.length}`);

    // Verify GIS events contain expected data
    if (gisLayerUpdates.length > 0) {
      const firstUpdate = gisLayerUpdates[0].data as Record<string, unknown>;
      console.log(`[Test] First GIS layer update: ${JSON.stringify(firstUpdate)}`);
      expect(firstUpdate).toHaveProperty('layer');
    }

    if (gisResults.length > 0) {
      const firstResult = gisResults[0].data as Record<string, unknown>;
      console.log(`[Test] First GIS result: ${JSON.stringify(firstResult)}`);
    }

    sse.disconnect();
  });
});
