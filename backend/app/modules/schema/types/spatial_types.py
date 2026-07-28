from __future__ import annotations

from typing import Any, ClassVar, Dict, Literal, Union

from pydantic import BaseModel, Field
from typing_extensions import Annotated

from .base import SpatialFeature, PointFeature, LineFeature, PolygonFeature

GB_T21010 = "gbt21010"
TUGUI = "tugui"
APPENDIX5 = "appendix5"
GHFLBM_SYS = "ghflbm"
YDYHFL = "ydyhfldm"
VNE = "vne"


class AdminArea(PolygonFeature):
    layer_type: Literal["admin_area"] = "admin_area"
    djzqdm: str = ""
    djzqmc: str = ""
    mj: float = 0.0
    bz: str = ""
    shape_length: float = 0.0
    shape_area: float = 0.0


class AdminBoundaryLine(LineFeature):
    layer_type: Literal["admin_boundary_line"] = "admin_boundary_line"
    djzqdm: str = ""
    boundary_type: int = 0
    boundary_desc: str = ""


class BaseLandUseParcel(PolygonFeature):
    layer_type: str = ""
    dlbm: str = ""
    dlbm_system: str = ""
    name: str = ""
    area_sqm: float = 0.0
    zone_type: str = ""
    planning_zone: str = ""
    primary_zone: str = ""

    @property
    def primary_code(self) -> str:
        return self.dlbm

    @property
    def primary_system(self) -> str:
        return self.dlbm_system


class CurrentLandUseParcel(BaseLandUseParcel):
    layer_type: Literal["landuse_current"] = "landuse_current"
    sddlbm: str = Field(default="", alias="SDDLBM")
    sddlbm_system: str = ""


class PlannedLandUseParcel(BaseLandUseParcel):
    layer_type: Literal["landuse_planned"] = "landuse_planned"
    qmdlbm: str = Field(default="", alias="QMDLBM")
    qmdlbm_system: str = ""
    ghytbm: str = Field(default="", alias="GHYTBM")
    ghytbm_system: str = ""
    ghytmc: str = ""
    ghflbm: str = Field(default="", alias="GHFLBM")
    ghflbm_system: str = ""
    qmghflbm: str = ""
    qmghflbm_system: str = ""

    @property
    def primary_code(self) -> str:
        return self.ghytbm or self.dlbm

    @property
    def primary_system(self) -> str:
        return self.ghytbm_system or self.dlbm_system


class CurrentBuilding(PointFeature):
    layer_type: Literal["current_building"] = "current_building"
    building_type: str = ""
    floors: int = 0
    area_sqm: float = 0.0
    structure: str = ""


class BaseRoad(LineFeature):
    layer_type: str = ""
    road_level: str = ""
    road_width: float = 0.0
    road_name: str = ""
    shape_length: float = 0.0


class CurrentRoad(BaseRoad):
    layer_type: Literal["current_road"] = "current_road"


ANNOTATION_LABEL_TYPE_MAP: Dict[str, str] = {
    "篮": "体育", "健": "体育", "广": "广场", "停": "停车",
    "电": "电力", "污": "排水", "水": "给水", "垃": "环卫",
    "卫": "公厕", "祠": "文化", "村": "村委会", "站": "交通",
    "小": "学校",
}


class BaseFacility(PointFeature):
    layer_type: str = ""
    facility_type: str = ""
    facility_name: str = ""
    scale: str = ""
    service_radius: float = 0.0
    category: str = ""


class CurrentFacility(BaseFacility):
    layer_type: Literal["current_facility"] = "current_facility"

    @classmethod
    def from_annotation_feature(cls, feature: dict) -> "CurrentFacility | None":
        props = feature.get("properties", {})
        category = props.get("分类", props.get("category", ""))
        if category != "现状设施点":
            return None

        text = props.get("注记", props.get("text", ""))
        facility_type = ANNOTATION_LABEL_TYPE_MAP.get(text, "公共服务")
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
        )


class PlannedFacility(BaseFacility):
    layer_type: Literal["planned_facility"] = "planned_facility"
    status: str = ""


class AnnotationFeature(PointFeature):
    layer_type: str = ""
    text: str = ""
    category: str = ""


class CurrentAnnotation(AnnotationFeature):
    layer_type: Literal["current_annotation"] = "current_annotation"
    text: str = Field(default="", alias="注记")
    category: str = Field(default="", alias="分类")


