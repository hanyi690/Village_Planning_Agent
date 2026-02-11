# TaskController轮询检测和报告显示问题修复总结

## 修复日期
2025年（根据系统日期）

## 问题描述
### 核心问题
移除SSE事件后，TaskController的REST轮询检测没有正确触发layer完成事件，导致：
1. 前端`/api/planning/status/{id}`返回的`layer_X_completed`字段始终为`false`
2. TaskController无法检测到状态变化
3. `handleLayerCompleted`回调从未被触发
4. 报告显示"暂无维度数据"

### 根本原因
1. 后端layer完成状态未正确同步到数据库
2. TaskController缺少调试日志
3. 报告加载时机问题

## 修复方案

### Phase 1: 修复后端layer完成状态同步 ✅

#### 文件：`backend/api/planning.py`

**1. 增强layer完成检测日志（第412-421行）**
```python
if now_completed and not was_completed:
    logger.info(f"[Planning] [{session_id}] ✓ Layer {layer_num} completed detected in graph stream")
```

**2. 确保数据库和内存状态同步更新（第431-456行）**
```python
if USE_DATABASE_PERSISTENCE:
    update_state = {
        f"layer_{layer_num}_completed": True,
        "current_layer": layer_num,
        "status": "paused" if should_pause else "running",
        "pause_after_step": should_pause,
        "updated_at": datetime.now().isoformat()
    }
    # ✅ 同步更新数据库
    update_session_state(session_id, update_state)
    logger.info(f"[Planning] [{session_id}] ✅ Database updated: layer_{layer_num}_completed=True")

# ✅ 同步更新内存状态
_sessions[session_id][f"layer_{layer_num}_completed"] = True
_sessions[session_id]["current_layer"] = layer_num
_sessions[session_id]["status"] = "paused" if should_pause else "running"
_sessions[session_id]["pause_after_step"] = should_pause

logger.info(f"[Planning] [{session_id}] Memory state updated: layer_{layer_num}_completed={now_completed}")
```

**3. 添加layer_report_ready事件（第458-463行）**
```python
events_list.append({
    "type": "layer_report_ready",
    "layer": layer_num,
    "timestamp": datetime.now().isoformat(),
    "message": f"Layer {layer_num} report ready for loading"
})
logger.info(f"[Planning] [{session_id}] Added layer_report_ready event for layer {layer_num}")
```

**4. 增强状态端点日志（第980-1005行）**
```python
@router.get("/api/planning/status/{session_id}", response_model=SessionStatusResponse)
async def get_status(session_id: str):
    # ... 加载数据 ...

    # ✅ 添加调试日志
    layer_1_completed = session.get("layer_1_completed", False)
    layer_2_completed = session.get("layer_2_completed", False)
    layer_3_completed = session.get("layer_3_completed", False)
    status = session.get("status", "pending")
    pause_after_step = session.get("pause_after_step", False)

    logger.debug(f"[Planning API] Status for {session_id}: "
                f"L1={layer_1_completed}, L2={layer_2_completed}, L3={layer_3_completed}, "
                f"status={status}, pause={pause_after_step}")
```

### Phase 2: 增强TaskController调试和检测 ✅

#### 文件：`frontend/src/controllers/TaskController.tsx`

**1. 添加详细的状态轮询日志（第82-95行）**
```typescript
const pollStatus = async () => {
  try {
    const statusData = await planningApi.getStatus(taskId);

    // ✅ 添加轮询结果日志
    console.log(`[TaskController] 📊 Poll result:`, {
      taskId: taskId,
      status: statusData.status,
      layer: statusData.current_layer,
      layer1: statusData.layer_1_completed,
      layer2: statusData.layer_2_completed,
      layer3: statusData.layer_3_completed,
      pause: statusData.pause_after_step
    });
```

**2. 添加状态变化检测日志（第105-114行）**
```typescript
console.log(`[TaskController] 🔍 State change:`, {
  layer1: `${prev.layer1Completed} → ${newState.layer1Completed}`,
  layer2: `${prev.layer2Completed} → ${newState.layer2Completed}`,
  layer3: `${prev.layer3Completed} → ${newState.layer3Completed}`,
  pause: `${prev.pauseAfterStep} → ${newState.pauseAfterStep}`
});
```

