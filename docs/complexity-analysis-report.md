# 系统代码复杂度分析报告

## 概述

本次分析统计了整个 Village_Planning_Agent 项目的代码行数和复杂度，识别出需要关注的高复杂度文件。

**统计范围**: 排除 `.venv`, `node_modules`, `__pycache__`, `.git`, `.next` 等目录

---

## Python 后端复杂度分析

### 🔴 高复杂度文件 (>800 行或复杂度评分 > 1500)

| 文件 | 行数 | 函数 | 类 | 复杂度评分 | 问题 |
|------|------|------|----|----|------|
| `backend/api/planning.py` | 1313 | 24 | 6 | 1943 | **API 层过重，需继续拆分** |
| `src/subgraphs/detailed_plan_prompts.py` | 1807 | 3 | 0 | 1915 | **提示词文件过大** |
| `backend/database/operations_async.py` | 1028 | 31 | 0 | 1665 | 数据库操作集中 |
| `src/config/dimension_metadata.py` | 1128 | 22 | 0 | 1624 | 配置数据庞大 |
| `src/rag/utils/loaders.py` | 833 | 26 | 7 | 1266 | 加载器集合 |
| `src/tools/geocoding/tianditu_provider.py` | 823 | 17 | 2 | 1103 | 地理编码服务 |
| `src/orchestration/nodes/revision_node.py` | 866 | 13 | 2 | 1091 | 修订节点逻辑 |
| `src/subgraphs/analysis_prompts.py` | 972 | 4 | 0 | 1050 | **提示词文件过大** |

### 🟡 中等复杂度文件 (500-800 行)

| 文件 | 行数 | 函数 | 类 | 状态 |
|------|------|------|----|----|
| `src/planners/generic_planner.py` | 798 | 27 | 3 | ✓ |
| `backend/services/sse_manager.py` | 658 | 30 | 1 | ✓ |
| `backend/services/planning_service.py` | 700 | 13 | 1 | ✓ |
| `src/orchestration/nodes/dimension_node.py` | 652 | 16 | 0 | ✓ |
| `src/rag/core/tools.py` | 631 | 18 | 0 | ✓ |
| `src/orchestration/main_graph.py` | 601 | 15 | 0 | ✓ |

---

## 前端 TypeScript/TSX 复杂度分析

### 🔴 高复杂度文件 (ESLint 复杂度警告)

| 文件 | 行数 | ESLint 复杂度 | 问题 |
|------|------|---------------|------|
| `src/components/chat/ChatPanel.tsx` | 1324 | **54** | 主组件过于复杂 |
| `src/stores/planningStore.ts` | 942 | **70** | handleSSEEventInStore 函数复杂度最高 |
| `src/hooks/planning/useSessionRestore.ts` | 239 | **38** | 恢复逻辑复杂 |
| `src/stores/planning-context.tsx` | 377 | **38** | Context 逻辑复杂 |
| `src/lib/api/planning-api.ts` | 410 | **24** | parseEvent 函数 |
| `src/components/chat/LayerReportCard.tsx` | 269 | **25** | 报告卡片组件 |
| `src/components/layout/KnowledgePanel.tsx` | 1001 | **18** | 知识面板 |
| `src/components/chat/CheckpointMarker.tsx` | 194 | **17** | 检查点标记 |

### 🟡 中等复杂度文件 (>300 行)

| 文件 | 行数 | 状态 |
|------|------|------|
| `src/hooks/planning/usePlanningHandlers.ts` | 395 | ✓ |
| `src/components/layout/HistoryPanel.tsx` | 409 | ✓ |
| `src/hooks/planning/usePlanningSelectors.ts` | 359 | ✓ |
| `src/components/VillageInputForm.tsx` | 362 | ✓ |

---

## 复杂度指标说明

- **复杂度评分** = 行数 × (1 + 函数数/50)
- **ESLint 复杂度** = 圈复杂度 (分支条件数量)
- **阈值**: 行数 > 800 或 ESLint 复杂度 > 15 标记为 ⚠️

---

## 优化建议

### 后端优先级

1. **`detailed_plan_prompts.py` (1807 行)** - 考虑拆分为多个按层级/维度分组的提示词模块
2. **`analysis_prompts.py` (972 行)** - 同上，拆分提示词模板
3. **`planning.py` (1313 行)** - 继续将辅助函数迁移到 Service 层
4. **`dimension_metadata.py` (1128 行)** - 考虑将配置数据迁移到 JSON/YAML 文件

### 前端优先级

1. **`planningStore.ts` - handleSSEEventInStore (复杂度 70)**
   - 拆分为多个专用处理函数
   - 按事件类型分发到不同 handler

2. **`ChatPanel.tsx` (复杂度 54)**
   - 抽取子组件
   - 将状态逻辑移到 hooks

3. **`useSessionRestore.ts` (复杂度 38)**
   - 拆分为多个独立 hook

---

## 统计汇总

| 类别 | 文件数 | 总行数 |
|------|--------|--------|
| Python 后端 | ~150 | 43,788 |
| 前端 TS/TSX | ~80 | 14,002 |
| **总计** | ~230 | **57,790** |