class BaseControlZone(PolygonFeature):
    layer_type: str = ""
    mj: float = 0.0
    protection_level: str = ""
    control_measure: str = ""


class ControlLine(BaseControlZone):
    layer_type: str = ""


class FarmlandProtection(ControlLine):
    layer_type: Literal["farmland_protection"] = "farmland_protection"
    xzqhdm: str = ""
    xzqhmc: str = ""
    jbnt_mj: float = 0.0


class EcologicalRedline(ControlLine):
    layer_type: Literal["ecological_redline"] = "ecological_redline"
    district: str = Field(default="", alias="区县")
    zone: float = 0.0
    city: str = Field(default="", alias="地市")
    object_id: int = Field(default=0, alias="OBJECTID")


class CultivatedLandTarget(ControlLine):
    layer_type: Literal["cultivated_land_target"] = "cultivated_land_target"
    target_level: str = ""


class UrbanDevBoundary(ControlLine):
    layer_type: Literal["urban_dev_boundary"] = "urban_dev_boundary"
    dev_type: str = ""


class VillageDevBoundary(ControlLine):
    layer_type: Literal["village_dev_boundary"] = "village_dev_boundary"
    boundary_type: str = ""


class HazardControlLine(ControlLine):
    layer_type: Literal["hazard_control_line"] = "hazard_control_line"
    hazard_type: str = ""
    risk_level: str = ""


class GeologicalHazardPoint(PointFeature):
    layer_type: Literal["geological_hazard_point"] = "geological_hazard_point"
    name: str = Field(default="", alias="名称")
    longitude: str = Field(default="", alias="经度")
    latitude: str = Field(default="", alias="纬度")
    hazard_type: str = Field(default="", alias="类型")
    scale: str = Field(default="", alias="大小")


class FloodControlLine(ControlLine):
    layer_type: Literal["flood_control_line"] = "flood_control_line"
    flood_frequency: str = ""
    control_elevation: float = 0.0


class PlannedRoad(BaseRoad):
    layer_type: Literal["planned_road"] = "planned_road"
    ln_type: str = ""
    left_ln_fid: str = ""
    right_ln_fid: str = ""


class PlannedAnnotation(AnnotationFeature):
    layer_type: Literal["planned_annotation"] = "planned_annotation"


class HistoricalProtection(PolygonFeature):
    layer_type: Literal["historical_protection"] = "historical_protection"
    buff_dist: float = 0.0
    orig_fid: float = 0.0
    protection_scope: str = ""
    protection_level: str = ""


class LandUseZone(PolygonFeature):
    layer_type: Literal["land_use_zone"] = "land_use_zone"
    xzqhdm: str = ""
    xzqhmc: str = ""
    tdyfqdm: str = ""
    tdyfqbh: str = ""
    mj: float = 0.0
    ms: str = ""
    ytfqmc: str = ""


class ConstructionCtrlZone(PolygonFeature):
    layer_type: Literal["construction_ctrl_zone"] = "construction_ctrl_zone"
    xzqhdm: str = ""
    xzqhmc: str = ""
    tdkjgzfqdm: str = ""
    tdkjgzfqbh: str = ""
    ghnf: str = ""
    mj: float = 0.0
    gzfqmc: str = ""

    ALLOWED_CONSTRUCTION: ClassVar[str] = "01"
    RESTRICTED: ClassVar[str] = "02"
    CONDITIONAL: ClassVar[str] = "03"
    PROHIBITED: ClassVar[str] = "04"
    BASIC_FARMLAND_ZONE: ClassVar[str] = "05"
    ECOLOGICAL_REDLINE_ZONE: ClassVar[str] = "06"


class ConditionalConstructionZone(PolygonFeature):
    layer_type: Literal["conditional_construction_zone"] = "conditional_construction_zone"
    bh: str = ""
    xzqhdm: str = ""
    xzqhm: str = ""
    lx: str = ""
    mj: float = 0.0
    shape_length: float = 0.0
    shape_area: float = 0.0


class PlanningScope(PolygonFeature):
    layer_type: Literal["planning_scope"] = "planning_scope"
    xzqhdm: str = ""
    xzqhmc: str = ""
    mj: float = 0.0
    bz: str = ""


