/**
 * E2E Contract Smoke Test: 前端 x 后端 v1 稳定契约闭环。
 *
 * 不依赖完整 LLM 工作流完成，只验证前端所依赖的 v1 端点按契约响应：
 *   POST /sessions -> /state -> /events/sync -> /delivery -> /human-review
 *   -> /map-layers（200 或 404 均合法）-> /artifacts/{key}（200 或 404 均合法）
 *   且遗留端点（/api/projects）已下线（404）。
 *
 * 运行：BACKEND_URL=http://127.0.0.1:8000 npx playwright test v1-contract.spec.ts
 */

import { test, expect, type APIRequestContext } from '@playwright/test';
import { BACKEND_URL } from './fixtures/village-data';

const VILLAGE_DATA =
  '冒烟村是平原村，总面积 120 公顷，户籍人口 980 人，耕地 60 公顷，村庄建设用地 30 公顷。';

async function createSession(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${BACKEND_URL}/api/v1/sessions`, {
    multipart: {
      project_name: 'contract-smoke',
      village_name: '冒烟村',
      village_data: VILLAGE_DATA,
    },
  });
  expect(res.status()).toBe(201);
  const body = await res.json();
  expect(typeof body.session_id).toBe('string');
  expect(typeof body.stream_url).toBe('string');
  expect(body.status).toBe('running');
  // 注意：SessionCreated 与其他投影不同，不含 schema_version（后端契约如此）。
  expect(body.schema_version).toBeUndefined();
  return body.session_id as string;
}

test.describe('v1 contract closed loop', () => {
  test('legacy project endpoint is removed (404)', async ({ request }) => {
    const res = await request.get(`${BACKEND_URL}/api/projects`);
    expect([404, 405]).toContain(res.status());
  });

  test('create -> state -> events -> delivery -> human-review -> map-layers -> artifacts', async ({ request }) => {
    test.setTimeout(90000);

    const sessionId = await createSession(request);
    expect(sessionId.length).toBeGreaterThan(10);

    // /state -> SessionProjection
    // 会话创建后首个检查点异步落库，前端需轮询等待（与真实前端行为一致）。
    let stateRes = await request.get(`${BACKEND_URL}/api/v1/sessions/${sessionId}/state`);
    for (let attempt = 0; stateRes.status() === 404 && attempt < 10; attempt++) {
      await new Promise((r) => setTimeout(r, 500));
      stateRes = await request.get(`${BACKEND_URL}/api/v1/sessions/${sessionId}/state`);
    }
    expect(stateRes.status()).toBe(200);
    const state = await stateRes.json();
    expect(state.schema_version).toBe('1.0');
    expect(state.session_id).toBe(sessionId);
    expect(['pending', 'running', 'paused', 'reviewing', 'revising', 'completed', 'failed']).toContain(state.status);
    expect(typeof state.progress).toBe('number');
    expect(typeof state.last_event_seq).toBe('number');
    expect(state.links).toBeTruthy();
    expect(typeof state.links.events).toBe('string');
    expect(typeof state.links.delivery).toBe('string');
    expect(typeof state.links.map_layers).toBe('string');

    // /events/sync -> EventSyncResponse
    const syncRes = await request.get(`${BACKEND_URL}/api/v1/sessions/${sessionId}/events/sync?after=0`);
    expect(syncRes.status()).toBe(200);
    const sync = await syncRes.json();
    expect(Array.isArray(sync.events)).toBe(true);
    expect(typeof sync.last_seq).toBe('number');
    expect(sync.resync_required).toBe(false);
    // 事件是判别联合：type 只允许 v1 六种顶层类型
    const allowed = new Set(['progress', 'human_review', 'delivery_ready', 'completed', 'failed', 'resync_required']);
    for (const ev of sync.events) {
      expect(allowed.has(ev.type)).toBe(true);
      expect(typeof ev.seq).toBe('number');
      expect(ev.session_id).toBe(sessionId);
    }

    // /delivery -> DeliveryProjection
    const deliveryRes = await request.get(`${BACKEND_URL}/api/v1/sessions/${sessionId}/delivery`);
    expect(deliveryRes.status()).toBe(200);
    const delivery = await deliveryRes.json();
    expect(delivery.schema_version).toBe('1.0');
    expect(typeof delivery.available).toBe('boolean');
    expect(Array.isArray(delivery.deliverables)).toBe(true);
    expect(Array.isArray(delivery.downloads)).toBe(true);

    // /human-review -> HumanReviewProjection
    const reviewRes = await request.get(`${BACKEND_URL}/api/v1/sessions/${sessionId}/human-review`);
    expect(reviewRes.status()).toBe(200);
    const review = await reviewRes.json();
    expect(review.schema_version).toBe('1.0');
    expect(typeof review.pending).toBe('boolean');
    expect(Array.isArray(review.items)).toBe(true);

    // /map-layers -> 200 或 404（交付前 404，交付后 200）
    const layersRes = await request.get(`${BACKEND_URL}/api/v1/sessions/${sessionId}/map-layers`);
    expect([200, 404]).toContain(layersRes.status());
    if (layersRes.status() === 200) {
      const layers = await layersRes.json();
      expect(Array.isArray(layers.layers)).toBe(true);
      expect(typeof layers.snapshot_checksum).toBe('string');
    }

    // /artifacts/{key} -> 200 或 404（未产出 404 为正常等待态）
    const artifactRes = await request.get(`${BACKEND_URL}/api/v1/sessions/${sessionId}/artifacts/l1_snapshot`);
    expect([200, 404]).toContain(artifactRes.status());
  });
});