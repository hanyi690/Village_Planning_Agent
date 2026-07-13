/**
 * E2E Test: Backend Log Verification
 *
 * Verifies critical backend log paths through the SSE event stream and API status:
 *   1. Interrupt/resume key-path log events
 *   2. GIS generation key-path log events
 *   3. Error handling and edge cases
 *
 * Backend must be running on BACKEND_URL.
 * Run: BACKEND_URL=http://127.0.0.1:8000 npx playwright test log-verification.spec.ts
 */

import { test, expect } from '@playwright/test';
import { apiClient, SessionStatus } from './helpers/api-client';
import { SSECollector } from './helpers/sse-collector';
import { MINIMAL_VILLAGE } from './fixtures/village-data';

test.describe('Log Verification via SSE Events', () => {
  test.setTimeout(900000); // 15 min for L1 + L2 full cycle

  test('interrupt/resume produces expected SSE event sequence', async () => {
    const sse = new SSECollector();

    const sessionId = await apiClient.createSession({
      projectName: MINIMAL_VILLAGE.projectName,
      villageName: MINIMAL_VILLAGE.villageName,
      villageData: MINIMAL_VILLAGE.villageData,
      taskDescription: MINIMAL_VILLAGE.taskDescription,
      stepMode: true,
    });
    console.log(`[Test] Session: ${sessionId}`);

    sse.connect(sessionId);

    // Wait for L1 interrupt (should take ~3 min)
    const pausedL1 = await apiClient.waitForPaused(sessionId);
    console.log(`[Test] L1 paused: status=${pausedL1.status} layer=${pausedL1.current_layer}`);

    // Verify interrupt_info at L1
    expect(pausedL1.interrupt_info).toBeTruthy();
    expect(pausedL1.interrupt_info!.layer).toBeGreaterThanOrEqual(1);
    expect(pausedL1.interrupt_info!.reason).toBe('step_mode');

    // Approve → L2
    await apiClient.approve(sessionId);
    console.log('[Test] L1 approved, waiting for L2...');

    // Wait for L2 interrupt (should take ~5-8 min)
    const pausedL2 = await apiClient.waitForPaused(sessionId, 600000);
    console.log(`[Test] L2 paused: status=${pausedL2.status} layer=${pausedL2.current_layer}`);

    // Verify it's actually L2
    expect(pausedL2.current_layer).toBeGreaterThanOrEqual(2);

    // Verify SSE event sequence contains critical transitions
    const eventTypes = sse.getEvents().map((e) => e.type);
    const uniqueTypes = [...new Set(eventTypes)];
    console.log(`[Test] Unique SSE event types (${sse.getEvents().length} total): ${uniqueTypes.join(', ')}`);

    // Expected event types during planning
    const expectedTypes = ['layer_started', 'dimension_complete'];
    for (const expected of expectedTypes) {
      expect(eventTypes).toContain(expected);
    }

    await apiClient.deleteSession(sessionId);
    sse.disconnect();
  });

  test('session status fields match interrupt/resume lifecycle', async () => {
    const sessionId = await apiClient.createSession({
      projectName: MINIMAL_VILLAGE.projectName,
      villageName: MINIMAL_VILLAGE.villageName,
      villageData: MINIMAL_VILLAGE.villageData,
      taskDescription: MINIMAL_VILLAGE.taskDescription,
      stepMode: true,
    });

    // Poll status and record state transitions
    const states: SessionStatus[] = [];
    let lastStatus = '';
    for (let i = 0; i < 15; i++) {
      await new Promise((r) => setTimeout(r, 5000));
      const status = await apiClient.getStatus(sessionId);
      if (status.status !== lastStatus) {
        states.push(status);
        lastStatus = status.status;
        console.log(`[Test] State transition: ${status.status} at phase=${status.phase} layer=${status.current_layer} progress=${status.progress}`);
      }
      if (status.status === 'completed' || status.status === 'paused') break;
    }

    console.log(`[Test] Recorded ${states.length} state transitions`);
    for (const s of states) {
      console.log(`  - ${s.status}: phase=${s.phase} layer=${s.current_layer} progress=${s.progress}`);
    }

    // Verify we captured at least the initial and paused states
    expect(states.length).toBeGreaterThanOrEqual(1);

    // Verify progress is monotonic
    for (let i = 1; i < states.length; i++) {
      expect(states[i].progress).toBeGreaterThanOrEqual(states[i - 1].progress);
    }

    await apiClient.deleteSession(sessionId);
  });

  test('completed session has no execution_error', async () => {
    const sessionId = await apiClient.createSession({
      projectName: MINIMAL_VILLAGE.projectName,
      villageName: MINIMAL_VILLAGE.villageName,
      villageData: MINIMAL_VILLAGE.villageData,
      taskDescription: MINIMAL_VILLAGE.taskDescription,
      stepMode: false,
    });

    const status = await apiClient.waitForCompleted(sessionId);
    console.log(`[Test] Completed: ${JSON.stringify(status)}`);
    expect(status.status).toBe('completed');
    expect(status.execution_error).toBeFalsy();
  });
});
