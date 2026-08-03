# planning_text 模块（规划文本生成）

> 从数据库中的维度报告生成完整村庄规划文本：三级策略路由（S-COPY / S-ASSEMBLE / S-TEMPLATE / S-GENERATE）组装 22 条条文 + 可选 RAG 附录，导出 Markdown / JSON / 分层 DOCX。
> **Updated: 2026-08-02**

---

## 一、定位

分析 Agent 产出三层（L1 现状分析 / L2 规划思路 / L3 详细规划）维度报告后，本模块负责**最终成果文档生成**：把 L2/L3 报告的既有内容**复制或按模板组装**进 22 条条文，对少数无来源的条文用 **Flash LLM 按内置格式规则生成**（S-GENERATE），最后附加 RAG 知识来源附录并导出。

> 消费方：`app/api/session_routes.py` 的 `/api/sessions/{session_id}/planning-text` 接口（生成/查询/版本列表），以及 `/export` 接口（规划文本导出，含 DOCX）。

---

## 二、目录结构

```
planning_text/
├── __init__.py             # 公开 API 汇总导出
├── config.py               # PlanningTextConfig（生成配置 dataclass）
├── generator.py            # ★ PlanningTextGenerator：8 阶段主流程编排
├── content_extractor.py    # ExtractedData / ContentExtractor / create_extracted_data
├── section_builder.py      # ★ SectionBuilder / BuildReport / ArticleOutput / ARTICLE_DEFS（22 条定义）
├── llm_styler.py           # LLMStyler：FlashLLM 生成 S-GENERATE 条文（内置格式规则）
├── rag_appender.py         # RAGAppender：追加「附录：知识来源与参考依据」
├── json_exporter.py        # JsonExporter：导出结构化 JSON
├── layer_exporter.py       # LayerExporter：分层报告导出（MD/JSON/DOCX）
└── docx_styles.py          # DOCX 排版样式工具（中文字体/页边距/表格）
```

---

## 三、公开 API

```python
from app.modules.planning_text import (
    PlanningTextConfig, PlanningTextGenerator, GenerationResult,
    ExtractedData, ContentExtractor, create_extracted_data,
    SectionBuilder, BuildReport, ArticleOutput, ARTICLE_DEFS,
    LLMStyler, RAGAppender, JsonExporter,
    LayerExportConfig, LayerExporter, LayerExportResult, LAYER_NAMES,
)

config = PlanningTextConfig(
    session_id="...",
    project_name="金田村村庄规划",
    village_name="金田村委会",
    province="广东省", city="...", county="...", township="...",
    planning_period="2022-2035年",
    generate_tier3=True,          # 是否 LLM 生成 S-GENERATE 条文
    append_rag=True,              # 是否追加 RAG 附录
    output_dir="output/export",
    output_formats=("md", "json"),
    export_layers=False,          # 是否导出分层报告
)

result = await PlanningTextGenerator(config).generate()   # GenerationResult
# result.markdown / .md_path / .json_path / .build_report / .rag_data / .layer_reports / .errors
result_sync = generator.generate_sync()                   # asyncio.run 包装
```

---

## 四、主流程（generator.generate，8 阶段）

```
1. 并行拉取三层报告（ReportStore.get_layer_reports）——无报告则抛 ValueError
2. create_extracted_data + 并行拉取三层摘要注入数值字段
   （append_rag=True 时 _collect_legal_titles 收集法规标题注入法律依据）
3. SectionBuilder.build_all —— 22 条策略路由组装（§五）
4. generate_tier3=True → LLMStyler.generate_all() 填充 S-GENERATE 条文
   （失败条目保留【待LLM生成】占位，不阻断）
5. builder.render → Markdown 全文
6. append_rag=True → RAGAppender.append 追加知识来源附录
7. 导出 md / json（{project_name}_规划文本.md / .json）
8. export_layers=True → LayerExporter 分层导出（L1/L2/L3 各 MD/JSON/DOCX）
```

---

## 五、条文策略路由（section_builder）

`ARTICLE_DEFS` 定义 **22 条**条文，每条的 `(标题, 章, 策略, 来源映射)`：

