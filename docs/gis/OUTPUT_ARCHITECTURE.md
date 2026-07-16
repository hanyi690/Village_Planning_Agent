# GIS 输出架构 — 广东省村庄规划标准

> 版本: 3.0 | 日期: 2026-07-16 | 参照: 广东省村庄规划编制基本技术指南（试行）附录4/5 + 附件1/2

## 设计原则

1. **输出驱动**：以广东省汇交标准定义输出层，反向推导生成层
2. **输入即真实**：以 `data/gis/jintian/` 实测数据为唯一输入真相
3. **分层解耦**：输入 → 内部生成抽象 → 标准输出，每层独立可替换
4. **规范字段名**：GDB 字段名严格遵循广东省技术规范表3-6，不使用自定义缩写
5. **可扩展**：新增省份标准 = 新增一个 output profile，不改生成核心
6. **增量可控**：Text2GIS 操作以 5 种原子操作为粒度，每次操作可追溯、可撤销

---

## 一、输入

### 1.1 现状 GIS 数据（`data/gis/jintian/current/`）

| 图层         | 文件                        | 要素 | 关键字段                         | 几何            |
| ------------ | --------------------------- | ---- | -------------------------------- | --------------- |
| 行政区划面   | boundary.geojson            | 1    | BSM, XZQHDM, XZQHMC, MJ          | MultiPolygon    |
| 行政区划界线 | admin_boundary_line.geojson | 561  | BSM, YSDM, DJZQDM                | MultiLineString |
| 现状地类图斑 | landuse.geojson             | 660  | DLBM, DLMC, SDDLBM, SDDLMC, DLMJ | MultiPolygon    |
| 现状道路     | road.geojson                | 131  | Shape_Length                     | MultiLineString |
| 现状注记     | annotation.geojson          | 34   | 注记, 分类                       | Point           |

### 1.2 权威外部数据（"三区三线"，不得自行生成）

| 图层                 | 权威来源                 | 获取方式                              | 说明                   |
| -------------------- | ------------------------ | ------------------------------------- | ---------------------- |
| 永久基本农田保护红线 | 自然资源部"三区三线"成果 | 自然资源部查询平台 / 地方"一张图"系统 | **不可自行调整** |
| 生态保护红线         | 自然资源部"三区三线"成果 | 同上                                  | **不可自行调整** |
| 历史文化保护线       | 地方住建/文旅部门        | 地方提供或现场调查标注                | 有条件配建             |
| 地质灾害点           | 地方自然资源局地勘部门   | 地质灾害调查成果导入                  | 有条件配建             |

### 1.3 规划参考数据（`data/gis/jintian/planned/`，开发测试对比用）

| 图层         | 文件                      | 要素 | 用途             |
| ------------ | ------------------------- | ---- | ---------------- |
| 期末地类图斑 | landuse.geojson           | 582  | 生成结果对比基准 |
| 有条件建设区 | construction_zone.geojson | 139  | 生成结果对比基准 |
| 规划道路     | road.geojson              | 170  | 生成结果对比基准 |

### 1.4 规划文本（统一解析为操作序列 + 约束集）

所有规划文本经 PARSE Agent 解析后，统一输出为 **OperationSequence**（可执行操作序列）和 **ConstraintSet**（约束集）。区别只在操作批量程度和确认粒度：

| 类别     | 示例                                     | 解析输出                             | 操作规模 | 确认方式     |
| -------- | ---------------------------------------- | ------------------------------------ | -------- | ------------ |
| 规划报告 | "农田保护区≥98.54ha"                   | OperationSequence（批量 reclassify） | 660 地块 | 批量确认+抽查 |
| 管制规则 | "允许建设区内不得安排基本农田"         | ConstraintSet（约束注入）            | 规则级   | 自动生效     |
| 建设项目 | "新建400㎡农产品展销中心"             | OperationSequence（create/split）    | 1-5 地块 | 逐条确认卡片 |
| 村民决议 | "同意搬迁学校"                         | OperationSequence（modify+create）   | 中等     | 逐条确认     |

