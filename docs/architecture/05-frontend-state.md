# 前端状态与组件架构

> **更新日期**: 2026-05-10
> **版本**: v3.1 (三栏工作台布局)
> **状态**: ✅ 已完整实现

本文档详细说明前端状态管理架构、三栏工作台布局和 SSE 事件处理机制。

## 目录

- [Feature Module 结构](#feature-module-结构)
- [状态管理架构](#状态管理架构)
- [PlanningState 接口](#planningstate-接口)
- [三栏工作台布局](#三栏工作台布局)
- [组件层级图](#组件层级图)
- [SSE 批处理机制](#sse-批处理机制)
- [关键文件路径](#关键文件路径)

---

## Feature Module 结构

### 目录架构

前端已迁移到 **feature-based 目录架构**，所有规划相关代码集中在 `features/planning/` 模块：

```
frontend/src/features/planning/
├── api/                    # API 客户端和类型定义
│   ├── types.ts            # 统一 API 类型
│   ├── planning-api.ts     # 规划流程 API
│   └── index.ts            # API 导出
├── components/             # UI 组件
│   ├── Dashboard.tsx       # 主布局（三栏工作台）
│   ├── CascadePanel.tsx    # 级联修复可视化
│   ├── MessagePanel.tsx    # 消息面板
│   ├── ChatInput.tsx       # 简化输入框
│   ├── DimensionCard.tsx   # 维度状态卡片
│   ├── VillageInputForm.tsx# 村庄信息输入表单
│   ├── chat/               # 对话相关组件
│   │   ├── MessageBubble.tsx
│   │   ├── MessageList.tsx
│   │   ├── StreamingText.tsx
│   │   ├── ToolStatusPanel.tsx
│   │   ├── ReviewPanel.tsx
│   │   ├── ProgressPanel.tsx
│   │   └── ...
│   ├── gis/                # GIS 组件
│   │   ├── MapView.tsx
│   │   ├── LegendPanel.tsx
│   │   ├── DataUpload.tsx
│   │   └── index.ts
│   └── layout/             # 三栏布局组件
│       ├── AppHeader.tsx       # 顶部导航栏 (56px)
│       ├── LayerNav.tsx        # 左侧导航 (280px)
│       ├── ContextPanel.tsx    # 右侧上下文面板 (280px)
│       ├── FocusArea.tsx       # 中央工作区
│       ├── BottomActionBar.tsx # 底部操作栏 (64px)
│       └── index.ts
├── hooks/                  # 自定义 Hooks
│   ├── useSSE.ts           # SSE 连接（批处理优化）
│   ├── useSelectors.ts     # 状态选择器
│   ├── useHandlers.ts      # 事件处理器
│   ├── usePersistence.ts   # 消息持久化
│   ├── useSessionRestore.ts# Session 恢复
│   ├── useApprovalActions.ts# 审批操作
│   └── index.ts            # Hooks 导出
├── store/                  # 状态管理
│   ├── planningStore.ts    # Zustand Store
│   └── planning-context.tsx # Context Provider
├── types/                  # 类型定义
│   ├── base.ts
│   └── index.ts
├── config/                 # 配置
│   ├── dimensions.ts
│   └── planning.ts
├── constants/              # 常量
│   └── index.ts            # LAYER_IDS, NAV_KEYS 等
└── utils/                  # 工具函数
    ├── message-helpers.ts
    ├── cn.ts
    ├── logger.ts
    └── report-parser.ts
```

---

## 状态管理架构

### Zustand + Immer

```typescript
// frontend/src/features/planning/store/planningStore.ts
import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';

export const usePlanningStore = create<PlanningState & PlanningActions>()(
  immer((set, get) => ({
    conversationId: '',
    sessionId: null,
    projectName: null,
    status: 'idle',
    phase: 'init',
    currentWave: 1,
    reports: {},
    pause_after_step: false,
    previous_layer: 0,
    step_mode: false,
  }))
);
```

### 状态选择器 Hooks

为优化性能，使用细粒度选择器避免不必要的重渲染：

```typescript
export function useStatus(): Status {
  return usePlanningStore((state) => state.status);
}

export function useCurrentLayer(): number | null {
  return usePlanningStore((state) => state.currentLayer);
}

export function useIsPaused(): boolean {
  return usePlanningStore((state) => state.isPaused);
}

export function useCascadeChain(): CascadeChain | null {
  return usePlanningStore((state) => state.cascadeChain);
}

export function useDimensionProgressAll(): Record<string, DimensionProgressItem> {
  return usePlanningStore((state) => state.dimensionProgress);
}
```

---

## PlanningState 接口

### 核心字段

```typescript
export interface PlanningState {
  conversationId: string;

  // Session
  sessionId: string | null;
  projectName: string | null;
  status: Status;

  // Agent State (SSOT)
  phase: string;
  currentWave: number;
  reports: Reports;
  pause_after_step: boolean;
  previous_layer: number;
  step_mode: boolean;

  // Derived UI State
  completedDimensions: CompletedDimensions;
  currentLayer: number | null;
  currentPhase: LayerPhase | '修复中';
  completedLayers: { 1: boolean; 2: boolean; 3: boolean };
  isPaused: boolean;
  pendingReviewLayer: number | null;

  // SSE Reconnect
  sseResumeTrigger: number;
  lastProcessedSeq: number;

  // Messages
  messages: Message[];

  // Progress
  dimensionProgress: Record<string, DimensionProgressItem>;
  executingDimensions: string[];
  layerDimensionCount: Record<number, number>;
  layerProgressHistory: { layer1?: LayerProgressSnapshot; ... };

  // RAG & Cascade (Demo System)
  dimensionRagSources: Record<string, DimensionRagSource>;
  cascadeChain: CascadeChain | null;
  dimensionVersions: Record<string, number>;
  streamingContent: Record<string, string>;
  resettingDimensions: string[];
  runningTools: string[];

  // UI State
  viewerVisible: boolean;
  referencedSection?: string;
  viewingFile: FileMessage | null;
  viewMode: 'WELCOME_FORM' | 'SESSION_ACTIVE';
  villageFormData: VillageInputData | null;
  progressPanelVisible: boolean;
  layerReportVisible: boolean;
  activeReportLayer: number;

  // History
  villages: VillageInfo[];
  selectedVillage: VillageInfo | null;
  selectedSession: VillageSession | null;

  // Checkpoints
  checkpoints: Checkpoint[];
  selectedCheckpoint: string | null;

  // Tools
  toolStatuses: Record<string, ToolStatus>;
  gisLayers: Record<string, GISLayerConfig[]>;

  // Three-Panel Layout Navigation State
  selectedNavigationKey: NavigationKey | null;
  isRightPanelExpanded: boolean;
  isLeftNavCollapsed: boolean;
}
```

### 三栏布局相关字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `selectedNavigationKey` | `NavigationKey \| null` | `null` | 当前选中导航键 |
| `isRightPanelExpanded` | `boolean` | `true` | 右侧上下文面板展开状态 |
| `isLeftNavCollapsed` | `boolean` | `false` | 左侧导航折叠状态 |

### NavigationKey 类型

```typescript
export const NAV_KEYS = {
  OVERVIEW: 'overview',
  CHAT: 'chat',
  APPROVAL: 'approval',
  dim: (key: string) => `dim:${key}`,
} as const;

export type NavigationKey = (typeof NAV_KEYS)[keyof typeof NAV_KEYS] | `dim:${string}`;
```

---

## 三栏工作台布局

### 设计风格

- **配色**: 白色背景 + slate 中性色 + emerald 强调色
  - 主背景: `bg-white` / `bg-slate-50`
  - 边框: `border-slate-200`
  - 强调色: `emerald-50`/`emerald-500`/`emerald-700`
- **形状**: 8px-12px `rounded-lg/xl` 圆角
- **字体**: 全局 `text-sm`(14px) / `text-base`(16px) / `text-xl`(20px)
- **响应式**: `lg:` 断点（1024px）区分桌面和移动端

### 布局结构

```
┌───────────────────────────────────────────────────────────┐
│ AppHeader (56px)  项目名 | L1 L2 L3 进度 | 导出 新会话    │
├──────────┬──────────────────────────────┬─────────────────┤
│          │                              │                 │
│ LayerNav │        FocusArea             │  ContextPanel   │
│ (280px)  │        (flex:1)              │  (280px)        │
│          │                              │                 │
│  总览    │   idle → VillageInputForm   │  GIS 地图       │
│  对话    │   chat → MessagePanel       │  级联修复链     │
│  L1 资源 │   dim  → 分析报告           │  运行中工具     │
│  L2 产业 │   review → ReviewPanel      │  知识来源       │
│  L3 设施 │   overview → 规划总览       │                 │
│          │                              │                 │
├──────────┴──────────────────────────────┴─────────────────┤
│ BottomActionBar (64px)  审查 / 打开对话                   │
└───────────────────────────────────────────────────────────┘
```

### 布局尺寸（桌面端 lg:）

| 区域 | 尺寸 | 说明 |
|------|------|------|
| AppHeader | `h-[56px]` | 固定顶部，半透明背景 |
| LayerNav | `w-[280px]` | 内联边栏，可折叠 |
| FocusArea | `flex:1` | 中央内容区，`max-w-4xl` |
| ContextPanel | `w-[280px]` | 右侧上下文面板，可展开/折叠 |
| BottomActionBar | `h-[64px]` | 条件渲染底部栏 |

### 响应式行为

- **桌面端 (lg: 1024px+)**: 三栏并排内联布局
- **移动端 (<lg)**: LayerNav 切换为固定定位 overlay + 半透明 backdrop

```tsx
{/* Desktop: inline sidebar */}
<div className="hidden lg:block shrink-0">
  {!isLeftNavCollapsed && <LayerNav />}
</div>
{/* Mobile: overlay drawer */}
{!isLeftNavCollapsed && (
  <div className="lg:hidden fixed inset-0 z-30">
    <div className="fixed inset-0 bg-black/30" onClick={handleToggleLeftNav} />
    <div className="fixed left-0 top-[56px] bottom-0 z-40 w-[280px] shadow-xl">
      <LayerNav />
    </div>
  </div>
)}
```

### FocusArea 内容切换

FocusArea 根据 `selectedNavigationKey` 和 `status` 渲染不同内容：

| 条件 | 渲染组件 |
|------|----------|
| `status === 'idle'` | `VillageInputForm` |
| `cascadeChain && !selectedNavigationKey` | `CascadePanel` + `ChatInput` |
| `selectedNavigationKey === NAV_KEYS.CHAT` | `MessagePanel` + `ChatInput` |
| `selectedNavigationKey === NAV_KEYS.APPROVAL` | `ReviewPanel` |
| `selectedNavigationKey?.startsWith('dim:')` | Markdown 分析报告 |
| 默认（总览） | 规划总览 + Layer 摘要 |

### 页面集成

```typescript
// frontend/src/app/page.tsx
import { PlanningProvider } from '@/features/planning';
import Dashboard from '@/features/planning/components/Dashboard';

export default function HomePage() {
  return (
    <PlanningProvider conversationId="default-session">
      <Dashboard />
    </PlanningProvider>
  );
}
```

---

## 组件层级图

```
page.tsx
└── PlanningProvider
    └── Dashboard
        ├── AppHeader
        │   ├── 汉堡按钮
        │   ├── 项目名称
        │   ├── L1/L2/L3 进度条
        │   ├── 导出按钮
        │   └── 新会话按钮
        ├── [Desktop] LayerNav (hidden lg:block)
        │   ├── 导航项（总览/对话）
        │   └── Layer 展开列表（L1/L2/L3）
        │       └── 维度项 + 状态圆点
        ├── [Mobile] LayerNav (lg:hidden overlay)
        ├── FocusArea (flex:1)
        │   └── 按 navigationKey 切换
        ├── ContextPanel (w-[280px])
        │   ├── GIS MapView
        │   ├── CascadePanel
        │   ├── 运行中工具
        │   └── 知识来源
        └── BottomActionBar
            ├── [审查] 批准/驳回/反馈
            └── [默认] 打开对话
```

### 组件使用状态

| 组件 | 文件路径 | 使用状态 |
|------|----------|----------|
| `Dashboard` | `components/Dashboard.tsx` | page.tsx 使用 |
| `AppHeader` | `components/layout/AppHeader.tsx` | Dashboard 使用 |
| `LayerNav` | `components/layout/LayerNav.tsx` | Dashboard 使用 |
| `FocusArea` | `components/layout/FocusArea.tsx` | Dashboard 使用 |
| `ContextPanel` | `components/layout/ContextPanel.tsx` | Dashboard 使用 |
| `BottomActionBar` | `components/layout/BottomActionBar.tsx` | Dashboard 使用 |
| `CascadePanel` | `components/CascadePanel.tsx` | ContextPanel/FocusArea |
| `MessagePanel` | `components/MessagePanel.tsx` | FocusArea |
| `ChatInput` | `components/ChatInput.tsx` | FocusArea |
| `ReviewPanel` | `components/chat/ReviewPanel.tsx` | FocusArea |
| `VillageInputForm` | `components/VillageInputForm.tsx` | FocusArea |
| `MapView` | `components/gis/MapView.tsx` | ContextPanel |

---

## SSE 批处理机制

### 批处理参数

```typescript
const BATCH_WINDOW = 50;      // 50ms 批处理窗口
const MAX_BATCH_SIZE = 50;    // 最大队列大小
const MAX_DELTA_PER_KEY = 3;  // 每维度保留最新3个delta
```

### 关键事件类型（跳过队列）

```typescript
const criticalEventTypes = [
  'dimension_start', 'dimension_complete',
  'layer_started', 'layer_completed',
  'tool_started', 'tool_status',
  'rag_query', 'rag_result',
  'cascade_impact', 'cascade_complete',
  'dimension_reset', 'dimension_reset_complete',
  'state_sync', 'layer_paused',
];
```

### Override 机制

当 `dimension_complete` 事件到达时，跳过该维度所有待处理的 `dimension_delta` 事件：

```typescript
const completedDimensionKeysRef = useRef<Set<string>>(new Set());
if (completedKeys.has(key)) continue;
```

### Delta 合并策略

对于同一维度的多个 delta 事件，只保留最新的（包含完整 accumulated 内容）：

```typescript
let deltaList = dimensionDeltaMap.get(key);
if (!deltaList) {
  deltaList = [];
  dimensionDeltaMap.set(key, deltaList);
}
deltaList.push(event);
if (deltaList.length > MAX_DELTA_PER_KEY) deltaList.shift();
```

---

## SSE 事件类型

```typescript
export type PlanningSSEEventType =
  | 'tool_started' | 'tool_status'
  | 'tool_call' | 'tool_progress' | 'tool_result'       // Legacy
  | 'layer_started' | 'layer_completed'
  | 'dimension_start' | 'dimension_complete' | 'dimension_error'
  | 'dimension_delta' | 'dimension_revised'
  | 'dimension_reset' | 'dimension_reset_complete'
  | 'progress' | 'checkpoint_saved'
  | 'pause' | 'resumed' | 'completed' | 'complete' | 'error'
  | 'text_chunk' | 'content_delta'
  | 'ai_response_delta' | 'ai_response_complete'
  | 'thinking_start' | 'thinking' | 'thinking_end' | 'stream_paused'
  | 'review_request'
  | 'rag_query' | 'rag_result' | 'cascade_impact' | 'cascade_complete'
  | 'state_sync' | 'layer_paused' | 'connected';
```

---

## 关键文件路径

| 功能 | 文件路径 |
|------|----------|
| 状态管理 | `frontend/src/features/planning/store/planningStore.ts` |
| Context Provider | `frontend/src/features/planning/store/planning-context.tsx` |
| SSE 连接 | `frontend/src/features/planning/hooks/useSSE.ts` |
| 状态选择器 | `frontend/src/features/planning/hooks/useSelectors.ts` |
| API 类型 | `frontend/src/features/planning/api/types.ts` |
| API 客户端 | `frontend/src/features/planning/api/planning-api.ts` |
| 主布局 | `frontend/src/features/planning/components/Dashboard.tsx` |
| 顶部导航 | `frontend/src/features/planning/components/layout/AppHeader.tsx` |
| 左侧导航 | `frontend/src/features/planning/components/layout/LayerNav.tsx` |
| 中央工作区 | `frontend/src/features/planning/components/layout/FocusArea.tsx` |
| 右侧面板 | `frontend/src/features/planning/components/layout/ContextPanel.tsx` |
| 底部操作栏 | `frontend/src/features/planning/components/layout/BottomActionBar.tsx` |
| 常量定义 | `frontend/src/features/planning/constants/index.ts` |
| 层级配置 | `frontend/src/features/planning/config/planning.ts` |
