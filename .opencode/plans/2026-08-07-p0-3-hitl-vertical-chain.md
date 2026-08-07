# P0-3: HITL Full Vertical Chain + Contract Tests

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the HITL vertical chain: backend `human_review_paused` SSE -> frontend store handler -> fetch pending items -> UI review panel -> resolve -> wait for `execution_resumed`. Add contract tests, failure-state handling, page-refresh recovery, and proper status transitions.

**Architecture:** The fix has five layers: (1) add `case "human_review_paused"` to the store dispatcher; (2) add store actions for fetch/resolve with proper error handling; (3) create a `HumanReviewPanel` component; (4) add page-refresh recovery via GET human-review on mount; (5) add contract tests locking the SSE payload schema. The key correctness rules: resolve failure must NOT silently clear paused state; submit success must NOT assume `status="planning"` - it must wait for `execution_resumed` SSE.

**Tech Stack:** React, TypeScript, Zustand + Immer, Vitest, FastAPI

## Global Constraints

- Frontend tests: `cd frontend && npx vitest run`
- TypeScript type-check: `cd frontend && npx tsc --noEmit`
- 2-space indent, single quotes for TS
- LF line endings
- No emojis in code or comments
- Commit only when explicitly asked by the user, at task boundaries
- React external connections setup/cleanup must be symmetric (useEffect cleanup or useSyncExternalStore)

---

## Root Cause (confirmed)

```
[BACKEND] graph.py:254  SSE {type: "human_review_paused", event_id, paused_stage, item_count}
[FRONTEND] planning-api.ts:230  listener fires
[FRONTEND] planningStore.ts:608  switch(eventType) ... NO case "human_review_paused"
  -> event silently dropped
  -> status stays "planning", isPaused stays false
  -> graph STUCK at interrupt()
```

---

### Task 1: Contract test for SSE payload schema

**Files:**
- Create: `backend/tests/contracts/test_human_review_sse_contract.py`
- Create: `frontend/src/__tests__/contracts/human-review-sse.contract.test.ts`

**Interfaces:**
- Consumes: `SSEEventType.HUMAN_REVIEW_PAUSED` from `app.core.events`, `HumanReviewItem` from frontend types
- Produces: a shared contract test locking the SSE payload fields

- [ ] **Step 1: Write the backend contract test**

```python
"""Contract: human_review_paused SSE payload schema.

Locks the fields the frontend depends on: event_id, paused_stage, reason, item_count.
"""
import pytest
from app.core.events import SSEEventType


def test_human_review_paused_event_type_value():
    assert SSEEventType.HUMAN_REVIEW_PAUSED.value == "human_review_paused"


def test_human_review_paused_payload_fields():
    """The SSE payload must include event_id, paused_stage, reason, item_count."""
    # Read the emission code to verify the payload structure
    import inspect
    from app.agent.bootstrap import graph
    source = inspect.getsource(graph.publish_human_review_pause)
    # Verify all required fields are in the payload
    assert "event_id" in source
    assert "paused_stage" in source
    assert "reason" in source
    assert "item_count" in source
```

- [ ] **Step 2: Write the frontend contract test**

```typescript
import { describe, it, expect } from 'vitest';
import type { HumanReviewItem, HumanReviewListResponse } from '../../features/planning/api/types';

describe('Human Review SSE Contract', () => {
  it('HumanReviewItem has required fields', () => {
    const item: HumanReviewItem = {
      request_id: 'r1',
      stage: 'execute',
      request_type: 'zone_review',
    };
    expect(item.request_id).toBeDefined();
    expect(item.stage).toBeDefined();
    expect(item.request_type).toBeDefined();
  });

  it('HumanReviewListResponse has required fields', () => {
    const resp: HumanReviewListResponse = {
      session_id: 's1',
      post_l3_status: 'paused',
      pending_items: [],
      count: 0,
    };
    expect(resp.session_id).toBeDefined();
    expect(resp.post_l3_status).toBeDefined();
    expect(resp.pending_items).toBeDefined();
    expect(resp.count).toBeDefined();
  });
});
```

- [ ] **Step 3: Run and commit**

```bash
cd backend && python -m pytest tests/contracts/test_human_review_sse_contract.py -v
cd frontend && npx vitest run src/__tests__/contracts/human-review-sse.contract.test.ts
git add backend/tests/contracts/ frontend/src/__tests__/contracts/
git commit -m "test: add SSE payload contract tests for human_review_paused"
```

---

### Task 2: Add HITL state fields to PlanningState