> **核心统一**：规划报告的"整村生成"本质就是 660 个 reclassify 操作的批量执行。建设项目落地是 1-5 个操作的逐条执行。不存在两条路径，只有批量 vs 逐条。

---

## 二、输出（14 层 + 2 表 + 变更日志，广东标准）

### 2.1 输出目录结构

```
output/{village_name}/
├── 01_boundary.geojson                   ← current/ 直出
├── 02_admin_boundary_line.geojson        ← current/ 直出
├── 03_current_landuse.geojson            ← current/ 直出（基准）
├── 04_current_road.geojson               ← current/ 直出
├── 05_current_annotation.geojson         ← current/ 直出
├── 06_planned_landuse.geojson            ★ 期末地类图斑 QMDLTB（20+字段）
├── 07_farmland_protection.geojson        ★ 外部权威数据
├── 08_ecological_protection.geojson      ★ 外部权威数据
├── 09_historical_protection.geojson      ★ 外部数据
├── 10_space_control_zone.geojson         ★ 建设用地管制区 JSYDGZQ（9字段）
├── 11_land_use_zone.geojson              ★ 土地用途分区 TDYT（9字段）
├── 12_geological_hazard_points.geojson   ★ 外部数据
├── 13_planned_road.geojson               ★ 规划道路
├── 14_planned_annotation.geojson         ★ 规划注记
├── tables/
│   ├── planning_targets.json             ★ 规划目标表（附表1）
│   ├── land_balance.json                 用地平衡表
│   └── land_use_structure.json           ★ 土地利用结构调整表（附表2）
├── changelog.jsonl                       ★ Text2GIS 操作变更日志（追加写入）
└── layout.json                           布局配置
```

### 2.2 核心输出层字段结构（广东省技术规范表3-6 对齐）

#### GHCFW 规划村范围（01 boundary）

对标：规范表3 GHCFW 属性结构

| 字段代码 | 字段名称     | 类型  | 长度 | 约束 | 说明               |
| -------- | ------------ | ----- | ---- | ---- | ------------------ |
| BSM      | 标识码       | Int   | 10   | 必选 | >0                 |
| XZQHDM   | 行政区划代码 | Char  | 12   | 必选 | GB/T 2260 扩展到村 |
| XZQHMC   | 行政区划名称 | Char  | 100  | 必选 |                    |
| MJ       | 面积         | Float | 15   | 必选 | 平方米，保留到个位 |
| BZ       | 备注         | Char  | 200  | 可选 |                    |

#### QMDLTB 期末地类图斑（06 planned_landuse）★ 核心

对标：规范表4 QMDLTB 属性结构，20 必选字段

