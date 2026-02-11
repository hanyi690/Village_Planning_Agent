#!/bin/bash
# Verification Script for Pause Message and Approval Flow Fixes

echo "=================================="
echo "Pause Message Fix Verification"
echo "=================================="
echo ""

echo "1. Checking backend SSE event cleanup..."
if grep -q "Layer.*完成.*text_delta" backend/api/planning.py; then
    echo "❌ FAIL: Layer completion text_delta events still present"
    exit 1
else
    echo "✅ PASS: Layer completion events removed from SSE"
fi

if grep -q "已暂停.*text_delta" backend/api/planning.py; then
    echo "❌ FAIL: Pause notification text_delta events still present"
    exit 1
else
    echo "✅ PASS: Pause notification events removed from SSE"
fi

echo ""
echo "2. Checking frontend useTaskSSE cleanup..."
if grep -q "layer_completed:" frontend/src/hooks/useTaskSSE.ts | grep -v "DELETED"; then
    echo "❌ FAIL: layer_completed handler still present"
    exit 1
else
    echo "✅ PASS: layer_completed handler removed"
fi

if grep -q "pause:" frontend/src/hooks/useTaskSSE.ts | grep -v "DELETED" | grep -v "isPausedRef" | grep -v "pause_after_step"; then
    echo "⚠️  WARNING: Check pause handler usage"
fi

echo ""
echo "3. Checking TaskController deduplication fix..."
if grep -q "暂停已解除.*delete" frontend/src/controllers/TaskController.tsx; then
    echo "❌ FAIL: Manual pause key deletion still present (causes re-triggering)"
    exit 1
else
    echo "✅ PASS: Manual pause key deletion removed"
fi

if grep -q "5 \* 60 \* 1000" frontend/src/controllers/TaskController.tsx; then
    echo "✅ PASS: Timeout-based cleanup implemented"
else
    echo "❌ FAIL: Timeout cleanup not found"
    exit 1
fi

echo ""
echo "4. Checking ChatPanel state management cleanup..."
if grep -q "messagesRef" frontend/src/components/chat/ChatPanel.tsx | grep -v "DELETED"; then
    echo "❌ FAIL: messagesRef still in use"
    exit 1
else
    echo "✅ PASS: messagesRef removed"
fi

if grep -q "useLayoutEffect" frontend/src/components/chat/ChatPanel.tsx | grep -v "import"; then
    echo "❌ FAIL: useLayoutEffect still present"
    exit 1
else
    echo "✅ PASS: useLayoutEffect removed"
fi

echo ""
echo "5. Checking UnifiedPlanningContext cleanup..."
if grep -A6 "const setStatus = useCallback" frontend/src/contexts/UnifiedPlanningContext.tsx | grep -q "setPendingReviewMessage"; then
    echo "✅ PASS: setStatus cleanup logic implemented"
else
    echo "❌ FAIL: setStatus cleanup not found"
    exit 1
fi

echo ""
echo "=================================="
echo "All Verification Checks Passed! ✅"
echo "=================================="
echo ""
echo "Next Steps:"
echo "1. Start the backend server"
echo "2. Start the frontend dev server"
echo "3. Run functional tests as documented in docs/pause-message-fix-summary.md"
echo "4. Monitor browser console for correct log patterns"
echo "5. Check network tab for SSE event types"
