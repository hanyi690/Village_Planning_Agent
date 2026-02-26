# 前端视觉设计指南

> UI/UX 设计规范与组件样式

## 设计原则

1. **简洁优先**: 减少视觉干扰，聚焦核心内容
2. **清晰反馈**: 每个操作都有明确视觉反馈
3. **一致性**: 统一视觉语言和交互模式

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

## 排版

### 字体

```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 
             'PingFang SC', 'Microsoft YaHei', sans-serif;
```

### 字号

| 类名 | 大小 | 用途 |
|------|------|------|
| text-xs | 12px | 辅助信息 |
| text-sm | 14px | 次要文本 |
| text-base | 16px | 正文 |
| text-lg | 18px | 标题 |

## 页面布局

### 主布局

```
┌─────────────────────────────────────────────────────────────┐
│                           Header                             │
│  Logo          项目名称              [历史] [设置]            │
├─────────────────────────────────────────────────────────────┤
│                           Main                               │
│                                                              │
│                     Content                                  │
│              (Form 或 ChatPanel)                             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### ChatPanel 布局

```
┌─────────────────────────────────────────────────────────────┐
│  ProgressHeader                                              │
│  Layer 1 ████████░░░░░░░░  50%      状态: 执行中             │
├─────────────────────────────────────────────────────────────┤
│  MessageList                                                 │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ 开始规划金田村...                                        ││
│  └─────────────────────────────────────────────────────────┘│
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

## 组件样式

### 按钮

```css
/* 主要按钮 */
.btn-primary {
  background-color: var(--primary-500);
  color: white;
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
}

/* 成功按钮 */
.btn-success { background-color: var(--success-500); }

/* 危险按钮 */
.btn-danger { background-color: var(--error-500); }
```

### 卡片

```css
.card {
  background-color: white;
  border: 1px solid var(--gray-200);
  border-radius: 0.5rem;
  padding: 1rem;
}
```

### 消息气泡

```css
/* 助手消息 */
.message-assistant {
  background-color: var(--gray-100);
  border-radius: 1rem 1rem 1rem 0;
  padding: 0.75rem 1rem;
  max-width: 80%;
}

/* 用户消息 */
.message-user {
  background-color: var(--primary-500);
  color: white;
  border-radius: 1rem 1rem 0 1rem;
}
```

## 状态样式

### 状态徽章

```css
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0.75rem;
  border-radius: 9999px;
  font-size: 0.875rem;
}

.status-badge-info { background: #dbeafe; color: #1e40af; }
.status-badge-success { background: #dcfce7; color: #166534; }
.status-badge-warning { background: #fef9c3; color: #854d0e; }
.status-badge-error { background: #fee2e2; color: #991b1b; }
```

### 进度条

```css
.progress-bar {
  width: 100%;
  height: 0.5rem;
  background-color: var(--gray-200);
  border-radius: 0.25rem;
}

.progress-fill {
  height: 100%;
  background-color: var(--success-500);
  transition: width 0.3s ease;
}
```

### 加载动画

```css
.spinner {
  width: 1.5rem;
  height: 1.5rem;
  border: 2px solid var(--gray-200);
  border-top-color: var(--primary-500);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }
```

## 响应式断点

```css
/* 移动设备 */
@media (max-width: 640px) {
  .container { padding: 0 0.5rem; }
  .message { max-width: 90%; }
}

/* 平板设备 */
@media (min-width: 641px) and (max-width: 1024px) {
  .container { padding: 0 1rem; }
}

/* 桌面设备 */
@media (min-width: 1025px) {
  .container { max-width: 1200px; margin: 0 auto; }
}
```

## 动画

```css
/* 淡入 */
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* 滑入 */
@keyframes slideIn {
  from { transform: translateY(10px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

/* 打字光标 */
.typing-cursor::after {
  content: '|';
  animation: blink 1s infinite;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}
```

## 图标

使用 Font Awesome:

| 图标 | 用途 |
|------|------|
| fa-play | 开始规划 |
| fa-check | 批准 |
| fa-times | 驳回 |
| fa-history | 历史 |
| fa-folder | 文件夹 |
| fa-map-marker-alt | 区位 |
