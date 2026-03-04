# 前端视觉设计指南

> UI/UX 设计规范与组件样式

## 设计原则

1. **简洁优先**: 减少视觉干扰，聚焦核心内容
2. **清晰反馈**: 每个操作都有明确视觉反馈
3. **一致性**: 统一视觉语言和交互模式
4. **单一状态源**: UI 完全由后端状态驱动

## 页面布局

### 主布局 (UnifiedLayout)

```
┌─────────────────────────────────────────────────────────────┐
│                           Header                             │
│  Logo          项目名称              [历史] [知识库] [新建]   │
├─────────────────────────────────────────────────────────────┤
│                           Main                               │
│              (VillageInputForm 或 ChatPanel)                │
└─────────────────────────────────────────────────────────────┘
```

### ChatPanel 布局

```
┌─────────────────────────────────────────────────────────────┐
│  MessageList                                                 │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ 🚀 规划任务已创建，任务ID: 20260304_123456...           ││
│  ├─────────────────────────────────────────────────────────┤│
│  │ 📋 Layer 1 现状分析已完成                               ││
│  │ ├─ 📍 区位与对外交通分析    [查看]                      ││
│  │ ├─ 👥 社会经济分析          [查看]                      ││
│  │ └─ ...                                                  ││
│  ├─────────────────────────────────────────────────────────┤│
│  │ 📝 维度报告（流式中...）                                ││
│  │ 产业规划: 正在生成...▋                                  ││
│  └─────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│  ReviewPanel (条件渲染: isPaused && pendingReviewLayer)     │
│  ⏸️ Layer 1 现状分析已完成，请审查                           │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 驳回维度选择:                                          │ │
│  │ ☑ 土地利用分析   ☐ 基础设施分析   ☐ 生态绿地分析      │ │
│  │ 反馈意见: [____________________________________]       │ │
│  └────────────────────────────────────────────────────────┘ │
│  [查看详情]  [❌ 驳回修改]  [✅ 批准继续]                    │
└─────────────────────────────────────────────────────────────┘
```

### 欢迎页面 (VillageInputForm)

```
┌─────────────────────────────────────────────────────────────┐
│              🏘️ 村庄规划智能体                               │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ 村庄名称: [________________]                             ││
│  │                                                          ││
│  │ 村庄数据:                                                ││
│  │ ┌─────────────────────────────────────────────────────┐ ││
│  │ │  拖拽上传文件或粘贴文本                              │ ││
│  │ │  支持: .txt, .md, .docx, .doc, .pdf, .xlsx          │ ││
│  │ └─────────────────────────────────────────────────────┘ ││
│  │                                                          ││
│  │ 规划要求: [________________________________]             ││
│  │                                                          ││
│  │ ☐ 启用步进审查（每层暂停等待审核）                      ││
│  │                                                          ││
│  │                              [开始规划]                  ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

### 历史面板 (HistoryPanel)

```
┌─────────────────────────────────────────────────────────────┐
│  📜 历史记录                                        [关闭 ×] │
├─────────────────────────────────────────────────────────────┤
│  金田村 (3个会话)                                            │
│  ├─ 20260304_143052 - 已完成 ✓                              │
│  ├─ 20260303_101234 - 已完成 ✓                              │
│  └─ 20260302_091800 - 已完成 ✓                              │
│                                                              │
│  泗水村 (1个会话)                                            │
│  └─ 20260301_151200 - 已完成 ✓                              │
└─────────────────────────────────────────────────────────────┘
```

### 知识库面板 (KnowledgePanel)

```
┌─────────────────────────────────────────────────────────────┐
│  📚 知识库管理                                      [关闭 ×] │
├─────────────────────────────────────────────────────────────┤
│  统计: 15 个文档, 1200 个片段                                │
│                                                              │
│  [+ 上传文档]  [同步目录]                                    │
│                                                              │
│  文档列表:                                                   │
│  ├─ 村庄规划技术规范.pdf (150 chunks)      [删除]           │
│  ├─ 土地利用规划标准.docx (200 chunks)     [删除]           │
│  └─ 基础设施配置指南.md (50 chunks)        [删除]           │
└─────────────────────────────────────────────────────────────┘
```

## 色彩系统

### 主色调
```css
--primary-green: #16a34a;       /* green-600 主品牌色 */
--primary-green-hover: #15803d; /* green-700 悬停色 */
```

### 中性色
```css
--text-cream-primary: #FFFEF8;  /* 奶油白主背景 */
--gray-50:  #f9fafb;            /* 背景 */
--gray-100: #f3f4f6;            /* 次级背景 */
--gray-200: #e5e7eb;            /* 边框 */
--gray-700: #374151;            /* 文本 */
```

### 语义色
```css
--success-500: #22c55e;  /* 成功/完成 */
--warning-500: #eab308;  /* 警告/审查 */
--error-500:  #ef4444;   /* 错误/失败 */
--info-500:   #3b82f6;   /* 信息 */
```

### Bootstrap 兼容
```css
/* 使用 Bootstrap 5 主题色 */
--bs-primary: #16a34a;
--bs-success: #22c55e;
--bs-danger: #ef4444;
--bs-warning: #eab308;
```

## 组件样式

### 按钮
```css
.btn-primary {
  background-color: var(--primary-green);
  color: white;
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
  transition: background-color 0.2s;
}
.btn-primary:hover {
  background-color: var(--primary-green-hover);
}