class ThreeZoneItem(PolygonFeature):
    layer_type: Literal["three_zone_item"] = "three_zone_item"
    zone_type: str = ""
    zone_name: str = ""
    area_ha: float = 0.0


class ContourLine(LineFeature):
    layer_type: Literal["contour_line"] = "contour_line"
    elevation: float = 0.0
    contour_type: str = ""


class ElevationPoint(PointFeature):
    layer_type: Literal["elevation_point"] = "elevation_point"
    elevation: float = 0.0
    point_type: str = ""


class WaterFeature(PolygonFeature):
    layer_type: Literal["water"] = "water"
    water_type: str = ""
    water_name: str = ""
    flow_direction: str = ""


class SoilType(PolygonFeature):
    layer_type: Literal["soil_type"] = "soil_type"
    soil_code: str = ""
    soil_name: str = ""


class SoilErosion(PolygonFeature):
    layer_type: Literal["soil_erosion"] = "soil_erosion"
    erosion_level: str = ""


class Watershed(PolygonFeature):
    layer_type: Literal["watershed"] = "watershed"
    watershed_code: str = ""
    watershed_name: str = ""


class NatureReserve(PolygonFeature):
    layer_type: Literal["nature_reserve"] = "nature_reserve"
    reserve_name: str = ""
    reserve_level: str = ""


class HydrogeologyZone(PolygonFeature):
    layer_type: Literal["hydrogeology_zone"] = "hydrogeology_zone"
    zone_code: str = ""
    zone_name: str = ""


GisFeature = Annotated[
    Union[
        CurrentLandUseParcel, PlannedLandUseParcel,
        CurrentBuilding, CurrentRoad, PlannedRoad,
        CurrentFacility, PlannedFacility,
        CurrentAnnotation, PlannedAnnotation,
        AdminArea, AdminBoundaryLine,
        FarmlandProtection, EcologicalRedline, CultivatedLandTarget,
        UrbanDevBoundary, VillageDevBoundary,
        HazardControlLine, GeologicalHazardPoint, FloodControlLine,
        HistoricalProtection, LandUseZone, ConstructionCtrlZone,
        ConditionalConstructionZone, PlanningScope, ThreeZoneItem,
        ContourLine, ElevationPoint, WaterFeature,
        SoilType, SoilErosion, Watershed, NatureReserve, HydrogeologyZone,
    ],
    Field(discriminator="layer_type"),
]

SPACE_CONTROL_ZONE_TYPES = {
    "01": "允许建设区",
    "02": "限制建设区",
    "03": "有条件建设区",
    "04": "禁止建设区",
    "05": "永久基本农田保护区",
    "06": "生态保护红线区",
}

SPACE_CONTROL_ZONE_COLORS = {
    "01": "#FF6B6B",
    "02": "#FFD93D",
    "03": "#6BCB77",
    "04": "#4D96FF",
    "05": "#C9B1FF",
    "06": "#FF8B94",
}

__all__ = [
    "SpatialFeature", "PointFeature", "LineFeature", "PolygonFeature",
    "AdminArea", "AdminBoundaryLine",
    "BaseLandUseParcel", "CurrentLandUseParcel", "PlannedLandUseParcel",
    "GB_T21010", "TUGUI", "APPENDIX5", "GHFLBM_SYS", "YDYHFL", "VNE",
    "BaseRoad", "BaseFacility", "BaseControlZone", "AnnotationFeature",
    "CurrentBuilding", "CurrentRoad", "CurrentFacility", "CurrentAnnotation",
    "PlannedFacility", "ControlLine",
    "FarmlandProtection", "EcologicalRedline", "CultivatedLandTarget",
    "UrbanDevBoundary", "VillageDevBoundary", "HazardControlLine",
    "FloodControlLine", "HistoricalProtection", "PlannedRoad",
    "PlannedAnnotation", "GeologicalHazardPoint",
    "ConditionalConstructionZone", "LandUseZone", "ConstructionCtrlZone",
    "PlanningScope", "ThreeZoneItem",
    "ContourLine", "ElevationPoint", "WaterFeature",
    "SoilType", "SoilErosion", "Watershed", "NatureReserve", "HydrogeologyZone",
    "GisFeature",
    "ANNOTATION_LABEL_TYPE_MAP",
    "SPACE_CONTROL_ZONE_TYPES", "SPACE_CONTROL_ZONE_COLORS",
]