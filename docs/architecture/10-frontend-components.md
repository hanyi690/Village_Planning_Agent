# 前端组件架构

本文档详细说明前端每个文件的功能及组件间的对应关系。

> **更新日期**: 2026-05-17
> **版本**: v3.0 (完整版)

## 目录

- [目录结构概览](#目录结构概览)
- [布局组件](#布局组件)
- [聊天组件](#聊天组件)
- [GIS 组件](#gis-组件)
- [对比组件](#对比组件)
- [设置组件](#设置组件)
- [UI 通用组件](#ui-通用组件)
- [状态管理层](#状态管理层)
- [Hooks 层](#hooks-层)
- [组件关系可视化](#组件关系可视化)
- [关键设计模式](#关键设计模式)

---

## 目录结构概览

```
frontend/src/features/planning/
├── api/                    # API 客户端
│   ├── client.ts           # SSE 连接与请求封装
│   ├── data-api.ts         # 数据 API（村庄历史等）
│   ├── planning-api.ts     # 规划 API
│   ├── types.ts            # API 类型定义
│   └── index.ts            # API 导出
├── components/
│   ├── layout/             # 布局组件
│   │   ├── AppHeader.tsx       # 顶部导航
│   │   ├── LayerNav.tsx        # 左侧维度导航
│   │   ├── FocusArea.tsx       # 中央工作区
│   │   ├── ReportViewer.tsx    # 报告查看器
│   │   ├── ProcessPanel.tsx    # 右侧处理面板
│   │   └── index.ts            # 布局组件导出
│   ├── chat/               # 聊天组件
│   │   ├── MessageList.tsx     # 消息列表
│   │   ├── MessageBubble.tsx   # 消息气泡
│   │   ├── MessageContent.tsx  # 消息内容
│   │   ├── LayerReportMessage.tsx # 层级完成消息
│   │   ├── ProgressPanel.tsx   # 执行进度面板
│   │   ├── ToolStatusPanel.tsx # 工具状态面板
│   │   ├── ToolStatusCard.tsx  # 工具状态卡片
│   │   ├── CheckpointMarker.tsx # 检查点标记
│   │   ├── StreamingText.tsx   # 流式文本渲染
│   │   ├── ThinkingIndicator.tsx # 思考指示器
│   │   ├── GisResultCard.tsx   # GIS 结果卡片
│   │   ├── KnowledgeSliceCard.tsx # 知识切片卡片
│   │   └── FileViewerSidebar.tsx # 文件查看侧边栏
│   ├── gis/                # GIS 地图组件
│   │   ├── MapView.tsx
│   │   ├── LegendPanel.tsx
│   │   └── index.ts
│   ├── compare/            # 对比组件
│   │   ├── ReportComparePanel.tsx
│   │   ├── ReportCompareModal.tsx
│   │   └── index.ts
│   ├── settings/           # 设置组件
│   │   ├── SettingsPanel.tsx
│   │   └── index.ts
│   ├── ui/                 # UI 通用组件
│   │   ├── MarkdownRenderer.tsx
│   │   ├── ImagePreview.tsx
│   │   └── index.ts
│   ├── knowledge/          # 知识组件（预留）
│   │   └── index.ts
│   ├── Dashboard.tsx       # 主布局容器
│   ├── VillageInputForm.tsx # 村庄输入表单
│   ├── ChatInput.tsx       # 聊天输入框
│   ├── MessagePanel.tsx    # 消息面板
│   ├── CascadePanel.tsx    # 级联修复面板
│   ├── DimensionCard.tsx   # 维度状态卡片
│   └── index.ts            # 组件导出
├── store/                  # Zustand 状态管理
│   ├── planningStore.ts    # 主状态存储
│   ├── planning-context.tsx # React Context 包装
│   └── index.ts
├── hooks/                  # 自定义 Hooks
│   ├── useSSE.ts           # SSE 连接管理
│   ├── useSelectors.ts     # 状态选择器
│   ├── useHandlers.ts      # 事件处理器
│   ├── useStreaming.ts     # 流式渲染
│   ├── usePersistence.ts    # 持久化
│   ├── useSessionRestore.ts # 会话恢复
│   ├── useApprovalActions.ts # 审批操作
│   ├── ui/                 # UI 相关 Hooks
│   ├── utils/              # Hook 工具
│   │   └── useStreamingRender.ts
│   └── index.ts
├── config/                 # 配置
│   ├── dimensions.ts       # 维度配置
│   ├── phases.ts           # 阶段配置
│   ├── planning.ts         # 规划配置
│   └── index.ts
├── constants/              # 常量
│   ├── gis.ts              # GIS 常量
│   └── index.ts            # 通用常量
├── types/                  # 类型定义
│   ├── base.ts             # 基础类型
│   ├── events.ts           # SSE 事件类型
│   ├── messages.ts         # 消息类型
│   ├── guards.ts           # 类型守卫
│   ├── helpers.ts          # 类型辅助函数
│   └── index.ts
├── utils/                  # 工具函数
│   ├── cn.ts               # 类名合并
│   ├── format.ts           # 格式化工具
│   ├── logger.ts           # 日志工具
│   ├── message-helpers.ts  # 消息辅助函数
│   ├── report-parser.ts    # 报告解析
│   ├── throttle.ts         # 节流工具
│   └── index.ts
└── index.ts                # 模块导出
```

---

## 布局组件

### 组件层级图

```
Dashboard (主容器)
├── AppHeader (顶部导航)
│   ├── Logo
│   ├── LayerProgressBar (L1/L2/L3 进度)
│   └── ActionButtons
├── <三栏布局>
│   ├── LayerNav (左侧 280px)
│   │   ├── 导航项（总览/聊天）
│   │   ├── Layer 展开列表
│   │   │   └── 维度项 + 状态圆点
│   │   └── ToolStatusPanel (底部折叠)
│   ├── FocusArea (中央 flex:1)
│   │   └── ReportViewer
│   │       ├── [idle] VillageInputForm
│   │       ├── [dim:*] 维度详情视图
│   │       │   ├── MarkdownRenderer (报告内容)
│   │       │   ├── KnowledgeSliceCard (知识切片)
│   │       │   └── FileViewerSidebar (文件侧边栏)
│   │       └── [默认] 规划总览
│   └── ProcessPanel (右侧 320px)
│       ├── TabNavigation (消息/地图/历史/设置)
│       ├── MessageList
│       └── ChatInput
└── ChatBar (底部输入栏)
```

### `Dashboard.tsx`

**功能**: 主布局容器，三栏工作台

**子组件**:
- `AppHeader`: 顶部导航
- `LayerNav`: 左侧维度导航
- `FocusArea`: 中央内容区
- `ProcessPanel`: 右侧处理面板

### `LayerNav.tsx`

**功能**: 左侧维度导航树 + 工具状态面板

**状态依赖**:
- `dimensionProgress`: 维度执行进度
- `completedDimensions`: 已完成维度列表
- `currentLayer`: 当前层级
- `toolStatuses`: 工具状态映射

**交互**:
- 点击维度：跳转到对应报告
- 展开层级：显示所有维度
- 状态图标：pending/streaming/completed/failed
- 底部工具状态：可折叠显示

### `FocusArea.tsx`

**功能**: 中央内容区容器，委托给 ReportViewer

**子组件**:
- `ReportViewer`: 报告查看器
- `CascadePanel`: 级联修复覆盖层

### `ReportViewer.tsx`

**功能**: 报告查看器，三种显示模式

**三种显示模式**:

| 模式 | 条件 | 渲染内容 |
|------|------|----------|
| 输入表单 | `status === 'idle'` | `VillageInputForm` |
| 维度详情 | `selectedNavigationKey.startsWith('dim:')` | 报告内容 + RAG 知识面板 |
| 规划总览 | 默认 | 各层报告完成情况概览 |

**维度详情视图布局**:
```
┌─────────────────────────────────────────────────────────────┐
│  Header: 维度标题 + Layer 标签 + [对比] [查看过程]          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│     MarkdownRenderer (报告内容)                             │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  [知识来源] (可折叠面板，位于报告下方)                       │
│  ├── 检索词显示                                             │
│  ├── 文档卡片列表                                           │
│  └── 点击卡片 → 右侧详情抽屉                                │
└─────────────────────────────────────────────────────────────┘
```

**RAG 知识来源功能**:
- 可折叠面板，显示在报告内容下方
- 显示检索词和文档列表
- 点击文档卡片打开右侧详情抽屉
- 详情抽屉显示完整标题、内容和来源

### `ProcessPanel.tsx`

**功能**: 右侧处理面板，四个标签页

**标签页**:
1. **消息**: MessageList + ChatInput
2. **地图**: MapView GIS 数据
3. **历史**: 执行历史记录
4. **设置**: SettingsPanel 设置面板

---

## 聊天组件

### `MessageList.tsx`

**功能**: 消息列表渲染，类型分发

**Props**:
- `messages`: Message[] 消息数组
- `isTyping`: 是否正在输入
- `thinkingState`: 思考状态
- `checkpoints`: 检查点列表
- `onRollback`: 回滚回调

**消息类型分发**:
```typescript
switch (message.type) {
  case 'text': return <MessageBubble />;
  case 'layer_completed': return <LayerReportMessage />;
  case 'dimension_report': return <DimensionReportMessage />;
  case 'file': return <FileMessage />;
  case 'gis_result': return <GisResultCard />;
  case 'tool_status': return <ToolStatusCard />;
}
```

### `LayerReportMessage.tsx`

**功能**: 层级完成消息，简化显示

**显示**: "Layer X · N 个维度已完成"

### `MessageBubble.tsx`

**功能**: 单条消息气泡，Gemini 风格设计

**视觉设计**:
- AI 消息：透明背景，左对齐
- 用户消息：药丸形状，右对齐

### `ProgressPanel.tsx`

**功能**: 执行进度面板，显示维度级进度

**状态图标**:
- pending: 等待中
- streaming: 执行中（动画）
- completed: 已完成
- failed: 失败

### `ToolStatusPanel.tsx`

**功能**: 工具状态面板，显示运行中工具

**位置**: LayerNav 底部，可折叠

### `StreamingText.tsx`

**功能**: 流式文本渲染组件

**特性**:
- 支持打字机效果
- 自动滚动到底部
- 支持 Markdown 实时渲染

### `ThinkingIndicator.tsx`

**功能**: 思考指示器，显示 AI 思考状态

**视觉**: 动态圆点动画

### `KnowledgeSliceCard.tsx`

**功能**: 知识切片卡片，显示 RAG 检索结果

**Props**:
- `title`: 文档标题
- `snippet`: 内容片段
- `source`: 来源
- `score`: 相关性分数

### `FileViewerSidebar.tsx`

**功能**: 文件查看侧边栏

**特性**:
- 支持图片预览
- 支持文档预览
- 可折叠侧边栏

---

## GIS 组件

### `MapView.tsx`

**功能**: MapLibre GL 地图组件

**技术栈**:
- MapLibre GL JS
- 天地图瓦片底图
- GeoJSON 图层

---

## 对比组件

### `ReportCompareModal.tsx`

**功能**: 模态框对比组件

**特性**:
- 全屏模态框
- 会话选择器
- 双栏对比显示

---

## 设置组件

### `SettingsPanel.tsx`

**功能**: 设置面板

**设置项**:
- RAG 层级开关配置
- 步进模式开关
- 其他系统设置

---

## UI 通用组件

### `MarkdownRenderer.tsx`

**功能**: Markdown 内容渲染

**特性**:
- 支持 GFM (GitHub Flavored Markdown)
- 表格支持
- 图片懒加载
- 数学公式支持

### `ImagePreview.tsx`

**功能**: 图片预览组件

**特性**:
- 全屏预览
- 缩放支持
- 旋转支持

### `DimensionCard.tsx`

**功能**: 维度状态卡片（简化版）

**Props**:
- `dimensionKey`: 维度键
- `dimensionName`: 维度名称
- `status`: 维度状态
- `isExecuting`: 是否执行中
- `isResetting`: 是否重置中
- `onClick`: 点击回调

**显示**: 状态圆点 + 维度名称

---

## 状态管理层

### `usePlanningStore.ts`

**技术**: Zustand + Immer 中间件

**状态切片**:

| 切片 | 用途 |
|------|------|
| `messages` | 聊天消息列表 |
| `currentPhase` | 当前规划阶段 |
| `currentLayer` | 当前层级 |
| `dimensionProgress` | 维度进度映射 |
| `completedDimensions` | 已完成维度 |
| `isStreaming` | 是否流式中 |
| `isPaused` | 是否暂停 |
| `mapLayers` | 地图图层配置 |
| `dimensionRagSources` | RAG 知识来源 |
| `cascadeChain` | 级联修复链 |
| `streamingContent` | 流式内容 |
| `toolStatuses` | 工具状态 |
| `runningTools` | 运行中工具列表 |
| `resettingDimensions` | 重置中维度列表 |
| `dimensionVersions` | 维度版本号 |
| `ragLayerConfig` | RAG 层级开关配置 |
| `processPanelTab` | 处理面板当前标签页 |
| `selectedNavigationKey` | 当前选中导航键 |
| `isRightPanelExpanded` | 右侧面板展开状态 |
| `isLeftNavCollapsed` | 左侧导航折叠状态 |

### `planning-context.tsx`

**功能**: React Context 包装器，提供兼容层

---

## Hooks 层

### `useSSE.ts`

**功能**: SSE 连接管理

**批处理配置**:
- BATCH_WINDOW_MS = 50
- MAX_BATCH_SIZE = 50

### `useSelectors.ts`

**功能**: 状态选择器

**导出**:
- `useStatus()`: 规划状态
- `useCurrentLayer()`: 当前层级
- `useIsPaused()`: 是否暂停
- `useDimensionProgressAll()`: 所有维度进度
- `useDimensionRagSources()`: RAG 知识来源

### `useHandlers.ts`

**功能**: 事件处理器集合

### `useStreaming.ts`

**功能**: 流式渲染管理

### `usePersistence.ts`

**功能**: 状态持久化

### `useSessionRestore.ts`

**功能**: 会话恢复逻辑

### `useApprovalActions.ts`

**功能**: 审批操作（通过/拒绝）

---

## 组件关系可视化

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Dashboard                                  │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                        AppHeader                              │   │
│  │  [Logo]  [L1 Progress] [L2 Progress] [L3 Progress]  [Actions]│   │
│  └─────────────────────────────────────────────────────────────┘   │
├──────────┬──────────────────────────────────┬──────────────────────┤
│          │                                  │                      │
│ LayerNav │           FocusArea              │    ProcessPanel      │
│ (280px)  │           (flex:1)               │      (320px)         │
│          │                                  │                      │
│ ┌──────┐ │  ┌────────────────────────────┐  │  ┌────────────────┐  │
│ │导航  │ │  │      ReportViewer          │  │  │[消息][地图][历史][设置]│
│ │总览  │ │  │  ┌──────────────────────┐  │  │  ├────────────────┤  │
│ │聊天  │ │  │  │   MarkdownRenderer   │  │  │  │   MessageList   │  │
│ │      │ │  │  │   (报告内容)         │  │  │  │                │  │
│ │L1    │ │  │  └──────────────────────┘  │  │  └────────────────┘  │
│ │L2    │ │  │  ┌──────────────────────┐  │  │  ┌────────────────┐  │
│ │L3    │ │  │  │ KnowledgeSliceCard   │  │  │  │   ChatInput    │  │
│ │      │ │  │  │ (知识切片)           │  │  │  └────────────────┘  │
│ └──────┘ │  │  └──────────────────────┘  │  │                      │
│ ┌──────┐ │  └────────────────────────────┘  │                      │
│ │工具  │ │                                  │                      │
│ │状态  │ │                                  │                      │
│ └──────┘ │                                  │                      │
└──────────┴──────────────────────────────────┴──────────────────────┘
```

---

## 关键设计模式

### 1. 细粒度状态选择

避免使用整个 store，而是选择具体的状态片段：

```typescript
// ✅ 推荐：只选择需要的状态
const messages = usePlanningStore(s => s.messages);
const isStreaming = usePlanningStore(s => s.isStreaming);
```

### 2. React.memo 优化

高频更新的组件使用 memo：

```typescript
const MemoizedLayerReportMessage = React.memo(LayerReportMessage);
```

### 3. SSE 批处理

减少高频事件导致的重渲染：

```typescript
const BATCH_WINDOW_MS = 50;
const MAX_BATCH_SIZE = 50;
```

### 4. 组件职责分离

- **容器组件**: 处理状态和逻辑（如 ProcessPanel）
- **展示组件**: 只负责渲染（如 MessageBubble）
- **UI 组件**: 可复用的基础组件（如 MarkdownRenderer）

### 5. RAG 知识面板模式

知识切片显示在报告下方：

```typescript
// KnowledgeSliceCard 显示检索到的知识来源
<KnowledgeSliceCard
  title={doc.title}
  snippet={doc.snippet}
  source={doc.source}
  score={doc.score}
/>
```

---

## 相关文档

- [05-frontend-state](./05-frontend-state.md) - 前端状态管理详解
- [04-backend-api](./04-backend-api.md) - 后端 API 与 SSE 架构
