"""Structured summary schemas for all 28 planning dimensions.

Each dimension has a Pydantic model with:
- Common fields: dimension_key, layer, word_count, key_points, text_summary
- Dimension-specific metrics: numeric/enum fields extracted from LLM output + RAG
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field


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
    registered_population: Optional[int] = Field(default=None, description="户籍人口(人)")
    resident_population: Optional[int] = Field(default=None, description="常住人口(人)")
    households: Optional[int] = Field(default=None, description="户数(户)")
    labor_force: Optional[int] = Field(default=None, description="劳动力(人)")
    migrant_workers: Optional[int] = Field(default=None, description="外出务工(人)")
    aging_rate: Optional[float] = Field(default=None, description="老龄化率(%)")
    per_capita_income: Optional[float] = Field(default=None, description="人均纯收入(元/年)")
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
    ecological_redline_ha: Optional[float] = Field(default=None, description="生态红线面积(ha)")
    farmland_protection_ha: Optional[float] = Field(default=None, description="耕地保护面积(ha)")
    urban_boundary_ha: Optional[float] = Field(default=None, description="城镇开发边界面积(ha)")

class NaturalEnvironmentSummary(BaseDimensionSummary):
    climate_type: Optional[str] = Field(default=None, description="气候类型")
    annual_precipitation_mm: Optional[float] = Field(default=None, description="年均降水量(mm)")
    annual_temp_c: Optional[float] = Field(default=None, description="年均温度(℃)")
    elevation_min_m: Optional[float] = Field(default=None, description="最低海拔(m)")
    elevation_max_m: Optional[float] = Field(default=None, description="最高海拔(m)")
    forest_coverage_rate: Optional[float] = Field(default=None, description="森林覆盖率(%)")
    hazard_points_count: Optional[int] = Field(default=None, description="地质灾害隐患点数量(处)")
    main_rivers: List[str] = Field(default_factory=list, description="主要河流名称列表")

class LandUseSummary(BaseDimensionSummary):
    total_area_ha: Optional[float] = Field(default=None, description="总用地面积(ha)")
    farmland_area_ha: Optional[float] = Field(default=None, description="耕地面积(ha)")
    construction_area_ha: Optional[float] = Field(default=None, description="建设用地面积(ha)")
    ecological_area_ha: Optional[float] = Field(default=None, description="生态用地面积(ha)")
    water_area_ha: Optional[float] = Field(default=None, description="水域面积(ha)")
    per_capita_farmland_mu: Optional[float] = Field(default=None, description="人均耕地(亩)")
    forest_coverage_rate: Optional[float] = Field(default=None, description="森林覆盖率(%)")

class TrafficSummary(BaseDimensionSummary):
    external_road_level: Optional[str] = Field(default=None, description="对外连接道路等级")
    internal_road_hardening_rate: Optional[float] = Field(default=None, description="内部道路硬化率(%)")
    road_network_length_km: Optional[float] = Field(default=None, description="路网总长度(km)")

class PublicServicesSummary(BaseDimensionSummary):
    school_count: Optional[int] = Field(default=None, description="学校数量(所)")
    clinic_count: Optional[int] = Field(default=None, description="卫生室数量(个)")
    cultural_center_count: Optional[int] = Field(default=None, description="文化活动中心数量(个)")
    service_coverage_rate: Optional[float] = Field(default=None, description="公共服务覆盖率(%)")

class InfrastructureSummary(BaseDimensionSummary):
    water_supply_type: Optional[str] = Field(default=None, description="供水方式")
    power_capacity_kva: Optional[float] = Field(default=None, description="变压器容量(kVA)")
    broadband_coverage_rate: Optional[float] = Field(default=None, description="宽带覆盖率(%)")

class EcologicalGreenSummary(BaseDimensionSummary):
    green_area_ha: Optional[float] = Field(default=None, description="绿地面积(ha)")
    green_rate: Optional[float] = Field(default=None, description="绿地率(%)")
    ecological_redline_ha: Optional[float] = Field(default=None, description="生态红线面积(ha)")

class ArchitectureSummary(BaseDimensionSummary):
    total_buildings: Optional[int] = Field(default=None, description="建筑总量(栋)")
    building_area_sqm: Optional[float] = Field(default=None, description="建筑总面积(m2)")
    quality_a_rate: Optional[float] = Field(default=None, description="A级建筑占比(%)")
    quality_b_rate: Optional[float] = Field(default=None, description="B级建筑占比(%)")
    quality_c_rate: Optional[float] = Field(default=None, description="C级建筑占比(%)")
    quality_d_rate: Optional[float] = Field(default=None, description="D级(危房)占比(%)")

class HistoricalCultureSummary(BaseDimensionSummary):
    heritage_buildings: List[str] = Field(default_factory=list, description="传统风貌建筑列表")
    ancient_trees: List[str] = Field(default_factory=list, description="古树名木列表")
    intangible_heritage_items: List[str] = Field(default_factory=list, description="非物质文化遗产列表")


# ---- Layer 2: Planning concept (4) ----

class ResourceEndowmentSummary(BaseDimensionSummary):
    pass

class PlanningPositioningSummary(BaseDimensionSummary):
    pass

class DevelopmentGoalsSummary(BaseDimensionSummary):
    pass

class PlanningStrategiesSummary(BaseDimensionSummary):
    pass


# ---- Layer 3: Detailed planning (12) ----

class IndustrySummary(BaseDimensionSummary):
    pass

class SpatialStructureSummary(BaseDimensionSummary):
    pass

class LandUsePlanningSummary(BaseDimensionSummary):
    pass

class SettlementPlanningSummary(BaseDimensionSummary):
    pass

class TrafficPlanningSummary(BaseDimensionSummary):
    pass

class PublicServicePlanningSummary(BaseDimensionSummary):
    pass

class InfrastructurePlanningSummary(BaseDimensionSummary):
    pass

class EcologicalPlanningSummary(BaseDimensionSummary):
    pass

class DisasterPreventionSummary(BaseDimensionSummary):
    pass

class HeritagePlanningSummary(BaseDimensionSummary):
    pass

class LandscapeSummary(BaseDimensionSummary):
    pass

class ProjectBankSummary(BaseDimensionSummary):
    pass


# ---- Registry ----

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
    "resource_endowment": ResourceEndowmentSummary,
    "planning_positioning": PlanningPositioningSummary,
    "development_goals": DevelopmentGoalsSummary,
    "planning_strategies": PlanningStrategiesSummary,
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

# Metrics description for LLM prompt guidance
METRICS_DESCRIPTIONS: Dict[str, Dict[str, str]] = {
    "location": {
        "province": "省份",
        "city": "城市",
        "county": "县区",
        "town": "镇",
        "road_connections": "对外连接道路列表",
    },
    "socio_economic": {
        "registered_population": "户籍人口",
        "resident_population": "常住人口",
        "households": "户数",
        "labor_force": "劳动力",
        "migrant_workers": "外出务工",
        "aging_rate": "老龄化率(%)",
        "per_capita_income": "人均收入(元)",
        "primary_industry": "第一产业描述",
        "secondary_industry": "第二产业描述",
        "tertiary_industry": "第三产业描述",
    },
    "villager_wishes": {
        "industry_wishes": "产业发展诉求列表",
        "environment_wishes": "环境美化诉求列表",
        "facility_wishes": "配套设施诉求列表",
        "priority_order": "诉求优先级排序",
    },
    "superior_planning": {
        "planning_positioning_type": "规划定位类型",
        "ecological_redline_ha": "生态红线面积(ha)",
        "farmland_protection_ha": "耕地保护面积(ha)",
        "urban_boundary_ha": "城镇开发边界面积(ha)",
    },
    "natural_environment": {
        "climate_type": "气候类型",
        "annual_precipitation_mm": "年均降水量(mm)",
        "annual_temp_c": "年均温度(℃)",
        "elevation_min_m": "最低海拔(m)",
        "elevation_max_m": "最高海拔(m)",
        "forest_coverage_rate": "森林覆盖率(%)",
        "hazard_points_count": "地质灾害隐患点数量(处)",
        "main_rivers": "主要河流名称列表",
    },
    "land_use": {
        "total_area_ha": "总面积(ha)",
        "farmland_area_ha": "耕地(ha)",
        "construction_area_ha": "建设用地(ha)",
        "ecological_area_ha": "生态用地(ha)",
        "water_area_ha": "水域(ha)",
        "per_capita_farmland_mu": "人均耕地(亩)",
        "forest_coverage_rate": "森林覆盖率(%)",
    },
    "traffic": {
        "external_road_level": "对外连接道路等级",
        "internal_road_hardening_rate": "内部道路硬化率(%)",
        "road_network_length_km": "路网总长度(km)",
    },
    "public_services": {
        "school_count": "学校数量(所)",
        "clinic_count": "卫生室数量(个)",
        "cultural_center_count": "文化活动中心数量(个)",
        "service_coverage_rate": "公共服务覆盖率(%)",
    },
    "infrastructure": {
        "water_supply_type": "供水方式",
        "power_capacity_kva": "变压器容量(kVA)",
        "broadband_coverage_rate": "宽带覆盖率(%)",
    },
    "ecological_green": {
        "green_area_ha": "绿地面积(ha)",
        "green_rate": "绿地率(%)",
        "ecological_redline_ha": "生态红线面积(ha)",
    },
    "architecture": {
        "total_buildings": "建筑总量(栋)",
        "building_area_sqm": "建筑总面积(m2)",
        "quality_a_rate": "A级建筑占比(%)",
        "quality_b_rate": "B级建筑占比(%)",
        "quality_c_rate": "C级建筑占比(%)",
        "quality_d_rate": "D级(危房)占比(%)",
    },
    "historical_culture": {
        "heritage_buildings": "传统风貌建筑列表",
        "ancient_trees": "古树名木列表",
        "intangible_heritage_items": "非物质文化遗产列表",
    },
    "development_goals": {
        "target_population": "规划目标人口",
        "farmland_protection_ha": "耕地保护(ha)",
        "ecological_redline_ha": "生态红线(ha)",
        "forest_coverage_target_rate": "森林覆盖率目标(%)",
    },
    "settlement_planning": {
        "current_population": "现状人口",
        "target_population": "规划人口",
        "per_capita_construction_sqm": "人均建设用地(m2)",
    },
    "project_bank": {
        "total_projects": "项目总数",
        "total_investment_wan_yuan": "总投资(万元)",
        "short_term_projects": "近期项目数",
    },
}


def get_dimension_schema(dimension_key: str) -> Type[BaseDimensionSummary]:
    """Return the Pydantic model class for a given dimension key."""
    return _DIMENSION_SCHEMAS.get(dimension_key, BaseDimensionSummary)


def get_metrics_description(dimension_key: str) -> Dict[str, str]:
    """Return human-readable metrics description for a dimension."""
    return METRICS_DESCRIPTIONS.get(dimension_key, {})