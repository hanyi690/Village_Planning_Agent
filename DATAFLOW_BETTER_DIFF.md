# dataflow-better 分支与 main 分支差异说明

> 生成日期: 2026-02-17
> 分支对比: `main` vs `dataflow-better`

---

## 📋 概述

`dataflow-better` 分支相对于 `main` 分支，主要进行了**状态合并修复与代码优化**，以及将数据库文件添加到 `.gitignore`。

### 提交记录

| 提交哈希 | 提交信息 |
|---------|---------|
| `118333c2` | chore: 将数据库文件添加到 .gitignore |
| `6f71d3de` | refactor: 状态合并修复与代码优化 |

### 变更统计

- **新增文件**: 约 120+ 个
- **修改文件**: 约 46 个
- **总变更**: +32,488 行 / -3,767 行

---

## 🆕 新增功能模块

### 1. 前端组件 (Frontend Components)

| 文件路径 | 功能说明 |
|---------|---------|
| `frontend/src/components/ChatInterface.tsx` | 聊天界面组件 (545行) |
| `frontend/src/components/CheckpointViewer.tsx` | 检查点查看器 (273行) |
| `frontend/src/components/ConversationManager.tsx` | 会话管理器 (364行) |
| `frontend/src/components/ReviewDrawer.tsx` | 审核抽屉组件 (401行) |
| `frontend/src/components/RevisionProgress.tsx` | 修订进度组件 (190行) |
| `frontend/src/components/ViewerSidePanel.tsx` | 查看侧边栏 (376行) |

### 2. 前端页面 (Frontend Pages)

| 文件路径 | 功能说明 |
|---------|---------|
| `frontend/src/app/chat/[conversationId]/page.tsx` | 动态会话页面 |
| `frontend/src/app/chat/[conversationId]/layout.tsx` | 会话页面布局 |
| `frontend/src/app/chat/new/page.tsx` | 新建会话页面 |
| `frontend/src/app/villages/new/page.tsx` | 新建村庄页面 (459行) |

### 3. 前端上下文与工具 (Frontend Contexts & Utils)

| 文件路径 | 功能说明 |
|---------|---------|
| `frontend/src/contexts/ConversationContext.tsx` | 会话上下文 (161行) |
| `frontend/src/contexts/PlanningContext.tsx` | 规划上下文 (209行) |
| `frontend/src/lib/layerReportParser.ts` | 层级报告解析器 (321行) |
| `frontend/src/lib/logger.ts` | 前端日志工具 (50行) |
| `frontend/src/lib/utils/button-styles.ts` | 按钮样式工具 (94行) |
| `frontend/src/lib/utils/cn.ts` | 类名合并工具 (37行) |

### 4. 核心模块 (Core Modules)

| 文件路径 | 功能说明 |
|---------|---------|
| `src/core/dimension_mapping.py` | 维度映射配置 (416行) |
| `src/core/langsmith_integration.py` | LangSmith 集成 (318行) |
| `src/core/streaming.py` | 流式处理模块 (433行) |

### 5. 规划器模块 (Planners)

| 文件路径 | 功能说明 |
|---------|---------|
| `src/planners/base_planner.py` | 基础规划器 (430行) |
| `src/planners/analysis_planners.py` | 分析规划器 (301行) |
| `src/planners/concept_planners.py` | 概念规划器 (286行) |
| `src/planners/detailed_planners.py` | 详细规划器 (356行) |

### 6. 知识库模块 (Knowledge)

| 文件路径 | 功能说明 |
|---------|---------|
| `src/knowledge/__init__.py` | 知识库模块初始化 |
| `src/knowledge/ingest.py` | 知识库导入工具 (34行) |
| `src/knowledge/rag.py` | RAG 检索增强生成 (297行) |

### 7. 工具模块 (Tools)

| 文件路径 | 功能说明 |
|---------|---------|
| `src/tools/__init__.py` | 工具模块初始化 (24行) |
| `src/tools/interactive_tool.py` | 交互工具 (997行) |
| `src/tools/map_tool.py` | 地图工具 (16行) |
| `src/tools/planner_tool.py` | 规划工具 (23行) |

