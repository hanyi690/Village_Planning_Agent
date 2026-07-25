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

from .base import SpatialFeature, PointFeature, LineFeature, PolygonFeature  # noqa: F401


# ── 空间要素基类 (SpatialFeature → 定义在 base.py, 这里重导出) ──

GB_T21010 = "gbt21010"
TUGUI = "tugui"
APPENDIX5 = "appendix5"
GHFLBM_SYS = "ghflbm"
YDYHFL = "ydyhfldm"
VNE = "vne"


# ============================================================
# Group A: 行政区划
# ============================================================


@dataclass
class AdminArea(PolygonFeature):
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
class AdminBoundaryLine(LineFeature):
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
class BaseLandUseParcel(PolygonFeature):
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
class CurrentBuilding(PointFeature):
    """现状建筑 (面) — 基期年现状要素.

    来源于现状调查, 包含建筑类型、层数、面积等信息.
    """

    building_type: str = "" # 建筑类型 (住宅/公建/产业/附属)
    floors: int = 0         # 层数
    area_sqm: float = 0.0   # 建筑面积 (平方米)
    structure: str = ""     # 结构类型 (砖混/框架/土木/钢)


# ── [v4.2] BaseRoad (道路基类, 现状/规划共享) ──


@dataclass
class BaseRoad(LineFeature):
    """道路基类 — 现状道路和规划道路的共享属性."""

    road_level: str = ""       # 道路等级 (村道/乡道/县道)
    road_width: float = 0.0    # 道路宽度 (米)
    road_name: str = ""        # 道路名称
    shape_length: float = 0.0  # 几何长度 (米)


@dataclass
class CurrentRoad(BaseRoad):
    """现状道路 (线) — 基期年现状要素.

    GDB 图层: current_road
    """

    @classmethod
    def from_geojson_feature(cls, feature: dict) -> "CurrentRoad":
        """从 GeoJSON Feature 构建 typed model."""
        props = feature.get("properties", {})
        return cls(
            geometry=feature.get("geometry", {}),
            bsm=props.get("BSM", ""),
            shape_length=float(props.get("Shape_Length", 0) or 0),
            road_level=props.get("road_level", "村道"),
            road_width=float(props.get("road_width", 0) or 0),
            road_name=props.get("road_name", ""),
            _raw=props,
        )


# Facility type mapping from annotation text labels.
# Single source of truth — used by spatial_types.CurrentFacility.from_annotation_feature
# and spatial_context._extract_facility_anchors.
ANNOTATION_LABEL_TYPE_MAP: Dict[str, str] = {
    "篮": "体育", "健": "体育", "广": "广场", "停": "停车",
    "电": "电力", "污": "排水", "水": "给水", "垃": "环卫",
    "卫": "公厕", "祠": "文化", "村": "村委会", "站": "交通",
    "小": "学校",
}


# ── [v4.2] BaseFacility (设施基类, 现状/规划共享) ──


@dataclass
class BaseFacility(PointFeature):
    """设施基类 — 空间实体 (入 KG, 参与空间分析).

    现状设施和规划设施的共享属性.
    """

    facility_type: str = ""  # 设施类型 (给水/排水/电力/环卫/公厕/村委会/卫生室/学校/广场)
    facility_name: str = ""  # 设施名称
    scale: str = ""          # 规模描述 (如 "50m³/d", "200㎡")
    service_radius: float = 0.0  # 服务半径 (米, 公共服务设施)
    category: str = ""       # 分类: infrastructure(基础设施) / public_service(公共服务)


@dataclass
class CurrentFacility(BaseFacility):
    """现状设施 (点) — 基期年现状要素.

    包含基础设施点和公共服务设施点.
    """

    @classmethod
    def from_annotation_feature(cls, feature: dict) -> "CurrentFacility | None":
        """从 annotation.geojson 的设施点 Feature 构建.
        注记文本作为设施名称, 坐标作为位置.
        返回 None 如果分类不是现状设施点.
        """
        props = feature.get("properties", {})
        category = props.get("分类", props.get("category", ""))
        if category != "现状设施点":
            return None

        text = props.get("注记", props.get("text", ""))
        facility_type = ANNOTATION_LABEL_TYPE_MAP.get(text, "公共服务")
        # 分类: 基础设施(电/水/污) vs 公共服务(广场/文化/体育/学校)
        infra_types = {"电力", "排水", "给水", "环卫", "交通"}
        cat = "infrastructure" if facility_type in infra_types else "public_service"

        return cls(
            geometry=feature.get("geometry", {}),
            bsm=props.get("BSM", ""),
            facility_type=facility_type,
            facility_name=text,
            scale="",
            service_radius=0.0,
            category=cat,
            _raw=props,
        )