| 字段代码 | 字段名称         | 类型  | 长度 | 约束     | 生成方式                          |
| -------- | ---------------- | ----- | ---- | -------- | --------------------------------- |
| BSM      | 标识码           | Int   | 10   | 必选     | 自动编码                          |
| YSDM     | 要素代码         | Char  | 10   | 必选     | 固定 2003070100                   |
| TBH      | 图斑号           | Char  | 8    | 必选     | 自动编码                          |
| XZQHDM   | 行政区划代码     | Char  | 12   | 必选     | 固定                              |
| XZQHMC   | 行政区划名称     | Char  | 100  | 必选     | 固定                              |
| DLBM     | 地类编码         | Char  | 4    | 必选     | 从 current/landuse 继承           |
| DLMJ     | 图斑地类面积     | Float | 15   | 必选     | 几何计算，平方米                  |
| QMDLBM   | 期末地类编码     | Char  | 4    | 必选     | ★ 生成：重分类后编码             |
| LYYSDM   | 来源要素代码     | Char  | 10   | 条件可选 | 地类变更时非空                    |
| MS       | 描述             | Char  | 90   | 可选     |                                   |
| GHFLBM   | 规划分类编码     | Char  | 4    | 必选     | ★ 生成：规划分类                 |
| QMGHFLBM | 期末规划分类编码 | Char  | 4    | 必选     | = GHFLBM                          |
| GHYTBM   | 规划用途编码     | Char  | 4    | 必选     | ★ 生成：规划用途                 |
| GHYTMC   | 规划用途名称     | Char  | 20   | 必选     | ★ 生成：从 GHYTBM 查 ghytbm.yaml |
| LSYSXZB1 | 落实约束性指标1  | Char  | 4    | 可选     |                                   |
| LSZBMJ1  | 落实指标面积1    | Float | 15   | 可选     |                                   |
| LSYSXZB2 | 落实约束性指标2  | Char  | 4    | 可选     |                                   |
| LSZBMJ2  | 落实指标面积2    | Float | 15   | 可选     |                                   |
| LSYSXZB3 | 落实约束性指标3  | Char  | 4    | 可选     |                                   |
| LSZBMJ3  | 落实指标面积3    | Float | 15   | 可选     |                                   |

> **LSYSXZB1-3 / LSZBMJ1-3** 对应规范"落实约束性指标"字段，用于记录地块落实的耕地保有量/基本农田保护/建设用地规模等约束性指标。

#### TDYT 土地用途分区（11 land_use_zone）

对标：规范表5 TDYT 属性结构

| 字段代码 | 字段名称         | 类型  | 长度 | 约束 | 生成方式                         |
| -------- | ---------------- | ----- | ---- | ---- | -------------------------------- |
| BSM      | 标识码           | Int   | 10   | 必选 | 自动编码                         |
| YSDM     | 要素代码         | Char  | 10   | 必选 |                                  |
| XZQHDM   | 行政区划代码     | Char  | 12   | 必选 |                                  |
| XZQHMC   | 行政区划名称     | Char  | 100  | 必选 |                                  |
| TDYTFQDM | 土地用途分区代码 | Char  | 4    | 必选 | ★ 生成：DLBM→GHYTBM→VNE 查表  |
| TDYTFQBH | 土地用途分区编号 | Char  | 4    | 必选 |                                  |
| MJ       | 面积             | Float | 15   | 必选 | 椭球面积，平方米                 |
| MS       | 描述             | Char  | 90   | 可选 |                                  |
| YTFQMC   | 用途分区名称     | Char  | 30   | 必选 | ★ 生成：从 TDYTFQDM 查 vne.yaml |

#### JSYDGZQ 建设用地管制区（10 space_control_zone）

对标：规范表6 JSYDGZQ 属性结构

| 字段代码   | 字段名称             | 类型  | 长度 | 约束 | 生成方式            |
| ---------- | -------------------- | ----- | ---- | ---- | ------------------- |
| BSM        | 标识码               | Int   | 10   | 必选 | 自动编码            |
| YSDM       | 要素代码             | Char  | 10   | 必选 |                     |
| XZQHDM     | 行政区划代码         | Char  | 12   | 必选 |                     |
| XZQHMC     | 行政区划名称         | Char  | 100  | 必选 |                     |
| TDKJGZFQDM | 土地空间管制分区类型 | Char  | 4    | 必选 | ★ 510/520/530/540  |
| TDKJGZFQBH | 土地空间管制分区编号 | Char  | 2    | 必选 |                     |
| GHNF       | 规划年份             | Char  | 4    | 可选 |                     |
| MJ         | 面积                 | Float | 15   | 必选 | 平方米              |
| GZFQMC     | 管制分区名称         | Char  | 50   | 必选 | ★ 510=允许建设区等 |

### 2.3 管制区划分规则

