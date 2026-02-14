# 前端视觉设计指南 (Frontend Visual Design Guide)

> **村庄规划智能体** - UI/UX 设计规范与视觉系统

## 目录

- [设计原则](#设计原则)
- [色彩系统](#色彩系统)
- [排版系统](#排版系统)
- [组件样式](#组件样式)
- [布局规范](#布局规范)
- [交互模式](#交互模式)

---

## 设计原则

### 核心理念

1. **简洁优先**: 减少视觉干扰，聚焦核心内容
2. **清晰反馈**: 每个操作都有明确的视觉反馈
3. **一致性**: 统一的视觉语言和交互模式
4. **可访问性**: 确保所有用户都能顺畅使用
5. **性能优先**: 60fps 流畅动画，快速响应

### 设计语言

- **现代简约**: 干净的界面，充足的留白
- **卡片式布局**: 信息模块化，层次清晰
- **柔和阴影**: 轻微的深度感，不抢眼
- **圆角设计**: 友好的视觉体验

---

## 色彩系统

### 主色调

```css
/* 品牌色 - 蓝色系 */
--primary-500: #3b82f6;  /* 主色 */
--primary-600: #2563eb;
```

**使用场景**:
- 主要按钮
- 链接
- 选中状态
- 进度指示

### 中性色

```css
/* 灰色系 */
--gray-50:  #f9fafb;
--gray-100: #f3f4f6;
--gray-200: #e5e7eb;
--gray-300: #d1d5db;
--gray-700: #374151;
```

**使用场景**:
- 文本（gray-700）
- 边框（gray-200, gray-300）
- 背景（gray-50, gray-100）

### 语义色

```css
/* 成功 - 绿色 */
--success-500: #22c55e;
--success-600: #16a34a;

/* 警告 - 黄色 */
--warning-500: #eab308;
--warning-600: #ca8a04;

/* 错误 - 红色 */
--error-500:  #ef4444;
--error-600:  #dc2626;
```

**使用场景**:
- **成功**: 规划完成、审查通过
- **警告**: 需要人工审查
- **错误**: 执行失败、网络错误

---

## 排版系统

### 字体家族

```css
/* 中英文混排 */
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Helvetica Neue',
             'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
```

### 字体大小

```css
--text-xs:   0.75rem;   /* 12px */
--text-sm:   0.875rem;  /* 14px */
--text-base: 1rem;      /* 16px */
--text-lg:   1.125rem;  /* 18px */
--text-xl:   1.25rem;   /* 20px */
--text-2xl:  1.5rem;    /* 24px */
```

**使用场景**:
- **text-xs**: 辅助信息、时间戳
- **text-sm**: 次要文本、标签
- **text-base**: 正文、按钮文字
- **text-lg**: 标题、重要信息
- **text-xl**: 区块标题
- **text-2xl**: 页面标题

### 字重

```css
--font-normal:   400;
--font-medium:   500;
--font-semibold: 600;
--font-bold:     700;
```

---

## 组件样式

### 按钮

#### 主要按钮

```css
.btn-primary {
  background-color: var(--primary-500);
  color: white;
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
  font-weight: 500;
  transition: background-color 0.2s;
}

.btn-primary:hover {
  background-color: var(--primary-600);
}
```

#### 成功按钮

```css
.btn-success {
  background-color: var(--success-500);
  color: white;
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
  font-weight: 500;
}

.btn-success:hover {
  background-color: var(--success-600);
}
```

#### 危险按钮

```css
.btn-danger {
  background-color: var(--error-500);
  color: white;
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
  font-weight: 500;
}

.btn-danger:hover {
  background-color: var(--error-600);
}
```

### 卡片

```css
.card {
  background-color: white;
  border: 1px solid var(--gray-200);
  border-radius: 0.5rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  padding: 1rem;
}

.card-header {
  font-weight: 600;
  font-size: var(--text-lg);
  margin-bottom: 0.5rem;
}

.card-body {
  font-size: var(--text-base);
  color: var(--gray-700);
}
```

### 输入框

```css
.input {
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--gray-300);
  border-radius: 0.375rem;
  font-size: var(--text-base);
  transition: border-color 0.2s;
}

.input:focus {
  outline: none;
  border-color: var(--primary-500);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}
```

### 消息气泡

#### 用户消息

```css
.message-user {
  background-color: var(--primary-500);
  color: white;
  padding: 0.75rem 1rem;
  border-radius: 1rem 1rem 0 1rem;
  max-width: 80%;
  align-self: flex-end;
}
```

#### 助手消息

```css
.message-assistant {
  background-color: var(--gray-100);
  color: var(--gray-700);
  padding: 0.75rem 1rem;
  border-radius: 1rem 1rem 1rem 0;
  max-width: 80%;
  align-self: flex-start;
}
```

#### 审查消息

```css
.message-review {
  background-color: var(--warning-500);
  color: white;
  padding: 0.75rem 1rem;
  border-radius: 0.5rem;
  border-left: 4px solid var(--warning-600);
  max-width: 80%;
}
```

### 进度指示器

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
  background-color: var(--primary-500);
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
  to {
    transform: rotate(360deg);
  }
}
```

---

## 布局规范

### 间距系统

```css
--spacing-1: 0.25rem;   /* 4px */
--spacing-2: 0.5rem;    /* 8px */
--spacing-3: 0.75rem;   /* 12px */
--spacing-4: 1rem;      /* 16px */
--spacing-6: 1.5rem;    /* 24px */
--spacing-8: 2rem;      /* 32px */
```

### 容器

```css
.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 var(--spacing-4);
}
```

### 网格布局

```css
.grid {
  display: grid;
  gap: var(--spacing-4);
}

.grid-cols-1 {
  grid-template-columns: repeat(1, minmax(0, 1fr));
}

.grid-cols-2 {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.grid-cols-3 {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

@media (max-width: 768px) {
  .grid-cols-2,
  .grid-cols-3 {
    grid-template-columns: repeat(1, minmax(0, 1fr));
  }
}
```

### Flexbox 布局

```css
.flex {
  display: flex;
}

.flex-col {
  flex-direction: column;
}

.items-center {
  align-items: center;
}

.justify-between {
  justify-content: space-between;
}

.gap-4 {
  gap: var(--spacing-4);
}
```

---

## 交互模式

### 按钮状态

```css
/* 默认状态 */
.btn {
  background-color: var(--primary-500);
}

/* 悬停状态 */
.btn:hover {
  background-color: var(--primary-600);
}

/* 激活状态 */
.btn:active {
  transform: translateY(1px);
}

/* 禁用状态 */
.btn:disabled {
  background-color: var(--gray-300);
  cursor: not-allowed;
}
```

### 消息列表动画

```css
.message-item {
  animation: slideIn 0.3s ease;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
```

### 流式文本动画

```css
.streaming-text {
  display: inline;
}

.streaming-text::after {
  content: '|';
  animation: blink 1s infinite;
}

@keyframes blink {
  0%, 50% {
    opacity: 1;
  }
  51%, 100% {
    opacity: 0;
  }
}
```

### 审查交互样式

```css
.review-actions {
  display: flex;
  gap: var(--spacing-2);
  margin-top: var(--spacing-3);
}

.review-approve {
  background-color: var(--success-500);
}

.review-reject {
  background-color: var(--error-500);
}

.review-feedback {
  width: 100%;
  margin-top: var(--spacing-2);
}
```

### 状态指示器

```css
.status-indicator {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-2);
  padding: var(--spacing-1) var(--spacing-3);
  border-radius: 9999px;
  font-size: var(--text-sm);
  font-weight: 500;
}

.status-running {
  background-color: #dbeafe;
  color: #1e40af;
}

.status-completed {
  background-color: #dcfce7;
  color: #166534;
}

.status-reviewing {
  background-color: #fef9c3;
  color: #854d0e;
}

.status-failed {
  background-color: #fee2e2;
  color: #991b1b;
}
```

---

## 响应式设计

### 断点

```css
/* 移动设备 */
@media (max-width: 640px) {
  /* 移动端样式 */
}

/* 平板设备 */
@media (min-width: 641px) and (max-width: 1024px) {
  /* 平板端样式 */
}

/* 桌面设备 */
@media (min-width: 1025px) {
  /* 桌面端样式 */
}
```

### 移动端优化

```css
@media (max-width: 640px) {
  .container {
    padding: 0 var(--spacing-2);
  }

  .card {
    padding: 0.75rem;
  }

  .message-user,
  .message-assistant {
    max-width: 90%;
  }
}
```

---

## 可访问性

### 对比度

- **文本对比度**: 至少 4.5:1
- **大文本对比度**: 至少 3:1
- **UI 组件对比度**: 至少 3:1

### 焦点状态

```css
.focusable:focus {
  outline: 2px solid var(--primary-500);
  outline-offset: 2px;
}
```

### ARIA 属性

```html
<!-- 按钮示例 -->
<button
  class="btn btn-primary"
  aria-label="提交规划"
  disabled={isSubmitting}
>
  {isSubmitting ? '提交中...' : '提交'}
</button>

<!-- 进度条示例 -->
<div
  class="progress-bar"
  role="progressbar"
  aria-valuenow={completed}
  aria-valuemin={0}
  aria-valuemax={total}
>
  <div class="progress-fill" style={{ width: `${percentage}%` }} />
</div>
```

---

## 性能优化

### CSS 优化

```css
/* 使用 transform 和 opacity 进行动画 */
.animated-element {
  transform: translateX(0);
  opacity: 1;
  transition: transform 0.3s ease, opacity 0.3s ease;
}

/* 避免使用 top/left 进行动画 */
.animated-element-bad {
  top: 0;
  left: 0;
  transition: top 0.3s ease, left 0.3s ease;
}
```

### 减少重绘

```css
/* 使用 will-change 提示浏览器优化 */
.will-animate {
  will-change: transform, opacity;
}

/* 使用 transform 代替位置改变 */
.move-element {
  transform: translateX(100px);
}
```

---

## 主题定制

### Tailwind CSS 配置

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
          600: '#16a34a',
        },
        warning: {
          500: '#eab308',
          600: '#ca8a04',
        },
        error: {
          500: '#ef4444',
          600: '#dc2626',
        },
      },
      spacing: {
        '1': '0.25rem',
        '2': '0.5rem',
        '3': '0.75rem',
        '4': '1rem',
        '6': '1.5rem',
        '8': '2rem',
      },
      fontSize: {
        'xs': '0.75rem',
        'sm': '0.875rem',
        'base': '1rem',
        'lg': '1.125rem',
        'xl': '1.25rem',
        '2xl': '1.5rem',
      },
    },
  },
}
```