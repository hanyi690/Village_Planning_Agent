"""Pydantic output schemas for structured LLM parsing.

Contains:
- IntentOutput: GIS spatial layout intent (replaces regex-parsed JSON)
- BaseDimensionSummary + 28 dimension schemas (from summary/schema.py)
- Registry: _DIMENSION_SCHEMAS, ALL_DIMENSION_KEYS, LAYER_DIMENSIONS
- METRICS_DESCRIPTIONS: per-dimension metric hints for LLM prompts
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field, field_validator

from .semantics import SemanticField, ValueSemantics


# ---------------------------------------------------------------------------
# GIS Spatial Layout Intent Schemas
# ---------------------------------------------------------------------------


class ZoneOutput(BaseModel):
    """Functional zone intent — schema constrains area_ratio in [0,1]."""

    zone_id: str = Field(description="Zone ID, e.g. Z01")
    land_use: str = Field(
        description="Land use type",
        json_schema_extra={"enum": [
            "居住用地", "产业用地", "公共服务用地",
            "生态绿地", "交通用地", "水域", "农业用地", "商业用地",
        ]},
    )
    dlbm: str = Field(description="Primary DLBM code, e.g. 2121")
    area_ratio: float = Field(description="Area ratio (0-1)", ge=0, le=1)
    direction: str = Field(
        description="Spatial direction",
        json_schema_extra={"enum": [
            "center", "north", "south", "east", "west",
            "northeast", "northwest", "southeast", "southwest", "periphery",
            "east-west", "north-south",
        ]},
        default="center",
    )
    reference_feature: str = Field(default="", description="Location reference, e.g. 'near village committee'")
    adjacent_to: List[str] = Field(default_factory=list, description="Preferred adjacent land use types")
    avoid_adjacent_to: List[str] = Field(default_factory=list, description="Land use types to avoid adjacency")
    density: str = Field(
        description="Development density",
        json_schema_extra={"enum": ["high", "medium", "low"]},
        default="medium",
    )


class FacilityOutput(BaseModel):
    """Facility intent."""

    facility_id: str = Field(description="Facility ID, e.g. F01")
    facility_type: str = Field(
        description="Facility type",
        json_schema_extra={"enum": [
            "村委会", "学校", "卫生站", "文化站",
            "市场", "养老服务", "产业服务中心", "停车场",
        ]},
    )
    status: str = Field(
        description="Facility status",
        json_schema_extra={"enum": ["现状保留", "规划新建", "规划改扩建", "规划迁建"]},
        default="现状保留",
    )
    location_hint: str = Field(default="", description="Location hint, e.g. 'village center'")
    service_radius: int = Field(default=500, description="Service radius in meters", ge=100, le=2000)


class AxisOutput(BaseModel):
    """Development axis intent."""

    axis_id: str = Field(description="Axis ID, e.g. A01")
    axis_type: str = Field(
        description="Axis type",
        json_schema_extra={"enum": ["primary", "secondary", "corridor", "connector"]},
    )
    direction: str = Field(
        description="Direction",
        json_schema_extra={"enum": [
            "center", "north", "south", "east", "west",
            "northeast", "northwest", "southeast", "southwest",
            "east-west", "north-south",
        ]},
        default="east-west",
    )
    reference_feature: str = Field(default="", description="Reference feature for axis")


class IntentOutput(BaseModel):
    """Planning intent — replaces SPATIAL_LAYOUT_PARSE_PROMPT + regex parsing.

    Instructor + max_retries=3 guarantees schema compliance.
    """

    zones: List[ZoneOutput] = Field(description="Functional zones, area_ratio sum should be ~1.0")
    facilities: List[FacilityOutput] = Field(description="Facility layout list")
    axes: List[AxisOutput] = Field(default_factory=list, description="Development axes")
    rationale: str = Field(default="", description="Overall planning rationale")
    metadata: dict = Field(default_factory=dict, description="Metadata (total area, etc.)")


# ---------------------------------------------------------------------------
# Dimension Summary Schemas (28 dimensions)
# ---------------------------------------------------------------------------

class BaseDimensionSummary(BaseModel):
    """Common fields shared by all dimension summaries."""

    dimension_key: str = Field(description="Dimension identifier")
    layer: int = Field(ge=1, le=3, description="Planning layer")
    word_count: int = Field(ge=0, description="Word count of full report")
    key_points: List[str] = Field(default_factory=list, description="3-5 key findings")
    text_summary: str = Field(default="", description="Natural-language summary (<=200 chars)")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Dimension-specific metrics")


# ---- Layer 1: Current situation (12) ----

class LocationSummary(BaseDimensionSummary):
    province: Optional[str] = Field(default=None, description="省份")
    city: Optional[str] = Field(default=None, description="城市")
    county: Optional[str] = Field(default=None, description="县区")
    town: Optional[str] = Field(default=None, description="镇")
    road_connections: List[str] = Field(default_factory=list, description="对外连接道路列表")

class SocioEconomicSummary(BaseDimensionSummary):
    registered_population: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "人", "户籍统计", True),
        Field(default=None, description="户籍人口(人) [现状观测值]")
    ]
    resident_population: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "人", "人口普查", True),
        Field(default=None, description="常住人口(人) [现状观测值]")
    ]
    households: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "户", "户籍统计", False),
        Field(default=None, description="户数(户) [现状观测值]")
    ]
    labor_force: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "人", "户籍统计", False),
        Field(default=None, description="劳动力(人) [现状观测值]")
    ]
    migrant_workers: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "人", "户籍统计", False),
        Field(default=None, description="外出务工(人) [现状观测值]")
    ]
    aging_rate: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "%", "人口普查", False),
        Field(default=None, description="老龄化率(%) [现状观测值]")
    ]
    per_capita_income: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "元/年", "统计年鉴", False),
        Field(default=None, description="人均纯收入(元/年) [现状观测值]")
    ]
    primary_industry: Optional[str] = Field(default=None, description="第一产业描述")
    secondary_industry: Optional[str] = Field(default=None, description="第二产业描述")
    tertiary_industry: Optional[str] = Field(default=None, description="第三产业描述")

class VillagerWishesSummary(BaseDimensionSummary):
    industry_wishes: List[str] = Field(default_factory=list, description="产业发展诉求")
    environment_wishes: List[str] = Field(default_factory=list, description="环境美化诉求")
    facility_wishes: List[str] = Field(default_factory=list, description="配套设施诉求")
    priority_order: List[str] = Field(default_factory=list, description="诉求优先级排序")

class SuperiorPlanningSummary(BaseDimensionSummary):
    planning_positioning_type: Optional[str] = Field(default=None, description="规划定位类型")
    min_ecological_redline_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CONSTRAINT_LOWER, "ha", "上位规划", True),
        Field(default=None, description="生态红线面积(ha) [约束下限值]")
    ]
    min_farmland_protection_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CONSTRAINT_LOWER, "ha", "上位规划", True),
        Field(default=None, description="耕地保护面积(ha) [约束下限值]")
    ]
    max_construction_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CONSTRAINT_UPPER, "ha", "上位规划", True),
        Field(default=None, description="城镇开发边界面积(ha) [约束上限值]")
    ]

    @field_validator("max_construction_ha")
    @classmethod
    def construction_cap_must_be_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError("max_construction_ha must be positive")
        return v

    @field_validator("min_ecological_redline_ha", "min_farmland_protection_ha")
    @classmethod
    def constraint_lower_must_be_positive(cls, v):
        if v is not None and v < 0:
            raise ValueError("constraint lower bound must be non-negative")
        return v

class NaturalEnvironmentSummary(BaseDimensionSummary):
    climate_type: Optional[str] = Field(default=None, description="气候类型")
    annual_precipitation_mm: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "mm", "气象数据", False),
        Field(default=None, description="年均降水量(mm) [现状观测值]")
    ]
    annual_temp_c: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "℃", "气象数据", False),
        Field(default=None, description="年均温度(℃) [现状观测值]")
    ]
    elevation_min_m: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "m", "DEM", False),
        Field(default=None, description="最低海拔(m) [现状观测值]")
    ]
    elevation_max_m: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "m", "DEM", False),
        Field(default=None, description="最高海拔(m) [现状观测值]")
    ]
    forest_coverage_rate: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "%", "调查数据", True),
        Field(default=None, description="森林覆盖率(%) [现状观测值]")
    ]
    hazard_points_count: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "处", "地灾调查", True),
        Field(default=None, description="地质灾害隐患点数量(处) [现状观测值]")
    ]
    main_rivers: List[str] = Field(default_factory=list, description="主要河流名称列表")

class LandUseSummary(BaseDimensionSummary):
    total_area_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.BASELINE_YEAR, "ha", "三调", True),
        Field(default=None, description="总用地面积(ha) [基准年总量]")
    ]
    current_farmland_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "ha", "三调", True),
        Field(default=None, description="现状耕地面积(ha) [现状观测值]")
    ]
    current_construction_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "ha", "三调", True),
        Field(default=None, description="现状建设用地面积(ha) [现状观测值]")
    ]
    ecological_area_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "ha", "三调", True),
        Field(default=None, description="生态用地面积(ha) [现状观测值]")
    ]
    water_area_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "ha", "三调", False),
        Field(default=None, description="水域面积(ha) [现状观测值]")
    ]
    per_capita_farmland_mu: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "亩/人", "三调", False),
        Field(default=None, description="人均耕地(亩) [现状观测值]")
    ]
    forest_coverage_rate: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "%", "调查数据", True),
        Field(default=None, description="森林覆盖率(%) [现状观测值]")
    ]

class TrafficSummary(BaseDimensionSummary):
    external_road_level: Optional[str] = Field(default=None, description="对外连接道路等级")
    internal_road_hardening_rate: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "%", "交通调查", False),
        Field(default=None, description="内部道路硬化率(%) [现状观测值]")
    ]
    road_network_length_km: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "km", "交通调查", False),
        Field(default=None, description="路网总长度(km) [现状观测值]")
    ]

class PublicServicesSummary(BaseDimensionSummary):
    school_count: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "所", "设施调查", False),
        Field(default=None, description="学校数量(所) [现状观测值]")
    ]
    clinic_count: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "个", "设施调查", False),
        Field(default=None, description="卫生室数量(个) [现状观测值]")
    ]
    cultural_center_count: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "个", "设施调查", False),
        Field(default=None, description="文化活动中心数量(个) [现状观测值]")
    ]
    service_coverage_rate: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "%", "设施调查", False),
        Field(default=None, description="公共服务覆盖率(%) [现状观测值]")
    ]

class InfrastructureSummary(BaseDimensionSummary):
    water_supply_type: Optional[str] = Field(default=None, description="供水方式")
    power_capacity_kva: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "kVA", "电力调查", True),
        Field(default=None, description="变压器容量(kVA) [现状观测值]")
    ]
    broadband_coverage_rate: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "%", "通信调查", False),
        Field(default=None, description="宽带覆盖率(%) [现状观测值]")
    ]

class EcologicalGreenSummary(BaseDimensionSummary):
    green_area_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "ha", "绿地调查", False),
        Field(default=None, description="绿地面积(ha) [现状观测值]")
    ]
    green_rate: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "%", "绿地调查", False),
        Field(default=None, description="绿地率(%) [现状观测值]")
    ]
    min_ecological_redline_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CONSTRAINT_LOWER, "ha", "上位规划", True),
        Field(default=None, description="生态红线面积(ha) [约束下限值]")
    ]

class ArchitectureSummary(BaseDimensionSummary):
    total_buildings: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "栋", "建筑调查", False),
        Field(default=None, description="建筑总量(栋) [现状观测值]")
    ]
    building_area_sqm: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "m2", "建筑调查", False),
        Field(default=None, description="建筑总面积(m2) [现状观测值]")
    ]
    quality_a_rate: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "%", "建筑调查", False),
        Field(default=None, description="A级建筑占比(%) [现状观测值]")
    ]
    quality_b_rate: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "%", "建筑调查", False),
        Field(default=None, description="B级建筑占比(%) [现状观测值]")
    ]
    quality_c_rate: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "%", "建筑调查", False),
        Field(default=None, description="C级建筑占比(%) [现状观测值]")
    ]
    quality_d_rate: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "%", "建筑调查", True),
        Field(default=None, description="D级(危房)占比(%) [现状观测值]")
    ]

class HistoricalCultureSummary(BaseDimensionSummary):
    heritage_buildings: List[str] = Field(default_factory=list, description="传统风貌建筑列表")
    ancient_trees: List[str] = Field(default_factory=list, description="古树名木列表")
    intangible_heritage_items: List[str] = Field(default_factory=list, description="非物质文化遗产列表")


# ---- Layer 2: Planning concept (4) ----
# Layer 2 dimensions have no specific fields beyond BaseDimensionSummary.
# They map directly to BaseDimensionSummary in the registry.


# ---- Layer 3: Detailed planning (12) ----

class IndustrySummary(BaseDimensionSummary):
    primary_industry_type: Optional[str] = Field(default=None, description="主导产业类型")
    industry_area_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "ha", "三调", True),
        Field(default=None, description="产业用地面积(ha) [现状观测值]")
    ]
    planned_industry_area_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.PLANNED_TARGET, "ha", "规划编制", True),
        Field(default=None, description="规划产业用地面积(ha) [规划目标值]")
    ]
    layout_direction: Optional[str] = Field(default=None, description="产业布局方向")
    zone_count: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "个", "规划编制", False),
        Field(default=None, description="产业分区数量(个) [现状观测值]")
    ]

class SpatialStructureSummary(BaseDimensionSummary):
    structure_pattern: Optional[str] = Field(default=None, description="空间结构模式(如一核一带三区)")
    core_count: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.PLANNED_TARGET, "个", "规划编制", False),
        Field(default=None, description="核心数量(个) [规划目标值]")
    ]
    axis_count: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.PLANNED_TARGET, "个", "规划编制", False),
        Field(default=None, description="发展轴数量(个) [规划目标值]")
    ]
    zone_names: List[str] = Field(default_factory=list, description="分区名称列表")
    zone_directions: Dict[str, str] = Field(default_factory=dict, description="分区方向映射")

class LandUsePlanningSummary(BaseDimensionSummary):
    current_construction_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "ha", "三调", True),
        Field(default=None, description="现状建设用地面积(ha) [现状观测值]")
    ]
    planned_construction_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.PLANNED_TARGET, "ha", "规划编制", True),
        Field(default=None, description="规划建设用地面积(ha) [规划目标值]")
    ]
    planned_farmland_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.PLANNED_TARGET, "ha", "规划编制", True),
        Field(default=None, description="规划耕地面积(ha) [规划目标值]")
    ]
    planned_ecological_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.PLANNED_TARGET, "ha", "规划编制", True),
        Field(default=None, description="规划生态用地面积(ha) [规划目标值]")
    ]
    planned_residential_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.PLANNED_TARGET, "ha", "规划编制", False),
        Field(default=None, description="规划居住用地面积(ha) [规划目标值]")
    ]
    planned_industry_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.PLANNED_TARGET, "ha", "规划编制", True),
        Field(default=None, description="规划产业用地面积(ha) [规划目标值]")
    ]
    planned_public_service_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.PLANNED_TARGET, "ha", "规划编制", False),
        Field(default=None, description="规划公共服务用地面积(ha) [规划目标值]")
    ]
    planned_traffic_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.PLANNED_TARGET, "ha", "规划编制", False),
        Field(default=None, description="规划交通用地面积(ha) [规划目标值]")
    ]

    @field_validator("planned_construction_ha")
    @classmethod
    def planned_construction_sanity(cls, v, info):
        current = info.data.get("current_construction_ha")
        if v is not None and current is not None and current > 0 and v < current * 0.5:
            raise ValueError(
                f"planned_construction_ha ({v}) 远小于 current_construction_ha ({current})"
            )
        return v

class SettlementPlanningSummary(BaseDimensionSummary):
    current_construction_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "ha", "调查数据", True),
        Field(default=None, description="现状建设用地面积(ha) [现状观测值]")
    ]
    planned_construction_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.PLANNED_TARGET, "ha", "规划编制", True),
        Field(default=None, description="规划建设用地面积(ha) [规划目标值]")
    ]
    per_capita_construction_sqm: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "m2/人", "调查数据", True),
        Field(default=None, description="人均建设用地(m2/人) [现状观测值]")
    ]
    planned_population: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.PLANNED_TARGET, "人", "规划编制", True),
        Field(default=None, description="规划人口(人) [规划目标值]")
    ]
    residential_area_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "ha", "调查数据", False),
        Field(default=None, description="居住用地面积(ha) [现状观测值]")
    ]
    expansion_direction: Optional[str] = Field(default=None, description="村庄扩展方向")

class TrafficPlanningSummary(BaseDimensionSummary):
    planned_road_length_km: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.PLANNED_TARGET, "km", "规划编制", False),
        Field(default=None, description="规划道路总长度(km) [规划目标值]")
    ]
    planned_road_count: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.PLANNED_TARGET, "条", "规划编制", False),
        Field(default=None, description="规划道路数量(条) [规划目标值]")
    ]
    main_road_names: List[str] = Field(default_factory=list, description="主要道路名称")

class PublicServicePlanningSummary(BaseDimensionSummary):
    planned_facility_count: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.PLANNED_TARGET, "个", "规划编制", False),
        Field(default=None, description="规划设施数量(个) [规划目标值]")
    ]
    planned_facility_types: List[str] = Field(default_factory=list, description="规划设施类型列表")

class InfrastructurePlanningSummary(BaseDimensionSummary):
    planned_water_supply_type: Optional[str] = Field(default=None, description="规划供水方式")
    planned_power_capacity_kva: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.PLANNED_TARGET, "kVA", "规划编制", True),
        Field(default=None, description="规划变压器容量(kVA) [规划目标值]")
    ]

class EcologicalPlanningSummary(BaseDimensionSummary):
    planned_ecological_area_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.PLANNED_TARGET, "ha", "规划编制", True),
        Field(default=None, description="规划生态用地面积(ha) [规划目标值]")
    ]
    min_ecological_redline_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CONSTRAINT_LOWER, "ha", "上位规划", True),
        Field(default=None, description="生态保护红线面积(ha) [约束下限值]")
    ]
    protection_zone_names: List[str] = Field(default_factory=list, description="保护区名称列表")

class DisasterPreventionSummary(BaseDimensionSummary):
    hazard_points_count: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.CURRENT_OBSERVED, "处", "地灾调查", True),
        Field(default=None, description="地质灾害隐患点数量(处) [现状观测值]")
    ]
    hazard_buffer_zone_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CONSTRAINT_LOWER, "ha", "地灾评估", True),
        Field(default=None, description="地质灾害缓冲区面积(ha) [约束下限值]")
    ]
    evacuation_routes: List[str] = Field(default_factory=list, description="疏散路线列表")

class HeritagePlanningSummary(BaseDimensionSummary):
    protection_zone_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.CONSTRAINT_LOWER, "ha", "文物保护", True),
        Field(default=None, description="文物保护用地面积(ha) [约束下限值]")
    ]
    heritage_items: List[str] = Field(default_factory=list, description="文物保护项目列表")

class LandscapeSummary(BaseDimensionSummary):
    landscape_area_ha: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.PLANNED_TARGET, "ha", "规划编制", False),
        Field(default=None, description="景观绿地面积(ha) [规划目标值]")
    ]
    landscape_nodes: List[str] = Field(default_factory=list, description="景观节点列表")

class ProjectBankSummary(BaseDimensionSummary):
    total_projects: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.PLANNED_TARGET, "个", "项目库", False),
        Field(default=None, description="项目总数(个) [规划目标值]")
    ]
    total_investment_wan_yuan: Annotated[
        Optional[float],
        SemanticField(ValueSemantics.PLANNED_TARGET, "万元", "项目库", False),
        Field(default=None, description="总投资(万元) [规划目标值]")
    ]
    short_term_projects: Annotated[
        Optional[int],
        SemanticField(ValueSemantics.PLANNED_TARGET, "个", "项目库", False),
        Field(default=None, description="近期项目数(个) [规划目标值]")
    ]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_DIMENSION_SCHEMAS: Dict[str, Type[BaseDimensionSummary]] = {
    "location": LocationSummary,
    "socio_economic": SocioEconomicSummary,
    "villager_wishes": VillagerWishesSummary,
    "superior_planning": SuperiorPlanningSummary,
    "natural_environment": NaturalEnvironmentSummary,
    "land_use": LandUseSummary,
    "traffic": TrafficSummary,
    "public_services": PublicServicesSummary,
    "infrastructure": InfrastructureSummary,
    "ecological_green": EcologicalGreenSummary,
    "architecture": ArchitectureSummary,
    "historical_culture": HistoricalCultureSummary,
    "resource_endowment": BaseDimensionSummary,
    "planning_positioning": BaseDimensionSummary,
    "development_goals": BaseDimensionSummary,
    "planning_strategies": BaseDimensionSummary,
    "industry": IndustrySummary,
    "spatial_structure": SpatialStructureSummary,
    "land_use_planning": LandUsePlanningSummary,
    "settlement_planning": SettlementPlanningSummary,
    "traffic_planning": TrafficPlanningSummary,
    "public_service": PublicServicePlanningSummary,
    "infrastructure_planning": InfrastructurePlanningSummary,
    "ecological": EcologicalPlanningSummary,
    "disaster_prevention": DisasterPreventionSummary,
    "heritage": HeritagePlanningSummary,
    "landscape": LandscapeSummary,
    "project_bank": ProjectBankSummary,
}

ALL_DIMENSION_KEYS = list(_DIMENSION_SCHEMAS.keys())

LAYER_DIMENSIONS: Dict[int, List[str]] = {
    1: [
        "location", "socio_economic", "villager_wishes", "superior_planning",
        "natural_environment", "land_use", "traffic", "public_services",
        "infrastructure", "ecological_green", "architecture", "historical_culture",
    ],
    2: [
        "resource_endowment", "planning_positioning", "development_goals",
        "planning_strategies",
    ],
    3: [
        "industry", "spatial_structure", "land_use_planning", "settlement_planning",
        "traffic_planning", "public_service", "infrastructure_planning", "ecological",
        "disaster_prevention", "heritage", "landscape", "project_bank",
    ],
}

_BASE_SUMMARY_FIELDS = frozenset({
    "dimension_key", "layer", "word_count", "key_points", "text_summary", "metrics",
})


def _build_metrics_descriptions() -> Dict[str, Dict[str, str]]:
    """Auto-generate metric descriptions from schema model_fields.

    Replaces the old hardcoded METRICS_DESCRIPTIONS dict.
    Reads Field(description=...) from each dimension schema class,
    skipping the 6 common BaseDimensionSummary fields.
    """
    descriptions: Dict[str, Dict[str, str]] = {}
    for dim_key, schema_cls in _DIMENSION_SCHEMAS.items():
        fields: Dict[str, str] = {}
        for fname, finfo in schema_cls.model_fields.items():
            if fname in _BASE_SUMMARY_FIELDS:
                continue
            desc = finfo.description
            if desc:
                fields[fname] = desc
        if fields:
            descriptions[dim_key] = fields
    return descriptions


METRICS_DESCRIPTIONS: Dict[str, Dict[str, str]] = _build_metrics_descriptions()


def get_dimension_schema(dimension_key: str) -> Type[BaseDimensionSummary]:
    """Return the Pydantic model class for a given dimension key."""
    return _DIMENSION_SCHEMAS.get(dimension_key, BaseDimensionSummary)


def get_metrics_description(dimension_key: str) -> Dict[str, str]:
    """Return human-readable metrics description for a dimension."""
    return METRICS_DESCRIPTIONS.get(dimension_key, {})
