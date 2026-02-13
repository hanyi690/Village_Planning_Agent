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
```

### 字重

```css
--font-normal: 400;
--font-medium: 500;
--font-semibold: 600;
--font-bold: 700;
```

---

## 组件样式

### 按钮

#### 主要按钮

```css
.btn-primary {
  background-color: var(--primary-500);
  color: white;
  padding: 0.625rem 1.25rem;
  border-radius: 0.5rem;
  font-weight: var(--font-medium);
  transition: all 0.2s ease;

  &:hover {
    background-color: var(--primary-600);
    box-shadow: 0 4px 6px -1px rgba(59, 130, 246, 0.2);
  }
}
```

### 卡片

```css
.card {
  background-color: white;
  border-radius: 0.75rem;
  padding: 1.5rem;
  box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1);
  border: 1px solid var(--gray-200);
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
}

/* AI 消息 */
.message-bubble.assistant {
  background-color: var(--gray-100);
  color: var(--gray-900);
  border-radius: 1rem 1rem 1rem 0;
}
```

---

## 布局规范

### 间距系统

```css
/* 间距单位（基于 4px 网格） */
--spacing-1:   0.25rem;  /* 4px */
--spacing-2:   0.5rem;   /* 8px */
--spacing-4:   1rem;     /* 16px */
--spacing-6:   1.5rem;   /* 24px */
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
```

---

## 相关文档

- **[前端组件架构](FRONTEND_COMPONENT_ARCHITECTURE.md)** - 详细的组件架构说明
- **[前端实现文档](docs/frontend.md)** - Next.js 14 技术栈、维度级流式响应
- **[后端实现文档](docs/backend.md)** - FastAPI 架构、异步数据库
- **[核心智能体文档](docs/agent.md)** - LangGraph 架构、三层规划系统
- **[README](README.md)** - 项目概述和快速开始

---

**最后更新**: 2026-02-12
**维护者**: Village Planning Agent Team
