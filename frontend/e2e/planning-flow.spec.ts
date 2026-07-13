/**
 * E2E Test: Full Planning Flow
 *
 * Validates the complete interrupt/approve cycle:
 *   START → L1 (12 dims) → interrupt → approve → L2 → interrupt → approve → L3 → completed
 *
 * Backend must be running on BACKEND_URL (default http://127.0.0.1:8000).
 * Run: BACKEND_URL=http://127.0.0.1:8000 npx playwright test planning-flow.spec.ts
 */

import { test, expect } from '@playwright/test';
import { apiClient } from './helpers/api-client';
import { SSECollector } from './helpers/sse-collector';
import { TEST_VILLAGE, MINIMAL_VILLAGE } from './fixtures/village-data';

test.describe('Planning Flow', () => {
  test.setTimeout(600000); // 10 min timeout for full planning

  test('L1 → interrupt → approve → L2 → interrupt → approve → L3 → completed', async () => {
    const sse = new SSECollector();

    // Step 1: Create session with step_mode=true
    const sessionId = await apiClient.createSession({
      projectName: MINIMAL_VILLAGE.projectName,
      villageName: MINIMAL_VILLAGE.villageName,
      villageData: MINIMAL_VILLAGE.villageData,
      taskDescription: MINIMAL_VILLAGE.taskDescription,
      stepMode: true,
    });
    console.log(`[Test] Session created: ${sessionId}`);
    expect(sessionId).toBeTruthy();

    // Connect SSE collector to track events
    sse.connect(sessionId);

    // Step 2: Wait for L1 to complete and pause (interrupt)
    const paused1 = await apiClient.waitForPaused(sessionId);
    console.log(`[Test] L1 paused: phase=${paused1.phase}, status=${paused1.status}`);
    expect(paused1.status).toBe('paused');
    expect(paused1.current_layer).toBe(1);
    expect(paused1.interrupt_info).toBeTruthy();
    expect(paused1.interrupt_info!.reason).toBe('step_mode');
    expect(paused1.completed_dimensions.layer1.length).toBeGreaterThanOrEqual(1);

    // Verify SSE events for L1
    const layerStartedEvents = sse.getEventsByType('layer_started');
    expect(layerStartedEvents.length).toBeGreaterThanOrEqual(1);

    const dimCompleteEvents = sse.getEventsByType('dimension_complete');
    console.log(`[Test] L1 dimension_complete events: ${dimCompleteEvents.length}`);
    expect(dimCompleteEvents.length).toBeGreaterThan(0);

    // Step 3: Approve L1 → L2
    const approve1 = await apiClient.approve(sessionId);
    console.log(`[Test] L1 approved: ${JSON.stringify(approve1)}`);
    expect(approve1.status).toBe('approved');

    // Step 4: Wait for L2 to pause
    const paused2 = await apiClient.waitForPaused(sessionId, 600000);
    console.log(`[Test] L2 paused: phase=${paused2.phase}, status=${paused2.status}`);
    expect(paused2.status).toBe('paused');
    expect(paused2.current_layer).toBe(2);

    // Step 5: Approve L2 → L3
    const approve2 = await apiClient.approve(sessionId);
    console.log(`[Test] L2 approved: ${JSON.stringify(approve2)}`);
    expect(approve2.status).toBe('approved');

    // Step 6: Wait for L3 to pause
    const paused3 = await apiClient.waitForPaused(sessionId, 600000);
    console.log(`[Test] L3 paused: phase=${paused3.phase}, status=${paused3.status}`);
    expect(paused3.status).toBe('paused');
    expect(paused3.current_layer).toBe(3);

    // Step 7: Final approve → completed
    const approve3 = await apiClient.approve(sessionId);
    console.log(`[Test] L3 approved: ${JSON.stringify(approve3)}`);

    const completed = await apiClient.waitForCompleted(sessionId);
    console.log(`[Test] Completed: phase=${completed.phase}, status=${completed.status}`);
    expect(completed.status).toBe('completed');
    expect(completed.progress).toBeGreaterThanOrEqual(90);

    // Verify SSE event sequence contains the expected flow
    const allTypes = sse.getEvents().map((e) => e.type);
    console.log(`[Test] SSE event types: ${[...new Set(allTypes)].join(', ')}`);
    console.log(`[Test] Total SSE events: ${allTypes.length}`);

    // Verify planning text was generated
    const planningText = await apiClient.getPlanningText(sessionId);
    console.log(`[Test] Planning text version: ${planningText?.version}, length: ${planningText?.content?.length}`);
    expect(planningText).toBeTruthy();
    expect(planningText!.content.length).toBeGreaterThan(100);

    sse.disconnect();
  });

  test('reject with feedback triggers revision cascade', async () => {
    const sessionId = await apiClient.createSession({
      projectName: MINIMAL_VILLAGE.projectName,
      villageName: MINIMAL_VILLAGE.villageName,
      villageData: MINIMAL_VILLAGE.villageData,
      taskDescription: MINIMAL_VILLAGE.taskDescription,
      stepMode: true,
    });
    console.log(`[Test] Session created: ${sessionId}`);

    // Wait for L1 to pause
    const paused = await apiClient.waitForPaused(sessionId);
    expect(paused.status).toBe('paused');

    // Reject with feedback targeting specific dimensions
    const result = await apiClient.reject(
      sessionId,
      '土地利用率分析不够深入，需要补充森林覆盖率和基本农田分布的具体数据。',
      ['land_use', 'ecological_green'],
    );
    console.log(`[Test] Rejected: ${JSON.stringify(result)}`);

    // Check that session enters revising status
    const statusAfterReject = await apiClient.getStatus(sessionId);
    console.log(`[Test] Status after reject: ${statusAfterReject.status}`);
    // The status transitions to 'revising' or similar
    expect(['revising', 'running']).toContain(statusAfterReject.status);

    await apiClient.deleteSession(sessionId);
  });
});

test.describe('Session Status API', () => {
  test('status endpoint returns correct fields', async () => {
    const sessionId = await apiClient.createSession({
      projectName: TEST_VILLAGE.projectName,
      villageName: TEST_VILLAGE.villageName,
      villageData: TEST_VILLAGE.villageData,
      taskDescription: TEST_VILLAGE.taskDescription,
      stepMode: true,
    });

    const status = await apiClient.getStatus(sessionId);
    console.log(`[Test] Status: ${JSON.stringify(status, null, 2)}`);

    // Verify required fields
    expect(status.session_id).toBe(sessionId);
    expect(status.phase).toBeTruthy();
    expect(typeof status.current_layer).toBe('number');
    expect(typeof status.progress).toBe('number');
    expect(status.completed_dimensions).toBeTruthy();
    expect(typeof status.step_mode).toBe('boolean');

    await apiClient.deleteSession(sessionId);
  });
});
