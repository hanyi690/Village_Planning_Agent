# 前端视觉设计指南

> 村庄规划智能体 - UI/UX 设计规范

## 目录

- [设计原则](#设计原则)
- [色彩系统](#色彩系统)
- [排版系统](#排版系统)
- [组件样式](#组件样式)
- [状态样式](#状态样式)

---

## 设计原则

1. **简洁优先**: 减少视觉干扰，聚焦核心内容
2. **清晰反馈**: 每个操作都有明确的视觉反馈
3. **一致性**: 统一的视觉语言和交互模式
4. **性能优先**: 流畅动画，快速响应

---

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
--gray-300: #d1d5db;  /* 输入框边框 */
--gray-700: #374151;  /* 文本 */
```

### 语义色

```css
--success-500: #22c55e;  /* 成功/完成 */
--warning-500: #eab308;  /* 警告/审查 */
--error-500:  #ef4444;   /* 错误/失败 */
```

---

## 排版系统

### 字体家族

```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 
             'Microsoft YaHei', sans-serif;
```

### 字体大小

| 变量 | 大小 | 用途 |
|------|------|------|
| text-xs | 12px | 辅助信息、时间戳 |
| text-sm | 14px | 次要文本、标签 |
| text-base | 16px | 正文、按钮 |
| text-lg | 18px | 标题 |
| text-xl | 20px | 区块标题 |

---

## 组件样式

### 按钮

```css
/* 主要按钮 */
.btn-primary {
  background-color: var(--primary-500);
  color: white;
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
  font-weight: 500;
}

.btn-primary:hover {
  background-color: var(--primary-600);
}

/* 成功按钮 */
.btn-success {
  background-color: var(--success-500);
}

/* 危险按钮 */
.btn-danger {
  background-color: var(--error-500);
}
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

### 输入框

```css
.input {
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--gray-300);
  border-radius: 0.375rem;
}

.input:focus {
  outline: none;
  border-color: var(--primary-500);
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

---

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
  font-weight: 500;
}

/* 执行中 */
.status-badge-info {
  background-color: #dbeafe;
  color: #1e40af;
}

/* 完成 */
.status-badge-success {
  background-color: #dcfce7;
  color: #166534;
}

/* 审查中 */
.status-badge-warning {
  background-color: #fef9c3;
  color: #854d0e;
}

/* 失败 */
.status-badge-error {
  background-color: #fee2e2;
  color: #991b1b;
}
```

### 进度条

```css
.progress-bar {
  width: 100%;
  height: 0.5rem;
  background-color: var(--gray-200);
  border-radius: 0.25rem;
  overflow: hidden;
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

@keyframes spin {
  to { transform: rotate(360deg); }
}
```

---

## Tailwind 配置

```javascript
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        primary: {
          500: '#3b82f6',
          600: '#2563eb',
        },
        gray: {
          50: '#f9fafb',
          100: '#f3f4f6',
          200: '#e5e7eb',
          300: '#d1d5db',
          700: '#374151',
        },
        success: {
          500: '#22c55e',
        },
        warning: {
          500: '#eab308',
        },
        error: {
          500: '#ef4444',
        },
      },
    },
  },
}
```

---

## 响应式断点

```css
/* 移动设备 */
@media (max-width: 640px) {
  .container { padding: 0 0.5rem; }
  .message-user, .message-assistant { max-width: 90%; }
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
