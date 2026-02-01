"""
Schema注册表

管理适配器的Schema定义，提供Schema注册、验证和查询功能。
遵循契约驱动设计，确保数据格式的一致性。
"""

from typing import Dict, Any, List, Optional, Type
from dataclasses import dataclass, field
from collections import OrderedDict
import json

from ...utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SchemaDefinition:
    """Schema定义"""
    name: str                           # Schema名称
    version: str                        # Schema版本
    adapter_class: str                  # 适配器类名
    schema: Dict[str, Any]              # Schema结构（JSON Schema格式）
    description: Optional[str] = None   # 描述
    required_fields: List[str] = field(default_factory=list)  # 必填字段
    optional_fields: List[str] = field(default_factory=list)  # 可选字段

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "version": self.version,
            "adapter_class": self.adapter_class,
            "schema": self.schema,
            "description": self.description,
            "required_fields": self.required_fields,
            "optional_fields": self.optional_fields
        }


class SchemaRegistry:
    """
    Schema注册表

    负责管理所有适配器的Schema定义，提供注册、查询、验证功能。
    """

    def __init__(self):
        """初始化Schema注册表"""
        self._schemas: OrderedDict[str, SchemaDefinition] = OrderedDict()
        self._load_builtin_schemas()

    def _load_builtin_schemas(self):
        """加载内置的Schema定义"""
        logger.info("[SchemaRegistry] 加载内置Schema定义")

        # 土地利用分析Schema
        self.register(
            SchemaDefinition(
                name="land_use_analysis",
                version="1.0.0",
                adapter_class="GISAnalysisAdapter",
                description="土地利用分析结果",
                schema={
                    "type": "object",
                    "properties": {
                        "total_area": {"type": "number", "description": "总面积（平方公里）"},
                        "land_use_types": {
                            "type": "array",
                            "description": "土地利用类型列表",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "description": "用地类型（如耕地、林地、建设用地等）"},
                                    "area": {"type": "number", "description": "面积（平方公里）"},
                                    "percentage": {"type": "number", "description": "占比（%）"}
                                }
                            }
                        },
                        "land_use_efficiency": {"type": "number", "description": "土地利用效率指数"},
                        "development_intensity": {"type": "number", "description": "开发强度（%）"}
                    },
                    "required": ["total_area", "land_use_types"]
                },
                required_fields=["total_area", "land_use_types"],
                optional_fields=["land_use_efficiency", "development_intensity"]
            )
        )

        # 土壤分析Schema
        self.register(
            SchemaDefinition(
                name="soil_analysis",
                version="1.0.0",
                adapter_class="GISAnalysisAdapter",
                description="土壤分析结果",
                schema={
                    "type": "object",
                    "properties": {
                        "soil_types": {
                            "type": "array",
                            "description": "土壤类型分布",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "description": "土壤类型"},
                                    "area": {"type": "number", "description": "面积（平方公里）"},
                                    "suitability": {"type": "string", "description": "适宜性评价"}
                                }
                            }
                        },
                        "soil_quality_index": {"type": "number", "description": "土壤质量指数"},
                        "erosion_risk": {"type": "string", "description": "水土流失风险等级"}
                    },
                    "required": ["soil_types"]
                },
                required_fields=["soil_types"],
                optional_fields=["soil_quality_index", "erosion_risk"]
            )
        )

        # 水文分析Schema
        self.register(
            SchemaDefinition(
                name="hydrology_analysis",
                version="1.0.0",
                adapter_class="GISAnalysisAdapter",
                description="水文分析结果",
                schema={
                    "type": "object",
                    "properties": {
                        "water_systems": {
                            "type": "array",
                            "description": "水系分布",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "description": "水体名称"},
                                    "type": {"type": "string", "description": "水体类型（河流、湖泊、水库等）"},
                                    "length": {"type": "number", "description": "长度（公里，仅河流）"},
                                    "area": {"type": "number", "description": "面积（平方公里，仅湖泊/水库）"},
                                    "water_quality": {"type": "string", "description": "水质等级"}
                                }
                            }
                        },
                        "flood_risk_areas": {
                            "type": "array",
                            "description": "洪水风险区域",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "area_name": {"type": "string"},
                                    "risk_level": {"type": "string", "description": "风险等级（高/中/低）"},
                                    "area": {"type": "number", "description": "面积（平方公里）"}
                                }
                            }
                        }
                    },
                    "required": ["water_systems"]
                },
                required_fields=["water_systems"],
                optional_fields=["flood_risk_areas"]
            )
        )

        # 路网连通度分析Schema
        self.register(
            SchemaDefinition(
                name="connectivity_metrics",
                version="1.0.0",
                adapter_class="NetworkAnalysisAdapter",
                description="路网连通度指标",
                schema={
                    "type": "object",
                    "properties": {
                        "network_density": {"type": "number", "description": "路网密度（公里/平方公里）"},
                        "connectivity_index": {"type": "number", "description": "连通性指数"},
                        "accessibility_score": {"type": "number", "description": "可达性评分"},
                        "average_path_length": {"type": "number", "description": "平均路径长度（公里）"},
                        "isolated_nodes": {
                            "type": "array",
                            "description": "孤立节点列表",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["network_density", "connectivity_index"]
                },
                required_fields=["network_density", "connectivity_index"],
                optional_fields=["accessibility_score", "average_path_length", "isolated_nodes"]
            )
        )

        # 可达性分析Schema
        self.register(
            SchemaDefinition(
                name="accessibility_analysis",
                version="1.0.0",
                adapter_class="NetworkAnalysisAdapter",
                description="可达性分析结果",
                schema={
                    "type": "object",
                    "properties": {
                        "origin_destination_matrix": {
                            "type": "array",
                            "description": "起讫点矩阵",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "origin": {"type": "string"},
                                    "destination": {"type": "string"},
                                    "distance": {"type": "number", "description": "距离（公里）"},
                                    "travel_time": {"type": "number", "description": "行程时间（分钟）"}
                                }
                            }
                        },
                        "service_areas": {
                            "type": "array",
                            "description": "服务区域",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "center": {"type": "string", "description": "中心点"},
                                    "radius": {"type": "number", "description": "服务半径（公里）"},
                                    "coverage_ratio": {"type": "number", "description": "覆盖率（%）"}
                                }
                            }
                        }
                    },
                    "required": ["origin_destination_matrix"]
                },
                required_fields=["origin_destination_matrix"],
                optional_fields=["service_areas"]
            )
        )

        # 人口预测Schema
        self.register(
            SchemaDefinition(
                name="population_forecast",
                version="1.0.0",
                adapter_class="PopulationPredictionAdapter",
                description="人口预测结果",
                schema={
                    "type": "object",
                    "properties": {
                        "baseline_population": {"type": "integer", "description": "基期人口"},
                        "forecast_years": {
                            "type": "array",
                            "description": "预测年份",
                            "items": {"type": "integer"}
                        },
                        "forecast_population": {
                            "type": "array",
                            "description": "预测人口数",
                            "items": {"type": "integer"}
                        },
                        "growth_rate": {"type": "number", "description": "平均增长率（%）"},
                        "peak_year": {"type": "integer", "description": "人口峰值年份"},
                        "peak_population": {"type": "integer", "description": "峰值人口"}
                    },
                    "required": ["baseline_population", "forecast_years", "forecast_population"]
                },
                required_fields=["baseline_population", "forecast_years", "forecast_population"],
                optional_fields=["growth_rate", "peak_year", "peak_population"]
            )
        )

        # 人口结构模型Schema
        self.register(
            SchemaDefinition(
                name="population_structure",
                version="1.0.0",
                adapter_class="PopulationPredictionAdapter",
                description="人口结构模型",
                schema={
                    "type": "object",
                    "properties": {
                        "age_distribution": {
                            "type": "array",
                            "description": "年龄分布",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "age_group": {"type": "string", "description": "年龄段（如0-14, 15-64, 65+）"},
                                    "population": {"type": "integer", "description": "人口数"},
                                    "percentage": {"type": "number", "description": "占比（%）"}
                                }
                            }
                        },
                        "gender_ratio": {
                            "type": "object",
                            "description": "性别比例",
                            "properties": {
                                "male": {"type": "number", "description": "男性比例（%）"},
                                "female": {"type": "number", "description": "女性比例（%）"}
                            }
                        },
                        "labor_force_participation_rate": {"type": "number", "description": "劳动参与率（%）"},
                        "dependency_ratio": {"type": "number", "description": "抚养比（%）"}
                    },
                    "required": ["age_distribution"]
                },
                required_fields=["age_distribution"],
                optional_fields=["gender_ratio", "labor_force_participation_rate", "dependency_ratio"]
            )
        )

        logger.info(f"[SchemaRegistry] 已加载 {len(self._schemas)} 个内置Schema")

    def register(self, schema_def: SchemaDefinition) -> bool:
        """
        注册Schema定义

        Args:
            schema_def: Schema定义对象

        Returns:
            True if registration successful
        """
        try:
            key = f"{schema_def.name}:{schema_def.version}"
            if key in self._schemas:
                logger.warning(f"[SchemaRegistry] Schema已存在，将被覆盖: {key}")

            self._schemas[key] = schema_def
            logger.info(f"[SchemaRegistry] 已注册Schema: {key}")
            return True

        except Exception as e:
            logger.error(f"[SchemaRegistry] 注册Schema失败: {str(e)}")
            return False

    def get(self, name: str, version: str = "1.0.0") -> Optional[SchemaDefinition]:
        """
        获取Schema定义

        Args:
            name: Schema名称
            version: Schema版本（默认1.0.0）

        Returns:
            SchemaDefinition对象，如果不存在则返回None
        """
        key = f"{name}:{version}"
        return self._schemas.get(key)

    def list_schemas(self, adapter_class: Optional[str] = None) -> List[SchemaDefinition]:
        """
        列出所有Schema

        Args:
            adapter_class: 可选的适配器类名过滤

        Returns:
            Schema定义列表
        """
        schemas = list(self._schemas.values())

        if adapter_class:
            schemas = [s for s in schemas if s.adapter_class == adapter_class]

        return schemas

    def validate(self, name: str, data: Dict[str, Any], version: str = "1.0.0") -> Dict[str, Any]:
        """
        验证数据是否符合Schema

        Args:
            name: Schema名称
            data: 待验证的数据
            version: Schema版本（默认1.0.0）

        Returns:
            包含验证结果的字典:
            {
                "valid": bool,
                "errors": List[str],
                "schema": SchemaDefinition
            }
        """
        schema_def = self.get(name, version)
        if not schema_def:
            return {
                "valid": False,
                "errors": [f"Schema不存在: {name}:{version}"],
                "schema": None
            }

        errors = []

        # 检查必填字段
        for field in schema_def.required_fields:
            if field not in data:
                errors.append(f"缺少必填字段: {field}")

        # 基础类型检查（简化版，实际可使用jsonschema库进行更严格的验证）
        if "properties" in schema_def.schema:
            for prop_name, prop_def in schema_def.schema["properties"].items():
                if prop_name in data:
                    prop_type = prop_def.get("type")
                    if prop_type == "number" and not isinstance(data[prop_name], (int, float)):
                        errors.append(f"字段 {prop_name} 应为数字类型")
                    elif prop_type == "string" and not isinstance(data[prop_name], str):
                        errors.append(f"字段 {prop_name} 应为字符串类型")
                    elif prop_type == "array" and not isinstance(data[prop_name], list):
                        errors.append(f"字段 {prop_name} 应为数组类型")
                    elif prop_type == "object" and not isinstance(data[prop_name], dict):
                        errors.append(f"字段 {prop_name} 应为对象类型")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "schema": schema_def
        }

    def export_schemas(self, output_path: Optional[str] = None) -> str:
        """
        导出所有Schema定义

        Args:
            output_path: 可选的输出文件路径

        Returns:
            JSON格式的Schema定义字符串
        """
        schemas_dict = {
            schema_name: schema_def.to_dict()
            for schema_name, schema_def in self._schemas.items()
        }
        json_str = json.dumps(schemas_dict, indent=2, ensure_ascii=False)

        if output_path:
            try:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(json_str)
                logger.info(f"[SchemaRegistry] Schema定义已导出到: {output_path}")
            except Exception as e:
                logger.error(f"[SchemaRegistry] 导出Schema失败: {str(e)}")

        return json_str


# 全局Schema注册表实例
_global_registry: Optional[SchemaRegistry] = None


def get_schema_registry() -> SchemaRegistry:
    """
    获取全局Schema注册表实例

    Returns:
        SchemaRegistry实例
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = SchemaRegistry()
    return _global_registry