@dataclass
class PlannedFacility(BaseFacility):
    """规划设施 (点) — 目标年规划要素. [v4.2]

    从旧 PlannedAnnotation 拆出, 设施统一为空间实体.
    """

    status: str = ""  # "新建" | "改扩建" | "迁建"


# ── [v4.2] AnnotationFeature (表达要素基类, 非空间实体) ──


@dataclass
class AnnotationFeature(PointFeature):
    """表达要素基类 — 非空间实体, 不入 KG, 不参与空间分析.

    注记是文字标注, 不是空间实体. 设施是空间实体 (BaseFacility),
    注记降为表达层 (AnnotationFeature).
    geometry_kind="annotation" 在 layer_registry 中区分.
    """

    text: str = ""           # 注记文本 (≤100字符)
    category: str = ""       # 注记分类


@dataclass
class CurrentAnnotation(AnnotationFeature):
    """现状注记 (点) — 基期年现状要素, 辅助标注类型.

    广东省技术指南未定义"注记"图层, 此为辅助标注,
    不进入汇交成果, 仅用于可视化参考.
    GDB 导出层: current_annotation
    category 取值: 现状设施点/村名
    """

    @classmethod
    def from_geojson_feature(cls, feature: dict) -> "CurrentAnnotation":
        """从 GeoJSON Feature 构建 typed model.
        处理中文字段名: 注记→text, 分类→category
        """
        props = feature.get("properties", {})
        return cls(
            geometry=feature.get("geometry", {}),
            bsm=props.get("BSM", ""),
            text=props.get("注记", props.get("text", "")),
            category=props.get("分类", props.get("category", "")),
            _raw=props,
        )


# ============================================================
# Group D: 目标年规划要素 (Planned — Target Year)
# ============================================================
# 广东省技术指南 1.2.2 目标年规划要素:
#   控制线 (三条控制线/历史文化/安全控制线/村庄建设边界)
#   国土空间布局 (规划用地用海/重点地块图则)
#   规划道路, 地质灾害点, 有条件建设区等.
# 广东省技术指南表2: 4个必选汇交图层 (GHCFW/QMDLTB/TDYT/JSYDGZQ).


# ── [v4.2] BaseControlZone (管控区基类) ──


@dataclass
class BaseControlZone(PolygonFeature):
    """管控区基类 — 统一三区+三线+管制区+用途分区的管控语义.

    Shared fields: mj (面积), protection_level (保护等级), control_measure (管控措施).
    """

    mj: float = 0.0          # 面积 (平方米)
    protection_level: str = ""  # 保护等级 (核心/一般/缓冲)
    control_measure: str = ""   # 管控措施


@dataclass
class ControlLine(BaseControlZone):
    """控制线基类 (面) — 目标年规划要素.

    所有控制线/保护线/边界的共享属性.
    子类: 永久基本农田, 生态保护红线, 耕地保护目标,
          城镇开发边界, 村庄建设边界, 灾害风险防控线, 洪涝风险控制线
    """


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

    @classmethod
    def from_geojson_feature(cls, feature: dict) -> "EcologicalRedline":
        """从 GeoJSON Feature 构建 typed model.

        处理中文字段名: 区县→district, 地市→city, OBJECTID→object_id.
        ControlLine 共享字段: mj (面积).
        """
        props = feature.get("properties", {})
        try:
            obj_id = int(props.get("OBJECTID", props.get("object_id", 0)) or 0)
        except (ValueError, TypeError):
            obj_id = 0
        return cls(
            geometry=feature.get("geometry", {}),
            bsm=str(props.get("BSM", "")).strip(),
            mj=float(props.get("MJ", props.get("mj", 0)) or 0),
            district=str(props.get("区县", props.get("district", ""))).strip(),
            city=str(props.get("地市", props.get("city", ""))).strip(),
            object_id=obj_id,
            _raw=props,
        )


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
class GeologicalHazardPoint(PointFeature):
    """地质灾害点 (点) — 目标年规划要素.

    与 HazardControlLine (灾害风险防控线, 面) 不同,
    本类型表示单个地质灾害点 (崩塌/滑坡/泥石流等).
    """

    name: str = ""           # 地质灾害点名称
    longitude: str = ""      # 经度 (DMS 格式, 如 "116° 3' 39.000\" E")
    latitude: str = ""       # 纬度 (DMS 格式)
    hazard_type: str = ""    # 灾害类型 (崩塌/滑坡/泥石流/地面塌陷)
    scale: str = ""          # 灾害规模 (小型/中型/大型)

    @classmethod
    def from_geojson_feature(cls, feature: dict) -> "GeologicalHazardPoint":
        """从 GeoJSON Feature 构建 typed model.

        处理中文字段名: 名称→name, 类型→hazard_type, 大小→scale,
                       纬度→latitude, 经度→longitude
        """
        props = feature.get("properties", {})
        return cls(
            geometry=feature.get("geometry", {}),
            bsm=str(props.get("BSM", "")).strip(),
            name=str(props.get("名称", props.get("name", ""))).strip(),
            longitude=str(props.get("经度", props.get("longitude", ""))).strip(),
            latitude=str(props.get("纬度", props.get("latitude", ""))).strip(),
            hazard_type=str(props.get("类型", props.get("hazard_type", ""))).strip(),
            scale=str(props.get("大小", props.get("scale", ""))).strip(),
            _raw=props,
        )


