# 前端视觉设计指南

> UI/UX 设计规范与组件样式

## 设计原则

1. **简洁优先**: 减少视觉干扰，聚焦核心内容
2. **清晰反馈**: 每个操作都有明确视觉反馈
3. **一致性**: 统一视觉语言和交互模式
4. **后端状态驱动**: UI 完全由后端状态决定

## 页面布局

### 主布局 (UnifiedLayout)

```
┌─────────────────────────────────────────────────────────────┐
│                           Header                             │
│  Logo          项目名称              [历史] [新建]            │
├─────────────────────────────────────────────────────────────┤
│                           Main                               │
│              (Form 或 ChatPanel)                             │
└─────────────────────────────────────────────────────────────┘
```

### ChatPanel 布局

```
┌─────────────────────────────────────────────────────────────┐
│  ProgressHeader: Layer 1 ████████░░ 50%                     │
├─────────────────────────────────────────────────────────────┤
│  MessageList                                                 │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ Layer 1 完成 ▼                                           ││
│  │ ├─ 区位分析    [查看]                                    ││
│  │ ├─ 社会经济    [查看]                                    ││
│  │ └─ ...                                                   ││
│  └─────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│  ReviewPanel (条件渲染)                                      │
│  📋 Layer 1 已完成，请审查                                   │
│  [查看详情]  [驳回修改]  [批准继续]                           │
└─────────────────────────────────────────────────────────────┘
```

### 欢迎页面 (VillageInputForm)

```
┌─────────────────────────────────────────────────────────────┐
│              🏘️ 村庄规划智能体                               │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ 村庄名称: [________________]                             ││
│  │ 村庄数据: [拖拽上传或粘贴文本]                           ││
│  │ 规划要求: [________________]                             ││
│  │ [启用步进审查]                                          ││
│  │              [开始规划]                                  ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

## 色彩系统

### 主色调
```css
--primary-500: #3b82f6;  /* 品牌蓝 */
--primary-600: #2563eb;
```

### 中性色
```css
--gray-50:  #f9fafb;  /* 背景 */
--gray-100: #f3f4f6;  /* 次级背景 */
--gray-200: #e5e7eb;  /* 边框 */
--gray-700: #374151;  /* 文本 */
```

### 语义色
```css
--success-500: #22c55e;  /* 成功/完成 */
--warning-500: #eab308;  /* 警告/审查 */
--error-500:  #ef4444;   /* 错误/失败 */
```

## 组件样式

### 按钮
```css
.btn-primary {
  background-color: var(--primary-500);
  color: white;
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
}
.btn-success { background-color: var(--success-500); }
.btn-danger { background-color: var(--error-500); }
```

### 卡片 (Card)
```css
.card {
  background-color: white;
  border: 1px solid var(--gray-200);
  border-radius: 0.5rem;
  padding: 1rem;
}
```

### 消息气泡 (MessageBubble)
```css
.message-assistant {
  background-color: var(--gray-100);
  border-radius: 1rem 1rem 1rem 0;
}
.message-user {
  background-color: var(--primary-500);
  color: white;
  border-radius: 1rem 1rem 0 1rem;
}
```

## 状态样式

### 状态徽章
```css
.status-running { background: #dbeafe; color: #1e40af; }
.status-paused { background: #fef9c3; color: #854d0e; }
.status-completed { background: #dcfce7; color: #166534; }
.status-error { background: #fee2e2; color: #991b1b; }
```

### 进度条
```css
.progress-bar {
  height: 0.5rem;
  background-color: var(--gray-200);
  border-radius: 0.25rem;
}
.progress-fill {
  background-color: var(--success-500);
  transition: width 0.3s ease;
}
```

### 流式文本光标
```css
.streaming-cursor::after {
  content: '▋';
  animation: blink 1s infinite;
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
│  📍 区位分析                              [查看]            │
│  金田村位于泗水镇东部，距镇中心约5公里...                    │
│  📊 社会经济                              [查看]            │
│  全村共320户，总人口1280人...                               │
│  ... (其他维度折叠)                                         │
└─────────────────────────────────────────────────────────────┘
```

### 审查面板 (ReviewPanel)

```
┌─────────────────────────────────────────────────────────────┐
│  ⏸️ Layer 1 现状分析已完成                                   │
│  请审查后继续                                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  📄 查看详情  │  │  ❌ 驳回修改  │  │  ✅ 批准继续  │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

## 响应式断点

```css
/* 移动设备 */
@media (max-width: 640px) {
  .message { max-width: 90%; }
}

/* 桌面设备 */
@media (min-width: 1025px) {
  .container { max-width: 1200px; margin: 0 auto; }
}
```

## 动画

```css
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes slideIn {
  from { transform: translateY(10px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}
```

## 图标使用

| 图标 | 用途 |
|------|------|
| ▶️ | 开始规划 |
| ✅ | 批准 |
| ❌ | 驳回 |
| 📜 | 历史 |
| 📍 | 区位 |
| 📊 | 社会经济 |
| 🌳 | 自然环境 |
| 🏠 | 土地利用 |
| 🚗 | 道路交通 |
| 🏥 | 公共服务 |
| 💡 | 基础设施 |
| 🌿 | 生态绿地 |

## 关键交互

1. **开始规划**: 点击按钮 → 加载状态 → 跳转到 ChatPanel
2. **层级完成**: 自动弹出 LayerReportCard
3. **审查批准**: 点击批准 → 隐藏 ReviewPanel → 继续执行
4. **查看历史**: 点击历史按钮 → 打开 HistoryPanel
5. **维度查看**: 点击维度 → 展开/折叠详细内容
