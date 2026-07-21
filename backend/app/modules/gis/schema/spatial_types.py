"""村庄规划空间要素类型定义 — 覆盖全部空间要素类别。

参照: docs/gis/规划所需数据类型与图层分类.md
      广东省《村庄规划数据库技术规范》送审稿(2026)
      广东省村庄规划编制基本技术指南(试行)(2019)

类型分组:
  Group A: 行政区划 (AdminBoundary)
  Group C: 现状要素 (CurrentFeatures)
  Group D: 规划管控要素 (PlannedControls)

Group B (地类图斑 LandUse) 定义在 ingestion.py 中.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from .ingestion import SpatialFeature


# ============================================================
# Group A: 行政区划
# ============================================================


@dataclass
class AdminArea(SpatialFeature):
    """村级行政区 (面) — 基础地理信息要素.

    GDB 图层: GHCFW (规划村范围) — 表3字段
    输入数据字段: BSM, YSDM, DJZQDM, DJZQMC, MJ, BZ
    规范来源: 广东省技术指南 表3
    """

    djzqdm: str = ""       # 登记区划代码 (12位: 县级6+镇级3+村级3)
    djzqmc: str = ""       # 登记区划名称 (如 "金田村委会")
    mj: float = 0.0        # 椭球面积 (平方米, 保留到个位)
    bz: str = ""           # 备注 (≤200字符, 可选)
    shape_length: float = 0.0  # 几何周长 (数据自带)
    shape_area: float = 0.0    # 几何面积 (数据自带)


@dataclass
class AdminBoundaryLine(SpatialFeature):
    """村级行政区划界线 (线) — 基础地理信息要素.

    GDB 图层: admin_boundary_line
    """

    djzqdm: str = ""       # 登记区划代码 (12位)
    boundary_type: int = 0 # 界线类型 (670500=村界)
    boundary_desc: str = "" # 界线说明 (≤20字符)


# ============================================================
# Group C: 现状要素 (CurrentFeatures) + 规划对应要素
# ============================================================


@dataclass
class CurrentBuilding(SpatialFeature):
    """现状建筑 (面) — 基期年现状要素.

    来源于现状调查, 包含建筑类型、层数、面积等信息.
    """

    building_type: str = "" # 建筑类型 (住宅/公建/产业/附属)
    floors: int = 0         # 层数
    area_sqm: float = 0.0   # 建筑面积 (平方米)
    structure: str = ""     # 结构类型 (砖混/框架/土木/钢)


@dataclass
class CurrentRoad(SpatialFeature):
    """现状道路 (线) — 基期年现状要素.

    GDB 图层: current_road
    """

    shape_length: float = 0.0  # 几何长度 (米)
    road_level: str = ""       # 道路等级 (村道/乡道/县道)
    road_width: float = 0.0    # 道路宽度 (米)
    road_name: str = ""        # 道路名称


@dataclass
class CurrentFacility(SpatialFeature):
    """现状设施 (点/面) — 基期年现状要素.

    包含基础设施点和公共服务设施点.
    """

    facility_type: str = ""  # 设施类型 (给水/排水/电力/环卫/公厕/村委会/卫生室/学校/广场)
    facility_name: str = ""  # 设施名称
    scale: str = ""          # 规模描述 (如 "50m³/d", "200㎡")
    service_radius: float = 0.0  # 服务半径 (米, 公共服务设施)
    category: str = ""       # 分类: infrastructure(基础设施) / public_service(公共服务)


@dataclass
class CurrentAnnotation(SpatialFeature):
    """现状注记 (点) — 基期年现状要素. 规划注记复用此类型 (字段相同).

    GDB 图层: current_annotation, planned_annotation
    注记类型: 地名/设施点/高程点/规划设施点等
    """

    text: str = ""           # 注记文本 (≤100字符)
    category: str = ""       # 注记分类 (地名/设施点/规划设施点/其他)


@dataclass
class PlannedRoad(SpatialFeature):
    """规划道路 (线) — 目标年规划要素.

    GDB 图层: planned/road.geojson
    字段: LnType (道路类型), LeftLn_FID (左侧车道要素ID),
          RightLn_FID (右侧车道要素ID), Shape_Length (长度)
    """

    shape_length: float = 0.0   # 几何长度 (米)
    ln_type: str = ""           # 道路类型
    left_ln_fid: str = ""       # 左侧车道要素ID
    right_ln_fid: str = ""      # 右侧车道要素ID
    road_level: str = ""        # 规划道路等级 (村道/乡道/县道)


@dataclass
class GeologicalHazardPoint(SpatialFeature):
    """地质灾害点 (点) — 目标年规划要素.

    与 HazardControlLine (灾害风险防控线, 面) 不同,
    本类型表示单个地质灾害点 (崩塌/滑坡/泥石流等).
    """

    name: str = ""           # 地质灾害点名称
    longitude: str = ""      # 经度 (DMS 格式, 如 \"116° 3' 39.000\\\" E\")
    latitude: str = ""       # 纬度 (DMS 格式)
    hazard_type: str = ""    # 灾害类型 (崩塌/滑坡/泥石流/地面塌陷)
    scale: str = ""          # 灾害规模 (小型/中型/大型)


@dataclass
class ConditionalConstructionZone(SpatialFeature):
    """有条件建设区 (面) — 目标年规划要素.

    GDB 图层: construction_zone
    约束: 不超过现状建设用地规模 ×20%, 不得占用永久基本农田和生态保护红线
    """

    bh: str = ""             # 编号
    xzqhdm: str = ""         # 行政区划代码
    xzqhm: str = ""          # 行政区划名称
    lx: str = ""             # 类型 (固定值 "有条件建设区")
    mj: float = 0.0          # 面积 (平方米)
    shape_length: float = 0.0  # 几何周长
    shape_area: float = 0.0    # 几何面积


# ============================================================
# Group D: 规划管控要素 (PlannedControls)
# ============================================================


@dataclass
class ControlLine(SpatialFeature):
    """控制线基类 (面) — 目标年规划要素.

    所有控制线/保护线/边界的共享属性.
    子类: 永久基本农田, 生态保护红线, 耕地保护目标,
          城镇开发边界, 村庄建设边界, 灾害风险防控线, 洪涝风险控制线
    """

    mj: float = 0.0          # 面积 (平方米)
    protection_level: str = ""  # 保护等级 (核心/一般/缓冲)


@dataclass
class FarmlandProtection(ControlLine):
    """永久基本农田保护红线 (面).

    GDB 图层: farmland_protection
    来源: 自然资源部"三区三线"成果, 不可自行调整
    """

    xzqhdm: str = ""         # 行政区划代码
    xzqhmc: str = ""         # 行政区划名称
    jbnt_mj: float = 0.0     # 基本农田面积 (平方米)


@dataclass
class EcologicalRedline(ControlLine):
    """生态保护红线 (面).

    GDB 图层: ecological_redline
    来源: 自然资源部"三区三线"成果, 不可自行调整
    """

    district: str = ""       # 所属区县 (≤20字符)
    zone: float = 0.0        # 分带号
    city: str = ""           # 所属地市 (≤20字符)
    object_id: int = 0       # 对象ID


@dataclass
class CultivatedLandTarget(ControlLine):
    """耕地保护目标 (面).

    三条控制线之一 — 耕地和永久基本农田保护红线.
    来源: 自然资源部审核通过的数据
    """

    target_level: str = ""   # 保护目标等级


@dataclass
class UrbanDevBoundary(ControlLine):
    """城镇开发边界 (面).

    三条控制线之一 — 城镇开发边界.
    来源: 自然资源部审核通过的数据
    """

    dev_type: str = ""       # 开发类型 (集中建设/弹性发展/特殊用途)


@dataclass
class VillageDevBoundary(ControlLine):
    """村庄建设边界 (面).

    目标年规划要素 — 村庄建设边界.
    参考图层命名: CZJSBJ
    """

    boundary_type: str = ""  # 边界类型 (刚性/弹性)


@dataclass
class HazardControlLine(ControlLine):
    """灾害风险防控线 (面) — 安全控制线.

    参考图层命名: ZHFXFKX
    """

    hazard_type: str = ""    # 灾害类型 (崩塌/滑坡/泥石流/地面塌陷)
    risk_level: str = ""     # 风险等级 (高/中/低)


@dataclass
class FloodControlLine(ControlLine):
    """洪涝风险控制线 (面) — 安全控制线.

    参考图层命名: HLFXKZX
    """

    flood_frequency: str = ""  # 洪水频率 (如 "20年一遇", "50年一遇")
    control_elevation: float = 0.0  # 控制高程 (米)


@dataclass
class HistoricalProtection(SpatialFeature):
    """历史文化保护线 (点/面).

    GDB 图层: historical_protection
    来源: 衔接落实地方住建/文旅部门数据
    点图层: LSWHBHD, 面图层: LSWHBHM
    """

    buff_dist: float = 0.0   # 缓冲距离 (米)
    orig_fid: float = 0.0    # 原始要素ID
    protection_scope: str = ""  # 保护范围描述
    protection_level: str = ""  # 保护级别 (国家级/省级/市县级)


@dataclass
class LandUseZone(SpatialFeature):
    """土地用途分区 TDYT (面) — 核心规划数据 (必选).

    规范来源: 广东省技术指南 表5 (9字段)
    编码体系: TDYTFQDM (乡级规划分类, TD/T 1028-2010)
    """

    xzqhdm: str = ""         # 行政区划代码 (12位)
    xzqhmc: str = ""         # 行政区划名称 (≤100字符)
    tdyfqdm: str = ""        # 土地用途分区代码 (4位, 乡规分类编码)
    tdyfqbh: str = ""        # 土地用途分区编号 (4位)
    mj: float = 0.0          # 面积 (平方米, 保留到个位)
    ms: str = ""             # 描述 (≤90字符, 可选)
    ytfqmc: str = ""         # 用途分区名称 (≤30字符)


@dataclass
class ConstructionCtrlZone(SpatialFeature):
    """建设用地管制区 JSYDGZQ (面) — 核心规划数据 (必选).

    规范来源: 广东省技术指南 表6 (9字段)
    管制分区类型代码 (TDKJGZFQDM):
      01 — 允许建设区
      02 — 限制建设区
      03 — 有条件建设区
      04 — 禁止建设区
      05 — 永久基本农田保护区
      06 — 生态保护红线区
    双向约束: 允许建设区+有条件建设区 不能包含永久基本农田
              有条件建设区 ≤ 现状建设用地规模×20%
    """

    xzqhdm: str = ""         # 行政区划代码 (12位)
    xzqhmc: str = ""         # 行政区划名称 (≤100字符)
    tdkjgzfqdm: str = ""     # 土地空间管制分区类型代码 (2位: 01-06)
    tdkjgzfqbh: str = ""     # 土地空间管制分区编号 (2位)
    ghnf: str = ""           # 规划年份 (4位, 如 2025/2035)
    mj: float = 0.0          # 面积 (平方米, 保留到个位)
    gzfqmc: str = ""         # 管制分区名称 (≤50字符)

    # 管制分区类型常量
    ALLOWED_CONSTRUCTION = "01"
    RESTRICTED = "02"
    CONDITIONAL = "03"
    PROHIBITED = "04"
    BASIC_FARMLAND_ZONE = "05"
    ECOLOGICAL_REDLINE_ZONE = "06"


@dataclass
class PlanningScope(SpatialFeature):
    """规划村范围 GHCFW (面) — 管理类数据 (必选).

    规范来源: 广东省技术指南 表3 (5字段)
    用途: 定义本次村庄规划的编制范围
    """

    xzqhdm: str = ""         # 行政区划代码 (12位, GB/T 2260)
    xzqhmc: str = ""         # 行政区划名称 (≤100字符)
    mj: float = 0.0          # 椭球面积 (平方米, 保留到个位)
    bz: str = ""             # 备注 (≤200字符, 可选)


# ============================================================
# 管制分区类型编码常量
# ============================================================

SPACE_CONTROL_ZONE_TYPES = {
    "01": "允许建设区",
    "02": "限制建设区",
    "03": "有条件建设区",
    "04": "禁止建设区",
    "05": "永久基本农田保护区",
    "06": "生态保护红线区",
}

SPACE_CONTROL_ZONE_COLORS = {
    "01": "#FF6B6B",  # 允许建设区 — 红色
    "02": "#FFD93D",  # 限制建设区 — 黄色
    "03": "#6BCB77",  # 有条件建设区 — 绿色
    "04": "#4D96FF",  # 禁止建设区 — 蓝色
    "05": "#C9B1FF",  # 永久基本农田保护区 — 紫色
    "06": "#FF8B94",  # 生态保护红线区 — 粉色
}


__all__ = [
    # Group A: Admin
    "AdminArea",
    "AdminBoundaryLine",
    # Group C: Current features
    "CurrentBuilding",
    "CurrentRoad",
    "CurrentFacility",
    "CurrentAnnotation",
    "PlannedRoad",
    "GeologicalHazardPoint",
    "ConditionalConstructionZone",
    # Group D: Control lines
    "ControlLine",
    "FarmlandProtection",
    "EcologicalRedline",
    "CultivatedLandTarget",
    "UrbanDevBoundary",
    "VillageDevBoundary",
    "HazardControlLine",
    "FloodControlLine",
    "HistoricalProtection",
    # Group D: Core planning layers
    "LandUseZone",
    "ConstructionCtrlZone",
    "PlanningScope",
    # Constants
    "SPACE_CONTROL_ZONE_TYPES",
    "SPACE_CONTROL_ZONE_COLORS",
]