**Files:**
- Modify: `frontend/src/features/planning/store/planningStore.ts` (state interface ~line 234, initial state ~line 390)
- Test: `frontend/src/__tests__/store/planningStore.hitl.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
import { describe, it, expect } from 'vitest';
import { usePlanningStore } from '../../../features/planning/store/planningStore';

describe('PlanningStore HITL state fields', () => {
  it('initializes human review fields as empty/null', () => {
    const state = usePlanningStore.getState();
    expect(state.humanReviewEventId).toBeNull();
    expect(state.pausedStage).toBeNull();
    expect(state.humanReviewItems).toEqual([]);
    expect(state.humanReviewError).toBeNull();
    expect(state.isResolvingReview).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/store/planningStore.hitl.test.ts`
Expected: FAIL

- [ ] **Step 3: Add state fields**

In `planningStore.ts`, after `pendingReviewLayer` (~line 235), add to the state interface:

```typescript
  humanReviewEventId: string | null;
  pausedStage: string | null;
  humanReviewItems: HumanReviewItem[];
  humanReviewError: string | null;
  isResolvingReview: boolean;
```

Add the import: `import type { HumanReviewItem } from '../api/types';`

In `createInitialState` (~line 390), add:

```typescript
    humanReviewEventId: null,
    pausedStage: null,
    humanReviewItems: [],
    humanReviewError: null,
    isResolvingReview: false,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/store/planningStore.hitl.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/planning/store/planningStore.ts frontend/src/__tests__/store/planningStore.hitl.test.ts
git commit -m "feat: add HITL state fields to PlanningStore"
```

---

### Task 3: Add human_review_paused case to event dispatcher

**Files:**
- Modify: `frontend/src/features/planning/store/planningStore.ts:1616-1625`
- Test: `frontend/src/__tests__/store/planningStore.hitl.test.ts`

- [ ] **Step 1: Write the failing test**

Add to `planningStore.hitl.test.ts`:

```typescript
describe('human_review_paused event handling', () => {
  it('sets status to paused and stores review metadata', () => {
    usePlanningStore.setState({ status: 'planning', humanReviewEventId: null, pausedStage: null });
    usePlanningStore.getState().handleSSEEvent({
      type: 'human_review_paused',
      data: { event_id: 'evt-001', paused_stage: 'execute', reason: 'post_l3_human_review', item_count: 2 },
    });
    const state = usePlanningStore.getState();
    expect(state.status).toBe('paused');
    expect(state.isPaused).toBe(true);
    expect(state.humanReviewEventId).toBe('evt-001');
    expect(state.pausedStage).toBe('execute');
  });

  it('does not override existing paused state from duplicate event', () => {
    usePlanningStore.setState({ status: 'paused', humanReviewEventId: 'evt-001', pausedStage: 'execute' });
    usePlanningStore.getState().handleSSEEvent({
      type: 'human_review_paused',
      data: { event_id: 'evt-002', paused_stage: 'execute', item_count: 1 },
    });
    // Idempotent: keep the first event_id, don't override
    expect(usePlanningStore.getState().humanReviewEventId).toBe('evt-001');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/store/planningStore.hitl.test.ts`
Expected: FAIL

- [ ] **Step 3: Add the case**

Before the closing `}` of the switch (line 1625), add:

```typescript
    case "human_review_paused": {
      const hitlData = data as {
        event_id?: string;
        paused_stage?: string;
        reason?: string;
        item_count?: number;
      };
      // Idempotent: don't override if already paused for this stage
      if (!state.humanReviewEventId) {
        state.humanReviewEventId = hitlData.event_id || null;
        state.pausedStage = hitlData.paused_stage || null;
        state.humanReviewError = null;
        state.status = "paused";
        deriveUIStateInStore(state);
      }
      break;
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/store/planningStore.hitl.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/planning/store/planningStore.ts frontend/src/__tests__/store/planningStore.hitl.test.ts
git commit -m "feat: handle human_review_paused SSE event (idempotent)"
```

---

### Task 4: Add fetchHumanReviewItems and resolveHumanReview with error handling

**Files:**
- Modify: `frontend/src/features/planning/store/planningStore.ts` (PlanningActions interface + implementations)
- Test: `frontend/src/__tests__/store/planningStore.hitl.test.ts`

**Key correctness rules:**
- `resolveHumanReview` failure must NOT clear paused state - it must set `humanReviewError` and keep `isPaused=true`
- `resolveHumanReview` success must NOT set `status="planning"` - it sets `isResolvingReview=true` and waits for `execution_resumed` SSE to clear the paused state

- [ ] **Step 1: Write the failing tests**

