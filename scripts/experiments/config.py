"""
Experiment Configuration
实验配置

定义实验场景、关键词检测列表、输出路径等配置。

实验一：RAG开启/关闭条件下的法规引用幻觉率对比
实验二：级联一致性检验
"""

from pathlib import Path
from typing import Dict, List, Any

# ============================================
# Output Paths - 实验一（RAG幻觉率）
# ============================================

RAG_HALLUCINATION_DIR = Path(__file__).parent.parent.parent / "output" / "experiments" / "rag_hallucination"
RAG_ON_DIR = RAG_HALLUCINATION_DIR / "rag_on"
RAG_OFF_DIR = RAG_HALLUCINATION_DIR / "rag_off"
FIXED_CONTEXT_DIR = RAG_HALLUCINATION_DIR / "fixed_context"
ANNOTATION_DIR = RAG_HALLUCINATION_DIR / "annotation"

# ============================================
# Output Paths - 实验二（级联一致性）
# ============================================

CASCADE_DIR = Path(__file__).parent.parent.parent / "output" / "experiments" / "cascade_consistency"
BASELINE_DIR = CASCADE_DIR / "baseline"
SCENARIO1_DIR = CASCADE_DIR / "scenario1_planning_positioning"
SCENARIO2_DIR = CASCADE_DIR / "scenario2_natural_environment"
ANALYSIS_DIR = CASCADE_DIR / "analysis"


# ============================================
# 实验一：RAG 幻觉率实验配置
# ============================================

# Layer 3 中启用 RAG 的 5 个关键维度
RAG_ENABLED_DIMENSIONS = [
    "land_use_planning",      # 土地利用规划
    "infrastructure_planning", # 基础设施规划
    "ecological",             # 生态绿地规划
    "disaster_prevention",    # 防震减灾规划
    "heritage",               # 历史文保规划
]

# 法规引用标注字段
REGULATION_ANNOTATION_FIELDS = [
    {"field": "reference_id", "label": "引用序号", "type": "number"},
    {"field": "reference_text", "label": "引用原文", "type": "text"},
    {"field": "reference_type", "label": "引用类型", "type": "select",
     "options": ["法规文件名", "条款编号", "技术指标数值", "其他"]},
    {"field": "is_correct", "label": "是否正确", "type": "select",
     "options": ["正确", "虚构", "部分错误"]},
    {"field": "error_type", "label": "错误分类", "type": "select",
     "options": ["A-文件名虚构", "B-条款编号不符", "C-指标数值错误", "D-条款内容张冠李戴", "无错误"]},
    {"field": "verification_source", "label": "核查依据", "type": "text"},
]


# ============================================
# 实验二：级联一致性场景定义
# ============================================

SCENARIOS: Dict[str, Dict[str, Any]] = {
    "scenario1": {
        "name": "驳回规划定位（Layer 2）",
        "target_dimension": "planning_positioning",
        "target_layer": 2,
        "feedback": """金田村常住人口仅500人，不具备承接大规模旅游的基础设施条件。
千年古檀树、古茶亭遗址等核心历史资源应划定为绝对保护对象，剥离重度商业开发权。
规划定位应转向生态保育优先、客家文化微改造的渐进式发展路径。""",
        # 预期影响范围由运行时动态计算（get_impact_tree + get_revision_wave_dimensions）
        # Checkpoint配置
        "checkpoint_restore": True,  # 是否从checkpoint恢复
        "checkpoint_layer": 2,       # 恢复点layer
        # 关关键词检测
        "keywords": {
            "positive": ["生态保育", "渐进式发展", "客家文化微改造", "绝对保护", "保护优先", "微改造"],
            "negative": ["大规模旅游", "商业开发", "景区化", "旅游开发"],
        },
    },
    "scenario2": {
        "name": "驳回自然环境分析（Layer 1）",
        "target_dimension": "natural_environment",
        "target_layer": 1,
        "feedback": """现状报告中明确记载金田村存在5处崩塌隐患点和35处滑坡隐患点，
但当前分析未对隐患点的空间分布与影响范围进行充分评估，需强化地质灾害风险的分析深度。""",
        # 预期影响范围由运行时动态计算（get_impact_tree + get_revision_wave_dimensions）
        # Checkpoint配置
        "checkpoint_restore": True,
        "checkpoint_layer": 1,
        "keywords": {
            "positive": ["崩塌隐患", "滑坡隐患", "地质灾害风险", "隐患点分布", "风险管控", "风险评估"],
            "negative": [],
        },
    },
}


# ============================================
# Test Data Configuration
# ============================================

# Status report file path
STATUS_REPORT_PATH = Path(__file__).parent.parent.parent / "docs" / "泗水镇金田村现状报告.docx"


