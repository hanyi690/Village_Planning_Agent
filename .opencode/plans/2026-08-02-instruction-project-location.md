# 计划：L1/L3 报告【INSTRUCTION】段 → PARSE 结构化项目定位

日期：2026-08-02
状态：已批准执行

## 根因

L3 报告生成端已要求"位于[自然村]"+ 位置列（detailed.py），但 PARSE 侧全断：
- `_extract_project_tables` 表头必须含"项目名称"四字 → 漏大量项目表
- `_extract_zone_tables` 丢弃"位置"列
- 自然段项目描述（"古驿客家文化核心：位于园寨自然村"）未提取
- 自然村名 → BSM 未消费（gazetteer 已有能力，但 PARSE 产物不经过）
- 下游 MIP canvas（execute/agent.py B1）与 FacilityPlacer location_hint 接口现成，缺 intent 填充

## 方案

L1/L3 报告生成 prompt 文末追加【INSTRUCTION】固定列 markdown 表格段（不用 JSON，LLM 表格输出最稳、行级容错、复用 tables.py 解析器）。
保存时剥离该段存 DB 独立列（content 保持展示文本）。PARSE 读取 → 填充 intent 空间字段 → gazetteer 解析自然村→BSM → 走既有 build_intent_layer 写 L3 KG + B1 MIP canvas。

## 改动清单（不含道路，道路在远端分支）

1. `backend/app/modules/prompts/analysis.py`（L1）+ `detailed.py`（L3）：
   `get_dimension_prompt` 尾部统一追加 INSTRUCTION 输出引导
   - 固定 5 列：`| 类型 | 名称 | 位置 | 描述 | 规模 |`
   - 类型闭集：L3 = 项目/功能分区/设施/轴线；L1 = 现状设施/现状项目
   - 12 自然村名注入（田坑/黄竹/园寨/社前/分水/清明/塘笃/长塘/炉池/肩丰/营仔/新山）
   - 字段级指令（位置必须取自正文，无则空）+ 1 个真实示例

2. `backend/app/services/report_store.py` + `backend/app/database/engine.py`：
   - 保存前 `_split_instruction(content)` → content 存展示文本，instruction 存独立列
   - engine.py 幂等 ALTER：`ALTER TABLE dimension_reports ADD COLUMN instruction TEXT`（沿用现有先例）
   - 读取接口返回 `{content, instruction}`

3. `backend/app/modules/parsing/tables.py`：
   - `_classify_columns` 增"位置列"识别（表头含 位置|选址|所在位置）
   - `_extract_zone_tables` 位置列 → spatial_hint
   - `_extract_project_tables` 表头放宽（名称列含 项目|工程 即可）

4. `backend/app/agent/gis/parse/agent.py`：
   - 新增 `_extract_instruction_tables(text)`：识别【INSTRUCTION】段 → 复用 `_iter_tables`
   - 类型闭集校验 + 行级容错 → 填充 ZoneTarget.spatial_preference / FacilityTarget.location_hint+anchor_village / AxisTarget.reference_feature
   - 与既有提取去重合并

5. `backend/app/agent/gis/layout_pipeline.py`（_parse_intent_node 后置）：
   - 新增自然村→BSM resolver：收集位置文本 → `load_gazetteer(village)` resolve → 填 candidate_bsms（不落盘 gazetteer 文件）

6. 测试与回归：
   - 单测：INSTRUCTION 提取（正例/坏行/空位置/非法类型）、位置列提取、gazetteer 解析
   - 集成：重跑 session 验证 facilities 带位置、custom targets BSM 非空、分区有差异
   - 全量 pytest（543 基线）零新增失败