### 8. 工具函数 (Utils)

| 文件路径 | 功能说明 |
|---------|---------|
| `src/utils/report_generator.py` | 报告生成器 (150行) |
| `src/utils/test_memory_manager.py` | 测试内存管理器 (240行) |

### 9. 测试文件 (Tests)

| 文件路径 | 功能说明 |
|---------|---------|
| `tests/test_analysis_subgraph.py` | 分析子图测试 (421行) |
| `tests/test_concept_subgraph.py` | 概念子图测试 (388行) |
| `tests/test_detailed_plan_subgraph.py` | 详细规划子图测试 (497行) |
| `tests/test_dynamic_routing.py` | 动态路由测试 (335行) |
| `tests/test_file_manager.py` | 文件管理器测试 (187行) |
| `tests/test_integration.py` | 集成测试 (139行) |
| `tests/test_integration_partial_state.py` | 部分状态集成测试 (308行) |
| `tests/test_langsmith_integration.py` | LangSmith 集成测试 (308行) |
| `tests/test_state_filter.py` | 状态过滤器测试 (275行) |
| `tests/test_utils.py` | 工具函数测试 (290行) |
| `tests/verify_optimization.py` | 优化验证脚本 (263行) |
| `tests/run_all_tests.py` | 测试运行器 (136行) |
| `tests/simple_test_*.py` | 简单测试脚本 (5个) |
| `tests/README_SIMPLE_TESTS.md` | 测试说明文档 (188行) |

---

## 📝 修改的核心文件

### 后端 API (Backend API)

| 文件路径 | 变更说明 |
|---------|---------|
| `backend/api/files.py` | 文件处理 API 重构 (178行变更) |
| `backend/api/sessions.py` | 会话 API 重构 (213行变更) |
| `backend/api/tasks.py` | **新增** 任务管理 API (461行) |

### 后端服务 (Backend Services)

| 文件路径 | 变更说明 |
|---------|---------|
| `backend/services/shared_task_manager.py` | 共享任务管理器 (21行新增) |

### 后端工具 (Backend Utils)

| 文件路径 | 变更说明 |
|---------|---------|
| `backend/utils/__init__.py` | 模块初始化更新 |
| `backend/utils/error_handler.py` | 错误处理器重构 (343行变更) |
| `backend/utils/session_helper.py` | 会话助手更新 |

### 核心配置 (Core Config)

| 文件路径 | 变更说明 |
|---------|---------|
| `src/core/config.py` | 配置模块重构 (87行变更) |
| `src/core/llm_factory.py` | LLM 工厂更新 (82行变更) |
| `src/core/state_builder.py` | 状态构建器重构 (105行变更) |

### 节点模块 (Nodes)

| 文件路径 | 变更说明 |
|---------|---------|
| `src/nodes/base_node.py` | 基础节点更新 (54行变更) |
| `src/nodes/final_nodes.py` | 最终节点更新 (6行变更) |
| `src/nodes/layer_nodes.py` | 层级节点重构 (564行变更) |
| `src/nodes/subgraph_nodes.py` | 子图节点重构 (362行变更) |
| `src/nodes/tool_nodes.py` | 工具节点扩展 (346行变更) |

### 子图模块 (Subgraphs)

| 文件路径 | 变更说明 |
|---------|---------|
| `src/subgraphs/analysis_subgraph.py` | 分析子图重构 (330行变更) |
| `src/subgraphs/analysis_prompts.py` | 分析提示词更新 |
| `src/subgraphs/concept_subgraph.py` | 概念子图重构 (262行变更) |
| `src/subgraphs/concept_prompts.py` | 概念提示词更新 |
| `src/subgraphs/detailed_plan_subgraph.py` | 详细规划子图重构 (400行变更) |
| `src/subgraphs/detailed_plan_prompts.py` | 详细规划提示词更新 (512行变更) |

### 编排模块 (Orchestration)