.btn-success { background-color: var(--success-500); }
.btn-danger { background-color: var(--error-500); }
.btn-secondary { background-color: var(--gray-200); color: var(--gray-700); }
```

### 卡片 (Card)
```css
.card {
  background-color: white;
  border: 1px solid var(--gray-200);
  border-radius: 0.5rem;
  padding: 1rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}
```

### 消息气泡 (MessageBubble)
```css
.message-assistant {
  background-color: var(--gray-100);
  border-radius: 1rem 1rem 1rem 0;
  padding: 0.75rem 1rem;
  max-width: 80%;
}

.message-user {
  background-color: var(--primary-green);
  color: white;
  border-radius: 1rem 1rem 0 1rem;
  padding: 0.75rem 1rem;
  max-width: 80%;
  margin-left: auto;
}

.message-system {
  background-color: var(--gray-50);
  border: 1px solid var(--gray-200);
  border-radius: 0.5rem;
  padding: 0.5rem 1rem;
  text-align: center;
  color: var(--gray-700);
  font-size: 0.875rem;
}
```

## 状态样式

### 状态徽章
```css
.status-idle { 
  background: #f3f4f6; 
  color: #374151; 
}
.status-collecting { 
  background: #dbeafe; 
  color: #1e40af; 
}
.status-planning { 
  background: #dbeafe; 
  color: #1e40af; 
}
.status-paused { 
  background: #fef9c3; 
  color: #854d0e; 
}
.status-reviewing { 
  background: #fef9c3; 
  color: #854d0e; 
}
.status-revising { 
  background: #fed7aa; 
  color: #9a3412; 
}
.status-completed { 
  background: #dcfce7; 
  color: #166534; 
}
.status-failed { 
  background: #fee2e2; 
  color: #991b1b; 
}
```

### 层级状态
```css
.layer-pending { 
  opacity: 0.5; 
}
.layer-active { 
  border-left: 3px solid var(--primary-green);
  animation: pulse 2s infinite;
}
.layer-completed { 
  opacity: 1; 
}
@keyframes pulse {
  0%, 100% { border-left-color: var(--primary-green); }
  50% { border-left-color: var(--success-500); }
}
```

### 进度条
```css
.progress-bar {
  height: 0.5rem;
  background-color: var(--gray-200);
  border-radius: 0.25rem;
  overflow: hidden;
}
.progress-fill {
  background-color: var(--primary-green);
  height: 100%;
  transition: width 0.3s ease;
}
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

## 关键组件布局

### 层级报告卡片 (LayerReportCard)

```
┌─────────────────────────────────────────────────────────────┐
│  📋 Layer 1 现状分析                              [展开 ▼]  │
├─────────────────────────────────────────────────────────────┤
│  📍 区位与对外交通分析                          [查看]      │
│  金田村位于泗水镇东部，距镇中心约5公里...                    │
│                                                              │
│  👥 社会经济分析                                [查看]      │
│  全村共320户，总人口1280人...                               │
│                                                              │
│  💭 村民意愿与诉求分析                          [查看]      │
│  村民普遍希望改善基础设施...                                │
│  ... (其他维度折叠)                                         │
└─────────────────────────────────────────────────────────────┘
```

### 审查面板 (ReviewPanel)

```
┌─────────────────────────────────────────────────────────────┐
│  ⏸️ Layer 1 现状分析已完成                                   │
│  请审查后继续                                                │
├─────────────────────────────────────────────────────────────┤
│  [展开维度选择 ▼]                                           │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 选择要修改的维度:                                      │ │
│  │ ☑ 土地利用分析      ☐ 基础设施分析                    │ │
│  │ ☐ 生态绿地分析      ☐ 历史文化与乡愁保护分析          │ │
│  │                                                        │ │
│  │ 反馈意见:                                              │ │
│  │ ┌──────────────────────────────────────────────────┐   │ │
│  │ │ 土地利用分析中，耕地面积数据不准确，请核实...    │   │ │
│  │ └──────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  📄 查看详情  │  │  ❌ 驳回修改  │  │  ✅ 批准继续  │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### 维度报告流式 (DimensionReportStreaming)

```
┌─────────────────────────────────────────────────────────────┐
│  🏭 产业规划                                      [完成 ✓]  │
├─────────────────────────────────────────────────────────────┤
│  ## 一、产业发展现状                                        │
│                                                              │
│  金田村现有产业以传统农业为主，主要种植水稻、蔬菜等...      │
│  正在生成...▋                                              │
│                                                              │
│  [字数: 1250]                                               │
└─────────────────────────────────────────────────────────────┘
```

### 维度修复消息 (DimensionRevisedMessage)

```
┌─────────────────────────────────────────────────────────────┐
│  🔄 维度已修复: 土地利用规划                                │
├─────────────────────────────────────────────────────────────┤
│  📝 修改意见:                                               │
│  耕地面积需要更新为最新数据...                              │
│                                                              │
│  ✨ 修复后内容:                                             │
│  根据最新土地利用调查数据，金田村耕地面积为...              │
│                                                              │
│  [查看完整修改]  [查看历史版本]                             │
└─────────────────────────────────────────────────────────────┘
```

## 响应式断点

```css
/* 移动设备 */
@media (max-width: 640px) {
  .message { max-width: 90%; }
  .card { padding: 0.75rem; }
  .header-buttons { gap: 0.5rem; }
}

