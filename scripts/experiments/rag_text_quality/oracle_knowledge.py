"""
Oracle Knowledge Module
Oracle 法规预选模块

为每个维度预选 3-5 条最相关法规/标准原文，
作为 G4（理想上限）的知识来源。

使用方法:
    oracle = OracleKnowledge()
    knowledge = oracle.get_oracle_knowledge("disaster_prevention")
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


# ============================================
# Oracle 法规配置
# ============================================

# 每个维度预选的法规/标准
ORACLE_KNOWLEDGE_CONFIG = {
    # Layer 1 维度
    "location": {
        "name": "区位分析",
        "regulations": [
            {
                "source": "《广东省村庄规划编制导则》",
                "content": "区位分析应包括：村庄与城镇的距离、交通可达性、周边资源分布、区域功能定位等。",
            },
            {
                "source": "《村镇总体规划》（叶昌东）",
                "content": "区位分析需评估村庄在区域中的地位，包括经济区位、交通区位、生态区位等维度。",
            },
        ],
    },
    "population": {
        "name": "人口分析",
        "regulations": [
            {
                "source": "《镇规划标准》（GB 50188-2007）",
                "content": "村庄人口预测方法：自然增长法、机械增长法、综合分析法。人均建设用地指标控制在100-150平方米。",
            },
            {
                "source": "《实用性村庄规划编制手册》",
                "content": "人口规模预测应考虑：常住人口、户籍人口、流动人口、季节性人口变化。",
            },
        ],
    },
    "land_use_status": {
        "name": "土地利用现状",
        "regulations": [
            {
                "source": "《土地利用现状分类》（GB/T 21010-2017）",
                "content": "土地利用分类：耕地、园地、林地、草地、商服用地、工矿用地、住宅用地、公共管理与公共服务用地等。",
            },
            {
                "source": "《广东省村庄规划编制导则》",
                "content": "现状用地调查应包括：用地类型、面积、权属、利用强度、存在问题。",
            },
        ],
    },
    # Layer 3 维度
    "road_planning": {
        "name": "道路规划",
        "regulations": [
            {
                "source": "《镇规划标准》（GB 50188-2007）",
                "content": "村庄道路等级：主干路（红线宽度16-24米）、干路（10-14米）、支路（6-8米）、巷路（3-5米）。道路密度不低于8km/km²。",
            },
            {
                "source": "《农村公路建设指导意见》",
                "content": "通村公路宽度不低于4.5米，路面硬化率应达到100%。村内主干道应设置人行道。",
            },
        ],
    },
    "water_supply": {
        "name": "给水规划",
        "regulations": [
            {
                "source": "《农村生活饮用水卫生标准》（GB 5749）",
                "content": "农村饮用水水质应符合GB 5749标准，供水普及率应达到95%以上。",
            },
            {
                "source": "《村镇供水工程技术规范》（SL 310）",
                "content": "人均日用水量：100-150L/d。供水管网压力不低于0.1MPa。",
            },
        ],
    },
    "disaster_prevention": {
        "name": "防灾规划",
        "regulations": [
            {
                "source": "《地质灾害防治条例》",
                "content": "崩塌隐患点避让距离不少于50米，滑坡隐患点避让距离不少于100米。地质灾害易发区应划定禁止建设区和限制建设区。",
            },
            {
                "source": "《建筑工程抗震设防分类标准》（GB 50223）",
                "content": "村庄公共建筑抗震设防类别为丙类，抗震设防烈度按当地标准执行。",
            },
            {
                "source": "《防洪标准》（GB 50201）",
                "content": "村庄防洪标准：一般村庄20年一遇，重要村庄50年一遇。",
            },
        ],
    },
}


@dataclass
class OracleRegulation:
    """Oracle 法规条目"""
    source: str              # 法规来源
    content: str             # 法规内容
    relevance_score: float = 1.0  # 相关性评分


@dataclass
class OracleKnowledgeResult:
    """Oracle 知识结果"""
    dimension_key: str
    dimension_name: str
    regulations: List[OracleRegulation]
    total_length: int
    formatted_context: str


class OracleKnowledge:
    """Oracle 法规预选管理器"""

    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化 Oracle 知识管理器

        Args:
            config: 自定义配置（可选，默认使用 ORACLE_KNOWLEDGE_CONFIG）
        """
        self.config = config or ORACLE_KNOWLEDGE_CONFIG
        self._cache: Dict[str, OracleKnowledgeResult] = {}

    def get_oracle_knowledge(
        self,
        dimension_key: str,
        max_regulations: int = 5
    ) -> OracleKnowledgeResult:
        """
        获取指定维度的 Oracle 知识

        Args:
            dimension_key: 维度键
            max_regulations: 最大法规数量

        Returns:
            Oracle 知识结果
        """
        # 检查缓存
        if dimension_key in self._cache:
            return self._cache[dimension_key]

        # 获取配置
        dim_config = self.config.get(dimension_key)
        if not dim_config:
            logger.warning(f"[Oracle] No knowledge configured for {dimension_key}")
            return OracleKnowledgeResult(
                dimension_key=dimension_key,
                dimension_name=dimension_key,
                regulations=[],
                total_length=0,
                formatted_context="",
            )

        # 构建法规列表
        regulations = []
        for reg_data in dim_config.get("regulations", [])[:max_regulations]:
            reg = OracleRegulation(
                source=reg_data.get("source", ""),
                content=reg_data.get("content", ""),
                relevance_score=reg_data.get("relevance_score", 1.0),
            )
            regulations.append(reg)

        # 构建格式化上下文
        formatted_context = self._format_context(regulations)

        # 计算总长度
        total_length = sum(len(r.content) for r in regulations)

        result = OracleKnowledgeResult(
            dimension_key=dimension_key,
            dimension_name=dim_config.get("name", dimension_key),
            regulations=regulations,
            total_length=total_length,
            formatted_context=formatted_context,
        )

        # 缓存结果
        self._cache[dimension_key] = result

        return result

    def _format_context(self, regulations: List[OracleRegulation]) -> str:
        """
        格式化法规上下文

        Args:
            regulations: 法规列表

        Returns:
            格式化后的上下文文本
        """
        if not regulations:
            return ""

        parts = []
        for reg in regulations:
            parts.append(f"【{reg.source}】\n{reg.content}")

        return "\n\n".join(parts)

    def get_all_oracle_knowledge(
        self,
        dimension_keys: List[str] = None
    ) -> Dict[str, OracleKnowledgeResult]:
        """
        获取所有维度的 Oracle 知识

        Args:
            dimension_keys: 维度键列表（可选，默认使用所有配置的维度）

        Returns:
            {dimension_key: OracleKnowledgeResult} 映射
        """
        if dimension_keys is None:
            dimension_keys = list(self.config.keys())

        results = {}
        for dim_key in dimension_keys:
            results[dim_key] = self.get_oracle_knowledge(dim_key)

        return results

    def add_custom_knowledge(
        self,
        dimension_key: str,
        source: str,
        content: str,
        relevance_score: float = 1.0
    ):
        """
        添加自定义 Oracle 知识

        Args:
            dimension_key: 维度键
            source: 法规来源
            content: 法规内容
            relevance_score: 相关性评分
        """
        if dimension_key not in self.config:
            self.config[dimension_key] = {
                "name": dimension_key,
                "regulations": [],
            }

        self.config[dimension_key]["regulations"].append({
            "source": source,
            "content": content,
            "relevance_score": relevance_score,
        })

        # 清除缓存
        if dimension_key in self._cache:
            del self._cache[dimension_key]

    def save_config(self, output_path: str):
        """
        保存配置到文件

        Args:
            output_path: 输出文件路径
        """
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
        logger.info(f"[Oracle] Saved config to {output_path}")

    def load_config(self, input_path: str):
        """
        从文件加载配置

        Args:
            input_path: 输入文件路径
        """
        with open(input_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
        self._cache.clear()
        logger.info(f"[Oracle] Loaded config from {input_path}")


def get_oracle_context_for_dimension(dimension_key: str) -> str:
    """
    获取指定维度的 Oracle 上下文（便捷函数）

    Args:
        dimension_key: 维度键

    Returns:
        格式化的法规上下文
    """
    oracle = OracleKnowledge()
    result = oracle.get_oracle_knowledge(dimension_key)
    return result.formatted_context


if __name__ == "__main__":
    # 测试
    oracle = OracleKnowledge()

    # 获取防灾规划的 Oracle 知识
    result = oracle.get_oracle_knowledge("disaster_prevention")

    print(f"维度: {result.dimension_name}")
    print(f"法规数量: {len(result.regulations)}")
    print(f"总长度: {result.total_length}")
    print("\n格式化上下文:")
    print(result.formatted_context)