def load_status_report() -> str:
    """
    Load village status report from docx file.

    Returns:
        Status report content as string (empty if file not found)
    """
    if not STATUS_REPORT_PATH.exists():
        print(f"[Config] Status report not found: {STATUS_REPORT_PATH}")
        return ""

    try:
        from src.rag.utils.loaders import MarkItDownLoader

        loader = MarkItDownLoader(STATUS_REPORT_PATH)
        docs = loader.load()

        # Combine all document pages/sections
        content = "\n\n".join([doc.page_content for doc in docs])
        print(f"[Config] Loaded status report: {len(content)} chars")
        return content

    except Exception as e:
        print(f"[Config] Failed to load status report: {e}")
        return ""


JINTIAN_VILLAGE_DATA = {
    "village_name": "金田村委会",
    "area_km2": 23.53,
    "population": 500,
    "administrative": "梅州市梅县区水车镇",
    "coordinate_system": "EPSG:4326",
    "status_report": load_status_report(),
}


# ============================================
# Annotation Template Configuration
# ============================================

ANNOTATION_FIELDS = [
    {"field": "dimension_key", "label": "维度编号", "type": "text"},
    {"field": "dimension_name", "label": "维度名称", "type": "text"},
    {"field": "layer", "label": "层级", "type": "number"},
    {"field": "wave", "label": "波次", "type": "number"},
    {"field": "positive_keyword_coverage", "label": "正向关键词检出率", "type": "percentage"},
    {"field": "negative_keyword_residual", "label": "残留负面关键词", "type": "text"},
    {"field": "human_judgment", "label": "人工判定", "type": "select", "options": ["达标", "部分达标", "未达标"]},
    {"field": "notes", "label": "备注", "type": "text"},
]


# ============================================
# Utility Functions
# ============================================

def ensure_rag_experiment_dirs():
    """Ensure RAG hallucination experiment directories exist."""
    for dir_path in [RAG_HALLUCINATION_DIR, RAG_ON_DIR, RAG_OFF_DIR, FIXED_CONTEXT_DIR, ANNOTATION_DIR]:
        dir_path.mkdir(parents=True, exist_ok=True)


def ensure_cascade_dirs():
    """Ensure cascade consistency experiment directories exist."""
    for dir_path in [CASCADE_DIR, BASELINE_DIR, SCENARIO1_DIR, SCENARIO2_DIR, ANALYSIS_DIR]:
        dir_path.mkdir(parents=True, exist_ok=True)


def ensure_output_dirs():
    """Ensure all experiment directories exist."""
    ensure_rag_experiment_dirs()
    ensure_cascade_dirs()


def get_scenario_config(scenario_name: str) -> Dict[str, Any]:
    """Get scenario configuration by name."""
    if scenario_name not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario_name}")
    return SCENARIOS[scenario_name]


def get_checkpoint_restore_config(scenario_name: str) -> Dict[str, Any]:
    """
    Get checkpoint restoration config for a scenario.

    Args:
        scenario_name: Scenario name (scenario1 or scenario2)

    Returns:
        {
            "checkpoint_restore": bool,
            "checkpoint_layer": int,
        }
    """
    config = get_scenario_config(scenario_name)
    return {
        "checkpoint_restore": config.get("checkpoint_restore", True),
        "checkpoint_layer": config.get("checkpoint_layer", config.get("target_layer", 2)),
    }


def get_output_dir(scenario_name: str) -> Path:
    """Get output directory for a scenario."""
    if scenario_name == "baseline":
        return BASELINE_DIR
    elif scenario_name == "scenario1":
        return SCENARIO1_DIR
    elif scenario_name == "scenario2":
        return SCENARIO2_DIR
    elif scenario_name == "analysis":
        return ANALYSIS_DIR
    else:
        raise ValueError(f"Unknown scenario: {scenario_name}")


# ============================================
# Knowledge Base Status Check
# ============================================

def check_kb_status(required_docs: List[str] = None) -> Dict[str, Any]:
    """
    Check if knowledge base contains necessary documents.

    Args:
        required_docs: List of required document names (optional)

    Returns:
        Status dict with total_chunks, total_docs, missing_docs, is_ready
    """
    try:
        from src.rag.core.vector_store import get_parent_child_store

        store = get_parent_child_store()
        stats = store.get_stats()

        total_chunks = stats.get("total_chunks", 0)
        total_docs = stats.get("total_docs", 0)

        # Check required documents
        missing = []
        if required_docs:
            available_docs = stats.get("documents", [])
            for doc in required_docs:
                # Check if doc name appears in available docs
                if not any(doc in d for d in available_docs):
                    missing.append(doc)

        return {
            "total_chunks": total_chunks,
            "total_docs": total_docs,
            "missing_docs": missing,
            "is_ready": len(missing) == 0 and total_chunks > 100,
        }

    except Exception as e:
        # If RAG module not available, return unavailable status
        return {
            "total_chunks": 0,
            "total_docs": 0,
            "missing_docs": required_docs if required_docs else [],
            "is_ready": False,
            "error": str(e),
        }