**3. 增强layer完成检测日志（第118-145行）**
```typescript
// Layer 1完成检测
if (!prev.layer1Completed && newState.layer1Completed && !triggeredEventsRef.current.has(layer1Key)) {
  console.log(`[TaskController] 🔥🔥🔥 Layer 1 完成！触发回调`);
  callbacksRef.current.onLayerCompleted?.(1);
  triggeredEventsRef.current.add(layer1Key);
} else if (!prev.layer1Completed && newState.layer1Completed && triggeredEventsRef.current.has(layer1Key)) {
  console.log(`[TaskController] Layer 1 完成事件已触发过，跳过`);
}

// Layer 2完成检测（类似）
// Layer 3完成检测（类似）
```

**4. 修复taskId闭包问题（第154-164行）**
```typescript
if (isPaused && !wasPaused) {
  // ✅ 捕获taskId避免闭包中为undefined
  const currentTaskId = taskId;
  const currentLayer = newState.currentLayer ?? 1;

  if (!currentTaskId) {
    console.warn('[TaskController] ❌ 无法触发暂停：taskId为空');
    return currentState;
  }

  const pauseKey = `pause_${currentTaskId}_layer_${currentLayer}`;
  // ... 暂停处理逻辑 ...
}
```

### Phase 3: 添加layer_report_ready事件处理 ✅

#### 文件：`frontend/src/hooks/useTaskSSE.ts`

**1. 更新UseTaskSSECallbacks接口（第18-31行）**
```typescript
export interface UseTaskSSECallbacks {
  // ... 其他回调 ...
  onLayerReportReady?: (layer: number) => void;  // ✅ 新增
  onMaxRetriesReached?: () => void;
}
```

**2. 添加layer_report_ready事件处理（第52-60行）**
```typescript
const createEventHandlers = () => ({
  // ... 其他事件处理 ...

  // ✅ 新增：layer报告就绪事件
  layer_report_ready: (event: PlanningSSEEvent) => {
    const layer = event.data?.layer;
    console.log(`[useTaskSSE] 📋 Layer ${layer} report ready event received`);
    callbacks.onLayerReportReady?.(layer);
    // 这个事件只用于通知，不触发回调（回调由REST轮询触发）
  },
```

### Phase 4: 修复ChatPanel错误处理 ✅

#### 文件：`frontend/src/components/chat/ChatPanel.tsx`

**1. 增强loadLayerReportContent日志（第95-122行）**
```typescript
const loadLayerReportContent = useCallback(async (layer: number): Promise<string | null> => {
  const layerId = getLayerId(layer);
  if (!layerId || !taskId || !projectName) {
    console.warn('[ChatPanel] ❌ Missing required data for layer content load', {
      layer,
      hasLayerId: !!layerId,
      hasTaskId: !!taskId,
      hasProjectName: !!projectName
    });
    return null;
  }

  console.log(`[ChatPanel] 📥 开始加载Layer ${layer}报告...`, { layerId, taskId, projectName });

  try {
    const data = await dataApi.getLayerContent(projectName, layerId, taskId, 'markdown');

    if (data.content && data.content.trim().length > 0) {
      console.log(`[ChatPanel] ✅ Layer ${layer}报告加载成功，长度: ${data.content.length}`);
      return data.content;
    } else {
      console.warn(`[ChatPanel] ⚠️ Layer ${layer}报告内容为空`);
      return null;
    }
  } catch (error) {
    console.error(`[ChatPanel] ❌ Layer ${layer}报告加载失败:`, error);
    return null;
  }
}, [taskId, projectName]);
```

