# Layer 报告消息改进 - 维度内容高度限制和图标点击功能

## Context

用户要求对 Layer 报告消息中的维度内容进行两项改进：
1. 去除维度内容的高度限制
2. 维度标题左侧的图标（如 `fa-file-alt`）需要可点击，点击后在侧边栏查看该维度的完整内容

背景：
- `LayerReportMessage.tsx` 已经修改完成（`defaultExpanded={true}`, `maxHeight="none"`）
- 但 `LayerReportCard` 和 `DimensionSection` 仍有限制需要处理

## 当前实现分析

### 1. LayerReportCard 的高度限制
**文件**: `frontend/src/components/chat/LayerReportCard.tsx` (行 208-218)

```tsx
{/* Dimension sections */}
<div
  className="space-y-3"
  style={{
    maxHeight: localExpanded
      ? '80vh'        // ← 展开时限制为 80vh
      : mode === 'chat' && !localExpanded
        ? actualMaxHeight
        : 'none',
    overflow: 'auto',
  }}
>
```

**问题**: 即使 `localExpanded` 为 true，内容也被限制在 `80vh` 高度内。

### 2. DimensionSection 的图标
**文件**: `frontend/src/components/chat/DimensionSection.tsx` (行 68-69)

```tsx
<h4 className="flex items-center gap-2 text-sm font-semibold text-emerald-800">
  <i className={`fas ${icon} text-emerald-500`} />
  {name}
</h4>
```

**问题**: 图标只是装饰性的，没有点击事件来查看完整内容。

## 实现方案

### 修改 1: LayerReportCard.tsx - 移除 80vh 限制

**位置**: 行 212-213

```tsx
// 修改前
maxHeight: localExpanded
  ? '80vh'
  : mode === 'chat' && !localExpanded
    ? actualMaxHeight
    : 'none',

// 修改后
maxHeight: 'none',
```

### 修改 2: DimensionSection.tsx - 添加图标点击事件

**需求**: 点击维度图标时，在侧边栏中查看该维度的完整内容。

**实现步骤**:

#### 2a. DimensionSection.tsx - 添加 onOpenInSidebar prop
```tsx
interface DimensionSectionProps {
  name: string;
  content: string;
  icon: string;
  subsections?: ParsedSubsection[];
  defaultExpanded?: boolean;
  onCopy?: () => void;
  onExport?: () => void;
  onOpenInSidebar?: () => void;  // 新增
}

// 图标添加点击事件
<h4 className="flex items-center gap-2 text-sm font-semibold text-emerald-800">
  <i
    className={`fas ${icon} text-emerald-500 cursor-pointer hover:text-emerald-700 transition-colors`}
    onClick={(e) => {
      e.stopPropagation();
      onOpenInSidebar?.();
    }}
    title="在侧边栏查看完整内容"
  />
  {name}
</h4>
```

#### 2b. LayerReportCard.tsx - 传递 onOpenInSidebar 到 DimensionSection
```tsx
{dimensions.map((dimension, index) => (
  <DimensionSection
    key={index}
    name={dimension.name}
    content={dimension.content}
    icon={dimension.icon}
    subsections={dimension.subsections}
    defaultExpanded={allExpanded || actualDefaultExpanded}
    onCopy={() => handleCopyDimension(dimension.name, dimension.content)}
    onExport={() => handleExportDimension(dimension.name, dimension.content)}
    onOpenInSidebar={() => {
      // TODO: 如何在侧边栏中显示单个维度内容？
    }}
  />
))}
```

### 问题：侧边栏如何显示单个维度内容？

当前 `LayerSidebar` 是显示整个 Layer 的报告，不支持单独显示某个维度。

**可能的解决方案**:

**方案 A**: 修改 `LayerSidebar` 支持高亮/聚焦特定维度
- 添加 `highlightDimension` prop
- 侧边栏中自动展开并滚动到该维度

**方案 B**: 创建轻量级的维度内容查看器
- 类似 Modal 的简单侧边栏
- 只显示维度名称和内容

**方案 C (推荐)**: 复用 LayerSidebar，传递层号和维度名称
- 打开侧边栏时自动展开对应维度
- 保持 UI 一致性

## 推荐实现

考虑到代码复用和用户体验，推荐方案 C：

1. `LayerSidebar` 添加 `highlightDimensionKey` prop
2. 在侧边栏打开时，自动展开并滚动到指定的维度
3. `DimensionSection` 的图标点击时，传递 layer 和 dimensionKey 打开侧边栏

## 关键文件路径

- `frontend/src/components/chat/LayerReportCard.tsx` - 移除 80vh 限制
- `frontend/src/components/chat/DimensionSection.tsx` - 添加图标点击事件
- `frontend/src/components/layer/LayerSidebar.tsx` - 添加维度高亮功能
- `frontend/src/components/chat/LayerReportMessage.tsx` - 传递 onOpenInSidebar（已完成）

## 验证步骤

1. 启动前端开发服务器
2. 查看 Layer 报告消息
3. 确认报告默认展开，无高度截断
4. 确认维度内容区域无 80vh 限制
5. 点击维度图标（如文件图标）
6. 侧边栏打开，显示该层完整报告
7. 对应维度自动展开并高亮显示