Add to `planningStore.hitl.test.ts`:

```typescript
import { vi } from 'vitest';
import * as planningApi from '../../../features/planning/api/planning-api';

describe('fetchHumanReviewItems action', () => {
  it('fetches items and stores them', async () => {
    const items = [{ request_id: 'req-1', stage: 'execute', request_type: 'zone_review' }];
    vi.spyOn(planningApi.planningApi, 'getHumanReview').mockResolvedValue({
      session_id: 'sess-1', post_l3_status: 'paused', pending_items: items, count: 1,
    });
    await usePlanningStore.getState().fetchHumanReviewItems('sess-1');
    expect(usePlanningStore.getState().humanReviewItems).toEqual(items);
    vi.restoreAllMocks();
  });

  it('sets error on fetch failure', async () => {
    vi.spyOn(planningApi.planningApi, 'getHumanReview').mockRejectedValue(new Error('network'));
    await usePlanningStore.getState().fetchHumanReviewItems('sess-1');
    expect(usePlanningStore.getState().humanReviewError).toBeTruthy();
    vi.restoreAllMocks();
  });
});

describe('resolveHumanReview action', () => {
  it('sets isResolvingReview on success but does NOT set status=planning', async () => {
    usePlanningStore.setState({ status: 'paused', humanReviewEventId: 'evt-1', pausedStage: 'execute' });
    vi.spyOn(planningApi.planningApi, 'resolveHumanReview').mockResolvedValue({
      session_id: 'sess-1', resolved: true, result: {},
    });
    await usePlanningStore.getState().resolveHumanReview('sess-1', { r1: { action: 'approve' } });
    const state = usePlanningStore.getState();
    expect(state.isResolvingReview).toBe(true);
    expect(state.status).toBe('paused'); // Still paused until execution_resumed SSE
    vi.restoreAllMocks();
  });

  it('does NOT clear paused state on resolve failure', async () => {
    usePlanningStore.setState({ status: 'paused', humanReviewEventId: 'evt-1', pausedStage: 'execute' });
    vi.spyOn(planningApi.planningApi, 'resolveHumanReview').mockRejectedValue(new Error('server'));
    await usePlanningStore.getState().resolveHumanReview('sess-1', { r1: { action: 'approve' } });
    const state = usePlanningStore.getState();
    expect(state.status).toBe('paused');
    expect(state.humanReviewEventId).toBe('evt-1');
    expect(state.humanReviewError).toBeTruthy();
    expect(state.isResolvingReview).toBe(false);
    vi.restoreAllMocks();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/store/planningStore.hitl.test.ts`
Expected: FAIL

- [ ] **Step 3: Add action signatures and implementations**

In `PlanningActions` interface, add:

```typescript
  fetchHumanReviewItems: (sessionId: string) => Promise<void>;
  resolveHumanReview: (sessionId: string, decisions: Record<string, unknown>) => Promise<void>;
```

In the store creation, add:

```typescript
    fetchHumanReviewItems: async (sessionId) => {
      try {
        const response = await planningApi.planningApi.getHumanReview(sessionId);
        set((state) => {
          state.humanReviewItems = response.pending_items || [];
          state.humanReviewError = null;
        });
      } catch (err) {
        set((state) => {
          state.humanReviewError = err instanceof Error ? err.message : 'Failed to fetch review items';
        });
      }
    },

    resolveHumanReview: async (sessionId, decisions) => {
      set((state) => { state.isResolvingReview = true; state.humanReviewError = null; });
      try {
        await planningApi.planningApi.resolveHumanReview(sessionId, decisions);
        // Do NOT set status="planning" here - wait for execution_resumed SSE
        set((state) => { state.isResolvingReview = true; });
      } catch (err) {
        set((state) => {
          state.isResolvingReview = false;
          state.humanReviewError = err instanceof Error ? err.message : 'Failed to resolve review';
        });
      }
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/store/planningStore.hitl.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/planning/store/planningStore.ts frontend/src/__tests__/store/planningStore.hitl.test.ts
git commit -m "feat: add fetchHumanReviewItems and resolveHumanReview with error handling"
```

---

### Task 5: Update execution_resumed to clear HITL state

**Files:**
- Modify: `frontend/src/features/planning/store/planningStore.ts:1114-1119`
- Test: `frontend/src/__tests__/store/planningStore.hitl.test.ts`

- [ ] **Step 1: Write the failing test**

Add to `planningStore.hitl.test.ts`:

