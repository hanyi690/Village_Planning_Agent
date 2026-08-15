# Schema 覆盖度审计 - 2026-07-25

> 依据: `data/RAG_doc/_doc_md` 专业教材(7) + 技术规范(5) + 管控整治案例(9) = 21 文档
> 对照: schema/README.md v4.2 设计 + layer_registry 实际注册
> 目的: 评估 schema 定义充分性，区分"设计已规划待落地"与"真设计缺口"

---

## 一、设计已规划待落地（v4.1/v4.2 已设计，OPTIMIZATION_TASKS 批次 1-2 落地）

subagent 对照的是当前代码，报告"缺失"的下列项实际在 v4.2 设计里已覆盖，属代码未实现：

| 项 | 设计位置 | 落地任务 |
|---|---|---|
| Group F 5 类型（SoilType/SoilErosion/Watershed/NatureReserve/HydrogeologyZone） | schema/README §2.1 | S9 |
| PopulationGrid/GDPGrid | §2.2 | S9 |
| table_types.py + 7 表格类型 | §2.3 | ST1 |
| document_types.py + PlanningText/L3Report | §2.4 | ST2 |
| BaseControlZone + ThreeZoneItem | §2.1 | S10 |
| BaseRoad/BaseFacility/BaseAnnotation + PlannedFacility | §2.1 | S7 |
| output/tables.py 表格汇交 | §四 | ST3 |

---

## 二、真设计缺口（v4.2 也未覆盖，需新增类型）

### B1. 自然环境类（教材要求，建设适宜性评价基础）
| 缺口 | 教材来源 | 建议类型 | 形态 |
|---|---|---|---|
| 气象数据（温度/降水/风向/风速/日照/蒸发/冰冻） | 06-§4(7), 01-§10 | `ClimateRaster` / `MeteorologicalTable` | 栅格/表格 |
| 工程地质（地基承载力/地质构造/不良工程地质） | 06-§4(4), 01-§10 | `EngineeringGeologyZone` | 面 |

### B2. 设施子类型（GB50445 整治设施，当前 BaseFacility 过粗）
当前 `BaseFacility` 仅 facility_type/scale/service_radius，无法承载 GB50445 六类整治设施结构化参数。建议 `BaseFacility` 下增子类：

| 缺口 | 规范来源 | 关键字段 |
|---|---|---|
| `WaterSupplyFacility` | GB50445 §4, GB50188 10.2 | 水源类型/水处理方式/供水规模/管网长度/服务人口 |
| `DrainageFacility` | GB50445 §7, GB50188 10.3 | 排水体制(分流/合流)/处理方式/处理站规模/排放标准 |
| `WasteFacility` | GB50445 §5 | 收集方式(分类/混合)/处理方式(填埋/堆肥/转运)/服务半径 |
| `SanitaryFacility` | GB50445 §6, GBT32000 7.3 | 类型(公厕/户厕)/无害化方式(三格式/沼气池)/服务人口 |
| `FireFacility` | GB50188 11.2, GB50445 3.2 | 类型(消防站/水池/消火栓)/消防通道/水源 |
| `EvacuationShelter` | GB50188 11.4.6, GB50445 3.5 | 类型(广场/学校/绿地)/有效面积/容纳人数/应急设施 |
| `EnergyFacility` | GB50445 §12 | 能源类型(沼气/太阳能/生物质) |
| `LightingFacility` | GB50445 §9, GBT32000 6.7 | 照明类型 |

### B3. 防灾减灾类（schema 最弱领域，约 15% 覆盖）
| 缺口 | 规范来源 | 建议 |
|---|---|---|
| 抗震设防分类（特殊/重点/标准/适度） | GB50223 3.0.2 | `SeismicFortificationCategory` 枚举，作 CurrentBuilding/PlannedFacility 字段 |
| 次生灾害源（火灾/爆炸/毒物） | GB50188 11.4.5 | `SecondaryHazardSource` 类型 |
| 防洪安全设施（围埝/安全台/避水台） | GB50188 11.3.4 | `FloodSafetyFacility` 或并入 FloodControlLine |

### B4. 权属类
| 缺口 | 教材来源 | 建议类型 |
|---|---|---|
| 宅基地确权（权属/面积/位置） | 05-§2.1.2, 02-§3.2(5) | `LandRightConfirmation`（面） |

