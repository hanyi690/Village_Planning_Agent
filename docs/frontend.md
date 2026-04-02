# 前端实现文档

> Next.js 14 前端架构 - 单一状态源、后端驱动

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Page Layer (App Router)                         │
│                        app/page.tsx (首页)                           │
│              ⚠️ 已删除：app/village/[taskId]/page.tsx (冗余)         │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Context Layer                                   │
│  UnifiedPlanningContext (全局状态) ← TaskController (状态同步)       │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Component Layer                                   │
│  Layout: UnifiedLayout, Header, HistoryPanel, KnowledgePanel        │
│  Chat: ChatPanel, MessageList, ReviewPanel, LayerReportMessage      │
│  Form: VillageInputForm                                              │
│  Layer: LayerSidebar (首页渲染)                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## 页面架构说明

### 首页 (`app/page.tsx`) - 唯一用户交互页面

**功能**：
- 入口页面，用于创建新任务或从历史面板加载会话
- 通过 `HistoryPanel` 加载历史会话时，**不跳转路由**，直接设置 Context 中的 `taskId`
- 通过 `taskId` 和 `status` 状态切换视图（`UnifiedContentSwitcher`）
- **包含 Layer 侧边栏支持**：点击 Layer 按钮时拉取后端最新报告内容并显示

**Layer 侧边栏机制**：
```typescript
// HomePage - Layer sidebar state
const [layerSidebarOpen, setLayerSidebarOpen] = useState(false);
const [activeLayer, setActiveLayer] = useState<number | null>(null);

const handleLayerSidebarOpen = useCallback((layer: number) => {
  setActiveLayer(layer);
  setLayerSidebarOpen(true);
}, []);

const handleLayerSidebarClose = useCallback(() => {
  setLayerSidebarOpen(false);
  setActiveLayer(null);
}, []);

// 条件渲染 LayerSidebar
{layerSidebarOpen && (
  <LayerSidebar activeLayer={activeLayer} onClose={handleLayerSidebarClose} />
)}
```

### 村庄页面 (`app/village/[taskId]/page.tsx`) - 已删除

**删除原因**：
- 没有任何地方导航到这个页面
- 用户从历史面板加载会话后，留在首页 (`/`)
- 通过 Context 的 `taskId` 状态切换视图
- 这是冗余代码，已删除

## 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Next.js | 14.2.0 | React 框架 |
| React | 18.3.0 | UI 库 |
| TypeScript | 5.x | 类型安全 |
| Tailwind CSS | 4.2.1 | 实用类 |
| Framer Motion | 12.32.0 | 动画库 |
| react-markdown | 9.0.0 | Markdown 渲染 |

## 设计风格

### Gemini 风格暗色主题

前端采用 Gemini 风格的暗色主题设计，主要特点：

