# 前端实现文档 (Frontend Implementation)

> **村庄规划智能体** - Next.js 前端实现详解

## 目录

- [技术栈](#技术栈)
- [极简版 TaskController](#极简版-taskcontroller)
- [状态驱动 UI (State Driven)](#状态驱动-ui-state-driven)
- [数据流管理](#数据流管理)
- [核心组件](#核心组件)
- [类型系统](#类型系统)

---

## 技术栈

### 核心框架
- **Next.js 14** - React 框架 (App Router)
- **TypeScript** - 类型安全开发
- **Tailwind CSS** - 实用优先级 CSS 框架

### 构建模式
- **开发模式**: `npm run dev` - 热模块替换（HMR）
- **生产构建**: `npm run build` - 优化打包

---

## 极简版 TaskController

### 核心特性

**文件**: `frontend/src/controllers/TaskController.tsx`

**职责**: 纯数据搬运,不做任何业务逻辑判断

**删除内容**:
- ❌ 所有 Ref 和去重机制
- ❌ 回调函数
- ❌ 复杂的 `if` 判断逻辑

**保留内容**:
- ✅ `pollTimerRef` - 仅用于清除轮询定时器
- ✅ `sseConnectionRef` - SSE 连接管理
- ✅ 简单的轮询逻辑: 获取状态 -> 同步到 Context -> 检查是否停止

### 实现代码

```typescript
// 纯数据搬运逻辑
const fetchStatus = async () => {
  try {
    // 1. 获取后端全量状态
    const status = await planningApi.getStatus(sessionId);
    
    // 2. 直接同步到 Context (核心改动)
    // 不要在 Controller 里判断 "是否刚刚暂停" 或 "是否刚刚完成"
    // 让 React 的渲染循环去响应数据的变化
    actions.syncBackendState(status);

    // 3. 检查是否需要停止轮询
    // 注意：暂停状态下(pause_after_step=true) 仍需轮询，因为我们需要检测用户是否点击了"批准"
    // 只有当 execution_complete=true 时才彻底停止
    if (status.execution_complete) {
      return true; // 信号：停止轮询
    }
    return false; // 信号：继续

  } catch (error) {
    console.error("Status poll failed:", error);
    return false; // 出错也继续试
  }
};
```

### 轮询逻辑

```typescript
useEffect(() => {
  if (!isPollingEnabled || !sessionId) {
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    return;
  }

  const pollLoop = async () => {
    const shouldStop = await fetchStatus();
    
    if (!shouldStop) {
      pollTimerRef.current = setTimeout(pollLoop, 2000); // 2秒轮询一次
    }
  };

  // 立即执行一次，然后开始循环
  pollLoop();

  return () => {
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
  };
}, [sessionId, isPollingEnabled, fetchStatus]);
```

---

## 状态驱动 UI (State Driven)

### UnifiedPlanningContext 扩展

**文件**: `frontend/src/contexts/UnifiedPlanningContext.tsx`

**新增状态**:
```typescript
interface PlanningState {
  // ✅ 新增：简化后的审查状态（单一真实源，来自后端）
  isPaused: boolean;
  pendingReviewLayer: number | null;
  
  // ✅ 新增：层级完成状态
  completedLayers: {
    1: boolean;
    2: boolean;
    3: boolean;
  };
  
  // ... 其他状态
}
```

**新增 Action**:
```typescript
// Action 定义
syncBackendState: (backendData: SessionStatusResponse) => void;

// 实现
const syncBackendState = useCallback((backendData: SessionStatusResponse) => {
  setState(prev => ({
    ...prev,
    // 直接覆盖核心状态
    isPaused: backendData.pause_after_step || backendData.status === 'paused',
    pendingReviewLayer: backendData.previous_layer ?? backendData.pending_review_layer ?? null,
    currentLayer: backendData.current_layer ?? null,
    status: backendData.status,
    
    // 层级完成状态
    completedLayers: {
       1: backendData.layer_1_completed,
       2: backendData.layer_2_completed,
       3: backendData.layer_3_completed,
    },
    
    // 其他状态
    executionComplete: backendData.execution_complete,
    lastCheckpointId: backendData.last_checkpoint_id ?? null,
  }));
}, []);
```

### ChatPanel 条件渲染

**文件**: `frontend/src/components/chat/ChatPanel.tsx`

**新增内容**:
```typescript
// 直接从 Context 读取状态
const { isPaused, pendingReviewLayer, completedLayers } = useUnifiedPlanningContext();

// 条件渲染审查面板 (状态驱动)
{isPaused && pendingReviewLayer && (
  <div className="border-t border-gray-200 bg-white">
    <ReviewPanel
      layer={pendingReviewLayer}
      onApprove={async () => {
        await approve();
        addMessage(createSystemMessage(`✅ 已批准，继续执行下一层...`));
        setStatus('planning');
      }}
      onReject={async (feedback) => {
        await reject(feedback);
        addMessage(createSystemMessage('🔄 正在根据反馈修复规划内容...'));
        setStatus('revising');
      }}
      onRollback={async (checkpointId) => {
        await rollback(checkpointId);
        addMessage(createSystemMessage(`↩️ 已回退到检查点: ${checkpointId}`));
      }}
      isSubmitting={status === 'reviewing'}
    />
  </div>
)}
```

---

## 数据流管理

### UnifiedPlanningContext

**文件**: `frontend/src/contexts/UnifiedPlanningContext.tsx`

**职责**: 单一真实源,管理所有规划状态

**状态结构**:
```typescript
interface PlanningState {
  // 任务信息
  taskId: string | null;
  sessionId: string | null;
  projectName: string | null;

  // 消息（UI 状态通过 messages 数组表示）
  messages: Message[];

  // ✅ 新增：简化后的审查状态（单一真实源，来自后端）
  isPaused: boolean;
  pendingReviewLayer: number | null;
  
  // ✅ 新增：层级完成状态
  completedLayers: {
    1: boolean;
    2: boolean;
    3: boolean;
  };

  // 状态
  status: TaskStatus;
  currentLayer: number | null;
  currentCheckpoint: Checkpoint | null;

  // 错误
  error: string | null;
}
```

### TaskController 集成

**文件**: `frontend/src/controllers/TaskController.tsx`

**职责**: 无头状态管理,协调 REST 轮询和 SSE 回调

**关键特性**:
- REST 轮询每 2 秒获取状态（从 AsyncSqliteSaver 读取）
- SSE 事件处理（维度级流式）
- 纯数据搬运: 获取状态 -> 同步到 Context
- 无任何业务逻辑判断

**数据流**:
```
TaskController.fetchStatus()
  ↓
GET /api/planning/status/{session_id}
  ↓
AsyncSqliteSaver.get_state()
  ↓
返回状态 (pauseAfterStep, layer_X_completed, previousLayer, pendingReviewLayer, etc.)
  ↓
actions.syncBackendState(status)
  ↓
直接更新 Context 状态 (不做任何判断)
  ↓
UI 重新渲染 (条件渲染 ReviewPanel)
```

---

## 核心组件

### ChatPanel

**文件**: `frontend/src/components/chat/ChatPanel.tsx`

**职责**: 主聊天界面,管理消息显示和交互

**核心功能**:
- 消息列表渲染（流式文本）
- 条件渲染审查面板（状态驱动）
- 状态指示器（层进度、暂停状态）
- 错误提示

### ReviewPanel

**文件**: `frontend/src/components/chat/ReviewPanel.tsx`

**职责**: 极简 UI 审查面板

**核心功能**:
- 显示层级信息
- 批准/驳回/回退按钮
- 加载状态防重复点击

**UI 结构**:
```
┌─────────────────────────────────────┐
│ 📋 第 {layer} 层规划已完成           │
│                                     │
│   [查看详情]  [驳回]  [批准继续]     │
│                                     │
│ 📍 当前状态: 等待您的审查            │
└─────────────────────────────────────┘
```

### UnifiedPlanningContext

**文件**: `frontend/src/contexts/UnifiedPlanningContext.tsx`

**职责**: 全局状态管理

**核心状态**:
```typescript
const state: PlanningState = {
  sessionId: string | null;
  projectName: string | null;
  status: 'idle' | 'running' | 'paused' | 'reviewing' | 'completed' | 'failed';
  currentLayer: number | null;
  messages: Message[];
  
  // ✅ 新增
  isPaused: boolean;
  pendingReviewLayer: number | null;
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  
  error: string | null;
};
```

---

## 类型系统

### 核心类型定义

**文件**: `frontend/src/types/index.ts`

```typescript
// 任务状态
type TaskStatus =
  | 'idle'
  | 'running'
  | 'paused'
  | 'reviewing'
  | 'revising'
  | 'completed'
  | 'failed';

// 消息类型
type MessageRole = 'user' | 'assistant' | 'system' | 'review';

// 检查点类型
interface Checkpoint {
  checkpoint_id: string;
  description: string;
  timestamp: string;
  layer: number;
}

// TaskState
interface TaskState {
  status: TaskStatus;
  currentLayer: number | null;
  previousLayer: number | null;      // 上一个完成的层级
  pendingReviewLayer: number | null; // 待审查的层级
  layer1Completed: boolean;
  layer2Completed: boolean;
  layer3Completed: boolean;
  pauseAfterStep: boolean;
  waitingForReview: boolean;
  lastCheckpointId: string | null;
  executionError: string | null;
  executionComplete: boolean;
  progress: number | null;
}
```

### 状态响应类型

```typescript
// SessionStatusResponse
interface SessionStatusResponse {
  session_id: string;
  status: string;
  current_layer: number;
  previous_layer: number | null;      // 上一个完成的层级
  pending_review_layer: number | null; // 待审查的层级
  layer_1_completed: boolean;
  layer_2_completed: boolean;
  layer_3_completed: boolean;
  pause_after_step: boolean;
  waiting_for_review: boolean;
  execution_complete: boolean;
  progress: number | null;
}

// SSE 事件类型
interface DimensionDeltaEvent {
  dimension_key: string;
  dimension_name: string;
  layer: number;
  chunk: string;
  accumulated: string;
}

interface DimensionCompleteEvent {
  dimension_key: string;
  dimension_name: string;
  layer: number;
  full_content: string;
}
```

---

## 数据流总结

### 完整数据流

```
用户操作
  ↓
UnifiedPlanningContext.startPlanning()
  ↓
POST /api/planning/start
  ↓
TaskController (REST轮询每2秒) + useTaskSSE (SSE流式)
  ↓
├─ REST: /api/planning/status (从 AsyncSqliteSaver 读取状态)
│  ├─ pauseAfterStep (暂停状态)
│  ├─ layer_X_completed (层级完成)
│  ├─ previousLayer (上一个完成的层级)
│  ├─ pendingReviewLayer (待审查的层级)
│  └─ executionComplete (执行完成)
├─ SSE: /api/planning/stream (dimension_delta, dimension_complete)
└─ TaskController.syncBackendState()
   ↓
   直接更新 Context 状态 (不做任何判断)
   ↓
   UI 重新渲染 (条件渲染 ReviewPanel)
```

### 暂停/恢复流程

```
步进模式 + 层级完成
  ↓
PauseManagerNode 设置 pause_after_step=True
  ↓
前端 REST 轮询检测到 pauseAfterStep=true
  ↓
TaskController.syncBackendState()
  ↓
Context.isPaused = true, Context.pendingReviewLayer = 1
  ↓
条件渲染: {isPaused && <ReviewPanel layer={pendingReviewLayer} />}
  ↓
用户批准 → POST /api/planning/review/{id}?action=approve
  ↓
后端清除 pause 标志 → 恢复执行
  ↓
前端 REST 轮询检测到 pauseAfterStep=false
  ↓
Context.isPaused = false
  ↓
ReviewPanel 自动消失
  ↓
继续执行
```

### 状态同步流程

```
AsyncSqliteSaver (后端)
  ↓
GET /api/planning/status/{session_id}
  ↓
TaskController.fetchStatus()
  ↓
actions.syncBackendState(status)
  ↓
直接更新 Context 状态 (不做任何判断)
  ↓
UI 重新渲染
```

### 流式文本流程

```
LangGraph 节点执行
  ↓
维度内容生成
  ↓
SSE: dimension_delta 事件
  ↓
useTaskSSE.onDimensionDelta()
  ↓
UI 实时显示
```

---

## 性能优化

### 1. 极简版 TaskController

**技术**: 纯数据搬运,不做任何业务逻辑判断

**效果**:
- 代码量减少约 60%
- 无复杂的状态判断和去重机制
- 幂等性保证

### 2. 状态驱动 UI

**技术**: 条件渲染 `{isPaused && <ReviewPanel ... />}`

**效果**:
- 无重复渲染风险
- React 自动优化
- 状态一致性保证

### 3. SSE/REST 解耦

**技术**: REST 轮询 + SSE 流式

**效果**:
- 无事件丢失风险
- 无需复杂去重逻辑
- 状态一致性保证