@dataclass
class FloodControlLine(ControlLine):
    """洪涝风险控制线 (面) — 安全控制线.

    参考图层命名: HLFXKZX
    """

    flood_frequency: str = ""  # 洪水频率 (如 "20年一遇", "50年一遇")
    control_elevation: float = 0.0  # 控制高程 (米)


# ── 规划道路 (基础设施) ──


@dataclass
class PlannedRoad(BaseRoad):
    """规划道路 (线) — 目标年规划要素.

    GDB 图层: planned/road.geojson
    字段: LnType (道路类型), LeftLn_FID (左侧车道要素ID),
          RightLn_FID (右侧车道要素ID)
    road_level, road_width, road_name, shape_length 继承自 BaseRoad.
    """

    ln_type: str = ""           # 道路类型
    left_ln_fid: str = ""       # 左侧车道要素ID
    right_ln_fid: str = ""      # 右侧车道要素ID


# ── 规划注记 (辅助标注) ──


@dataclass
class PlannedAnnotation(AnnotationFeature):
    """规划注记 (点) — 目标年规划要素, 辅助标注类型.

    与 CurrentAnnotation 字段相同, 但类型独立,
    确保现状要素和规划要素的数据类型严格分离.
    GDB 导出层: planned_annotation
    category 取值: 规划设施点
    """


@dataclass
class HistoricalProtection(PolygonFeature):
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
class LandUseZone(PolygonFeature):
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
class ConstructionCtrlZone(PolygonFeature):
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
class ConditionalConstructionZone(PolygonFeature):
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
class PlanningScope(PolygonFeature):
    """规划村范围 GHCFW (面) — 管理类数据 (必选).

    规范来源: 广东省技术指南 表3 (5字段)
    用途: 定义本次村庄规划的编制范围
    """

    xzqhdm: str = ""         # 行政区划代码 (12位, GB/T 2260)
    xzqhmc: str = ""         # 行政区划名称 (≤100字符)
    mj: float = 0.0          # 椭球面积 (平方米, 保留到个位)
    bz: str = ""             # 备注 (≤200字符, 可选)


# ── [v4.2] ThreeZoneItem (三区空间类型) ──


@dataclass
class ThreeZoneItem(PolygonFeature):
    """三区 — 生态空间/农业空间/建设空间. [v4.2]

    矢量图层 (面), 引用层 (中央审批成果), 村庄级不重建.
    与 parse_contracts.ThreeZoneItem (PARSE 产出契约) 平行,
    本类为空间矢量类型 (有 geometry), 契约类为数据模型 (无 geometry).
    """

    zone_type: str = ""  # "ecological" | "agricultural" | "construction"
    zone_name: str = ""  # 生态空间 | 农业空间 | 建设空间
    area_ha: float = 0.0


# ============================================================
# Group E: 基础地理信息要素 (DLG) 🔴 未实现
# ============================================================
# 广东省技术指南表2定义的汇交图层仅4个 (GHCFW/QMDLTB/TDYT/JSYDGZQ),
# 以下要素属于"基础地理信息", 不进入汇交成果, 但作为输入/参考数据.
# 注记类地名由 CurrentAnnotation(category="村名") 覆盖, 不单独建类型.
# 注: PlaceNameAnnotation 已删除, 无需单独类型 (CurrentAnnotation 以 category 区分).


