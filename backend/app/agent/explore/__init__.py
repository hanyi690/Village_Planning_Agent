"""EXPLORE 能力引擎 — 概要层与访问层组装。

EXPLORE 在本仓库有两层实现并存：

1. **桥接 agent（Flash LLM 可选）** — ``ExploreFlashAgent`` / ``explore_planning_text``。
   文本分块 -> 6 域分类 -> BSM 识别 -> 通过 ``app.modules.kg`` 的稳定边界查
   session KG, 产出 ``ExplorationInstructionCollection``（供下游 Binder /
   PARSE 消费）。
2. **证据服务（确定性）** — ``retrieve_evidence`` / ``render_evidence_prompt_section``。
   由 L1/L2/L3 维度分析节点直接调用（替代已废弃的 ``_optimize_semantics`` +
   ``_build_explore_brief`` 路径），为每维度提供 KG 证据与 Prompt 片段（无 LLM 调用）。

工具定义位于 ``app.tools.access``（共享工具层）, 供 EXPLORE agent 与维度分析
复用, 通过 ``ToolRegistry.for_agent("explore")`` 统一注册。
"""

from .agent import ExploreFlashAgent, SessionKGQuery, explore_planning_text
from .contracts import ExplorationInstruction, ExplorationInstructionCollection
from .service import retrieve_evidence, render_evidence_prompt_section

__all__ = [
    # Bridge-mode agent (Flash LLM, opt-in via GIS_EXPLORE_LLM_ENABLED)
    "ExploreFlashAgent",
    "SessionKGQuery",
    "explore_planning_text",
    "ExplorationInstruction",
    "ExplorationInstructionCollection",
    # Evidence service (Wave C, deterministic orchestrator)
    "retrieve_evidence",
    "render_evidence_prompt_section",
]