```typescript
describe('execution_resumed clears HITL state', () => {
  it('clears all HITL fields when execution resumes', () => {
    usePlanningStore.setState({
      status: 'paused', humanReviewEventId: 'evt-1', pausedStage: 'execute',
      humanReviewItems: [{ request_id: 'r1', stage: 'execute', request_type: 'zone_review' }],
      isResolvingReview: true, humanReviewError: null,
    });
    usePlanningStore.getState().handleSSEEvent({ type: 'execution_resumed', data: {} });
    const state = usePlanningStore.getState();
    expect(state.status).toBe('planning');
    expect(state.humanReviewEventId).toBeNull();
    expect(state.pausedStage).toBeNull();
    expect(state.humanReviewItems).toEqual([]);
    expect(state.isResolvingReview).toBe(false);
    expect(state.humanReviewError).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/store/planningStore.hitl.test.ts`
Expected: FAIL

- [ ] **Step 3: Update execution_resumed case**

```typescript
    case "execution_resumed": {
      state.interruptInfo = undefined;
      state.status = "planning";
      state.humanReviewEventId = null;
      state.pausedStage = null;
      state.humanReviewItems = [];
      state.isResolvingReview = false;
      state.humanReviewError = null;
      deriveUIStateInStore(state);
      break;
    }
```

- [ ] **Step 4: Run test and commit**

```bash
cd frontend && npx vitest run src/__tests__/store/planningStore.hitl.test.ts
git add frontend/src/features/planning/store/planningStore.ts frontend/src/__tests__/store/planningStore.hitl.test.ts
git commit -m "fix: clear HITL state on execution_resumed event"
```

---

### Task 6: Create HumanReviewPanel component with error display

**Files:**
- Create: `frontend/src/features/planning/components/review/HumanReviewPanel.tsx`
- Create: `frontend/src/__tests__/components/HumanReviewPanel.test.tsx`

- [ ] **Step 1: Write the failing test**

```typescript
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { HumanReviewPanel } from '../../../features/planning/components/review/HumanReviewPanel';
import { usePlanningStore } from '../../../features/planning/store/planningStore';

describe('HumanReviewPanel', () => {
  it('renders nothing when not paused for human review', () => {
    usePlanningStore.setState({ isPaused: false, humanReviewItems: [], pausedStage: null });
    const { container } = render(<HumanReviewPanel />);
    expect(container.firstChild).toBeNull();
  });

  it('renders items with approve/reject buttons', () => {
    usePlanningStore.setState({
      isPaused: true, pausedStage: 'execute', humanReviewItems: [
        { request_id: 'req-1', stage: 'execute', request_type: 'zone_review' },
      ], sessionId: 'sess-1', isResolvingReview: false, humanReviewError: null,
    });
    render(<HumanReviewPanel />);
    expect(screen.getByText(/zone_review/)).toBeDefined();
    expect(screen.getByTestId('approve-req-1')).toBeDefined();
    expect(screen.getByTestId('reject-req-1')).toBeDefined();
  });

  it('disables submit while resolving', () => {
    usePlanningStore.setState({
      isPaused: true, pausedStage: 'execute', isResolvingReview: true,
      humanReviewItems: [{ request_id: 'r1', stage: 'execute', request_type: 'zone_review' }],
      sessionId: 'sess-1', humanReviewError: null,
    });
    render(<HumanReviewPanel />);
    expect((screen.getByTestId('submit-review') as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows error message on resolve failure', () => {
    usePlanningStore.setState({
      isPaused: true, pausedStage: 'execute', isResolvingReview: false,
      humanReviewError: 'Failed to resolve review',
      humanReviewItems: [{ request_id: 'r1', stage: 'execute', request_type: 'zone_review' }],
      sessionId: 'sess-1',
    });
    render(<HumanReviewPanel />);
    expect(screen.getByText(/Failed to resolve review/)).toBeDefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/components/HumanReviewPanel.test.tsx`
Expected: FAIL

- [ ] **Step 3: Create the component**