| 类型         | 代码 TDKJGZFQDM | 名称 GZFQMC  | 生成规则                                        |
| ------------ | --------------- | ------------ | ----------------------------------------------- |
| 允许建设区   | 510             | 允许建设区   | 村庄建设边界内部                                |
| 限制建设区   | 520             | 限制建设区   | 除以下三类以外的区域                            |
| 有条件建设区 | 530             | 有条件建设区 | ≤ 现状建设用地 × 20%，不占基本农田 + 生态红线 |
| 禁止建设区   | 540             | 禁止建设区   | 永久基本农田 + 生态保护红线（不可调整）         |

质量规则（附件2 编码 5301-5312）：

- 允许建设区和有条件建设区内不能有基本农田（5301）
- 有条件建设区内不能规划建设用地（5308）
- 限制建设区内不能有新增规划城乡建设用地（5309）
- 禁止建设区范围不可调整（5306）

### 2.4 规划目标表（附表1）

对标：广东省技术指南附表1，7 项指标

数据结构定义：`dicts/planning_targets.yaml`

```yaml
indicators:
  - code: "I01"    # 耕地保有量（约束性）
  - code: "I02"    # 基本农田保护面积（约束性）
  - code: "I03"    # 村庄建设用地规模（约束性）
  - code: "I04"    # 公共服务设施用地规模（预期性）
  - code: "I05"    # 基础设施用地规模（预期性）
  - code: "I06"    # 户均宅基地（预期性）
  - code: "I07"    # 人均村庄建设用地（预期性）
```

### 2.5 土地利用结构调整表（附表2）

对标：广东省技术指南附表2，三大类 × 二级地类

数据结构定义：`dicts/land_use_structure.yaml`

### 2.6 V/N/E 用途分区分类体系

采用住建部《村庄规划用地分类指南》，广东附录5 直接引用。

```
V  村庄建设用地
  V1  村民住宅用地      V11 住宅用地 / V12 混合式住宅用地
  V2  村庄公共服务用地  V21 村庄公共服务设施用地 / V22 村庄公共场地
  V3  村庄产业用地      V31 村庄商业服务业设施用地 / V32 村庄生产仓储用地
  V4  村庄基础设施用地  V41 村庄道路用地 / V42 村庄交通设施用地 / V43 村庄公用设施用地
  V9  村庄其他建设用地

N  非村庄建设用地
  N1  对外交通设施用地
  N2  国有建设用地

E  非建设用地
  E1  水域             E11 自然水域 / E12 水库 / E13 坑塘沟渠
  E2  农林用地         E21 设施农用地 / E22 农用道路 / E23 其他农林用地
  E9  其他非建设用地
```

---

## 三、附录5 用地分类表（21 编码全覆盖）

| 代码 | 名称             | 一级类            | 二级类           | VNE | zone_type    |
| ---- | ---------------- | ----------------- | ---------------- | --- | ------------ |
| 1100 | 耕地             | 农业用地          | 耕地             | E23 | 农业用地     |
| 1200 | 园地             | 农业用地          | 园地             | E23 | 农业用地     |
| 1340 | 商品林           | 农业用地          | 商品林           | E23 | 农业用地     |
| 1400 | 草地             | 农业用地          | 草地             | E23 | 生态绿地     |
| 1500 | 其他农用地       | 农业用地          | 其他农用地       | E23 | 农业用地     |
| 1510 | 设施农用地       | 农业用地          | 设施农用地       | E21 | 农业用地     |
| 2100 | 城镇用地         | 建设用地          | 城镇用地         | N2  | 居住用地     |
| 2121 | 宅基地           | 建设用地.村庄     | 宅基地           | V11 | 居住用地     |
| 2122 | 公共服务设施用地 | 建设用地.村庄     | 公共服务设施用地 | V21 | 公共服务用地 |
| 2123 | 基础设施用地     | 建设用地.村庄     | 基础设施用地     | V43 | 交通用地     |
| 2124 | 经营性建设用地   | 建设用地.村庄     | 经营性建设用地   | V31 | 产业用地     |
| 2125 | 景观与绿化用地   | 建设用地.村庄     | 景观与绿化用地   | V22 | 公共服务用地 |
| 2126 | 村内交通用地     | 建设用地.村庄     | 村内交通用地     | V41 | 交通用地     |
| 2310 | 风景名胜设施用地 | 建设用地.交通水利 | 风景名胜设施用地 | V22 | 公共服务用地 |
| 2320 | 特殊用地         | 建设用地.交通水利 | 特殊用地         | N2  | 公共服务用地 |
| 2200 | 对外交通用地     | 建设用地.交通水利 | 对外交通用地     | N1  | 交通用地     |
| 2130 | 采矿用地         | 建设用地.交通水利 | 采矿用地         | N2  | 产业用地     |
| 2270 | 水利设施用地     | 建设用地.交通水利 | 水利设施用地     | E12 | 农业用地     |
| 1350 | 生态林           | 生态用地          | 生态林           | E23 | 生态绿地     |
| 3100 | 水域             | 生态用地          | 水域             | E11 | 水域         |
| 3200 | 自然保留地       | 生态用地          | 自然保留地       | E9  | 农业用地     |