| 文件路径 | 变更说明 |
|---------|---------|
| `src/orchestration/main_graph.py` | **主图重构** (929行变更) |

### 工具模块 (Tools)

| 文件路径 | 变更说明 |
|---------|---------|
| `src/tools/checkpoint_tool.py` | 检查点工具重构 (292行变更) |
| `src/tools/knowledge_tool.py` | 知识工具更新 |
| `src/tools/revision_tool.py` | 修订工具更新 |

### 工具函数 (Utils)

| 文件路径 | 变更说明 |
|---------|---------|
| `src/utils/logger.py` | 日志工具更新 |
| `src/utils/output_manager.py` | 输出管理器重构 (171行变更) |
| `src/utils/retry_utils.py` | 重试工具更新 |
| `src/utils/state_filter.py` | 状态过滤器重构 (260行变更) |

### 前端修改 (Frontend Changes)

| 文件路径 | 变更说明 |
|---------|---------|
| `frontend/src/components/DimensionSelector.tsx` | 维度选择器更新 (201行变更) |
| `frontend/src/types/message.ts` | 消息类型定义扩展 (269行变更) |

---

## 📚 新增文档

| 文件路径 | 内容说明 |
|---------|---------|
| `API架构重构说明.md` | API 架构重构文档 (941行) |
| `CHANGELOG.md` | 更新日志 (148行) |
| `LAYER_COMPLETION_FIX_COMPLETE.md` | 层级完成修复文档 (126行) |
| `PROJECT_WORK_SUMMARY.md` | 项目工作总结 (131行) |
| `web_deployment_guide.md` | Web 部署指南 (341行) |
| `docs/fix_layer_completion_detection.md` | 层级完成检测修复文档 (351行) |

---

## 🔧 配置文件变更

| 文件路径 | 变更说明 |
|---------|---------|
| `.gitignore` | 更新忽略规则，添加数据库文件 |
| `.claudeignore` | 新增 Claude 忽略配置 |
| `requirements.txt` | 依赖更新 (25行新增) |
| `frontend/.env.local` | 前端环境配置 |

---

## 📊 结果文件 (Results)

新增多个规划执行结果目录：

- `backend/results/执行规划/20260205_042904/` - 包含分析报告和检查点
- `results/某某村/20260131_092801/` - 完整的三层规划结果
  - Layer 1: 分析报告 (12个维度)
  - Layer 2: 概念规划 (4个维度)
  - Layer 3: 详细规划 (10个维度)
  - Checkpoints: 检查点文件 (3个)

---

## 🗑️ 删除的文件

相比 main 分支，此分支主要**新增**内容，未删除任何源代码文件。

---

## 💡 主要改进总结

### 1. 状态管理优化
- 新增 `ConversationContext` 和 `PlanningContext` 进行状态管理
- 重构 `state_filter.py` 和 `state_builder.py` 提升状态处理效率

### 2. 前端架构完善
- 新增完整的聊天系统组件
- 新增检查点查看和审核功能
- 新建村庄和会话的页面支持

### 3. 后端 API 重构
- 新增任务管理 API (`tasks.py`)
- 重构文件处理和会话 API
- 新增共享任务管理器

### 4. 规划器模块化
- 新增基础规划器抽象类
- 实现分析、概念、详细规划器
- 提升代码复用性和可维护性

### 5. 知识库集成
- 新增 RAG 检索增强生成模块
- 支持知识库导入和查询

### 6. 测试覆盖
- 新增 15+ 测试文件
- 覆盖子图、路由、集成、工具等模块

### 7. 可观测性
- 新增 LangSmith 集成
- 新增流式处理模块
- 增强日志记录能力

---

## 🚀 建议后续操作

1. **合并到 main**: 确认功能稳定后，可将 `dataflow-better` 合并到 `main`
2. **运行测试**: 执行 `python tests/run_all_tests.py` 验证所有功能
3. **检查依赖**: 运行 `pip install -r requirements.txt` 更新依赖
4. **前端构建**: 执行 `npm run build` 验证前端编译

---

*此文档由 iFlow CLI 自动生成*
