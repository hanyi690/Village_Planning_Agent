# Planning Text 模块架构说明

## 1. 模块概述

`planning_text` 模块位于 `backend/app/services/modules/planning_text/`，是一个**独立的规划文本生成管道**，用于从数据库存储的维度报告生成正式的村庄规划法定文本。

### 核心功能

- 从数据库读取三层维度报告（L1现状分析、L2规划思路、L3详细规划）
- 提取结构化数据（数值、章节、表格、法律依据）
- 通过四层策略路由组装 22 条条文
- 可选的 LLM 生成补充内容
- RAG 知识来源附录
- 多格式导出（MD、JSON、DOCX）

### 当前状态

**重要说明**：该模块目前**尚未集成到主应用流程**。没有代码在 `app/api/`、`app/services/runtime.py` 或 `app/agent/` 中调用 `PlanningTextGenerator`。模块设计为 LangGraph Agent 完成三层规划后的后处理工具，但尚未接入主执行管道。

---

## 2. 模块结构

```
planning_text/
├── __init__.py          # 包入口，导出所有公共类
├── config.py            # PlanningTextConfig 配置类
├── generator.py         # PlanningTextGenerator 主编排器
├── content_extractor.py # ContentExtractor 数据提取器
├── section_builder.py   # SectionBuilder 策略路由与条文组装
├── llm_styler.py        # LLMStyler Flash LLM 生成器
├── rag_appender.py      # RAGAppender 知识来源附录
├── json_exporter.py     # JsonExporter JSON 导出
├── layer_exporter.py    # LayerExporter 分层报告导出
```

---

## 3. 数据流图

```
┌─────────────────────────────────────────────────────────────────┐
│                     PlanningTextConfig                           │
│  (session_id, project_name, village_name, province/city/...)    │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│              PlanningTextGenerator.generate()                    │
│                        8 阶段管道                                │
└───────────────────────────────┬─────────────────────────────────┘
                                │
    ┌───────────────────────────┼───────────────────────────┐
    │                           │                           │
    ▼                           ▼                           ▼
┌─────────┐              ┌─────────────┐              ┌─────────┐
│ Phase 1 │              │  Phase 2    │              │ Phase 3 │
│ 数据获取 │              │  数据提取   │              │ 条文组装│
└────┬────┘              └─────┬───────┘              └───┬─────┘
     │                         │                          │
     ▼                         ▼                          ▼
┌─────────────────┐    ┌────────────────────┐    ┌─────────────────┐
│ ReportStore     │    │ create_extracted_  │    │ SectionBuilder  │
│ .get_layer_     │───▶│ data(l1,l2,l3,     │───▶│ .build_all()    │
│ reports()       │    │ summaries,         │    │                 │
│                 │    │ province...)       │    │ S-COPY          │
│ L1/L2/L3 并行   │    │                    │    │ S-ASSEMBLE      │
└─────────────────┘    │ ExtractedData      │    │ S-TEMPLATE      │
                       └────────────────────┘    │ S-GENERATE      │
                                                 └─────────────────┘
     │                         │                          │
     │                         │                          │
     ▼                         ▼                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Phase 4: LLM 补充                            │
│            LLMStyler.generate_all() → 替换 S-GENERATE 占位符     │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Phase 5: Markdown 渲染                       │
│              SectionBuilder.render() → 完整文档字符串             │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Phase 6: RAG 附录                            │
│            RAGAppender.append() → 添加知识来源章节                │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Phase 7: 文件导出                            │
│              MD 文件 + JsonExporter.write() → JSON 文件          │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Phase 8: 分层导出                            │
│            LayerExporter.export_all_layers() → L1/L2/L3 报告     │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      GenerationResult                            │
│  (markdown, md_path, json_path, build_report, rag_data, errors) │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. 核心组件详解

### 4.1 PlanningTextConfig

配置类，控制生成参数：

```python
@dataclass
class PlanningTextConfig:
    session_id: str              # 必需，链接数据库会话
    project_name: str            # 项目名（文件命名）
    village_name: str            # 村庄名（文档内容）
    province: str                # 省份（法律依据分类）
    city: str                    # 城市
    county: str                  # 县区
    township: str                # 乡镇
    planning_period: str         # 规划期限，默认 "2022-2035年"
    generate_tier3: bool         # 是否 LLM 生成，默认 True
    output_dir: str              # 输出目录
    output_formats: Tuple        # ("md", "json")
    append_rag: bool             # 是否添加 RAG 附录
    export_layers: bool          # 是否导出分层报告
