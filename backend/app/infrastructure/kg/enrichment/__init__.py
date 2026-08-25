"""KG multi-level semantic enrichment — 报告 → KG 语义增强。

L1 现状语义回流（wave1）：村名→gazetteer 绑定（Flash 双确认）+ 批量实体描述
L2 意图语义（wave2）：功能分区实体注解 + 关系注记
L3 项目语义（wave3）：项目/功能区实体注解
按需：describe_entity 动态合成（属性+邻接注入）
"""
from .report_entity_enrichment import extract_bindings, run_wave
from .descriptions import describe_entity, describe_parcels
from .relations import annotate_cluster_relations, annotate_parcel_protection

__all__ = [
    "extract_bindings",
    "run_wave",
    "describe_entity",
    "describe_parcels",
    "annotate_cluster_relations",
    "annotate_parcel_protection",
]