| 策略 | 数量 | 行为 |
|---|---|---|
| **S-COPY** | 12 条（9-18 规划内容类） | 从 L3 指定维度的报告内容**直接复制**：`_build_copy` 按来源映射（如 `land_use_planning: ["土地利用规划","土地利用结构调整表",...]`）用 difflib 相似度匹配标题 → 截取段落/表格，渲染 `### 【维度名】` 小节 |
| **S-ASSEMBLE** | 3 条（4 规划依据 / 5 规划范围 / 8 规划指标） | **组装**：规划依据 = 法律依据列表（国家/省/市县分组）逐条列出；规划范围 = 区位字段 + 用地面积；规划指标 = L2/L3 指标表汇总 |
| **S-TEMPLATE** | 2 条（3 规划任务 / 6 规划期限） | **固定模板**：规划期限取 config（默认 2022-2035年） |
| **S-GENERATE** | 5 条（1 背景 / 2 原则 / 7 定位 / 19-22 保障监督） | 初始占位，由 **LLMStyler** 用 FlashLLM + 内置格式规则生成（见 §六） |

- 五章结构：1 总则 / 2 村庄发展目标 / 3 规划内容 / 4 实施计划 / 5 实施保障。
- 每条目渲染为 `第{中文数字}条 {标题}` + `### 【策略】` 策略标注。
- 失败条目收集进 `BuildReport.errors`（不中断整篇生成）。

**ExtractedData 字段**（content_extractor）：
- 区位：`province/city/county/town`（config 注入）；
- L2 复制：`development_goal/planning_positioning/planning_strategies/resource_endowment`；
- 数值字段（摘要注入，供 LLMStyler 用）：`total_area_ha/population_*/farmland_ha/construction_land_ha/...`，带 `_field_sources` 来源追踪 + `_qualified_metrics` 限定键名存储（避免静默覆盖）；
- L3 结构化：`layer3_sections`（【标题】解析）/ `layer3_tables`（**表格只从此复制，不正则组装**）；
- `legal_basis_national/provincial/planning`（superior_planning 提取 + RAG 法规标题合并）；`village_names`。

---

## 六、LLMStyler（S-GENERATE 条文）

- 只处理条文 `[1, 2, 7, 19, 20, 21, 22]`，few-shot 映射 `{1:'background', 7:'positioning', 19-21:'guarantee', 22:'supervision'}`。
- `_BUILTIN_RULES`：**内置格式规则**（法定文本/规范条文语言；不用「应该/建议」等模糊表述；结合村庄背景具体数据；只输出条文内容）。
- `_build_context(num)` 组装村庄背景（区位、人口、用地、产业数据）；只使用 **FlashLLM**，无主模型回退；失败返回通用占位。

---

## 七、导出器

| 导出器 | 产物 |
|---|---|
| `JsonExporter.export` | 单文件 JSON：`meta`（项目/会话/生成时间/策略计数）+ `chapters` + `articles`（含 strategy/content/来源）+ RAG 附录 + 三层报告 + 维度摘要 |
| `LayerExporter` | 分层报告 `{session_id}_layer{n}.md/.json/.docx`：每维度含 `DimensionReport`（content + summary + rag_sources），DOCX 用 `docx_styles` 排版 |
| `RAGAppender` | 追加 `## 附录：知识来源与参考依据`，按 L1/L2/L3 分维度列出检索来源（`source_metadata_map.json` 回填 title/doc_type，`_TYPE_LABELS` 中文化） |

---

## 八、输入输出契约

```
输入:  PlanningTextConfig
         session_id（必填）/ project_name / village_name / 行政区四级
         planning_period / generate_tier3 / append_rag / output_dir / output_formats
         export_layers / layer_output_formats / include_rag_details / include_summaries
      依赖: ReportStore（get_layer_reports / get_layer_summaries / get_layer_reports_with_sources）

输出:  GenerationResult
         markdown / md_path / json_path / build_report（含 strategy_counts, errors）
         rag_data（维度 → 来源清单）/ layer_reports / layer_export_results
      文件: output/export/{project_name}_规划文本.md / .json
           output/export/{session_id}_layer{n}.md / .json / .docx（export_layers 时）
```

API 层把生成结果持久化为 planning_text 文档（`services/document_store`），支持多版本查询。

---

## 九、相关文档

- `app/services/report_store.py` — 报告/摘要来源
- `app/api/session_routes.py` — `/planning-text` 生成与 `/export` 导出接口
- `app/agent/state.py` — `LAYER_NAMES_BY_NUMBER`（分层导出标题）
- `app/modules/rag/README.md` — 上游知识检索
