"""
维度规划器层

提供所有维度规划器的基类和实现。

三层架构：
- Layer 1: BaseAnalysisPlanner (现状分析规划器)
- Layer 2: BaseConceptPlanner (规划思路规划器)
- Layer 3: DimensionPlanner (详细规划规划器)
"""

# Layer 1: 现状分析规划器
from .analysis_planners import (
    BaseAnalysisPlanner,
    LocationAnalysisPlanner,
    SocioEconomicAnalysisPlanner,
    NaturalEnvironmentAnalysisPlanner,
    LandUseAnalysisPlanner,
    TrafficAnalysisPlanner,
    PublicServicesAnalysisPlanner,
    InfrastructureAnalysisPlanner,
    EcologicalGreenAnalysisPlanner,
    ArchitectureAnalysisPlanner,
    HistoricalCultureAnalysisPlanner,
    AnalysisPlannerFactory,
)

# Layer 2: 规划思路规划器
from .concept_planners import (
    BaseConceptPlanner,
    ResourceEndowmentPlanner,
    PlanningPositioningPlanner,
    DevelopmentGoalsPlanner,
    PlanningStrategiesPlanner,
    ConceptPlannerFactory,
)

# Layer 3: 详细规划规划器
from .base_planner import DimensionPlanner
from .detailed_planners import (
    IndustryPlanningPlanner,
    SpatialStructurePlanner,
    LandUsePlanningPlanner,
    SettlementPlanningPlanner,
    TrafficPlanningPlanner,
    PublicServicePlanner,
    InfrastructurePlanner,
    EcologicalPlanningPlanner,
    DisasterPreventionPlanner,
    HeritagePlanner,
    LandscapePlanner,
    ProjectBankPlanner,
    DetailedPlannerFactory,
)

__all__ = [
    # Layer 1: 现状分析规划器
    "BaseAnalysisPlanner",
    "LocationAnalysisPlanner",
    "SocioEconomicAnalysisPlanner",
    "NaturalEnvironmentAnalysisPlanner",
    "LandUseAnalysisPlanner",
    "TrafficAnalysisPlanner",
    "PublicServicesAnalysisPlanner",
    "InfrastructureAnalysisPlanner",
    "EcologicalGreenAnalysisPlanner",
    "ArchitectureAnalysisPlanner",
    "HistoricalCultureAnalysisPlanner",
    "AnalysisPlannerFactory",

    # Layer 2: 规划思路规划器
    "BaseConceptPlanner",
    "ResourceEndowmentPlanner",
    "PlanningPositioningPlanner",
    "DevelopmentGoalsPlanner",
    "PlanningStrategiesPlanner",
    "ConceptPlannerFactory",

    # Layer 3: 详细规划规划器
    "DimensionPlanner",
    "IndustryPlanningPlanner",
    "SpatialStructurePlanner",
    "LandUsePlanningPlanner",
    "SettlementPlanningPlanner",
    "TrafficPlanningPlanner",
    "PublicServicePlanner",
    "InfrastructurePlanner",
    "EcologicalPlanningPlanner",
    "DisasterPreventionPlanner",
    "HeritagePlanner",
    "LandscapePlanner",
    "ProjectBankPlanner",
    "DetailedPlannerFactory",
]
