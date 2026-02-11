# Fix Pause Message and Approval Flow Issues - Implementation Summary

## Root Causes Identified

### Issue 1: Architecture Inconsistency - Triple Triggering
Three independent systems were detecting and responding to the same state changes:
- **TaskController**: Detected state changes via REST polling (layer_completed, pause)
- **useTaskSSE**: Received same state changes via SSE events (layer_completed, pause)
- **ChatPanel**: Maintained its own state (pendingLayerCompletionRef)

**Result**: Same state change triggered multiple times, causing duplicate messages and UI flicker.

### Issue 2: SSE Event Sending Inconsistency
Backend was sending business logic state changes via SSE (layer completion, pause notifications) while the frontend was also polling for these states via REST. This created duplicate event handling.

### Issue 3: TaskController Deduplication Logic Error
Critical bug where pause deduplication keys were manually deleted when status changed from paused to running, causing the same pause event to fire again on the next poll.

### Issue 4: Complex Local State Management
- `messagesRef` with async useEffect updates
- `pendingLayerCompletionRef` with useLayoutEffect interference
- Status bouncing between 'paused' and 'planning'

## Solutions Implemented

### Fix 1: Cleaned Up Backend SSE Events
**File**: `backend/api/planning.py`

**Removed**:
- Layer completion notification events (lines ~459-464)
- Pause notification events (lines ~481-486)

**What remains**:
- Actual `text_delta` events from node execution (typewriter effect)
- `error` events
- `completed` event

**Result**: SSE now only sends streaming text content, not business logic state changes.

### Fix 2: Cleaned Up useTaskSSE Event Handlers
**File**: `frontend/src/hooks/useTaskSSE.ts`

**Removed handlers**:
- `layer_started`
- `layer_completed`
- `pause`
- `stream_paused`
- `resumed`
- `review_request`
- `progress`
- `checkpoint_saved`

**Kept handlers**:
- `text_delta` - streaming text
- `text_chunk` - streaming text chunks
- `thinking_start`, `thinking`, `thinking_end` - thinking states
- `completed`, `complete` - completion events (backup)
- `error` - error events

**Result**: SSE hook now only handles streaming text and errors.

### Fix 3: Fixed TaskController Deduplication Logic
**File**: `frontend/src/controllers/TaskController.tsx` (lines 122-149)

**Changes**:
1. Changed pause key to include session ID: `pause_${taskId}_layer_${layer}`
2. Removed manual key deletion when resuming (was causing re-triggering)
3. Added timeout-based auto-cleanup after 5 minutes to prevent memory leaks
4. Trigger pause callback immediately (removed `setTimeout(..., 0)`)

**Before**:
```typescript
// ❌ WRONG: Deleting dedupe key causes re-triggering
if (!isPaused && wasPaused) {
  const pauseKey = `pause_layer_${prev.currentLayer ?? 1}`;
  triggeredEventsRef.current.delete(pauseKey);  // ← This causes same event to fire again!
}
```

**After**:
```typescript
// ✅ Auto-cleanup after 5 minutes to prevent memory leaks
setTimeout(() => {
  triggeredEventsRef.current.delete(pauseKey);
  console.log(`[TaskController] Cleanup: Removed pause key ${pauseKey} after timeout`);
}, 5 * 60 * 1000);

// ❌ DELETED: Manual pause key reset causing re-triggering bug
// Keys are now only cleaned up by timeout (5 minutes)
```

### Fix 4: Simplified ChatPanel State Management
**File**: `frontend/src/components/chat/ChatPanel.tsx`

#### 4a: Removed messagesRef dependency
- Deleted `messagesRef` and its useEffect synchronization (lines 76-87)
- Removed closure dependency issues

#### 4b: Simplified handlePause
- Use functional state update: `setMessages(prevMessages => ...)`
- No dependency on `messagesRef`
- Same deduplication logic but using functional updates

#### 4c: Simplified handleLayerCompleted
- Removed `flushSync` usage
- Removed `pendingLayerCompletionRef.current = layer` assignment
- Cleaner message creation

#### 4d: Deleted useLayoutEffect
- Removed entire useLayoutEffect block (lines 300-307)
- This was causing status bounce between 'paused' and 'planning'
- Removed unused imports: `flushSync` from 'react-dom', `useLayoutEffect`

#### 4e: Updated approval handlers to clear state
- Added `setPendingReviewMessage(null)` to both approval handlers
- Ensures review mode is properly exited after approval

### Fix 5: Added Status Cleanup in UnifiedPlanningContext
**File**: `frontend/src/contexts/UnifiedPlanningContext.tsx`

**Changes**:
1. Renamed `useState` setter to `setStatusState`
2. Created custom `setStatus` callback with cleanup logic
3. Automatically clears `pendingReviewMessage` when status changes to 'planning' or 'revising'

**Code**:
```typescript
// ✅ Custom setStatus with cleanup logic
const setStatus = useCallback((newStatus: Status) => {
  setStatusState(newStatus);

  // ✅ Clear pending review when status changes to planning/revising
  if (newStatus === 'planning' || newStatus === 'revising') {
    setPendingReviewMessage(null);
  }
}, [setPendingReviewMessage]);
```

