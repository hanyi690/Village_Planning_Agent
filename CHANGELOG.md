# 变更日志 (CHANGELOG)

所有重要的项目变更都将记录在此文件中。

---

## [未发布] - 2026-02-07

### 🐛 Bug修复 - 修复前端未显示规划报告数据

#### 问题
- 前端没有显示 Layer 1 和 Layer 2 的规划报告数据
- 只有 Layer 3 的报告能正常显示
- 后端日志显示生成了所有三层的报告，但SSE事件只发送了Layer 3

#### 根本原因
LangGraph 的 `stream_mode="values"` 会累积状态，导致当 Layer 2 完成时，事件中同时包含 `layer_1_completed=True` 和 `layer_2_completed=True`。原有的条件判断逻辑 `layer_1_completed AND NOT layer_2_completed` 在 Layer 2 完成后变为 False。

#### 解决方案
- ✅ 实现状态转换检测机制
- ✅ 追踪每个层级完成标志从 False → True 的转换
- ✅ 在检测到转换时立即发送对应的 SSE 事件

#### 修改文件
- 📝 `src/core/streaming.py` (lines 103-204)
  - 添加 `previous_event` 状态追踪
  - 检测 `layer_X_completed` 的状态转换
  - 发送 `layer_completed` 事件

#### 测试
- ✅ `tests/test_layer_completion_detection.py` - 基础转换检测测试
- ✅ `tests/test_actual_issue.py` - Bug 复现测试
- ✅ `tests/test_realistic_issue.py` - 真实场景测试

#### 验证
- ✅ 后端日志显示三层完成事件均发送
- ✅ 前端收到并显示三个层级的报告
- ✅ 事件格式保持不变，向后兼容

#### 文档
- 📝 新增 `LAYER_COMPLETION_FIX_COMPLETE.md` - 修复总结文档
- 📝 新增 `docs/fix_layer_completion_detection.md` - 详细修复说明

---

## [未发布] - 2026-02-06

### 🔄 架构重构 - 删除汇总节点，优化检查点数据结构

#### 新增
- ✨ 统一的维度报告字段命名规范
  - Layer 1: `analysis_dimension_reports`
  - Layer 2: `concept_dimension_reports`
  - Layer 3: `detailed_dimension_reports`
- ✨ 主图添加 `_generate_simple_combined_report()` 辅助函数
  - 简单拼接维度报告，无需LLM调用
  - 用于显示和文件保存

#### 变更
- 🔄 **Layer 1 (现状分析)**
  - 删除 `reduce_analyses()` 节点函数
  - 删除 `generate_final_report()` 节点函数
  - `analyze_dimension()` 直接填充 `analysis_dimension_reports`
  - 子图流程：`analyze → END`（原来：`analyze → reduce → generate → END`）

- 🔄 **Layer 2 (规划思路)**
  - 删除 `reduce_concept_analyses()` 节点函数
  - 删除 `generate_final_concept()` 节点函数
  - `analyze_concept_dimension()` 直接填充 `concept_dimension_reports`
  - 子图流程：`analyze → END`（原来：`analyze → reduce → generate → END`）

- 🔄 **Layer 3 (详细规划)**
  - 删除 `generate_final_detailed_plan()` 节点函数
  - 添加 `_extract_dimension_reports()` 辅助函数
  - 添加 `end` 节点提取维度报告
  - `route_by_dependency_wave()` 返回 "end" 而非 "generate_final"

- 🔄 **主图编排**
  - `execute_layer1_analysis()` 使用新字段名
  - `execute_layer2_concept()` 使用新字段名
  - `execute_layer3_detail()` 使用新字段名
  - 所有层现在生成简单的综合报告（拼接方式）

#### 删除
- ❌ `ReduceAnalysesNode` (Layer 1 封装节点)
- ❌ `GenerateAnalysisReportNode` (Layer 1 封装节点)
- ❌ `ReduceConceptsNode` (Layer 2 封装节点)
- ❌ `GenerateConceptReportNode` (Layer 2 封装节点)
- ❌ `GenerateFinalDetailedPlanNode` (Layer 3 封装节点)

#### 优化
- ⚡ 减少约33%的子图节点数量
- ⚡ 每层减少1次LLM调用（汇总调用）
- 💾 检查点数据完整性提升（维度报告不再为空）
- 📦 更简洁的代码结构

#### 文档更新
- 📝 更新 `README.md` - 架构流程图和检查点数据结构说明
- 📝 更新 `docs/agent.md` - 子图结构说明
- 📝 新增 `docs/ARCHITECTURE_REFACTORING.md` - 详细重构说明文档
- 📝 新增 `CHANGELOG.md` - 变更日志

#### 兼容性
- ✅ 前端无需修改（字段名保持一致）
- ✅ API接口保持兼容
- ✅ 检查点工具无需修改
- ⚠️ 旧检查点可能需要字段迁移（`dimension_reports` → `analysis_dimension_reports`）

---

## 版本规划

### v5.1.0 (计划中)
- [ ] 前端优化：维度报告独立查看和组合
- [ ] PDF导出：自定义维度组合
- [ ] 检查点迁移工具

### v5.0.0 (当前版本)
- [x] 架构重构：删除汇总节点
- [x] 统一数据结构：`*_dimension_reports`
- [x] 优化检查点数据完整性

---

## 历史版本

### v4.2.0
- 适配器集成
- 子图节点封装

### v4.1.0
- Web应用界面
- SSE流式传输

### v4.0.0
- 三层规划架构
- 检查点持久化

---

**格式说明**：
- `✨ 新增` - 新功能
- `🔄 变更` - 现有功能的改进
- `❌ 删除` - 移除的功能
- `⚡ 优化` - 性能或代码质量改进
- `📝 文档` - 文档更新
- `✅ 兼容` - 兼容性说明
- `⚠️ 注意` - 需要注意的事项