### B5. 表格扩展
| 缺口 | 规范来源 | 建议类型 |
|---|---|---|
| 重要地块控制指标表（编码/用地代码/层数/高度/风貌） | 永安村案例 附表2 | `PlotControlTable`（TableDataset） |

---

## 三、字段不足（类型已有，需扩展字段）

### C1. 高优先级字段扩展（影响汇交合规性）
| 类型 | 缺字段 | 规范来源 |
|---|---|---|
| `PlannedLandUseParcel` | TBH(图斑号)/DLMJ(地类面积)/QMDLBM(期末编码)/LYYSDM(来源)/LSYSXZB1-3(落实指标)/LSZBMJ1-3(指标面积) 共10字段 | 广东指南 表2 QMDLTB |
| `ControlRuleTable` | 允许用途/禁止用途/管控级别(约束性/引导性) | 永安村案例 专栏3 |
| `ConstructionProjectTable` | 资金筹措方式/责任主体/建设方式/用地面积/建筑面积 | 广东指南 附录2 |
| `PlanningIndicatorTable` | 基期年/变化量 | 广东指南 附表1 |
| `LandUseStructureTable` | 比重(百分比) | 广东指南 附表2 |
| `BaseFacility` | 配置级别(中心村/基层村)/服务人口 | GB50188 表7.0.1 |
| `CurrentBuilding` | building_status(空置/废弃/未建)/抗震设防分类/建筑风貌 | 05-§2.3.5, GB50223 |
| `PlannedRoad` | 红线宽度/车行道宽度/人行道宽度/设计速度/路面材料 | GB50188 表9.2.3 |
| `GeologicalHazardPoint` | 治理措施/工程投资/治理时限 | GB50445 3.4 |
| `WaterLine`/`WaterArea` | 整治措施/水位控制/水质标准 | GB50445 §10 |
| `HistoricalProtection` | 保护措施类型(修缮/整治/控制)/保护对象细类(古井/古桥/古树) | 广东指南 附录3 |
| `ConstructionCtrlZone` | tdkjgzfqdm 长度 Char(2)->Char(4) | 广东指南 表6 |

### C2. 编码体系修正
| 类型.字段 | 当前 | 规范要求 | 优先级 |
|---|---|---|---|
| `CurrentLandUseParcel.sddlbm` | appendix5 | GB/T 21010（三调编码） | 高 |
| `PlannedLandUseParcel.dlbm` | appendix5 | tugui（土规编码） | 高 |
| 6 套编码（gbt21010/tugui/appendix5/ghflbm/ydyhfldm/vne） | 仅常量注册 | 无枚举校验，需补值域 | 中 |

### C3. 图层缺口
| 缺口 | 规范来源 | 优先级 |
|---|---|---|
| 宅基地建设范围线（五条核心控制线之一） | 广东指南 附录1 | 高 |
| 永久基本农田储备区（与 FarmlandProtection 不同） | 广东指南 附录1 | 高 |
| 乡村历史文化保护线（HistoricalProtection 未明确为"线"图层） | 广东指南 附录1 | 中 |

---

## 四、综合覆盖率评估

| 领域 | 覆盖率 | 说明 |
|---|---|---|
| 矢量空间要素（Group A-E） | ~75% | 行政/地类/控制线/道路/建筑/水系/地形良好；缺气象/工程地质/宅基地确权/设施细分/防灾 |
| 栅格 | ~85% | DEM/DOM/坡度/坡向/适宜性/人口/GDP 已设计；缺气象栅格 |
| 表格 | 设计 ~30% -> v4.1 已规划 7 类 | 字段与规范有差距（见 C1） |
| 设施 | ~20% | BaseFacility 过粗，缺 5-8 子类型（B2） |
| 防灾减灾 | ~15% | 最弱：抗震/避灾/消防/防洪安全全缺 |
| 编码体系 | 6 套常量已注册 | 无枚举校验 + 2 处编码错配（C2） |

---

## 五、补全建议（v4.3）

**S11 字段扩展与编码修正**（C1+C2+C3，高优先级，影响汇交合规）
**S12 设施子类型化**（B2，BaseFacility -> 8 子类）
**S13 防灾减灾要素**（B3，抗震枚举 + 避灾场所 + 次生灾害源）
**S14 自然环境新类型**（B1，ClimateRaster/EngineeringGeologyZone）
**S15 权属与地块控制表**（B4+B5，LandRightConfirmation + PlotControlTable）