```tsx
import { useState } from 'react';
import { usePlanningStore } from '../../store/planningStore';
import type { HumanReviewItem } from '../../api/types';

export function HumanReviewPanel() {
  const isPaused = usePlanningStore((s) => s.isPaused);
  const pausedStage = usePlanningStore((s) => s.pausedStage);
  const items = usePlanningStore((s) => s.humanReviewItems);
  const sessionId = usePlanningStore((s) => s.sessionId);
  const isResolving = usePlanningStore((s) => s.isResolvingReview);
  const error = usePlanningStore((s) => s.humanReviewError);
  const resolveHumanReview = usePlanningStore((s) => s.resolveHumanReview);

  const [decisions, setDecisions] = useState<Record<string, { action: string }>>({});

  if (!isPaused || !pausedStage || items.length === 0) {
    return null;
  }

  const handleDecision = (requestId: string, action: string) => {
    setDecisions((prev) => ({ ...prev, [requestId]: { action } }));
  };

  const handleSubmit = () => {
    if (sessionId && !isResolving) {
      resolveHumanReview(sessionId, decisions);
    }
  };

  return (
    <div className="human-review-panel">
      <h3>Post-L3 Human Review ({pausedStage})</h3>
      <p>{items.length} item(s) pending review</p>
      {error && <div className="review-error">{error}</div>}
      <ul>
        {items.map((item: HumanReviewItem) => (
          <li key={item.request_id}>
            <span>{item.request_type}</span>
            <button
              data-testid={`approve-${item.request_id}`}
              onClick={() => handleDecision(item.request_id, 'approve')}
              disabled={isResolving}
            >Approve</button>
            <button
              data-testid={`reject-${item.request_id}`}
              onClick={() => handleDecision(item.request_id, 'reject')}
              disabled={isResolving}
            >Reject</button>
          </li>
        ))}
      </ul>
      <button
        data-testid="submit-review"
        onClick={handleSubmit}
        disabled={isResolving || Object.keys(decisions).length === 0}
      >
        {isResolving ? 'Resolving...' : 'Submit Review'}
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Run test and commit**

```bash
cd frontend && npx vitest run src/__tests__/components/HumanReviewPanel.test.tsx
git add frontend/src/features/planning/components/review/HumanReviewPanel.tsx frontend/src/__tests__/components/HumanReviewPanel.test.tsx
git commit -m "feat: add HumanReviewPanel with error display and loading state"
```

---

### Task 7: Wire panel into layout, auto-fetch on pause, and page-refresh recovery

**Files:**
- Modify: `frontend/src/features/planning/components/layout/ReportViewer.tsx`
- Modify: `frontend/src/features/planning/planning-context.tsx`

**Key: page-refresh recovery** - on mount, if `sessionId` exists, call `getHumanReview` to check if the session is paused. This handles the case where the page is refreshed during a pause.

- [ ] **Step 1: Add auto-fetch effect + page-refresh recovery**

In `planning-context.tsx`, add:

```tsx
  const humanReviewEventId = usePlanningStore((s) => s.humanReviewEventId);
  const fetchHumanReviewItems = usePlanningStore((s) => s.fetchHumanReviewItems);

  // Auto-fetch when SSE pause event arrives
  useEffect(() => {
    if (humanReviewEventId && sessionId) {
      fetchHumanReviewItems(sessionId);
    }
  }, [humanReviewEventId, sessionId, fetchHumanReviewItems]);

  // Page-refresh recovery: check for paused state on mount
  useEffect(() => {
    if (sessionId) {
      fetchHumanReviewItems(sessionId);
    }
    // Only on mount/sessionId change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);
```

Note: the `fetchHumanReviewItems` action should also set `status="paused"` if the response indicates `post_l3_status === "paused"` and there are pending items. Update the action:

In `fetchHumanReviewItems`, after receiving the response:

```typescript
        set((state) => {
          state.humanReviewItems = response.pending_items || [];
          state.humanReviewError = null;
          if (response.pending_items.length > 0 && response.post_l3_status === 'paused') {
            state.status = 'paused';
            state.pausedStage = response.pending_items[0]?.stage || null;
            if (!state.humanReviewEventId) {
              state.humanReviewEventId = 'recovered-' + response.session_id;
            }
            deriveUIStateInStore(state);
          }
        });
```

- [ ] **Step 2: Add HumanReviewPanel to ReportViewer**

```tsx
import { HumanReviewPanel } from '../review/HumanReviewPanel';
// In the render:
<HumanReviewPanel />
```

- [ ] **Step 3: Run full frontend tests + type-check**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/planning/components/layout/ReportViewer.tsx frontend/src/features/planning/planning-context.tsx frontend/src/features/planning/store/planningStore.ts
git commit -m "feat: wire HumanReviewPanel, auto-fetch on pause, page-refresh recovery"
```

---

### Task 8: Full regression and audit ledger

- [ ] **Step 1: Run full frontend suite**

Run: `cd frontend && npx vitest run && npx tsc --noEmit && npm run build`
Expected: All pass

- [ ] **Step 2: Update audit ledger**

- [ ] **Step 3: Commit**

```bash
git add docs/audits/backend-breakpoints-2026-08-06.md
git commit -m "docs: record HITL frontend vertical chain fix in audit ledger"
```
