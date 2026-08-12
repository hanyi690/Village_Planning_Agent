# Data Documents — 非空间文档加载

> **定位**：规划 Markdown / L3 报告等**非空间文档**的高层加载器，喂养 PARSE/PLAN 管线。是低层 `sources/document.py`（经 Catalog 的文件访问）的**结构化解析补充**。

---

## 职责边界

**负责**：
- `load_planning_text()` / `load_l3_reports()`：加载规划文本与 L3 报告并返回结构化输出
- `list_available_documents()`：枚举可用文档
- 常量 `L3_BASELINE_PATH` / `L3_REPORT_PATH`：L3 报告路径约定

**不负责**：
- 不做 LLM / intent 解析（LLM 解析逻辑在 PARSE agent 侧）
- 不做空间数据加载（那是 `sources/` 与 `catalog/`）
- 不替代 Document DataSourceDriver（低层文件访问仍走 Catalog）

---

## 输入/输出契约

**输入**：文件系统路径（规划文本 / L3 报告目录）。

**输出**：

| 函数 | 输出 |
|---|---|
| `load_planning_text()` | 规划文本结构化内容 |
| `load_l3_reports()` | L3 报告列表（解析后） |
| `list_available_documents()` | 可用文档清单 |

**历史**：自 `gis/data/loader.py`（L3 report 段）与 `gis/data/text_loader.py`（PlanningTextLoader）迁入。

---

## 依赖方向

```
documents/ → app.infrastructure.logging 等
   ▲ 被 PARSE/PLAN 管线与 report 消费方调用
```

- 允许：`app.utils`、标准库（`glob` / `json` 等）
- 禁止：`agent` / `services` / `api` / `tools`；不做任何空间计算

---

## 禁止行为

- 在文档加载器内做 LLM 调用 / intent 解析（职责属于 PARSE agent 与 parsing 模块）
- 直接内联文件访问绕过 `DataCatalog` 的 document 驱动（低层读取应走 Catalog 路径）
- 返回非结构化原始文本给业务消费方（本层职责是"解析后结构化输出"）