## Expected Results

### Network Request Behavior
**Should see**:
```
GET /api/planning/status/{id}  (every 2 seconds) - State polling
POST /api/planning/review/{id}/approve  (on user action) - Approval
GET /api/planning/stream/{id}  (SSE connection) - Streaming text only
```

**SSE events should only be**:
- `text_delta` (streaming text for typewriter effect)
- `error` (immediate error notification)

**Should NOT see**:
- `layer_completed` events via SSE (handled by REST)
- `pause` events via SSE (handled by REST)

### Console Log Behavior
**✅ Correct logs**:
```
[TaskController] 检测到暂停状态 Layer 1 (pause_after_step=true, status=paused)
[ChatPanel] Task paused at Layer 1
[ChatPanel] Updated existing layer_completed message with review state
[ChatPanel] ✅ 已批准，继续执行下一层...
[TaskController] Cleanup: Removed pause key after timeout
```

**❌ Should NOT see**:
```
[useTaskSSE] Received layer_completed event
[useTaskSSE] Received pause event
[ChatPanel] No layer_completed message found for Layer 1
[TaskController] 暂停已解除，恢复执行 Layer 1 (multiple times)
Warning: Encountered two children with the same key
```

### Functional Test Results
1. **Start new planning task** with `step_mode: true`
2. **Wait for Layer 1 to complete**
3. **Verify**: Only ONE layer_completed message appears
4. **Verify**: Review state is added to the same message (not separate)
5. **Click "批准继续" button**
6. **Verify**: Status changes to 'planning' (not bouncing)
7. **Verify**: No review message flickering
8. **Verify**: Execution continues to Layer 2

### Multi-Layer Test Results
1. Complete Layer 1 → approve
2. Complete Layer 2 → approve
3. Complete Layer 3 → approve
4. **Verify**: No duplicate messages for any layer
5. **Verify**: Each layer shows exactly ONE message

### Input Bar Test Results
1. After approval, try typing in input bar
2. **Verify**: NOT in review mode (no orange border)
3. **Verify**: Can type and send messages normally

## Architecture Changes Summary

### Before
```
┌─────────────────────────────────────────────────────────────┐
│ Three Independent State Detection Systems                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐      ┌──────────────┐                   │
│  │ REST Polling │ ───→ │ TaskController│                   │
│  └──────────────┘      └──────┬───────┘                   │
│                                │                            │
│  ┌──────────────┐      ┌──────▼───────┐                   │
│  │ SSE Events   │ ───→ │  useTaskSSE  │                   │
│  │ (duplicate)  │      └──────────────┘                   │
│  └──────────────┘                                            │
│                         │                                     │
│                         ▼                                     │
│                   ┌──────────┐                               │
│                   │ChatPanel │ ← Local state causing bugs    │
│                   └──────────┘                               │
└─────────────────────────────────────────────────────────────┘
```

### After
```
┌─────────────────────────────────────────────────────────────┐
│ Single Source of Truth: REST Polling                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐      ┌──────────────┐                   │
│  │ REST Polling │ ───→ │ TaskController│ ───→ ChatPanel    │
│  │ (Only state) │      │ (Deduplicated)│     (Clean state) │
│  └──────────────┘      └──────────────┘                   │
│                                │                            │
│  ┌──────────────┐              │                            │
│  │ SSE Events   │ ────────────┘ (Typewriter only)         │
│  │ (Text only)  │                                           │
│  └──────────────┘                                           │
└─────────────────────────────────────────────────────────────┘
```

## Files Modified

### Backend (1 file)
| File | Lines | Action |
|------|-------|--------|
| `backend/api/planning.py` | ~459-464, ~481-486 | Remove layer completion and pause SSE events |

### Frontend (4 files)
| File | Lines | Action |
|------|-------|--------|
| `frontend/src/hooks/useTaskSSE.ts` | Event handlers | Remove unused handlers |
| `frontend/src/controllers/TaskController.tsx` | 122-149 | Delete buggy reset logic, add timeout cleanup |
| `frontend/src/components/chat/ChatPanel.tsx` | 76-87, 119-163, 165-241, 300-307, 342-351, 456-480 | Simplify state management, remove refs and effects |
| `frontend/src/contexts/UnifiedPlanningContext.tsx` | setStatus | Add cleanup logic |

## Testing Checklist

- [ ] Start planning task and verify single layer_completed message per layer
- [ ] Verify review state is added to existing message (not duplicate)
- [ ] Click approve and verify status changes to 'planning' without bounce
- [ ] Verify no review message flickering
- [ ] Complete all 3 layers without duplicate messages
- [ ] Verify input bar works normally after approval (no review mode)
- [ ] Check console logs - no duplicate pause/layer completion logs
- [ ] Check network requests - SSE only sends text_delta events
- [ ] Verify no React key warnings in console

## Notes

- The timeout-based cleanup (5 minutes) prevents memory leaks while avoiding the re-triggering bug
- REST polling is now the single source of truth for all business logic state
- SSE is used exclusively for typewriter effect (streaming text)
- Functional state updates in ChatPanel eliminate closure dependency issues
- Status cleanup in UnifiedPlanningContext ensures review mode is properly exited