> 数据源：`dicts/ghytbm.yaml`，21 个编码，与广东省技术指南附录5 完全对齐。

---

## 四、内部处理流程

### 4.1 统一数据流：文本 → 操作序列 → 执行

```
所有规划文本
    ↓
PARSE Agent → OperationSequence（可执行操作列表）+ ConstraintSet（约束集）
    ↓
┌─ ConstraintSet → KG（约束三元组）→ 合规检查规则 ──────────────────────────┐
│                                                                          │
└─ OperationSequence → 逐条执行（操作执行引擎）                             │
     ├── 空间定位（地名解析 → 候选图斑）                                    │
     ├── 用途查表（DictionaryCenter → QMDLBM/GHYTBM）                      │
     ├── 批量优化（可选：optimize_allocation tool，MIP 优化分配）            │
     ├── 合规预检（KG约束 + 冲突检测）                                      │
     ├── 人工确认（确认卡片 / 批量确认）                                    │
     └── 执行 + 变更日志                                                   │
           ├──→ 06_planned_landuse (QMDLTB)                               │
           ├──→ 10_space_control_zone (JSYDGZQ)                           │
           ├──→ 11_land_use_zone (TDYT)                                   │
           ├──→ 13_planned_road                                            │
           ├──→ 14_planned_annotation                                     │
           └──→ changelog.jsonl                                           │

现状 GIS 数据 ───────────────────────────────────→ 01-05 (直出)
外部权威数据（自然资源部"三区三线"） ────────────→ 07-09, 12 (校验后纳入)
```

### 4.2 操作执行引擎

5 种原子操作是统一的指令集，无论规划报告还是建设项目都使用同一套操作：