- **主色调**：绿色系 (#10b981 emerald-500) 作为强调色
- **背景色**：深灰色系 (#0f0f11, #1a1a1a)
- **文本色**：浅灰色 (#e5e5e5) 和白色
- **动画效果**：流畅的微动画和过渡效果
- **思考指示器**：脉动动画效果，模拟 AI 思考过程

### 色彩系统

```css
/* 主色调 */
--primary-green: #16a34a;       /* 主品牌色 */
--primary-green-hover: #15803d; /* 悬停色 */

/* 语义色 */
--success: #22c55e;  /* 成功/完成 */
--warning: #eab308;  /* 警告/审查 */
--error:   #ef4444;  /* 错误/失败 */
--info:    #3b82f6;  /* 信息 */
```

### 状态徽章

```css
.status-paused { background: #fef9c3; color: #854d0e; }
.status-completed { background: #dcfce7; color: #166534; }
.status-failed { background: #fee2e2; color: #991b1b; }
```

### 流式文本光标

```css
.streaming-cursor::after {
  content: '▋';
  animation: blink 1s infinite;
  color: var(--primary-green);
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}
```

### 维度图标

#### Layer 1: 现状分析

| 图标 | 维度 |
|------|------|
| 📍 | 区位与对外交通分析 |
| 👥 | 社会经济分析 |
| 💭 | 村民意愿与诉求分析 |
| 📋 | 上位规划与政策导向分析 |
| 🌿 | 自然环境分析 |
| 🏗️ | 土地利用分析 |
| 🚗 | 道路交通分析 |
| 🏛️ | 公共服务设施分析 |
| 🔧 | 基础设施分析 |
| 🌳 | 生态绿地分析 |
| 🏠 | 建筑分析 |
| 🏮 | 历史文化与乡愁保护分析 |

#### Layer 2: 规划思路

| 图标 | 维度 |
|------|------|
| 💎 | 资源禀赋分析 |
| 🎯 | 规划定位分析 |
| 📈 | 发展目标分析 |
| 📊 | 规划策略分析 |

#### Layer 3: 详细规划

| 图标 | 维度 |
|------|------|
| 🏭 | 产业规划 |
| 🗺️ | 空间结构规划 |
| 📐 | 土地利用规划 |
| 🏘️ | 居民点规划 |
| 🛣️ | 道路交通规划 |
| 🏥 | 公共服务设施规划 |
| 🔨 | 基础设施规划 |
| 🌲 | 生态绿地规划 |
| 🛡️ | 防震减灾规划 |
| 🏰 | 历史文保规划 |
| 🎨 | 村庄风貌指引 |
| 📦 | 建设项目库 |

### 响应式断点

```css
@media (max-width: 640px) {
  .message { max-width: 90%; }
}

@media (min-width: 1025px) {
  .container { max-width: 1200px; }
  .message { max-width: 80%; }
}
```

## 核心原则

### 单一状态源 (SSOT)

前端不存储独立业务状态，所有状态从后端 LangGraph Checkpoint 同步：

```
后端状态 (Checkpointer)        →    前端派生状态
────────────────────────────────────────────────
status: 'paused'               →    isPaused: true
previous_layer: 1              →    pendingReviewLayer: 1
layer_1_completed: true        →    completedLayers[1]: true
version: 102                   →    localVersionRef: 102
execution_complete: true       →    停止轮询
```

### Signal-Fetch Pattern

SSE 只发送轻量信号，完整数据通过 REST API 获取：

```
后端 SSE 事件                    前端处理
────────────────────────────────────────────────
layer_started: {layer, name}  → 创建空 LayerReportMessage
dimension_delta: {delta}      → 批量更新内容缓存 (useStreamingRender)
layer_completed: {layer, ver} → REST API 获取完整报告
pause: {layer}                → 显示审查面板
stream_paused: {reason}       → 关闭 SSE 连接，等待用户操作
```

## 状态同步机制

### SSE 事件驱动 + REST 状态确认

前端使用 SSE 接收实时事件，通过 REST API 确认状态：

```typescript
// controllers/TaskController.tsx
// SSE 连接建立（仅依赖 taskId）
useEffect(() => {
    if (!taskId) return;
    
    const es = planningApi.createStream(taskId, (event) => {
        switch (event.type) {
            case 'layer_completed':
                // Signal-Fetch: 触发 REST API 获取完整数据
                callbacks.onLayerCompleted?.(event.data.layer, '', {});
                break;
            case 'stream_paused':
                // SSE 流关闭，等待用户操作
                break;
            // ... 其他事件
        }
    });
    
    return () => es.close();
}, [taskId]);
```

### 版本化同步

使用 version 字段防止状态回滚：

```typescript
// contexts/UnifiedPlanningContext.tsx
const localVersionRef = useRef<number>(0);

const syncBackendState = useCallback((backendData: any) => {
    const serverVersion = backendData.version ?? 0;
    const localVersion = localVersionRef.current;
    
    // 跳过旧版本数据
    if (serverVersion > 0 && serverVersion <= localVersion) {
        console.log(`跳过旧版本: server=${serverVersion}, local=${localVersion}`);
        return;
    }
    
    // 更新本地版本号
    if (serverVersion > 0) {
        localVersionRef.current = serverVersion;
    }
    
    // 继续处理状态更新...
}, []);
```

### 断线重连机制

SSE 断线时自动重连，重连前先获取完整状态：

```typescript
// TaskController.tsx
const MAX_RECONNECT_ATTEMPTS = 5;

const handleSSEError = () => {
    if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        // 重连前先获取一次完整状态
        fetchStatus().then(() => {
            const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 5000);
            setTimeout(() => {
                sseConnectionRef.current = createSSEConnection();
                reconnectAttempts++;
            }, delay);
        });
    }
};
```

## 目录结构

```
frontend/src/
├── app/                        # 页面路由
│   ├── page.tsx                # 首页 (唯一用户交互页面)
│   ├── layout.tsx              # 根布局
│   └── village/[taskId]/       # ⚠️ 已删除 (冗余代码)
├── contexts/
│   └── UnifiedPlanningContext.tsx  # 全局状态管理
├── controllers/
│   └── TaskController.tsx      # SSE 连接管理、状态同步
├── components/
│   ├── layout/                 # 布局组件
│   │   ├── UnifiedLayout.tsx
│   │   ├── UnifiedContentSwitcher.tsx
│   │   ├── Header.tsx
│   │   ├── HistoryPanel.tsx
│   │   └── KnowledgePanel.tsx
│   ├── chat/                   # 聊天组件
│   │   ├── ChatPanel.tsx
│   │   ├── MessageList.tsx
│   │   ├── MessageBubble.tsx
│   │   ├── MessageContent.tsx
│   │   ├── StreamingText.tsx
│   │   ├── ThinkingIndicator.tsx
│   │   ├── ActionButtonGroup.tsx
│   │   ├── DimensionSection.tsx
│   │   ├── LayerReportCard.tsx
│   │   ├── ReviewPanel.tsx
│   │   ├── LayerReportMessage.tsx
│   │   ├── DimensionReportStreaming.tsx
│   │   ├── DimensionSelector.tsx
│   │   └── CheckpointMarker.tsx
│   ├── layer/                  # Layer 组件
│   │   └── LayerSidebar.tsx    # Layer 报告侧边栏 (首页渲染)
│   ├── report/                 # 报告组件
│   │   └── KnowledgeReference.tsx
│   ├── ui/                     # 通用UI组件
│   │   ├── Card.tsx
│   │   └── SegmentedControl.tsx
│   ├── MarkdownRenderer.tsx
│   └── VillageInputForm.tsx
├── hooks/
│   ├── useTaskSSE.ts           # SSE连接管理
│   ├── useStreamingRender.ts   # 流式渲染批处理
│   └── useStreamingText.ts     # 文本流式渲染
├── lib/
│   ├── api.ts                  # API客户端
│   ├── logger.ts               # 日志工具
│   ├── constants.ts            # 常量定义
│   └── utils/
│       └── message-helpers.ts  # 消息辅助函数
├── config/
│   ├── dimensions.ts           # 维度配置
│   └── planning.ts             # 规划配置
└── types/                      # 类型定义
    ├── message.ts
    └── message-types.ts
```

## Context 状态管理

### UnifiedPlanningContext

```typescript
interface PlanningState {
  // 任务标识
  taskId: string | null;
  projectName: string | null;
  
  // 状态 (从后端同步)
  status: Status;  // idle|collecting|planning|paused|completed|failed
  
  // 视图状态
  viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE';
  
  // 审查状态
  isPaused: boolean;              // = status === 'paused'
  pendingReviewLayer: number | null;  // = previous_layer
  
  // 层级完成状态
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  
  // 消息历史
  messages: Message[];
  
  // 历史数据
  villages: VillageInfo[];
  selectedSession: VillageSession | null;
}
```

### 状态同步方法

```typescript
// syncBackendState - 从REST轮询同步
const syncBackendState = useCallback((backendData: any) => {
  setStatusState(backendData.status);
  setIsPaused(backendData.status === 'paused');
  setPendingReviewLayer(backendData.previous_layer);
  
  // 只在会话结束/暂停时同步层级状态
  if (['idle', 'completed', 'failed', 'paused'].includes(backendData.status)) {
    setCompletedLayers({
      1: backendData.layer_1_completed || false,
      2: backendData.layer_2_completed || false,
      3: backendData.layer_3_completed || false,
    });
  }
}, []);

// setUILayerCompleted - SSE驱动更新
const setUILayerCompleted = useCallback((layer: number, completed: boolean) => {
  setCompletedLayers(prev => ({ ...prev, [layer]: completed }));
}, []);
```

## 组件层次

### 组件树

```
App (page.tsx)
  │
  ├── UnifiedPlanningProvider (Context)
  │
  └── UnifiedLayout
         │
         ├── Header (导航栏)
         │      ├── Logo
         │      ├── 新建规划按钮
         │      ├── 历史记录按钮
         │      └── 知识库按钮
         │
         └── UnifiedContentSwitcher
                │
                ├── [WELCOME_FORM] → VillageInputForm
                │
                └── [SESSION_ACTIVE] → ChatPanel
                       │
                       ├── useTaskSSE (SSE连接)
                       │
                       ├── MessageList
                       │      └── MessageBubble
                       │             └── MessageContent
                       │                    ├── StreamingText (流式文本)
                       │                    ├── ThinkingIndicator (思考动画)
                       │                    ├── MarkdownRenderer (Markdown)
                       │                    ├── LayerReportMessage
                       │                    │      └── LayerReportCard
                       │                    │             └── DimensionSection
                       │                    └── DimensionReportStreaming
                       │                           └── KnowledgeReference
                       │
                       ├── ActionButtonGroup (操作按钮)
                       │
                       └── ReviewPanel (条件渲染)
```

### 核心组件

| 组件 | 文件 | 功能 |
|------|------|------|
| UnifiedLayout | layout/UnifiedLayout.tsx | 主布局容器 |
| UnifiedContentSwitcher | layout/UnifiedContentSwitcher.tsx | 视图切换 |
| HistoryPanel | layout/HistoryPanel.tsx | 历史记录面板（支持删除会话） |
| ChatPanel | chat/ChatPanel.tsx | 主聊天面板 |
| MessageList | chat/MessageList.tsx | 消息列表渲染（集成检查点标记） |
| MessageBubble | chat/MessageBubble.tsx | 消息气泡容器 |
| MessageContent | chat/MessageContent.tsx | 消息内容包装器 |
| StreamingText | chat/StreamingText.tsx | 流式文本渲染动画 |
| ThinkingIndicator | chat/ThinkingIndicator.tsx | 思考指示器 (Gemini风格动画) |
| ActionButtonGroup | chat/ActionButtonGroup.tsx | 操作按钮组 (批准/驳回等) |
| DimensionSection | chat/DimensionSection.tsx | 维度报告区块 |
| LayerReportCard | chat/LayerReportCard.tsx | 层级报告卡片容器 |
| ReviewPanel | chat/ReviewPanel.tsx | 审查面板（支持批准/驳回） |
| LayerReportMessage | chat/LayerReportMessage.tsx | 层级完成消息 |
| DimensionReportStreaming | chat/DimensionReportStreaming.tsx | 维度流式报告 |
| DimensionSelector | chat/DimensionSelector.tsx | 维度选择器（驳回时选择修复维度） |
| CheckpointMarker | chat/CheckpointMarker.tsx | 检查点时间线标记（支持回滚） |
| LayerSidebar | layer/LayerSidebar.tsx | Layer 报告侧边栏（首页渲染） |
| KnowledgeReference | report/KnowledgeReference.tsx | 知识引用展示 |
| MarkdownRenderer | MarkdownRenderer.tsx | Markdown 渲染器 |
| Card | ui/Card.tsx | 通用卡片组件 |
| SegmentedControl | ui/SegmentedControl.tsx | 分段控制器 |

## 消息类型

| 类型 | 说明 | 关键字段 |
|------|------|----------|
| `text` | 普通文本 | content, streamingState |
| `file` | 文件上传 | content, filename, size |
| `progress` | 进度更新 | progress, currentLayer, currentPhase |
| `dimension_report` | 维度报告 | layer, dimensionKey, dimensionName, streamingState |
| `layer_completed` | 层级完成 | layer, fullReportContent, dimensionReports, checkpointId |

**注意**: 前端只使用 5 种消息类型，保持简洁。

## API 客户端

```typescript
// lib/api.ts

// Planning API
planningApi.startPlanning(request)           // POST /start
planningApi.createStream(sessionId, onEvent) // GET /stream (SSE)
planningApi.getStatus(sessionId)             // GET /status
planningApi.approveReview(sessionId)         // POST /review (approve)
planningApi.rejectReview(sessionId, feedback, dimensions)  // POST /review (reject)
planningApi.rollbackCheckpoint(sessionId, checkpointId)    // POST /review (rollback)
planningApi.deleteSession(sessionId)         // DELETE /sessions/{id}

// Data API
dataApi.listVillages()                       // GET /villages
dataApi.getLayerContent(villageName, layerId)  // GET 层级内容
dataApi.getCheckpoints(villageName)          // GET 检查点

// Knowledge API
knowledgeApi.listDocuments()                 // GET /documents
knowledgeApi.addDocument(file)               // POST /documents
```

## Hooks

| Hook | 功能 |
|------|------|
| useTaskSSE | SSE 连接管理、事件处理、重试机制 |
| useStreamingRender | 批处理流式渲染 (RAF + 防抖) |
| useStreamingText | 流式文本渲染动画 |

## 条件渲染

```typescript
// 视图模式切换
{viewMode === 'WELCOME_FORM' && <VillageInputForm />}
{viewMode === 'SESSION_ACTIVE' && <ChatPanel />}

// ReviewPanel 显示（支持批准和驳回）
{isPaused && pendingReviewLayer && (
  <ReviewPanel 
    layer={pendingReviewLayer}
    onApprove={() => planningApi.approveReview(taskId)}
    onReject={(feedback) => handleReviewReject(feedback)}
  />
)}

// CheckpointMarker 在 MessageList 中渲染
// 每个 layer_completed 消息后显示对应的检查点标记
{checkpoint && (
  <CheckpointMarker
    checkpoint={checkpoint}
    onRollback={() => handleRollback(checkpoint.checkpoint_id)}
    isRollingBack={isRollingBack}
  />
)}

// 消息类型渲染
switch (message.type) {
  case 'layer_completed': return <LayerReportMessage message={message} />;
  case 'dimension_report': return <DimensionReportStreaming message={message} />;
  default: return <TextMessage message={message} />;
}
```

## 关键文件

| 文件 | 功能 |
|------|------|
| `contexts/UnifiedPlanningContext.tsx` | 全局状态管理（消息、任务、进度面板） |
| `controllers/TaskController.tsx` | SSE 连接管理、状态同步、断线重连 |
| `lib/api.ts` | API客户端封装（Planning、Data、Knowledge） |
| `config/dimensions.ts` | 28个维度配置（名称、层级映射） |
| `types/message.ts` | 消息类型定义（5种消息类型联合） |
| `types/message-types.ts` | 具体消息类型详细定义 |
| `hooks/useTaskSSE.ts` | SSE连接管理 |
| `components/chat/ChatPanel.tsx` | 主界面容器 |
| `components/chat/ReviewPanel.tsx` | 审查面板（批准/驳回） |
| `components/chat/CheckpointMarker.tsx` | 检查点时间线标记（回滚） |
| `components/chat/DimensionSelector.tsx` | 维度选择器（驳回时选择修复维度） |
| `components/layout/HistoryPanel.tsx` | 历史记录面板（删除会话） |
| `components/chat/ThinkingIndicator.tsx` | 思考指示器（Gemini风格动画） |
| `lib/utils/message-helpers.ts` | 消息创建辅助函数 |

## Layer 侧边栏与报告拉取机制

### SegmentedControl 触发式按钮

**文件**: `components/ui/SegmentedControl.tsx` / `components/chat/ChatPanel.tsx`

SegmentedControl 从状态切换型改为触发式按钮，点击时从后端拉取最新报告内容：

```typescript
// ChatPanel.tsx - handleLayerChange
const handleLayerChange = useCallback(
  async (layer: string) => {
    const layerNumber = LAYER_LABEL_MAP[layer];
    if (layerNumber === undefined || !taskId) return;

    // 1. 从后端拉取最新报告（回滚后自动返回回滚后的内容）
    try {
      const reports = await planningApi.getLayerReports(taskId, layerNumber);

      // 2. 更新 context 中的报告内容
      if (layerNumber === 1) {
        setLayerReports({ analysis_report_content: reports.report_content || '' });
      } else if (layerNumber === 2) {
        setLayerReports({ concept_report_content: reports.report_content || '' });
      } else if (layerNumber === 3) {
        setLayerReports({ detail_report_content: reports.report_content || '' });
      }
    } catch (error) {
      console.error('[ChatPanel] 获取 Layer 报告失败:', error);
    }

    // 3. 打开侧边栏
    onOpenLayerSidebar?.(layerNumber);
  },
  [setCurrentLayer, onOpenLayerSidebar, taskId, setLayerReports]
);
```

**关键点**:
- 点击按钮时调用 `planningApi.getLayerReports()` 从后端获取最新报告
- 回滚后，后端 Checkpoint 已更新为目标状态，API 自动返回回滚后的内容
- 不需要传递 `checkpoint_id` 参数，后端自动返回当前最新 Checkpoint 数据

### UnifiedLayout cloneElement Prop 注入修复

**文件**: `components/layout/UnifiedLayout.tsx`

修复 cloneElement 无条件覆盖子组件已有 prop 的问题：

```typescript
// 修改前 (无条件覆盖)
{Children.map(children, (child) => {
  if (React.isValidElement(child)) {
    return React.cloneElement(child, { onOpenLayerSidebar });
  }
  return child;
})}

// 修改后 (检查已存在才注入)
{Children.map(children, (child) => {
  if (React.isValidElement(child)) {
    // 只在 children 没有 onOpenLayerSidebar 时才注入
    const existingProps = child.props as { onOpenLayerSidebar?: (layer: number) => void };
    if (!existingProps.onOpenLayerSidebar && onOpenLayerSidebar) {
      return React.cloneElement(child, { onOpenLayerSidebar });
    }
  }
  return child;
})}
```

### Layer 报告内容存储

**文件**: `contexts/UnifiedPlanningContext.tsx`

```typescript
export interface LayerReportContent {
  analysis_reports: Record<string, string>;   // Layer 1 维度报告
  concept_reports: Record<string, string>;    // Layer 2 维度报告
  detail_reports: Record<string, string>;     // Layer 3 维度报告
  analysis_report_content: string;            // Layer 1 汇总报告
  concept_report_content: string;             // Layer 2 汇总报告
  detail_report_content: string;              // Layer 3 汇总报告
}

// Context 提供 setLayerReports 方法
setLayerReports: (reports: Partial<LayerReportContent>) => void;
```

---

## 审查与回滚功能

### 审查面板 (ReviewPanel)

当层级完成并进入暂停状态时，显示审查面板：

```
┌────────────────────────────────────────┐
│ ⏸️ 现状分析 待审查                      │
│                                        │
│ ┌─────────────┐  ┌─────────────┐      │
│ │ ✅ 批准继续  │  │ ✏️ 驳回修改  │      │
│ └─────────────┘  └─────────────┘      │
└────────────────────────────────────────┘
```

点击「驳回修改」后展开输入框：
- 输入修改意见
- 选择需要修复的维度（可选）
- 提交后调用 `reject(feedback, dimensions)` API

### 检查点标记 (CheckpointMarker)

在每个层级完成后，在对话时间线中显示检查点标记：

```
────────────────────────────────────────
│ 📌 Layer 1 完成 · 2024-01-15 10:30   │
│ ──────────────  ───────────────────  │
│                [恢复到此点]           │
────────────────────────────────────────
```

功能：
- 显示层级完成时间
- 点击「恢复到此点」触发回滚确认弹窗
- 确认后调用 `rollback(checkpointId)` API

### 历史记录删除 (HistoryPanel)

在历史记录面板中，每个会话项右侧显示删除按钮：

```
┌────────────────────────────────────┐
│ 📁 某某村 (3条记录)                │
│   ├─ 2024-01-15 10:30    [🗑️]     │
│   ├─ 2024-01-14 14:20    [🗑️]     │
│   └─ 2024-01-13 09:00    [🗑️]     │
└────────────────────────────────────┘
```

删除流程：
1. 点击删除按钮
2. 显示确认弹窗
3. 确认后调用 `deleteSession(sessionId)` API
4. 后端完整删除：数据库记录 + UI消息 + Checkpoint数据