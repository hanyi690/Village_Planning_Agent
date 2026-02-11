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

/* 信息 - 蓝色 */
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
--text-2xl: 1.5rem;    /* 24px */
--text-3xl: 1.875rem;  /* 30px */
--text-4xl: 2.25rem;   /* 36px */
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
--leading-normal: 1.5;   /* 正文 */
--leading-relaxed: 1.625; /* 长文本 */
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
```

### 焦点状态

```css
/* 可聚焦元素 */
*:focus-visible {
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
  from { opacity: 0; }
  to { opacity: 1; }
}

.fade-in {
  animation: fadeIn var(--duration-base) var(--ease-in-out);
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

.slide-in-up {
  animation: slideInUp var(--duration-slow) var(--ease-out);
}
```

#### 流式文本打字机效果

```css
/* 流式文本光标动画 */
@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

.streaming-cursor {
  display: inline-block;
  width: 2px;
  height: 1em;
  background: var(--primary-500);
  animation: blink 1s infinite;
  vertical-align: middle;
  margin-left: 2px;
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
```

---

## 审查面板视觉规范

### 审查面板视觉状态

```css
/* Pending State - 等待审查 */
.review-panel.pending {
  display: flex;
  opacity: 1;
  animation: slideIn 0.3s ease-out;
}

/* Approved State - 已批准 */
.review-panel.approved {
  opacity: 0.7;
  pointer-events: none;
  transition: opacity 0.2s ease;
}

/* 审查按钮样式 */
.btn-approve {
  background-color: var(--success-500);
  color: white;
  padding: 0.625rem 1.25rem;
  border-radius: 0.5rem;
  transition: all 0.2s ease;

  &:hover {
    background-color: var(--success-600);
    box-shadow: 0 4px 6px -1px rgba(34, 197, 94, 0.2);
  }

  &:active {
    transform: translateY(1px);
  }
}

.btn-reject {
  background-color: var(--error-500);
  /* ... */
}

.btn-rollback {
  background-color: var(--warning-500);
  /* ... */
}
```

### 检查点时间轴样式

```css
/* 时间轴容器 */
.checkpoint-timeline {
  position: relative;
  padding-left: 2rem;
  border-left: 2px solid var(--gray-200);
}

/* 时间轴节点 */
.checkpoint-node {
  position: absolute;
  left: -0.625rem;
  width: 1.25rem;
  height: 1.25rem;
  border-radius: 50%;
  background: var(--primary-500);
  border: 3px solid white;
  box-shadow: 0 0 0 3px var(--primary-100);
}

/* 已完成状态 */
.checkpoint-node.completed {
  background: var(--success-500);
  box-shadow: 0 0 0 3px var(--success-100);
}

/* 当前状态 */
.checkpoint-node.current {
  background: var(--warning-500);
  box-shadow: 0 0 0 3px var(--warning-100);
  animation: pulse 2s infinite;
}
```

---

## 维度区块样式 (2025) ⭐ NEW

### 维度卡片布局

```css
/* 维度容器 */
.dimension-section {
  background: white;
  border-radius: 0.75rem;
  border: 1px solid var(--gray-200);
  padding: 1.5rem;
  margin-bottom: 1rem;
}

/* 维度头部 */
.dimension-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

/* 维度标签 - 按颜色区分 */
.dimension-tag {
  padding: 0.25rem 0.75rem;
  border-radius: 9999px;
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: white;
}

.dimension-tag.location {
  background: var(--dim-location);
}

.dimension-tag.socio-economic {
  background: var(--dim-socio-economic);
}

/* 维度内容 */
.dimension-content {
  line-height: var(--leading-relaxed);
  color: var(--gray-700);
}

/* 流式加载状态 */
.dimension-content.streaming::after {
  content: '';
  display: inline-block;
  width: 2px;
  height: 1em;
  background: var(--primary-500);
  animation: blink 1s infinite;
  vertical-align: middle;
  margin-left: 2px;
}
```

### 进度指示器

```css
/* 维度进度条 */
.dimension-progress {
  width: 100%;
  height: 4px;
  background: var(--gray-200);
  border-radius: 9999px;
  overflow: hidden;
}

.dimension-progress-bar {
  height: 100%;
  background: var(--primary-500);
  border-radius: 9999px;
  transition: width 0.3s ease;
}

/* 层级进度 */
.layer-progress-indicator {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: var(--primary-50);
  border-radius: 9999px;
  font-size: var(--text-sm);
  color: var(--primary-700);
}
```

---

## 最新改进 (2024-2025) ⭐

### 维度级流式响应架构 (2025) ⭐⭐⭐

**架构升级**: 维度级实时流式推送

**视觉影响**:
- ✅ **更流畅的打字机效果** - Token 批处理渲染，< 100ms 延迟
- ✅ **维度独立更新** - 每个维度独立显示进度
- ✅ **更少的闪烁** - RAF 批处理减少 DOM 更新 > 80%
- ✅ **更好的视觉反馈** - 层级进度百分比实时显示

### 类型系统重构 (2024)

**改进**: 将类型定义从单一文件拆分为5个专注文件

**对视觉系统的影响**:
- ✅ 更清晰的类型定义使组件 Props 更明确
- ✅ 类型守卫确保视觉组件收到正确的数据
- ✅ 统一的消息类型定义保证了 UI 渲染的一致性

### 组件精简 (2024)

**改进**: 删除未使用文件，简化现有组件

**对视觉系统的影响**:
- ✅ 减少了视觉组件的复杂度
- ✅ 提高了渲染性能
- ✅ 保持了视觉一致性

---

## 设计资源

### 图标库

- **Heroicons**: https://heroicons.com/
- **Lucide**: https://lucide.dev/
- **Phosphor Icons**: https://phosphoricons.com/

### 字体

- **Inter**: https://rsms.me/inter/
- **Noto Sans SC**: https://fonts.google.com/noto/specimen/Noto+Sans+SC

### 色彩工具

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

---

## 相关文档

- **[前端组件架构](FRONTEND_COMPONENT_ARCHITECTURE.md)** - 详细的组件架构说明
- **[前端实现文档](docs/frontend.md)** - Next.js 14 技术栈、维度级流式响应
- **[后端实现文档](docs/backend.md)** - FastAPI 架构、流式队列、异步存储
- **[核心智能体文档](docs/agent.md)** - LangGraph 架构、三层规划系统
- **[README](README.md)** - 项目概述和快速开始
