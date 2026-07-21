"""村庄规划空间要素类型定义 — 覆盖全部空间要素类别。

参照: docs/gis/规划所需数据类型与图层分类.md
      广东省《村庄规划数据库技术规范》送审稿(2026)
      广东省村庄规划编制基本技术指南(试行)(2019)

类型分组:
  Group A: 行政区划 (AdminBoundary)
  Group B: 地类图斑 (LandUse) — 基期年现状 + 目标年规划用地分类
  Group C: 基期年现状要素 (CurrentFeatures)
  Group D: 目标年规划要素 (Planned)
  Group E: 基础地理信息要素 (DLG)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


# ── 空间要素基类 (所有 Group 共享) ──

GB_T21010 = "gbt21010"
TUGUI = "tugui"
APPENDIX5 = "appendix5"
GHFLBM_SYS = "ghflbm"
YDYHFL = "ydyhfldm"
VNE = "vne"


@dataclass
class SpatialFeature:
    """所有空间要素的统一基类 — 从 GeoJSON Feature 解析。

    共享字段:
      - geometry: GeoJSON 几何对象 (必选, 无默认值)
      - bsm: 标识码 (必选, 流水编号)
      - ysdm: 要素代码 (必选, 10位)
      - _raw: 原始 properties dict (调试用, 禁止业务使用)
    """

    geometry: Dict[str, Any]      # GeoJSON geometry

    bsm: str = ""                 # 标识码 (必选, 流水编号)
    ysdm: str = ""                # 要素代码 (必选, 10位)

    _raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def geometry_type(self) -> str:
        return self.geometry.get("type", "Unknown")


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
# Group B: 地类图斑 (LandUse — Base Year / Planned)
# ============================================================
# 广东省技术指南附录5 村庄规划用地分类表
# 基期年现状: CurrentLandUseParcel (dlbm=appendix5, sddlbm=appendix5)
# 目标年规划: PlannedLandUseParcel (qmdlbm=tugui, ghytbm=appendix5, ghflbm=ghflbm)


# ── 地块基类 + 现状/规划子类 ──


@dataclass
class BaseLandUseParcel(SpatialFeature):
    """地块基类 — 现状层和规划层的共享属性。

    所有下游泛型代码使用此类处理不区分层的数据。
    需要层特定字段时使用 CurrentLandUseParcel 或 PlannedLandUseParcel。
    """

    # ── 地类编码 (共享, 但编码体系因层而异) ──
    dlbm: str = ""
    dlbm_system: str = ""    # 现状=appendix5, 规划=tugui

    # ── 通用属性 ──
    name: str = ""           # DLMC/GHYTMC 等名称字段
    area_sqm: float = 0.0    # 面积 (平方米)

    # ── 计算属性 ──
    zone_type: str = ""       # 从编码查表获得 (功能分区)
    planning_zone: str = ""   # 从编码查表获得 (规划分区)
    primary_zone: str = ""    # 从编码查表获得 (三区三线)

    @property
    def primary_code(self) -> str:
        """功能分区的首选编码 (基类默认用 DLBM)."""
        return self.dlbm

    @property
    def primary_system(self) -> str:
        """primary_code 对应的编码体系."""
        return self.dlbm_system


@dataclass
class CurrentLandUseParcel(BaseLandUseParcel):
    """现状地类图斑 — DLBM 使用 appendix5 编码 (编制实践, 非规范要求).

    独有字段: sddlbm (三调地类编码, 从 DLBM 复制, 值同 appendix5).
    无规划字段: ghytbm, ghflbm, qmdlbm 等均不存在.
    """

    sddlbm: str = ""
    sddlbm_system: str = ""  # appendix5 (从 DLBM 复制)


@dataclass
class PlannedLandUseParcel(BaseLandUseParcel):
    """期末地类图斑 — 多编码体系并存.

    编码体系:
      dlbm/qmdlbm  → tugui (广东省土规数据库标准)
      ghytbm        → appendix5 (广东省技术指南附录5)
      ghflbm/qmghflbm → ghflbm (规划分类编码, 比 appendix5 更粗)
    """

    qmdlbm: str = ""
    qmdlbm_system: str = ""      # tugui

    ghytbm: str = ""
    ghytbm_system: str = ""      # appendix5

    ghytmc: str = ""

    ghflbm: str = ""
    ghflbm_system: str = ""      # ghflbm

    qmghflbm: str = ""
    qmghflbm_system: str = ""    # ghflbm

    @property
    def primary_code(self) -> str:
        """规划层优先用 GHYTBM(附录5) 做功能分区."""
        return self.ghytbm or self.dlbm

    @property
    def primary_system(self) -> str:
        """primary_code 对应的编码体系."""
        return self.ghytbm_system or self.dlbm_system



# ============================================================
# Group C: 基期年现状要素 (CurrentFeatures — Base Year)
# ============================================================
# 广东省技术指南 1.2.1 基期年现状要素:
#   现状建筑, 现状道路, 现状基础设施, 现状公共服务设施, 现状用地用海
# 注记 (CurrentAnnotation) 为辅助标注类型, 不在标准图层定义中.


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
    """现状注记 (点) — 基期年现状要素, 辅助标注类型.

    广东省技术指南未定义"注记"图层, 此为辅助标注,
    不进入汇交成果, 仅用于可视化参考.
    GDB 导出层: current_annotation
    category 取值: 现状设施点/村名
    """

    text: str = ""           # 注记文本 (≤100字符)
    category: str = ""       # 注记分类 (现状设施点/村名)


# ============================================================
# Group D: 目标年规划要素 (Planned — Target Year)
# ============================================================
# 广东省技术指南 1.2.2 目标年规划要素:
#   控制线 (三条控制线/历史文化/安全控制线/村庄建设边界)
#   国土空间布局 (规划用地用海/重点地块图则)
#   规划道路, 地质灾害点, 有条件建设区等.
# 广东省技术指南表2: 4个必选汇交图层 (GHCFW/QMDLTB/TDYT/JSYDGZQ).


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


# ── 地质灾害点 (点要素, 与 HazardControlLine 面要素互补) ──


@dataclass
class GeologicalHazardPoint(SpatialFeature):
    """地质灾害点 (点) — 目标年规划要素.

    与 HazardControlLine (灾害风险防控线, 面) 不同,
    本类型表示单个地质灾害点 (崩塌/滑坡/泥石流等).
    """

    name: str = ""           # 地质灾害点名称
    longitude: str = ""      # 经度 (DMS 格式, 如 "116° 3' 39.000\" E")
    latitude: str = ""       # 纬度 (DMS 格式)
    hazard_type: str = ""    # 灾害类型 (崩塌/滑坡/泥石流/地面塌陷)
    scale: str = ""          # 灾害规模 (小型/中型/大型)


@dataclass
class FloodControlLine(ControlLine):
    """洪涝风险控制线 (面) — 安全控制线.

    参考图层命名: HLFXKZX
    """

    flood_frequency: str = ""  # 洪水频率 (如 "20年一遇", "50年一遇")
    control_elevation: float = 0.0  # 控制高程 (米)


# ── 规划道路 (基础设施) ──


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


# ── 规划注记 (辅助标注) ──


@dataclass
class PlannedAnnotation(SpatialFeature):
    """规划注记 (点) — 目标年规划要素, 辅助标注类型.

    与 CurrentAnnotation 字段相同, 但类型独立,
    确保现状要素和规划要素的数据类型严格分离.
    GDB 导出层: planned_annotation
    category 取值: 规划设施点
    """

    text: str = ""           # 注记文本 (≤100字符)
    category: str = ""       # 注记分类 (规划设施点)


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


# ── 有条件建设区 (与 ConstructionCtrlZone 互补, 面要素) ──


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
# Group E: 基础地理信息要素 (DLG) 🔴 未实现
# ============================================================
# 广东省技术指南表2定义的汇交图层仅4个 (GHCFW/QMDLTB/TDYT/JSYDGZQ),
# 以下要素属于"基础地理信息", 不进入汇交成果, 但作为输入/参考数据.
# 注记类地名由 CurrentAnnotation(category="村名") 覆盖, 不单独建类型.
# 注: PlaceNameAnnotation 已删除, 无需单独类型 (CurrentAnnotation 以 category 区分).


@dataclass
class ContourLine(SpatialFeature):
    """等高线 (线) -- 基础地理信息要素 (DLG).

    来源: 数字线划地图 (1:2000 DLG)
    用途: 地形可视化、DEM验证
    规范: GB/T 13923-2022 要素分类代码 210100(等高线)
    """

    elevation: float = 0.0        # 高程值 (米)
    contour_type: str = ""        # 等高线类型 (首曲线/计曲线/间曲线)


@dataclass
class ElevationPoint(SpatialFeature):
    """高程点 (点) -- 基础地理信息要素 (DLG).

    来源: 数字线划地图 (1:2000 DLG)
    用途: 高程控制点、地形标注
    规范: GB/T 13923-2022 要素分类代码 210200(高程点)
    注: 与 CurrentAnnotation(category="高程点") 不同,
        本类型有 elevation 数值字段, 适用于DEM验证和地形分析.
    """

    elevation: float = 0.0        # 高程值 (米, 1985国家高程基准)
    point_type: str = ""          # 点类型 (控制点/注记点/特征点)


@dataclass
class WaterFeature(SpatialFeature):
    """水系要素 (线/面) -- 基础地理信息要素 (DLG).

    来源: 天地图WFS (HYDL/HYDA) / 1:25万基础地理数据库
    用途: 洪涝风险分析、生态空间划定
    规范: GB/T 13923-2022 要素分类代码 210000(水系)
    """

    water_type: str = ""          # 水系类型 (河流/湖泊/水库/坑塘/沟渠)
    water_name: str = ""          # 水系名称
    flow_direction: str = ""      # 流向 (仅线要素)


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
    # Group B: LandUse parcels
    "SpatialFeature",
    "BaseLandUseParcel",
    "CurrentLandUseParcel",
    "PlannedLandUseParcel",
    # Encoding constants
    "GB_T21010", "TUGUI", "APPENDIX5",
    "GHFLBM_SYS", "YDYHFL", "VNE",
    # Group C: Current features
    "CurrentBuilding",
    "CurrentRoad",
    "CurrentFacility",
    "CurrentAnnotation",
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
    # Group D: Planned infrastructure
    "PlannedRoad",
    # Group D: Planned annotation
    "PlannedAnnotation",
    # Group D: Hazard points
    "GeologicalHazardPoint",
    # Group D: Conditional construction
    "ConditionalConstructionZone",
    # Group D: Core planning layers
    "LandUseZone",
    "ConstructionCtrlZone",
    "PlanningScope",
    # Group E: Basic geographic info (DLG)
    "ContourLine",
    "ElevationPoint",
    "WaterFeature",
    # Constants
    "SPACE_CONTROL_ZONE_TYPES",
    "SPACE_CONTROL_ZONE_COLORS",
]