| 操作           | 说明       | 输入               | 输出影响                    | 约束                         |
| -------------- | ---------- | ------------------ | --------------------------- | ---------------------------- |
| `create`     | 新增图斑   | 面积+用途+位置描述 | 新 BSM → 06 层             | 必须在允许建设区内           |
| `split`      | 分割图斑   | 源BSM+面积比例/线  | 2+新BSM替换源 → 06/10/11层 | 分割后每块≥最小面积         |
| `merge`      | 合并图斑   | 源BSM列表          | 1新BSM替换源 → 06/10/11层  | 相邻且同用途                 |
| `modify`     | 属性修改   | 源BSM+字段变更     | 仅改属性 → 06层            | 字段值域合规（dicts/*.yaml） |
| `reclassify` | 地类重分类 | 源BSM+新QMDLBM     | 改编码+属性 → 06/11层      | 不突破分区约束               |

### 4.3 批量 vs 逐条

| 场景 | 操作数量 | 优化策略 | 确认方式 | 示例 |
|------|---------|---------|---------|------|
| 整村重分类 | 660 reclassify | MIP 优化分配（`optimize_allocation` tool） | 批量确认+抽查 | 规划报告→全村分区 |
| 单项目落地 | 1-5 create/split | 直接执行 | 逐条确认卡片 | "新建400㎡展销中心" |
| 约束注入 | 0（仅规则） | 自动加入合规检查 | 自动生效 | "允许建设区内不得安排基本农田" |

> **MIP allocator 降级为辅助 tool**：不再是管道的独立步骤（ALLOCATE），而是操作执行引擎按需调用的 `optimize_allocation` 工具。整村重分类时由引擎调用 MIP 优化分配结果；单项目落地时直接执行操作，不调用 MIP。

### 4.4 辅助工具

| 工具 | 功能 | 调用时机 |
|------|------|---------|
| `optimize_allocation` | MIP 优化分配（6 规划分区 + 硬约束锁定） | 批量 reclassify 操作时 |
| `resolve_place_name` | 空间地名解析（自然语言→候选图斑） | 操作含 location_desc 时 |
| `lookup_land_use_code` | 规划用途字典（名称→编码+约束） | 操作含 land_use_name 时 |
| `check_compliance` | 合规预检（三区三线+建设边界） | 每次操作执行前 |
| `extract_structured_text` | 表格结构提取（建设项目表→JSON） | 输入含表格时 |

---

## 五、附件2 质量检查合规矩阵

| 检查编码 | 检查内容                     | 检查对象                           | 系统对应                  | 状态             |
| -------- | ---------------------------- | ---------------------------------- | ------------------------- | ---------------- |
| 2201     | 图层完整性                   | 4必选层(GHCFW/QMDLTB/TDYT/JSYDGZQ) | gdb_layers.yaml 定义      | ✅               |
| 3201     | 属性字段数量名称类型         | 所有图层                           | gdb.py GDB_LAYER_REGISTRY | ✅ 对齐规范表3-6 |
| 3301     | 代码字段取值                 | 编码字段                           | dicts/*.yaml 值域         | ✅               |
| 3302     | 要素代码唯一性               | 所有图层                           | BSM 自动编码              | ✅               |
| 3401     | 数值范围符合性               | 所有图层                           | field_defaults.yaml       | ✅               |
| 3601     | 必填字段非空                 | 所有图层                           | field_defaults.yaml 规则  | ✅               |
| 5301     | 允许/有条件建设区无基本农田  | 管制区+基本农田                    | conflict/detector.py      | ✅               |
| 5306     | 禁止建设区范围不可调整       | 管制区                             | MIP 硬约束锁定            | ✅               |
| 5307     | 永久基本农田内必须为农用地   | 基本农田+期末地类                  | MIP 硬约束                | ✅               |
| 5308     | 有条件建设区内无建设用地     | 管制区+期末地类                    | layout_validator.py       | ✅               |
| 5309     | 限制建设区无新增城乡建设用地 | 管制区+期末地类                    | layout_validator.py       | ✅               |

---

## 六、待实现（P1/P2）

| 项目                                | 优先级 | 说明                                                                        |
| ----------------------------------- | ------ | --------------------------------------------------------------------------- |
| 附录3 管制规则模板                  | P2     | 文本生成模板，与 GIS 空间逻辑关系不大，属于规划文档输出范畴。标记为后续处理 |
| Personal Geodatabase (.mdb) 输出    | P1     | 规范要求 .mdb 格式，当前仅 GeoJSON/GeoPackage                               |
| 质量检查自动化（30+检查项完整覆盖） | P1     | 当前仅覆盖 ~40%，附件2 检查编码 1101-5312                                   |
| 汇交目录结构（5个二级目录）         | P1     | 规范要求固定目录组织形式                                                    |
| 容差/分辨率参数（0.001/0.0001）     | P1     | 规范要求，未在数据中体现                                                    |
| RoadPlan 道路规划生成               | P2     | 无对应生成器，AxisBuilder 仅作可视化叠加                                    |

---

## 七、YAML 字典中心索引

| 文件                     | 用途                          | 条目数 |
| ------------------------ | ----------------------------- | ------ |
| dlbm.yaml                | 三调地类编码                  | 93     |
| ghytbm.yaml              | 规划用途编码（附录5）         | 21     |
| ghflbm.yaml              | 规划分类编码                  | 11     |
| ydyhfldm.yaml            | 用地用海分类代码              | 49     |
| vne.yaml                 | V/N/E 住建部分类              | 20     |
| sddlbm_to_ydyhfldm.yaml  | 三调基数转换建议              | 45     |
| element_codes.yaml       | 要素代码前缀                  | 9      |
| three_line_types.yaml    | 三线管控图层样式              | 3      |
| gdb_layers.yaml          | GDB 图层定义                  | 17     |
| planning_zone_rules.yaml | 规划分区规则                  | 4      |
| field_defaults.yaml      | GDB 字段默认值规则            | 35+    |
| planning_targets.yaml    | 规划目标表指标（附表1）       | 7      |
| land_use_structure.yaml  | 土地利用结构调整分类（附表2） | 21     |

---

## 八、操作输出规范（OperationSequence + 变更日志 + 确认卡片）

### 8.1 操作意图 JSON Schema（PARSE Agent 输出）

```json
{
  "action": "create|split|merge|modify|reclassify",
  "location_desc": "刘村小组东侧、晒谷场北边空地",
  "target_parcels": ["XG-005"],
  "area_sqm": 400,
  "land_use_name": "经营性建设用地",
  "project_name": "农产品展销中心",
  "source_text": "同意在刘村小组东侧...新建一处占地400平方米的农产品展销中心",
  "confidence": "high"
}
```

### 8.2 原子操作定义（5 种）

| 操作           | 说明       | 输入               | 输出影响                    | 约束                         |
| -------------- | ---------- | ------------------ | --------------------------- | ---------------------------- |
| `create`     | 新增图斑   | 面积+用途+位置描述 | 新 BSM → 06 层             | 必须在允许建设区内           |
| `split`      | 分割图斑   | 源BSM+面积比例/线  | 2+新BSM替换源 → 06/10/11层 | 分割后每块≥最小面积         |
| `merge`      | 合并图斑   | 源BSM列表          | 1新BSM替换源 → 06/10/11层  | 相邻且同用途                 |
| `modify`     | 属性修改   | 源BSM+字段变更     | 仅改属性 → 06层            | 字段值域合规（dicts/*.yaml） |
| `reclassify` | 地类重分类 | 源BSM+新QMDLBM     | 改编码+属性 → 06/11层      | 不突破分区约束               |

### 8.3 变更日志 Schema（`changelog.jsonl`，每行一条）

```json
{
  "operation_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-07-16T14:30:00+08:00",
  "action": "split",
  "source_text": "同意在刘村小组东侧...新建农产品展销中心",
  "affected_layers": ["06_planned_landuse", "11_land_use_zone"],
  "before": {
    "BSM": "XG-005",
    "DLBM": "3200",
    "QMDLBM": "3200",
    "DLMJ": 1200.0
  },
  "after": [
    {"BSM": "XG-005-A", "QMDLBM": "2124", "GHYTBM": "2124", "DLMJ": 400.0},
    {"BSM": "XG-005-B", "QMDLBM": "3200", "GHYTBM": "3200", "DLMJ": 800.0}
  ],
  "compliance": {
    "in_construction_boundary": true,
    "not_farmland": true,
    "not_ecological_redline": true
  },
  "confirmed_by": "human",
  "confirmed_at": "2026-07-16T14:32:15+08:00"
}
```

### 8.4 确认卡片 Schema（人工确认界面）

```json
{
  "operation_id": "550e8400-e29b-41d4-a716-446655440000",
  "summary": "在刘村小组东侧新增 400㎡ 经营性建设用地",
  "target_parcel": {
    "BSM": "XG-005",
    "DLBM": "3200",
    "DLMC": "自然保留地",
    "DLMJ": 1200.0
  },
  "proposed_change": {
    "action": "split",
    "new_QMDLBM": "2124",
    "new_GHYTBM": "2124",
    "new_GHYTMC": "经营性建设用地",
    "split_area_sqm": 400
  },
  "compliance_check": {
    "in_construction_boundary": true,
    "not_farmland": true,
    "not_ecological_redline": true,
    "within_village_boundary": true
  },
  "preview_geojson": {
    "type": "FeatureCollection",
    "features": []
  },
  "status": "pending",
  "alternatives": []
}
```

> **不确定性处理**：若文本未指定规划用途（如"闲置地利用"），确认卡片 `alternatives` 字段返回候选项列表，由规划师选取，Agent 不自动赋值。

---

## 九、统一路径与对比模式

### 9.1 生产路径（唯一）

```
规划文本（报告/规则/建设项目/决议）
    ↓
PARSE Agent → OperationSequence + ConstraintSet
    ↓
KG（约束注入，来自 ConstraintSet）
    ↓
CONFLICT（约束冲突检测）
    ↓
EXECUTE_OPERATIONS（逐条执行操作序列）
    ├── 空间定位（resolve_place_name）
    ├── 用途查表（lookup_land_use_code）
    ├── 批量优化（optimize_allocation，按需调用 MIP）
    ├── 合规预检（check_compliance）
    ├── 人工确认（确认卡片 / 批量确认）
    └── 执行 + 变更日志
    ↓
VALIDATE（8 项空间检查 + 合规验证，最多 3 轮）
    ↓
EXPORT（14 层 GeoJSON + 2 表 + 变更日志）
    ↓
RENDER（MapLibre 前端可视化）
```

> **与旧架构的关系**：旧管道中的 ALLOCATE（MIP）步骤已降级为 `optimize_allocation` 辅助工具，在批量 reclassify 操作时由执行引擎按需调用。GENERATE 步骤被 EXECUTE_OPERATIONS 替代——所有内部层（ParcelReclass/SpaceControl/UseZone/FacilityPlan/RoadPlan）都是操作执行的结果，不是独立管道步骤。

### 9.2 对比测试模式（非生产路径）

用于验证系统效果，不参与生产流程：

| 模式   | 输入源               | 用途                            |
| ------ | -------------------- | ------------------------------- |
| gen    | 人工规划 markdown    | 对比"AI 解读文本" vs "人工图纸" |
| plan   | L3 系统报告          | 对比"AI 基于 L3" vs "人工图纸"  |
| ground | planned/ 人工GIS图纸 | 效果验证的基准真值              |

三路对比：gen vs ground, plan vs ground, gen vs plan

---

## 十、外部参考

| 参考                               | 架构特点                                                       | 对本项目启示                                    |
| ---------------------------------- | -------------------------------------------------------------- | ----------------------------------------------- |
| JackDaw (PoliRural+)               | 工具预过滤 + RAG + 值工程模型编排                              | 空间数据源按查询条件动态筛选，避免扁平工具列表  |
| Spatial Text-to-SQL (2026)         | 多 Agent 分阶段：实体提取→Schema接地→逻辑规划→SQL生成→审查 | 分阶段解释优于端到端，审查 Agent 执行后验证     |
| GIS Data Agent (zhouning)          | 层级式多 Agent + NL2SQL + DRL 优化                             | 自然语言→SQL 可参考，HITLApproval 人机审批模式 |
| QGIS Multi-Agent (Mansourian 2026) | 6 Agent 管线：意图→数据→RAG→推理→代码→反思                | 自反思循环修复执行错误                          |
