# 前端视觉设计指南

> **村庄规划智能体** - UI/UX 设计规范与视觉系统

## 目录

- [设计原则](#设计原则)
- [色彩系统](#色彩系统)
- [排版系统](#排版系统)
- [组件样式](#组件样式)
- [布局规范](#布局规范)
- [交互模式](#交互模式)
- [动画与过渡](#动画与过渡)
- [响应式设计](#响应式设计)

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
--primary-50:  #eff6ff;
--primary-100: #dbeafe;
--primary-200: #bfdbfe;
--primary-300: #93c5fd;
--primary-400: #60a5fa;
--primary-500: #3b82f6;  /* 主色 */
--primary-600: #2563eb;
--primary-700: #1d4ed8;
--primary-800: #1e40af;
--primary-900: #1e3a8a;
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
--gray-400: #9ca3af;
--gray-500: #6b7280;
--gray-600: #4b5563;
--gray-700: #374151;
--gray-800: #1f2937;
--gray-900: #111827;
```

**使用场景**:
- 文本（gray-700, gray-800）
- 边框（gray-200, gray-300）
- 背景（gray-50, gray-100）
- 占位符（gray-400）

### 语义色

```css
/* 成功 - 绿色 */
--success-50:  #f0fdf4;
--success-500: #22c55e;
--success-600: #16a34a;
--success-700: #15803d;

/* 警告 - 黄色 */
--warning-50:  #fefce8;
--warning-500: #eab308;
--warning-600: #ca8a04;
--warning-700: #a16207;

/* 错误 - 红色 */
--error-50:   #fef2f2;
--error-500:  #ef4444;
--error-600:  #dc2626;
--error-700:  #b91c1c;

/* 信息 - 青色 */
--info-50:    #ecfeff;
--info-500:   #06b6d4;
--info-600:   #0891b2;
--info-700:   #0e7490;
```

**使用场景**:
- **成功**: 操作成功、任务完成
- **警告**: 需要注意的信息
- **错误**: 操作失败、错误消息
- **信息**: 提示、说明

### 特殊色

```css
/* 层级颜色 - 用于区分不同规划层级 */
--layer-1-color: #3b82f6;  /* 蓝色 - 现状分析 */
--layer-2-color: #8b5cf6;  /* 紫色 - 概念规划 */
--layer-3-color: #10b981;  /* 绿色 - 详细规划 */

/* 维度颜色 - 用于区分不同分析维度 */
--dim-location:           #ef4444;  /* 红 - 区位 */
--dim-socio-economic:     #f97316;  /* 橙 - 社会经济 */
--dim-natural-environment:#84cc16;  /* 黄绿 - 自然环境 */
--dim-land-use:           #10b981;  /* 绿 - 用地 */
--dim-traffic:            #06b6d4;  /* 青 - 交通 */
--dim-public-services:    #3b82f6;  /* 蓝 - 公共服务 */
--dim-infrastructure:     #6366f1;  /* 靛蓝 - 基础设施 */
--dim-ecological-system:  #8b5cf6;  /* 紫 - 生态 */
--dim-village-style:      #d946ef;  /* 粉 - 风貌 */
--dim-historical-cultural:#f43f5e;  /* 玫瑰红 - 历史 */
--dim-policy-planning:    #eab308;  /* 黄 - 政策 */
--dim-villager-wish:      #a3a3a3;  /* 灰 - 村民意愿 */
```

### 色彩应用示例

```css
/* 主要按钮 */
.btn-primary {
  background-color: var(--primary-500);
  color: white;
  &:hover {
    background-color: var(--primary-600);
  }
}

/* 次要按钮 */
.btn-secondary {
  background-color: white;
  color: var(--gray-700);
  border: 1px solid var(--gray-300);
  &:hover {
    background-color: var(--gray-50);
  }
}

/* 成功提示 */
.alert-success {
  background-color: var(--success-50);
  border-left: 4px solid var(--success-500);
  color: var(--success-700);
}

/* 错误提示 */
.alert-error {
  background-color: var(--error-50);
  border-left: 4px solid var(--error-500);
  color: var(--error-700);
}
```

---

## 排版系统

### 字体家族

```css
/* 中英文混排 */
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Helvetica Neue',
             'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;

/* 等宽字体（代码） */
font-family-mono: 'SF Mono', 'Monaco', 'Cascadia Code', 'Roboto Mono',
                  'Consolas', 'Courier New', monospace;
```

### 字体大小

```css
/* 标题 */
--text-xs:   0.75rem;   /* 12px */
--text-sm:   0.875rem;  /* 14px */
--text-base: 1rem;      /* 16px */
--text-lg:   1.125rem;  /* 18px */
--text-xl:   1.25rem;   /* 20px */
--text-2xl:  1.5rem;    /* 24px */
--text-3xl:  1.875rem;  /* 30px */
--text-4xl:  2.25rem;   /* 36px */
```

**使用场景**:
- **text-xs**: 辅助信息、标签
- **text-sm**: 次要文本、说明
- **text-base**: 正文内容（默认）
- **text-lg**: 重要内容
- **text-xl**: 小标题
- **text-2xl**: 页面标题
- **text-3xl**: 主标题
- **text-4xl**: 特大标题

### 字重

```css
--font-light: 300;
--font-normal: 400;
--font-medium: 500;
--font-semibold: 600;
--font-bold: 700;
```

**使用场景**:
- **light**: 辅助文本
- **normal**: 正文（默认）
- **medium**: 强调文本
- **semibold**: 小标题
- **bold**: 标题、重要信息

### 行高

```css
--leading-tight:   1.25;  /* 标题 */
--leading-normal:  1.5;   /* 正文 */
--leading-relaxed: 1.625; /* 长文本 */
```

### 排版示例

```css
/* 页面标题 */
.page-title {
  font-size: var(--text-3xl);
  font-weight: var(--font-bold);
  line-height: var(--leading-tight);
  color: var(--gray-900);
}

/* 卡片标题 */
.card-title {
  font-size: var(--text-xl);
  font-weight: var(--font-semibold);
  line-height: var(--leading-tight);
  color: var(--gray-800);
}

/* 正文 */
.body-text {
  font-size: var(--text-base);
  font-weight: var(--font-normal);
  line-height: var(--leading-normal);
  color: var(--gray-700);
}

/* 辅助文本 */
.helper-text {
  font-size: var(--text-sm);
  font-weight: var(--font-normal);
  line-height: var(--leading-normal);
  color: var(--gray-500);
}
```

---

## 组件样式

### 按钮

#### 主要按钮

```css
.btn-primary {
  background-color: var(--primary-500);
  color: white;
  padding: 0.625rem 1.25rem;  /* 10px 20px */
  border-radius: 0.5rem;       /* 8px */
  font-weight: var(--font-medium);
  font-size: var(--text-base);
  transition: all 0.2s ease;
  border: none;
  cursor: pointer;

  &:hover {
    background-color: var(--primary-600);
    box-shadow: 0 4px 6px -1px rgba(59, 130, 246, 0.2);
  }

  &:active {
    transform: translateY(1px);
  }

  &:disabled {
    background-color: var(--gray-300);
    cursor: not-allowed;
  }
}
```

#### 次要按钮

```css
.btn-secondary {
  background-color: white;
  color: var(--gray-700);
  padding: 0.625rem 1.25rem;
  border-radius: 0.5rem;
  font-weight: var(--font-medium);
  font-size: var(--text-base);
  transition: all 0.2s ease;
  border: 1px solid var(--gray-300);
  cursor: pointer;

  &:hover {
    background-color: var(--gray-50);
    border-color: var(--gray-400);
  }
}
```

#### 文本按钮

```css
.btn-text {
  background-color: transparent;
  color: var(--primary-500);
  padding: 0.5rem 1rem;
  border-radius: 0.375rem;
  font-weight: var(--font-medium);
  font-size: var(--text-sm);
  transition: all 0.2s ease;
  border: none;
  cursor: pointer;

  &:hover {
    background-color: var(--primary-50);
  }
}
```

### 卡片

```css
.card {
  background-color: white;
  border-radius: 0.75rem;        /* 12px */
  padding: 1.5rem;               /* 24px */
  box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1),
              0 1px 2px 0 rgba(0, 0, 0, 0.06);
  border: 1px solid var(--gray-200);
  transition: all 0.2s ease;

  &:hover {
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1),
                0 2px 4px -1px rgba(0, 0, 0, 0.06);
  }
}
```

### 输入框

```css
.input {
  width: 100%;
  padding: 0.625rem 0.875rem;   /* 10px 14px */
  border-radius: 0.5rem;        /* 8px */
  border: 1px solid var(--gray-300);
  font-size: var(--text-base);
  color: var(--gray-900);
  background-color: white;
  transition: all 0.2s ease;

  &::placeholder {
    color: var(--gray-400);
  }

  &:hover {
    border-color: var(--gray-400);
  }

  &:focus {
    outline: none;
    border-color: var(--primary-500);
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  }

  &:disabled {
    background-color: var(--gray-100);
    cursor: not-allowed;
  }
}
```

### 消息气泡

```css
/* 用户消息 */
.message-bubble.user {
  background-color: var(--primary-500);
  color: white;
  border-radius: 1rem 1rem 0 1rem;
  padding: 0.75rem 1rem;
  max-width: 70%;
  margin-left: auto;
}

/* AI 消息 */
.message-bubble.assistant {
  background-color: var(--gray-100);
  color: var(--gray-900);
  border-radius: 1rem 1rem 1rem 0;
  padding: 0.75rem 1rem;
  max-width: 70%;
  margin-right: auto;
}

/* 系统消息 */
.message-bubble.system {
  background-color: var(--info-50);
  color: var(--info-700);
  border-radius: 0.5rem;
  padding: 0.5rem 0.75rem;
  font-size: var(--text-sm);
  text-align: center;
  max-width: 100%;
}

/* 错误消息 */
.message-bubble.error {
  background-color: var(--error-50);
  color: var(--error-700);
  border: 1px solid var(--error-200);
  border-radius: 0.5rem;
  padding: 0.75rem 1rem;
}
```

### 徽章

```css
.badge {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.625rem;
  border-radius: 9999px;
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
}

/* 成功徽章 */
.badge-success {
  background-color: var(--success-50);
  color: var(--success-700);
}

/* 警告徽章 */
.badge-warning {
  background-color: var(--warning-50);
  color: var(--warning-700);
}

/* 错误徽章 */
.badge-error {
  background-color: var(--error-50);
  color: var(--error-700);
}

/* 信息徽章 */
.badge-info {
  background-color: var(--info-50);
  color: var(--info-700);
}
```

### 加载指示器

```css
/* Spinner */
.spinner {
  width: 1.5rem;
  height: 1.5rem;
  border: 2px solid var(--gray-200);
  border-top-color: var(--primary-500);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* Thinking Indicator */
.thinking-indicator {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.5rem;
}

.thinking-dot {
  width: 0.5rem;
  height: 0.5rem;
  background-color: var(--primary-500);
  border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out both;

  &:nth-child(1) { animation-delay: -0.32s; }
  &:nth-child(2) { animation-delay: -0.16s; }
  &:nth-child(3) { animation-delay: 0s; }
}

@keyframes bounce {
  0%, 80%, 100% {
    transform: scale(0.8);
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}
```

### 进度条

```css
.progress-bar {
  width: 100%;
  height: 0.5rem;
  background-color: var(--gray-200);
  border-radius: 9999px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background-color: var(--primary-500);
  transition: width 0.3s ease;
  border-radius: 9999px;

  /* 可选：添加渐变效果 */
  background: linear-gradient(
    90deg,
    var(--primary-400) 0%,
    var(--primary-500) 50%,
    var(--primary-600) 100%
  );
}
```

### 代码块

```css
.code-block {
  background-color: var(--gray-900);
  color: var(--gray-100);
  padding: 1rem;
  border-radius: 0.5rem;
  font-family: var(--font-family-mono);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  overflow-x: auto;
  position: relative;

  /* 语言标签 */
  &::before {
    content: attr(data-language);
    position: absolute;
    top: 0.5rem;
    right: 0.5rem;
    font-size: var(--text-xs);
    color: var(--gray-400);
    text-transform: uppercase;
  }
}

/* 行内代码 */
code {
  background-color: var(--gray-100);
  color: var(--gray-900);
  padding: 0.125rem 0.375rem;
  border-radius: 0.25rem;
  font-family: var(--font-family-mono);
  font-size: 0.875em;
}
```

---

## 布局规范

### 间距系统

```css
/* 间距单位（基于 4px 网格） */
--spacing-0:   0;
--spacing-1:   0.25rem;  /* 4px */
--spacing-2:   0.5rem;   /* 8px */
--spacing-3:   0.75rem;  /* 12px */
--spacing-4:   1rem;     /* 16px */
--spacing-5:   1.25rem;  /* 20px */
--spacing-6:   1.5rem;   /* 24px */
--spacing-8:   2rem;     /* 32px */
--spacing-10:  2.5rem;   /* 40px */
--spacing-12:  3rem;     /* 48px */
--spacing-16:  4rem;     /* 64px */
--spacing-20:  5rem;     /* 80px */
```

### 容器宽度

```css
.container {
  width: 100%;
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 var(--spacing-4);
}

.container-narrow {
  max-width: 768px;
}

.container-wide {
  max-width: 1536px;
}
```

### Grid 布局

```css
.grid {
  display: grid;
  gap: var(--spacing-6);
}

/* 2 列 */
.grid-cols-2 {
  grid-template-columns: repeat(2, 1fr);
}

/* 3 列 */
.grid-cols-3 {
  grid-template-columns: repeat(3, 1fr);
}

/* 4 列 */
.grid-cols-4 {
  grid-template-columns: repeat(4, 1fr);
}

/* 响应式 Grid */
.grid-responsive {
  display: grid;
  gap: var(--spacing-6);
  grid-template-columns: 1fr;

  @media (min-width: 768px) {
    grid-template-columns: repeat(2, 1fr);
  }

  @media (min-width: 1024px) {
    grid-template-columns: repeat(3, 1fr);
  }
}
```

### Flexbox 布局

```css
/* 居中对齐 */
.flex-center {
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 水平排列 */
.flex-row {
  display: flex;
  flex-direction: row;
  gap: var(--spacing-4);
}

/* 垂直排列 */
.flex-col {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-4);
}

/* 两端对齐 */
.flex-between {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
```

---

## 交互模式

### 悬停状态

```css
/* 按钮悬停 */
.button:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}

/* 卡片悬停 */
.card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
}

/* 链接悬停 */
.link:hover {
  color: var(--primary-600);
  text-decoration: underline;
}
```

### 焦点状态

```css
/* 可聚焦元素 */
*:focus-visible {
  outline: 2px solid var(--primary-500);
  outline-offset: 2px;
}

/* 按钮焦点 */
.button:focus-visible {
  outline: 2px solid var(--primary-500);
  outline-offset: 2px;
}
```

### 激活状态

```css
/* 按钮按下 */
.button:active {
  transform: translateY(1px);
}

/* 选中状态 */
.selected {
  background-color: var(--primary-50);
  border-color: var(--primary-500);
}
```

### 禁用状态

```css
.disabled {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}
```

---

## 动画与过渡

### 过渡时长

```css
--duration-fast:   150ms;
--duration-base:   200ms;
--duration-slow:   300ms;
--duration-slower: 500ms;
```

### 缓动函数

```css
--ease-linear:    linear;
--ease-in:        cubic-bezier(0.4, 0, 1, 1);
--ease-out:       cubic-bezier(0, 0, 0.2, 1);
--ease-in-out:    cubic-bezier(0.4, 0, 0.2, 1);
--ease-bounce:    cubic-bezier(0.68, -0.55, 0.265, 1.55);
```

### 常用动画

#### 淡入淡出

```css
@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes fadeOut {
  from {
    opacity: 1;
  }
  to {
    opacity: 0;
  }
}

.fade-in {
  animation: fadeIn var(--duration-base) var(--ease-in-out);
}

.fade-out {
  animation: fadeOut var(--duration-base) var(--ease-in-out);
}
```

#### 滑入滑出

```css
@keyframes slideInUp {
  from {
    transform: translateY(20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

@keyframes slideInDown {
  from {
    transform: translateY(-20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

.slide-in-up {
  animation: slideInUp var(--duration-slow) var(--ease-out);
}

.slide-in-down {
  animation: slideInDown var(--duration-slow) var(--ease-out);
}
```

#### 缩放

```css
@keyframes scaleIn {
  from {
    transform: scale(0.9);
    opacity: 0;
  }
  to {
    transform: scale(1);
    opacity: 1;
  }
}

.scale-in {
  animation: scaleIn var(--duration-base) var(--ease-out);
}
```

#### 旋转

```css
@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.spin {
  animation: spin 1s var(--ease-linear) infinite;
}
```

### 过渡效果

```css
/* 通用过渡 */
.transition {
  transition: all var(--duration-base) var(--ease-in-out);
}

/* 颜色过渡 */
.transition-colors {
  transition: color var(--duration-base) var(--ease-in-out),
              background-color var(--duration-base) var(--ease-in-out),
              border-color var(--duration-base) var(--ease-in-out);
}

/* 阴影过渡 */
.transition-shadow {
  transition: box-shadow var(--duration-base) var(--ease-in-out);
}

/* 变换过渡 */
.transition-transform {
  transition: transform var(--duration-base) var(--ease-in-out);
}
```

---

## 响应式设计

### 断点系统

```css
/* 断点 */
--breakpoint-sm:  640px;   /* 手机横屏 */
--breakpoint-md:  768px;   /* 平板竖屏 */
--breakpoint-lg:  1024px;  /* 平板横屏 / 小笔记本 */
--breakpoint-xl:  1280px;  /* 桌面 */
--breakpoint-2xl: 1536px;  /* 大屏桌面 */
```

### 媒体查询

```css
/* Mobile First */
.container {
  padding: 0 var(--spacing-4);
}

@media (min-width: 768px) {
  .container {
    padding: 0 var(--spacing-6);
  }
}

@media (min-width: 1024px) {
  .container {
    padding: 0 var(--spacing-8);
  }
}

/* Desktop First */
.sidebar {
  width: 256px;

  @media (max-width: 1024px) {
    width: 200px;
  }

  @media (max-width: 768px) {
    display: none;
  }
}
```

### 响应式字体

```css
/* 标题 */
.responsive-title {
  font-size: var(--text-2xl);

  @media (min-width: 768px) {
    font-size: var(--text-3xl);
  }

  @media (min-width: 1024px) {
    font-size: var(--text-4xl);
  }
}

/* 正文 */
.responsive-text {
  font-size: var(--text-sm);

  @media (min-width: 768px) {
    font-size: var(--text-base);
  }
}
```

### 响应式布局

```css
/* 卡片网格 */
.card-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--spacing-4);

  @media (min-width: 640px) {
    grid-template-columns: repeat(2, 1fr);
  }

  @media (min-width: 1024px) {
    grid-template-columns: repeat(3, 1fr);
  }

  @media (min-width: 1280px) {
    grid-template-columns: repeat(4, 1fr);
  }
}
```

---

## 可访问性

### 颜色对比度

确保文本和背景之间的对比度至少为：
- **WCAG AA**: 4.5:1（正常文本），3:1（大文本）
- **WCAG AAA**: 7:1（正常文本），4.5:1（大文本）

### 键盘导航

```css
/* 跳过链接 */
.skip-link {
  position: absolute;
  top: -40px;
  left: 0;
  background: var(--primary-500);
  color: white;
  padding: 8px;
  z-index: 100;

  &:focus {
    top: 0;
  }
}

/* 焦点指示器 */
:focus-visible {
  outline: 2px solid var(--primary-500);
  outline-offset: 2px;
}
```

### ARIA 标签

```tsx
/* 按钮 */
<button
  aria-label="关闭对话框"
  aria-pressed="false"
>
  <CloseIcon />
</button>

/* 加载状态 */
<div
  role="status"
  aria-live="polite"
  aria-busy="true"
>
  <Spinner />
  <span>加载中...</span>
</div>

/* 错误消息 */
<div
  role="alert"
  aria-live="assertive"
>
  操作失败，请重试
</div>
```

---

## 性能优化

### 减少重绘

```css
/* 使用 transform 而不是 top/left */
.animated-element {
  transform: translateX(100px);  /* ✅ 硬件加速 */
  /* top: 100px; left: 100px;     ❌ 触发重绘 */
}

/* 使用 opacity 而不是 visibility */
.fade-element {
  opacity: 0;  /* ✅ GPU 加速 */
  /* visibility: hidden;  ❌ CPU 渲染 */
}
```

### will-change 提示

```css
/* 提示浏览器优化 */
.animated-element {
  will-change: transform, opacity;
}

/* 动画结束后移除 */
.animated-element.finished {
  will-change: auto;
}
```

### 减少阴影模糊

```css
/* 使用简单的阴影 */
.card {
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);  /* ✅ 快 */
  /* box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);  ❌ 慢 */
}
```

---

## 设计资源

### 图标库

- **Heroicons**: https://heroicons.com/
- **Lucide**: https://lucide.dev/
- **Phosphor Icons**: https://phosphoricons.com/

### 字体

- **Inter**: https://rsms.me/inter/
- **Noto Sans SC**: https://fonts.google.com/noto/specimen/Noto+Sans+SC

### 颜色工具

- **Coolors**: https://coolors.co/
- **Adobe Color**: https://color.adobe.com/zh/create/color-wheel

### 设计灵感

- **Dribbble**: https://dribbble.com/
- **Behance**: https://www.behance.net/
- **Awwwards**: https://www.awwwards.com/

---

## 实施指南

### 使用 Tailwind CSS

项目使用 Tailwind CSS，所有设计变量都已映射到 Tailwind 类：

```tsx
// 间距
<div className="p-4 m-2">...</div>

// 颜色
<button className="bg-blue-500 text-white">...</button>

// 字体
<h1 className="text-3xl font-bold">...</h1>

// 响应式
<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3">...</div>

// 状态
<button className="hover:bg-blue-600 focus:ring-2 active:scale-95">...</button>
```

### 自定义主题

```js
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#eff6ff',
          500: '#3b82f6',
          600: '#2563eb',
        },
        // ...
      },
      spacing: {
        '18': '4.5rem',
        '88': '22rem',
      },
    },
  },
}
```

### 组件库

项目使用 shadcn/ui 作为基础组件库：

```bash
# 添加组件
npx shadcn-ui@latest add button
npx shadcn-ui@latest add card
npx shadcn-ui@latest add dialog
```

---

## 最新改进 (2024年) ⭐

### 代码架构优化

虽然本指南主要关注视觉设计，但2024年的前端架构简化也间接提升了视觉系统的一致性和可维护性。

#### 1. 类型系统重构

**改进**: 将类型定义从单一文件拆分为5个专注文件

**对视觉系统的影响**:
- ✅ 更清晰的类型定义使组件Props更明确
- ✅ 类型守卫确保视觉组件接收到正确的数据
- ✅ 统一的消息类型定义保证了UI渲染的一致性

**相关文件**:
```
types/
├── message.ts          # 核心类型
├── message-types.ts    # 具体消息类型
├── message-guards.ts   # 类型守卫
└── index.ts            # 统一导出
```

#### 2. 组件精简

**改进**: 删除未使用文件，简化现有组件

**删除的组件**:
- `frontend/src/config/features.ts` (238行) - 未使用的特性标志
- `frontend/src/components/report/index.ts` (8行) - 占位符文件

**简化的组件**:
- `ChatPanel.tsx`: 从1,033行减少到~640行
- `StreamingText.tsx`: 已经是thin wrapper,保持简洁

**对视觉系统的影响**:
- ✅ 减少了视觉组件的复杂度
- ✅ 提高了渲染性能
- ✅ 保持了视觉一致性

#### 3. 共享常量提取

**新增**: `frontend/src/lib/constants.ts`

**内容包括**:
```typescript
// 层级颜色映射
export const LAYER_COLOR_MAP = {
  1: '#3b82f6',  // 蓝色 - 现状分析
  2: '#8b5cf6',  // 紫色 - 规划思路
  3: '#10b981',  // 绿色 - 详细规划
};

// 层级标签映射
export const LAYER_LABEL_MAP = {
  1: '现状分析',
  2: '规划思路',
  3: '详细规划',
};
```

**对视觉系统的影响**:
- ✅ **统一的层级颜色** - 所有组件使用相同的颜色定义
- ✅ **一致的标签文本** - 避免硬编码带来的不一致
- ✅ **集中管理** - 更新设计时只需修改一处

#### 4. 样式一致性提升

**改进**: 通过代码组织优化提升了样式一致性

**具体改进**:
- 统一的导入路径 (`@/types` 替代具体路径)
- 共享的样式工具函数 (`lib/utils/`)
- 一致的错误处理模式

**对视觉系统的影响**:
- ✅ 减少了样式重复
- ✅ 提高了视觉一致性
- ✅ 简化了样式维护

### 视觉系统维护建议

基于2024年的架构改进,以下是维护视觉系统的最佳实践:

#### 1. 使用共享常量

**推荐**:
```tsx
// ✅ 使用共享常量
import { LAYER_COLOR_MAP } from '@/lib/constants';

<div style={{ color: LAYER_COLOR_MAP[layer] }}>
  {title}
</div>
```

**避免**:
```tsx
// ❌ 硬编码颜色
<div style={{ color: layer === 1 ? '#3b82f6' : layer === 2 ? '#8b5cf6' : '#10b981' }}>
  {title}
</div>
```

#### 2. 利用类型系统

**推荐**:
```tsx
// ✅ 使用类型守卫确保数据正确
import { isLayerCompletedMessage } from '@/types';

if (isLayerCompletedMessage(message)) {
  return <LayerReportCard layer={message.layer} summary={message.summary} />;
}
```

#### 3. 组件样式复用

**推荐**:
```tsx
// ✅ 使用 Tailwind 类组合
import { cn } from '@/lib/utils/cn';

const cardBase = "bg-white rounded-lg shadow-md p-6";
const cardHover = "hover:shadow-lg transition-shadow";

<div className={cn(cardBase, cardHover, className)}>
  {children}
</div>
```

#### 4. 遵循设计令牌

**颜色**:
```tsx
// 使用 Tailwind 的设计令牌
className="bg-primary-500 text-white"
className="border-gray-200 hover:border-gray-300"
```

**间距**:
```tsx
// 使用 Tailwind 的间距系统
className="p-4 m-2 gap-6"
```

**字体**:
```tsx
// 使用 Tailwind 的字体系统
className="text-base font-medium"
```

### 未来规划

基于当前的架构改进,视觉系统的未来规划包括:

1. **设计令牌库** - 提取所有设计变量到统一文件
2. **组件文档化** - 使用 Storybook 记录所有视觉组件
3. **暗色模式** - 基于当前色彩系统扩展暗色主题
4. **可访问性增强** - 添加更多 ARIA 标签和键盘导航
5. **动画库** - 基于 Framer Motion 统一动画效果

### 相关文档

如需了解更多关于代码架构的改进,请参阅:
- **[前端组件架构](FRONTEND_COMPONENT_ARCHITECTURE.md)** - 详细的组件架构说明
- **[前端实现文档](docs/前端.md)** - 完整的技术栈和实现细节
- **[README](README.md)** - 项目概述和快速开始

---

## 常见问题

### Q: 如何自定义颜色？

A: 修改 `tailwind.config.js` 或使用 CSS 变量：

```css
:root {
  --custom-color: #your-color;
}
```

### Q: 如何实现暗色模式？

A: 使用 Tailwind 的暗色模式：

```tsx
<div className="bg-white dark:bg-gray-900">
  <h1 className="text-gray-900 dark:text-white">标题</h1>
</div>
```

### Q: 如何优化动画性能？

A:
1. 使用 `transform` 和 `opacity`
2. 添加 `will-change` 提示
3. 使用 `requestAnimationFrame`
4. 避免强制同步布局

---

## 参考资源

- [Tailwind CSS 文档](https://tailwindcss.com/docs)
- [shadcn/ui 组件](https://ui.shadcn.com/)
- [Figma 设计资源](https://www.figma.com/)
- [WCAG 可访问性指南](https://www.w3.org/WAI/WCAG21/quickref/)
