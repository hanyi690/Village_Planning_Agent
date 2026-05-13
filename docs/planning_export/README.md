# 村庄规划导出文档

**项目名称**: 金田村基线实验

**会话ID**: `38b5fdbc-b6eb-4ed9-9312-a3da2807f2c7`

**导出时间**: 2026-05-11 18:42:56

---

## 文档结构

| 层级 | 文档名称 | 维度数量 |
|------|----------|----------|
| Layer 1 | [现状分析](layer1_现状分析.md) | 12 |
| Layer 2 | [规划思路](layer2_规划思路.md) | 4 |
| Layer 3 | [详细规划](layer3_详细规划.md) | 12 |

---

## 数据来源

- **数据库**: `data/database/village_planning.db`
- **Checkpoint表**: `checkpoints`
- **导出脚本**: `scripts/export_planning_to_docs.py`

---

## 维度说明

### Layer 1: 现状分析（12维度）

- `location`: 区位与对外交通分析
- `socio_economic`: 社会经济分析
- `villager_wishes`: 村民意愿与诉求分析
- `superior_planning`: 上位规划与政策导向分析
- `natural_environment`: 自然环境分析
- `land_use`: 土地利用分析
- `traffic`: 道路交通分析
- `public_services`: 公共服务设施分析
- `infrastructure`: 基础设施分析
- `ecological_green`: 生态绿地分析
- `architecture`: 建筑分析
- `historical_culture`: 历史文化与乡愁保护分析

### Layer 2: 规划思路（4维度）

- `resource_endowment`: 资源禀赋分析
- `planning_positioning`: 规划定位分析
- `development_goals`: 发展目标分析
- `planning_strategies`: 规划策略分析

### Layer 3: 详细规划（12维度）

- `industry`: 产业规划
- `spatial_structure`: 空间结构规划
- `land_use_planning`: 土地利用规划
- `settlement_planning`: 居民点规划
- `traffic_planning`: 道路交通规划
- `public_service`: 公共服务设施规划
- `infrastructure_planning`: 基础设施规划
- `ecological`: 生态绿地规划
- `disaster_prevention`: 防震减灾规划
- `heritage`: 历史文保规划
- `landscape`: 村庄风貌指引
- `project_bank`: 建设项目库