```

### 4.2 PlanningTextGenerator

主编排器，执行 8 阶段管道：

| 阶段 | 功能 | 关键调用 |
|------|------|----------|
| 1 | 数据获取 | `store.get_layer_reports(session_id, 1/2/3)` |
| 2 | 数据提取 | `create_extracted_data(l1, l2, l3, summaries, province...)` |
| 3 | 条文组装 | `SectionBuilder(data).build_all()` |
| 4 | LLM 补充 | `LLMStyler(data).generate_all()` |
| 5 | Markdown 渲染 | `builder.render(build_report)` |
| 6 | RAG 附录 | `RAGAppender(session_id).append(markdown)` |
| 7 | 文件导出 | `JsonExporter.write()` |
| 8 | 分层导出 | `LayerExporter.export_all_layers()` |

### 4.3 ExtractedData

核心数据结构，存储从维度报告提取的所有结构化数据：

```python
@dataclass
class ExtractedData:
    # 数值字段
    total_area_ha: float         # 总面积
    population_household: int    # 户数
    population_registered: int   # 户籍人口
    population_resident: int     # 常住人口
    farmland_ha: float           # 耕地面积
    construction_land_ha: float  # 建设用地
    ecological_land_ha: float    # 生态用地
    forest_coverage_pct: float   # 森林覆盖率
    water_ha: float              # 水域面积
    village_count: int           # 自然村数量
    building_count: int          # 建筑数量
    
    # 文本字段
    development_goal: str        # 发展目标
    planning_positioning: str    # 规划定位
    planning_strategies: str     # 规划策略
    resource_endowment: str      # 资源禀赋
    
    # 区位字段
    province: str
    city: str
    county: str
    town: str
    
    # 法律依据
    legal_basis_national: List[str]
    legal_basis_provincial: List[str]
    legal_basis_planning: List[str]
    
    # Layer 3 结构化数据
    layer3_sections: Dict[str, Dict[str, str]]  # 维度 → 章节 → 内容
    layer3_tables: Dict[str, List[Dict]]        # 维度 → 表格列表
    
    # 原始数据
    raw_numbers: Dict[str, float]
    _raw_reports: Dict[str, str]
