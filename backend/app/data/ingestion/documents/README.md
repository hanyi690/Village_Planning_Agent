# Data Documents — 显式配置的遗留报告 fixture

当前会话的原始输入由 session catalog 解析；本目录不再扫描仓库中的
`docs/`、MinerU 或其他项目参考文件。L1 是唯一把会话输入结构化为事实、登记
和证据定位的维度。

---

## 职责边界

**负责**：
- `load_l3_reports()`：读取离线工具显式配置的遗留 L3 report fixture
- 常量 `L3_BASELINE_PATH` / `L3_REPORT_PATH`：遗留 fixture 路径约定

**不负责**：
- 不做 LLM / intent 解析（LLM 解析逻辑在 PARSE agent 侧）
- 不做空间数据加载（那是 `sources/` 与 `catalog/`）
- 不替代 Document DataSourceDriver（低层文件访问仍走 Catalog）

---

## 输入/输出契约

`load_l3_reports()` 只服务离线 fixture，不是 session 启动或 L1 输入来源。
线上输入必须通过 session catalog 和显式 upload 进入 `L1InputRegister`。

---

## 依赖方向

```
documents/ → app.infrastructure.logging 等
   ▲ 仅被离线 fixture/report 工具显式调用
```

- 允许：`app.utils`、标准库（`json` / `re` 等）
- 禁止：`agent` / `services` / `api` / `tools`；不做任何空间计算

---

## 禁止行为

- 在文档加载器内做 LLM 调用 / intent 解析（职责属于 PARSE agent 与 parsing 模块）
- 直接内联文件访问绕过 `DataCatalog` 的 document 驱动（低层读取应走 Catalog 路径）
- 通过文件名猜测当前项目输入或向 session 注入仓库文档
