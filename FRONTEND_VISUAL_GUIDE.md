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
│  ├─ 🚀 规划任务已创建...                                     │
│  ├─ 📋 Layer 1 现状分析已完成                                │
│  │   ├─ 📍 区位与对外交通分析    [查看]                      │
│  │   └─ ...                                                  │
│  └─ 📝 维度报告（流式中...）▋                                │
├─────────────────────────────────────────────────────────────┤
│  ReviewPanel (条件渲染: isPaused && pendingReviewLayer)     │
│  ⏸️ Layer 1 现状分析已完成，请审查                           │
│  [驳回维度选择] [反馈意见输入]                               │
│  [查看详情]  [❌ 驳回修改]  [✅ 批准继续]                    │
└─────────────────────────────────────────────────────────────┘
```

## 色彩系统

### 主色调
```css
--primary-green: #16a34a;       /* 主品牌色 */
--primary-green-hover: #15803d; /* 悬停色 */
```

### 语义色
```css
--success: #22c55e;  /* 成功/完成 */
--warning: #eab308;  /* 警告/审查 */
--error:   #ef4444;  /* 错误/失败 */
--info:    #3b82f6;  /* 信息 */
```

## 组件样式

### 消息气泡 (MessageBubble)

```css
.message-assistant {
  background-color: var(--gray-100);
  border-radius: 1rem 1rem 1rem 0;
  max-width: 80%;
}

.message-user {
  background-color: var(--primary-green);
  color: white;
  border-radius: 1rem 1rem 0 1rem;
  margin-left: auto;
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

### 状态徽章

```css
.status-paused { background: #fef9c3; color: #854d0e; }
.status-completed { background: #dcfce7; color: #166534; }
.status-failed { background: #fee2e2; color: #991b1b; }
```

## 维度图标

### Layer 1: 现状分析

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

### Layer 2: 规划思路

| 图标 | 维度 |
|------|------|
| 💎 | 资源禀赋分析 |
| 🎯 | 规划定位分析 |
| 📈 | 发展目标分析 |
| 📊 | 规划策略分析 |

### Layer 3: 详细规划

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

## 关键交互流程

### 1. 开始规划
```
点击"开始规划" 
  → 表单验证
  → POST /api/planning/start
  → 切换到 ChatPanel
  → 启动 SSE 连接
```

### 2. 层级完成
```
SSE layer_completed 事件
  → 添加 LayerReportMessage
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
  → 选择维度 + 输入反馈
  → POST /api/planning/review {action: 'reject'}
  → 显示"正在修复..."消息
```

### 5. 维度修复完成
```
SSE dimension_revised 事件
  → 添加 DimensionRevisedMessage
  → 显示修复前后对比
```

## 响应式断点

```css
@media (max-width: 640px) {
  .message { max-width: 90%; }
}

@media (min-width: 1025px) {
  .container { max-width: 1200px; }
  .message { max-width: 80%; }
}
```

## 关键文件

| 文件 | 功能 |
|------|------|
| `styles/globals.css` | 全局样式 + CSS变量 |
| `components/layout/UnifiedLayout.tsx` | 主布局 |
| `components/chat/ChatPanel.tsx` | 聊天面板 |
| `components/chat/ReviewPanel.tsx` | 审查面板 |
| `components/chat/LayerReportMessage.tsx` | 层级报告 |
| `components/chat/DimensionReportStreaming.tsx` | 维度流式报告 |