/* 平板设备 */
@media (min-width: 641px) and (max-width: 1024px) {
  .message { max-width: 85%; }
}

/* 桌面设备 */
@media (min-width: 1025px) {
  .container { max-width: 1200px; margin: 0 auto; }
  .message { max-width: 80%; }
}
```

## 动画

```css
/* 淡入动画 */
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* 滑入动画 */
@keyframes slideIn {
  from { transform: translateY(10px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

/* 脉冲动画 */
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* 应用动画 */
.message-enter {
  animation: slideIn 0.3s ease-out;
}

.loading-indicator {
  animation: pulse 1.5s infinite;
}
```

## 图标使用

### 操作图标

| 图标 | 用途 |
|------|------|
| ▶️ | 开始规划 |
| ✅ | 批准 |
| ❌ | 驳回 |
| 🔄 | 回退 / 修复 |
| 📜 | 历史 |
| 📄 | 查看详情 |
| ⏸️ | 暂停 |
| ▶️ | 继续 |
| 📚 | 知识库 |

### Layer 1 维度图标 (现状分析)

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

### Layer 2 维度图标 (规划思路)

| 图标 | 维度 |
|------|------|
| 💎 | 资源禀赋分析 |
| 🎯 | 规划定位分析 |
| 📈 | 发展目标分析 |
| 📊 | 规划策略分析 |

### Layer 3 维度图标 (详细规划)

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

## 关键交互

### 1. 开始规划
```
点击"开始规划" 
  → 表单验证
  → 显示加载状态
  → POST /api/planning/start
  → 切换到 ChatPanel
  → 启动 SSE 连接
  → 显示"规划任务已创建"消息
```

### 2. 层级完成
```
SSE layer_completed 事件
  → 添加 LayerReportMessage 到消息列表
  → 更新 completedLayers[layer] = true
  → 如果 step_mode: 显示 ReviewPanel
```

### 3. 维度流式输出
```
SSE dimension_delta 事件
  → 找到或创建 DimensionReportStreaming 组件
  → 追加 delta 到当前内容
  → 显示流式光标
```

### 4. 审查驳回
```
点击"驳回修改"
  → 展开维度选择器
  → 选择要修改的维度
  → 输入反馈意见
  → 点击"确认驳回"
  → POST /api/planning/review {action: 'reject', feedback, dimensions}
  → 显示"正在修复..."消息
```

### 5. 维度修复完成
```
SSE dimension_revised 事件
  → 添加 DimensionRevisedMessage 到消息列表
  → 更新对应维度的内容
  → 显示修复前后对比
```

### 6. 查看历史
```
点击"历史"按钮
  → 打开 HistoryPanel 抽屉
  → GET /api/data/villages
  → 显示村庄列表和会话
  → 点击会话
  → GET /api/planning/status/{id}
  → 加载历史消息和报告
```

### 7. 知识库管理
```
点击"知识库"按钮
  → 打开 KnowledgePanel 抽屉
  → GET /api/knowledge/stats
  → GET /api/knowledge/documents
  → 显示统计和文档列表
  → 上传文档 / 删除文档 / 同步目录
```

## 关键文件

| 文件 | 功能 |
|------|------|
| `styles/globals.css` | 全局样式 + CSS变量 |
| `styles/layer-report.css` | 层级报告专用样式 |
| `components/layout/UnifiedLayout.tsx` | 主布局 |
| `components/layout/Header.tsx` | 导航栏 |
| `components/chat/ChatPanel.tsx` | 聊天面板 |
| `components/chat/ReviewPanel.tsx` | 审查面板 |
| `components/chat/LayerReportCard.tsx` | 层级报告卡片 |
| `components/chat/DimensionReportStreaming.tsx` | 维度流式报告 |
| `components/layout/HistoryPanel.tsx` | 历史面板 |
| `components/layout/KnowledgePanel.tsx` | 知识库面板 |