```

### 4.4 ContentExtractor

数据提取器，从原始报告文本提取结构化数据：

**提取方式**：

| 数据类型 | 提取方法 | 数据源 |
|----------|----------|--------|
| 数值字段 | 正则匹配 + 维度摘要覆盖 | 原始报告 + summaries |
| 区位信息 | config 注入（最高优先级） | PlanningTextConfig |
| 章节内容 | `【标题】内容` 格式解析 | Layer 3 报告 |
| 表格数据 | Markdown 表格解析 | Layer 3 报告 |
| 法律依据 | `《...》` 引用提取 + knowledge_sources | 所有报告 |

**关键方法**：

- `extract_all()` → 执行所有提取子方法
- `_extract_layer3_sections()` → 解析括号分隔章节
- `_parse_markdown_tables()` → 解析 Markdown 表格
- `_extract_legal_basis()` → 多源法律依据提取
- `_inject_from_summaries()` → 维度摘要数值注入（覆盖零值）

---

## 5. 四层策略路由

`SectionBuilder` 使用四种策略组装 22 条条文：

### 5.1 策略定义

| 策略 | 说明 | 适用条文 |
|------|------|----------|
| **S-COPY** | 直接复制 Layer 3 章节 | 9-18（规划内容） |
| **S-ASSEMBLE** | 从 ExtractedData 组装 | 1, 4, 5, 8 |
| **S-TEMPLATE** | 模板填充 | 2, 3, 6 |
| **S-GENERATE** | LLM 生成 | 7, 19-22 |

### 5.2 ARTICLE_DEFS 配置

```python
ARTICLE_DEFS = {
    # (标题, 章节, 策略, source_map)
    1:  ("规划背景", 1, "S-ASSEMBLE", {}),
    2:  ("规划原则", 1, "S-TEMPLATE", {}),
    3:  ("规划任务", 1, "S-TEMPLATE", {}),
    4:  ("规划依据", 1, "S-ASSEMBLE", {}),
    5:  ("规划范围", 1, "S-ASSEMBLE", {}),
    6:  ("规划期限", 1, "S-TEMPLATE", {}),
    7:  ("村庄发展定位和目标", 2, "S-GENERATE", {}),
    8:  ("规划指标", 2, "S-ASSEMBLE", {}),
    9:  ("建设用地布局优化", 3, "S-COPY", {
        "land_use_planning": ["土地利用规划", "土地利用结构调整表"],
        "settlement_planning": ["居民点规划", "规划目标"],
    }),
    # ... 10-18 类似
    19: ("加强组织领导", 5, "S-GENERATE", {}),
    20: ("驻村编制规划", 5, "S-GENERATE", {}),
    21: ("严格用途管制", 5, "S-GENERATE", {}),
    22: ("加强监督检查", 5, "S-GENERATE", {}),
}
```

### 5.3 S-COPY 策略详解

**流程**：
1. 从 `source_map` 获取目标维度和章节标题列表
2. 从 `data.layer3_sections[dim_key]` 获取章节字典
3. 匹配章节标题（精确匹配 + 模糊匹配，阈值 0.75）
4. 添加表格编号（章节序号）
5. 失败时 fallback 到完整维度报告

**示例**：第 9 条 "建设用地布局优化"

```python
sources = {
    "land_use_planning": ["土地利用规划", "土地利用结构调整表"],
    "settlement_planning": ["居民点规划", "规划目标"],
}
# 匹配 layer3_sections["land_use_planning"] 中的 "土地利用规划" 章节
# 匹配 layer3_sections["settlement_planning"] 中的 "居民点规划" 章节
```

### 5.4 S-ASSEMBLE 策略详解

| 条文 | 组装逻辑 |
|------|----------|
| 第 1 条 | 硬编码政策引用文本 |
| 第 4 条 | 从 `legal_basis_*` 字段组装法律依据列表 |
| 第 5 条 | 从 `total_area_ha` + `village_names` 组装范围描述 |
| 第 8 条 | 从数值字段组装规划指标表格 |

### 5.5 S-TEMPLATE 策略详解

| 条文 | 模板逻辑 |
|------|----------|
| 第 2 条 | 4 条标准原则 + 1 条条件原则（根据 `resource_endowment` 关键词） |
| 第 3 条 | 动态任务列表（根据有数据的 L3 维度） |
| 第 6 条 | 从 `planning_period` 计算规划期限文本 |

### 5.6 S-GENERATE 策略详解

**Phase 4 执行**：`LLMStyler.generate_all()` 并行生成 5 条条文

**LLM 调用配置**：
- 模型：Flash LLM（`create_flash_llm`）
- 参数：`max_tokens=800, temperature=0.3`
- Prompt 结构：格式规则 + 背景 Context + 任务描述

**第 7 条 Context 构建**：
```python
# 使用 Layer 2 规划思路数据
planning_positioning[:800]
development_goal[:500]
resource_endowment[:500]
planning_strategies[:500]
```

**第 19-22 条 Context 构建**：
```python
# 使用基本村庄概况数据
village_name, location, population, area, farmland, forest_coverage
```

---

## 6. RAG 附录生成

`RAGAppender` 在文档末尾添加知识来源章节：

**流程**：
1. 遍历三层维度
2. 调用 `store.get_layer_reports_with_sources()` 获取 knowledge_sources
3. 提取 `retrieved_chunks`
4. 按标题去重
5. 查询 `source_metadata_map.json` 补充缺失的 title/doc_type
6. 按 Layer + 维度分组输出

**输出格式**：
```markdown
## 附录：知识来源与参考依据

### 【Layer1 - 区位分析】
- [法规] 《中华人民共和国土地管理法》
- [标准] 《村庄规划技术规范》

