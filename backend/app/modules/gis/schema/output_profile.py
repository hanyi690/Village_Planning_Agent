"""Output Profile — province-extensible output layer configuration.

Different provinces have different data exchange standards for village planning.
The OutputProfile encapsulates all province-specific rules so the generation
core stays unchanged when adding a new province.

Examples:
  - Guangdong: 14 layers, CGCS2000 3° GK, GDB format, V/N/E classification
  - Shaanxi:   DB61/T 1852-2024, YDYHFLDM base conversion required
  - Henan:     similar to Guangdong with minor field differences
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# FieldSpec: (name, dtype, description)
@dataclass
class FieldSpec:
    name: str
    dtype: str  # "str:18", "float64", "int32", etc.
    description: str = ""
    default: str = ""


@dataclass
class LayerSpec:
    """Specification for one output layer."""
    layer_id: str            # "01_boundary", "06_planned_landuse", etc.
    gdb_key: str             # Key in GDB_LAYER_REGISTRY
    source: str              # "current/boundary.geojson" or generation layer name
    geometry: str            # "MultiPolygon", "MultiLineString", "Point"
    fields: List[FieldSpec]  # Required fields
    required: bool = True    # Whether this layer is mandatory for exchange
    description: str = ""


@dataclass
class OutputProfile:
    """Province-specific output configuration.

    Usage:
        guangdong = OutputProfile.guangdong()
        layers = guangdong.required_layers  # 14 layers
        crs = guangdong.crs                 # "EPSG:4527"

    To add a new province:
        @classmethod
        def shaanxi(cls) -> "OutputProfile":
            return cls(
                province="shaanxi",
                province_name="陕西省",
                crs="EPSG:4527",
                ...
            )
    """

    province: str                        # "guangdong" | "shaanxi" | "henan"
    province_name: str                   # "广东省" | "陕西省" | "河南省"
    crs: str                             # Target CRS for export
    db_format: str                       # "gdb" | "mdb" | "geojson"

    # Layer configuration
    layers: List[LayerSpec] = field(default_factory=list)

    # Classification standard
    use_zone_standard: str = "VNE"       # "VNE" (住建部) | "GB6" (国标6类)
    landuse_encoding: str = "DLBM"       # "DLBM" (三调) | "YDYHFLDM" (基数转换)

    # Exchange rules
    requires_base_conversion: bool = False  # Whether YDYHFLDM conversion is needed
    requires_space_control: bool = True     # Whether space control zone is mandatory
    requires_land_use_zone: bool = True     # Whether V/N/E zone is mandatory

    # Validation rules
    max_construction_ratio: float = 0.0  # 建设用地占比上限, 0=use GIS data
    min_farmland_area_ha: float = 0.0   # 耕地保有量下限, 0=use GIS data

    # ── Village-specific constraints (from GIS实测 + planning regulations) ──
    construction_cap_ha: float = 0.0     # 建设用地总量上限 (ha)
    farmland_min_ha: float = 0.0         # 耕地保有量下限 (ha)
    ecological_min_ha: float = 0.0       # 生态保护红线面积下限 (ha)
    forest_min_ha: float = 0.0           # 林地保有量下限 (ha)

    # ── Control zone rules ──
    conditional_zone_pct: float = 20.0   # 有条件建设区占比上限 (%)

    @property
    def required_layers(self) -> List[LayerSpec]:
        return [lyr for lyr in self.layers if lyr.required]

    @property
    def layer_count(self) -> int:
        return len(self.required_layers)

    @classmethod
    def guangdong(cls) -> "OutputProfile":
        """Guangdong Province village planning exchange standard.

        Based on: 广东省村庄规划编制基本技术指南（试行）
        CRS: CGCS2000 3° Gauss-Kruger zone (EPSG:4527 for zone 39, Meizhou area)
        """
        return cls(
            province="guangdong",
            province_name="广东省",
            crs="EPSG:4527",
            db_format="gdb",
            use_zone_standard="VNE",
            landuse_encoding="DLBM",
            requires_base_conversion=False,
            requires_space_control=True,
            requires_land_use_zone=True,
            construction_cap_ha=21.66,
            farmland_min_ha=98.54,
            ecological_min_ha=365.28,
            forest_min_ha=200.0,
            conditional_zone_pct=20.0,
            layers=[
                # ── 现状层 (5 layers, 直出) ──
                LayerSpec("01_boundary", "admin_area",
                          "current/boundary.geojson", "MultiPolygon",
                          [FieldSpec("BSM", "int16"), FieldSpec("YSDM", "str:10"),
                           FieldSpec("DJZQMC", "str:50"), FieldSpec("DJZQDM", "str:12")],
                          description="行政村行政区划面"),
                LayerSpec("02_admin_boundary_line", "admin_boundary_line",
                          "current/admin_boundary_line.geojson", "MultiLineString",
                          [FieldSpec("BSM", "int16"), FieldSpec("YSDM", "str:10"),
                           FieldSpec("界线类型", "int32")],
                          description="行政区划界线"),
                LayerSpec("03_current_landuse", "current_landuse",
                          "current/landuse.geojson", "MultiPolygon",
                          [FieldSpec("BSM", "str:18"), FieldSpec("DLBM", "str:4"),
                           FieldSpec("DLMC", "str:20"), FieldSpec("DLMJ", "float64")],
                          description="基期年现状地类图斑"),
                LayerSpec("04_current_road", "current_road",
                          "current/road.geojson", "MultiLineString",
                          [FieldSpec("Shape_Length", "float64")],
                          description="现状道路"),
                LayerSpec("05_current_annotation", "current_annotation",
                          "current/annotation.geojson", "Point",
                          [FieldSpec("注记", "str:100"), FieldSpec("分类", "str:20")],
                          description="现状注记"),

                # ── 规划层 (9 layers) ──
                LayerSpec("06_planned_landuse", "planned_landuse",
                          "generate:parcel_reclass", "MultiPolygon",
                          [FieldSpec("BSM", "str:18"), FieldSpec("YSDM", "str:10"),
                           FieldSpec("DLBM", "str:4"), FieldSpec("DLMJ", "float64"),
                           FieldSpec("QMDLBM", "str:4"), FieldSpec("GHFLBM", "str:4"),
                           FieldSpec("GHYTBM", "str:4"), FieldSpec("GHYTMC", "str:20"),
                           FieldSpec("Shape_Length", "float64"), FieldSpec("Shape_Area", "float64")],
                          description="目标年期末地类图斑"),
                LayerSpec("07_farmland_protection", "farmland_protection",
                          "external:farmland_redline", "MultiPolygon",
                          [FieldSpec("BSM", "str:18"), FieldSpec("JBNT_MJ", "float64")],
                          description="永久基本农田保护红线"),
                LayerSpec("08_ecological_protection", "ecological_redline",
                          "external:ecological_redline", "MultiPolygon",
                          [FieldSpec("OBJECTID", "int32"), FieldSpec("MJ", "float64")],
                          description="生态保护红线"),
                LayerSpec("09_historical_protection", "historical_protection",
                          "external:historical_line", "MultiPolygon",
                          [FieldSpec("BUFF_DIST", "float64"), FieldSpec("ORIG_FID", "float64")],
                          description="历史文化保护线", required=False),
                LayerSpec("10_space_control_zone", "space_control_zone",
                          "generate:space_control", "MultiPolygon",
                          [FieldSpec("TDKJGZFQDM", "str:4"), FieldSpec("GZFQMC", "str:50"),
                           FieldSpec("MJ", "float64")],
                          description="建设用地管制区 JSYDGZQ"),
                LayerSpec("11_land_use_zone", "land_use_zone",
                          "generate:land_use_zone", "MultiPolygon",
                          [FieldSpec("TDYTFQDM", "str:4"), FieldSpec("YTFQMC", "str:30"),
                           FieldSpec("MJ", "float64")],
                          description="土地用途分区 TDYT"),
                LayerSpec("12_geological_hazard_points", "hazard_points",
                          "external:hazard_points", "Point",
                          [FieldSpec("地质灾害点名称", "str:100"),
                           FieldSpec("类型", "str:20")],
                          description="地质灾害点", required=False),
                LayerSpec("13_planned_road", "planned_road",
                          "generate:road_plan", "MultiLineString",
                          [FieldSpec("Shape_Length", "float64")],
                          description="规划道路"),
                LayerSpec("14_planned_annotation", "planned_annotation",
                          "generate:facility_plan", "Point",
                          [FieldSpec("注记", "str:100"), FieldSpec("分类", "str:20")],
                          description="规划注记"),
            ],
        )


# Module-level singleton
_profile: Optional[OutputProfile] = None


def get_output_profile(province: str = "guangdong") -> OutputProfile:
    """Get the OutputProfile for a province."""
    global _profile
    if province == "guangdong":
        if _profile is None:
            _profile = OutputProfile.guangdong()
        return _profile
    raise ValueError(f"Unknown province: {province}. Available: guangdong")


__all__ = ["OutputProfile", "LayerSpec", "FieldSpec", "get_output_profile"]