@dataclass
class ContourLine(LineFeature):
    """等高线 (线) -- 基础地理信息要素 (DLG).

    来源: 数字线划地图 (1:2000 DLG)
    用途: 地形可视化、DEM验证
    规范: GB/T 13923-2022 要素分类代码 210100(等高线)
    """

    elevation: float = 0.0        # 高程值 (米)
    contour_type: str = ""        # 等高线类型 (首曲线/计曲线/间曲线)


@dataclass
class ElevationPoint(PointFeature):
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
class WaterFeature(PolygonFeature):
    """水系要素 (线/面) -- 基础地理信息要素 (DLG).

    来源: 天地图WFS (HYDL/HYDA) / 1:25万基础地理数据库
    用途: 洪涝风险分析、生态空间划定
    规范: GB/T 13923-2022 要素分类代码 210000(水系)
    """

    water_type: str = ""          # 水系类型 (河流/湖泊/水库/坑塘/沟渠)
    water_name: str = ""          # 水系名称
    flow_direction: str = ""      # 流向 (仅线要素)


# ============================================================
# Group F: 自然资源 (Natural Resources) [v4.2]
# ============================================================
# 对齐 docs/gis/01_DATA_ACQUISITION_PLAN.md §4.1
# 以及 SCHEMA_COVERAGE_AUDIT B1 自然环境类


@dataclass
class SoilType(PolygonFeature):
    """土壤类型 (面) — Group F 自然资源.

    来源: 土壤普查/农业农村部门
    用途: 农业适宜性评价、土壤污染防治
    """

    soil_code: str = ""          # 土壤类型编码
    soil_name: str = ""          # 土壤类型名称


@dataclass
class SoilErosion(PolygonFeature):
    """土壤侵蚀 (面) — Group F 自然资源.

    来源: 水利部门水土保持数据
    用途: 生态敏感区划定、水土保持规划
    """

    erosion_level: str = ""      # 侵蚀等级 (轻度/中度/强烈/极强烈/剧烈)


@dataclass
class Watershed(PolygonFeature):
    """流域 (面) — Group F 自然资源.

    来源: 水利部门流域数据
    用途: 水资源管理、生态空间划定
    """

    watershed_code: str = ""     # 流域编码
    watershed_name: str = ""     # 流域名称


@dataclass
class NatureReserve(PolygonFeature):
    """自然保护区 (面) — Group F 自然资源.

    来源: 林业和草原部门
    用途: 生态保护红线划定依据
    """

    reserve_name: str = ""       # 保护区名称
    reserve_level: str = ""      # 保护级别 (国家级/省级/市县级)


@dataclass
class HydrogeologyZone(PolygonFeature):
    """水文地质分区 (面) — Group F 自然资源.

    来源: 地质调查部门
    用途: 地下水资源评价、地质灾害评估
    """

    zone_code: str = ""          # 水文地质分区编码
    zone_name: str = ""          # 水文地质分区名称


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
    # Base (re-export from base.py)
    "SpatialFeature",
    "PointFeature",
    "LineFeature",
    "PolygonFeature",
    # Group A: Admin
    "AdminArea",
    "AdminBoundaryLine",
    # Group B: LandUse parcels
    "BaseLandUseParcel",
    "CurrentLandUseParcel",
    "PlannedLandUseParcel",
    # Encoding constants
    "GB_T21010", "TUGUI", "APPENDIX5",
    "GHFLBM_SYS", "YDYHFL", "VNE",
    # [v4.2] Phase-abstraction bases
    "BaseRoad",
    "BaseFacility",
    "BaseControlZone",
    "AnnotationFeature",
    # Group C: Current features
    "CurrentBuilding",
    "CurrentRoad",
    "CurrentFacility",
    "CurrentAnnotation",
    # [v4.2] Planned facility
    "PlannedFacility",
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
    # [v4.2] Three zones
    "ThreeZoneItem",
    # Group E: Basic geographic info (DLG)
    "ContourLine",
    "ElevationPoint",
    "WaterFeature",
    # [v4.2] Group F: Natural resources
    "SoilType",
    "SoilErosion",
    "Watershed",
    "NatureReserve",
    "HydrogeologyZone",
    # Annotation label map
    "ANNOTATION_LABEL_TYPE_MAP",
    # Constants
    "SPACE_CONTROL_ZONE_TYPES",
    "SPACE_CONTROL_ZONE_COLORS",
]