### 【Layer3 - 产业规划】
- [案例] 某村产业振兴案例
```

---

## 7. 文件导出

### 7.1 Markdown 导出

`SectionBuilder.render()` 生成完整文档：

```markdown
# 金田村规划文本

## 第一章 总则

第一条 规划背景
...

## 第二章 村庄发展目标
...

## 附件：村民参与报告
...
```

### 7.2 JSON 导出

`JsonExporter.export()` 输出结构：

```json
{
  "meta": {
    "project_name": "金田村",
    "session_id": "...",
    "strategy_counts": {"S-COPY": 10, "S-ASSEMBLE": 4, ...},
    "total_articles": 22,
    "completed_articles": 22
  },
  "dimension_summaries": {...},
  "chapters": [...],
  "articles": [...],
  "rag_appendix": [...],
  "layer_reports": {...},
  "markdown": "..."
}
```

### 7.3 分层导出

`LayerExporter` 可选导出 L1/L2/L3 独立报告：

- 格式：MD、JSON、DOCX（可选）
- 内容：维度报告 + 结构化摘要 + RAG 来源（可选）

---

## 8. 外部依赖

| 依赖 | 用途 |
|------|------|
| `app.services.report_store.ReportStore` | 数据库维度报告读取 |
| `app.core.llm.create_flash_llm()` | Flash LLM 实例创建 |
| `app.config.loader.load_phases_config()` | 维度显示名称获取 |
| `data/RAG_doc/_cache/source_metadata_map.json` | 知识来源元数据缓存 |
| `python-docx`（可选） | DOCX 格式导出 |

---

## 9. 使用示例

```python
from app.services.modules.planning_text import (
    PlanningTextConfig,
    PlanningTextGenerator,
)

config = PlanningTextConfig(
    session_id="abc123",
    project_name="金田村规划",
    village_name="金田村",
    province="广东省",
    city="梅州市",
    county="梅县区",
    township="泗水镇",
    planning_period="2022-2035年",
    generate_tier3=True,
    append_rag=True,
)

generator = PlanningTextGenerator(config)
result = await generator.generate()

print(result.md_path)      # 输出 MD 文件路径
print(result.json_path)    # 输出 JSON 文件路径
print(result.markdown)     # 完整文档内容
```

---

## 10. 文章章节对照表

| 章节 | 条文 | 策略 | 内容来源 |
|------|------|------|----------|
| 第一章 总则 | 1 | S-ASSEMBLE | 硬编码政策引用 |
| | 2 | S-TEMPLATE | 模板原则 |
| | 3 | S-TEMPLATE | 动态任务列表 |
| | 4 | S-ASSEMBLE | 法律依据组装 |
| | 5 | S-ASSEMBLE | 范围描述 |
| | 6 | S-TEMPLATE | 期限文本 |
| 第二章 发展目标 | 7 | S-GENERATE | LLM 生成 |
| | 8 | S-ASSEMBLE | 指标表格 |
| 第三章 规划内容 | 9-18 | S-COPY | L3 章节复制 |
| 第四章 实施计划 | 18 | S-COPY | 项目库章节 |
| 第五章 实施保障 | 19-22 | S-GENERATE | LLM 生成 |

---

## 11. 数据注入优先级

数值字段的注入优先级（从高到低）：

1. **PlanningTextConfig 参数**（province, city, county, township）
2. **维度摘要 summaries**（覆盖正则提取的零值）
3. **正则提取**（NUM_PATTERNS 匹配）

```python
# content_extractor.py 中的注入逻辑
if province: data.province = province  # config 最高优先级
if summaries: _inject_from_summaries(data, summaries)  # 次优先级
# 正则提取作为 fallback
```

---

## 12. 后续集成建议

模块设计为 LangGraph Agent 完成后的后处理工具。建议集成点：

1. **Agent 完成节点**：在 `app/agent/nodes/` 中添加 `export_text_node`
2. **API 端点**：`/api/planning/export` 调用 `PlanningTextGenerator`
3. **触发时机**：三层规划全部完成后，用户点击"导出规划文本"