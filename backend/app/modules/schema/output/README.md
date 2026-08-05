# Schema Output — 输出规范（GDB 图层 / 配色 / 表格导出）

> **定位**：规划成果**输出规范**的单一事实源——GDB 图层注册表、功能区配色、一图一表一规则表格导出。

---

## 职责边界

**负责**：
- `colors.py`：所有 GIS 配色定义（GB/T 21010 + GB/T 50280-98 规划配色），前端/后端/渲染/API 测试**统一从此文件 import**（与 `frontend/src/features/planning/constants/gis.ts` 同步）
- `gdb.py`：GDB 图层名（省级命名约定）、字段结构、`LayerType → GDB layer` 映射、命名规则 `{prefix}_{description}_{feature_type_code}_{date}`
- `tables.py`："一图一表一规则"的"表"与"规则"导出（`ConstructionProjectTable` / `ControlRuleTable` / `PlanningIndicatorTable` → 附表1 / `LandUseStructureTable` → Excel/CSV）

**不负责**：
- 不做几何 / 空间计算
- 不做编码体系定义（那是 `encodings/`）
- 不做契约定义（那是 `contracts/`）

---

## 输入/输出契约

| 文件 | 输出 |
|---|---|
| `colors.py` | `ZONE_COLORS` / `PLANNING_ZONE_COLORS` 等配色字典 |
| `gdb.py` | GDB 图层注册表 / 字段定义 / 命名约定 |
| `tables.py` | 各成果表 → Excel/CSV 导出函数 |

---

## 依赖方向

```
output/ → schema/contracts（表类型）、schema/encodings、app.utils
   ▲ 被工具导出层 / API / 渲染消费
```

- 允许：`schema` 内部、`app.utils`、标准库/第三方（openpyxl/pandas 视导出函数而定）
- 禁止：`agent` / `services` / `api` / `tools`、`data`、`kg`

---

## 禁止行为

- 在别处硬编码 GIS 配色（必须统一 `colors.py`，否则前端后端不一致）
- 把 GDB 图层约定写死在工具层（必须查 `gdb.py`）
- 在输出规范内做业务计算