**2. 增强handleLayerCompleted错误处理（第125-183行）**
```typescript
const handleLayerCompleted = useCallback(async (layer: number) => {
  // ✅ 添加调用日志，确认回调被触发
  console.log(`[ChatPanel] 🎯 handleLayerCompleted 被调用！`, {
    layer,
    taskId,
    timestamp: new Date().toISOString()
  });

  logger.chatPanel.info(`Layer ${layer} completed (detected via REST polling)`, { layer }, taskId);

  const result = await loadLayerReportContent(layer);
  const layerId = getLayerId(layer);
  if (!layerId) {
    console.error('[ChatPanel] ❌ Invalid layer number:', layer);
    return;
  }

  // 处理报告内容为空的情况
  if (!result || result.trim().length === 0) {
    console.warn(`[ChatPanel] ⚠️ Layer ${layer}报告内容为空，创建占位消息`);

    addMessage({
      id: `layer-completed-${layer}-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
      ...createBaseMessage('assistant'),
      type: 'layer_completed',
      layer,
      content: `✅ Layer ${layer} 已完成 (报告生成中...)`,
      summary: {
        word_count: 0,
        key_points: [],
        dimension_count: 0,
        dimension_names: [],
      },
      fullReportContent: '',
      dimensionReports: undefined,
      actions: [
        { id: 'refresh', label: '刷新报告', action: 'refresh', variant: 'primary' }
      ],
      needsReview: false,
      reviewState: undefined,
    });
    return;
  }

  // 解析报告
  const { parseLayerReport, getReportStats } = await import('@/lib/layerReportParser');
  const dimensions = parseLayerReport(result);
  const stats = getReportStats(result);

  console.log(`[ChatPanel] ✅ Layer ${layer}报告解析完成:`, {
    dimensions: dimensions.length,
    wordCount: stats?.wordCount
  });

  // 创建消息
  addMessage({
    id: `layer-completed-${layer}-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
    ...createBaseMessage('assistant'),
    type: 'layer_completed',
    layer,
    content: `✅ Layer ${layer} 已完成 (${stats?.wordCount || result.length}字, ${dimensions.length}个维度)`,
    summary: {
      word_count: stats?.wordCount || result.length || 0,
      key_points: [],
      dimension_count: dimensions.length,
      dimension_names: dimensions.map(d => d.name),
    },
    fullReportContent: result,
    dimensionReports: undefined,
    actions: [
      { id: 'open_review', label: '查看详情', action: 'view', variant: 'primary' },
      { id: 'approve_quick', label: '快速批准', action: 'approve', variant: 'success' }
    ],
    needsReview: false,
    reviewState: undefined,
  });
}, [taskId, loadLayerReportContent, addMessage]);
```

## 关键修复点总结

### 1. 后端状态同步（最关键）
- 确保layer完成状态同时更新到数据库和内存
- 添加详细的调试日志追踪状态变化
- 添加`layer_report_ready`事件通知前端报告就绪

### 2. 前端检测增强
- TaskController添加详细的轮询日志
- 状态变化检测有清晰的console输出
- 修复taskId闭包问题，避免undefined错误

### 3. 错误处理改进
- ChatPanel增强报告加载错误处理
- 处理报告内容为空的边界情况
- 每个步骤都有调试日志

### 4. 新增事件支持
- SSE添加`layer_report_ready`事件处理
- 更新接口定义支持新事件回调

## 验证步骤

### 1. 后端验证
```bash
# 查看后端日志
tail -f logs/backend.log | grep -E "Layer.*completed|Database updated"
```

**预期输出：**
```
[Planning] [20260211_XXXXXX] ✓ Layer 1 completed detected in graph stream
[Planning] [20260211_XXXXXX] ✅ Database updated: layer_1_completed=True
[Planning] [20260211_XXXXXX] Memory state updated: layer_1_completed=True
[Planning] [20260211_XXXXXX] Added layer_report_ready event for layer 1
```

### 2. 前端TaskController验证
打开浏览器控制台，应该看到：

**预期日志：**
```
[TaskController] 📊 Poll result: { layer1: true, layer2: false, ... }
[TaskController] 🔍 State change: { layer1: "false → true", ... }
[TaskController] 🔥🔥🔥 Layer 1 完成！触发回调
```

### 3. 前端ChatPanel验证
**预期日志：**
```
[ChatPanel] 🎯 handleLayerCompleted 被调用！
[ChatPanel] 📥 开始加载Layer 1报告...
[ChatPanel] ✅ Layer 1报告加载成功，长度: XXXX
[ChatPanel] ✅ Layer 1报告解析完成: { dimensions: X, wordCount: XXX }
```

### 4. 功能测试
1. 启动新规划任务
2. 等待Layer 1完成
3. **验证**：控制台显示完整的日志链路
4. **验证**：前端显示"Layer 1 已完成"消息
5. **验证**：点击"查看详情"能看到报告内容

## 预期结果

### 问题解决
- ✅ TaskController正确检测到layer完成状态变化
- ✅ `handleLayerCompleted`回调被触发
- ✅ 报告内容成功加载并显示
- ✅ 不再显示"暂无维度数据"

### 调试改进
- ✅ 完整的日志链路，易于诊断问题
- ✅ 每个步骤都有清晰的console输出
- ✅ 状态变化可视化

## 修改的文件列表

### 后端（1个文件）
1. `backend/api/planning.py` - layer完成状态同步、事件添加、日志增强

### 前端（3个文件）
1. `frontend/src/controllers/TaskController.tsx` - 轮询日志、状态检测、闭包修复
2. `frontend/src/hooks/useTaskSSE.ts` - layer_report_ready事件处理
3. `frontend/src/components/chat/ChatPanel.tsx` - 回调日志、错误处理
