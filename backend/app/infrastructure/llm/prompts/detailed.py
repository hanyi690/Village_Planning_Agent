"""Production prompt for the small, non-executable L3 intent pass.

L3 expresses a rough planning intention.  It does not pre-compile a target,
spatial relation, parameter block, candidate, or geometry for GROUND.
"""


CLAIMS_OUTPUT_GUIDE = """
【L3 planning-intent pass】
本轮只表达当前维度的粗略、非可执行规划意图。输出少量 claims；不要生成 report_body、项目包拆解、候选、空间关系、参数、数量、面积、容量、坐标、BSM 或 geometry。

每条 claim 只回答：想解决什么问题、希望形成什么方向、依据哪些事实、还需要核实什么。空间意图可以保留为“需要进一步接地”的语义，不要因为暂时没有位置就改写成另一个结论。

允许的 claim_family 只能使用当前维度语义契约中的粗粒度类别，例如 objective、constraint、action、facility、road、axis、zone、site_area、restoration、protection。类别只表示意图类型，不表示已经拥有对应的空间对象。

source_fact_refs 只能逐字复制当前 L1 facts 中出现的 fact_id；evidence_refs 只能逐字复制当前证据 projection 中出现的稳定 fact_id/source_refs/evidence_refs，不能把证据原文、推测、解释或新 ID 放进引用字段；没有合适引用时使用空数组。location_hints 只能是来源支持的自然语言线索，不是实体 ID。grounding_requirements 只描述后续 GROUND 需要核实的事实类型或关系，不填写 relation object、candidate ID 或 geometry。
"""


L3_EVIDENCE_PRIORITY_GUIDE = """
【证据优先级】
1. 优先使用当前上下文中带稳定 ID 的 typed facts 和 evidence。
2. 只复制上下文出现的身份；没有合适身份就留空并声明 grounding requirement。
3. 规划语义可以不完整，但不能用常识、名称相似或旧模板补齐空间事实。
"""


L3_EMISSION_CHECKLIST = """
【发射前检查】
1. 每条 claim 只保留一个粗粒度规划意图。
2. 只引用当前 L1 fact projection 中真实存在的 fact_id。
3. 没有位置或空间证据时保留 location_hints，并填写 grounding_requirements。
4. 不输出参数块、relation_template、object_ref、candidate、parcel、network 或 geometry。
"""


def get_dimension_prompt(
    dimension_key: str,
    *,
    project_name: str = "村庄",
    l1_facts: str = "",
    l2_decisions: str = "",
    same_layer_claims: str = "",
    evidence_context: str = "",
    task_constraints: str = "",
    semantic_contract: str = "",
    upstream_source_dimensions: str = "未提供",
    revision_instruction: str = "",
) -> str:
    """Build the only production L3 rough-intent prompt."""

    dimension_key = str(dimension_key or "").strip()
    if not dimension_key:
        return ""

    project_name = str(project_name or "村庄").strip()
    semantic_contract = str(semantic_contract or "").strip()
    l1_facts = str(l1_facts or "").strip()
    l2_decisions = str(l2_decisions or "").strip()
    same_layer_claims = str(same_layer_claims or "").strip()
    evidence_context = str(evidence_context or "").strip()
    task_constraints = str(task_constraints or "").strip()
    upstream_dimensions = str(upstream_source_dimensions or "未提供").strip()

    sections = [
        f"【L3 claims-only production pass | dimension_key={dimension_key}】",
        f"项目：{project_name}",
        "本轮只生成粗粒度、非可执行的结构化规划意图；报告正文由独立调用生成。",
        "上游 L1 source dimensions：" + upstream_dimensions,
    ]
    if revision_instruction:
        sections.insert(0, revision_instruction)
    if semantic_contract:
        sections.append("【维度语义契约】\n" + semantic_contract)
    if l1_facts:
        sections.append("【去重后的 L1 canonical facts】\n" + l1_facts)
    if l2_decisions:
        sections.append("【L2 abstract decisions】\n" + l2_decisions)
    if same_layer_claims:
        sections.append("【同层已形成的 rough claims；仅用于去重与边界协调】\n" + same_layer_claims)
    if task_constraints:
        sections.append("【任务约束】\n" + task_constraints)
    if evidence_context:
        sections.append("【当前维度的定向证据 projection】\n" + evidence_context)
    sections.extend([
        L3_EVIDENCE_PRIORITY_GUIDE,
        CLAIMS_OUTPUT_GUIDE,
        L3_EMISSION_CHECKLIST,
    ])
    return "\n\n".join(sections)


__all__ = [
    "CLAIMS_OUTPUT_GUIDE",
    "L3_EVIDENCE_PRIORITY_GUIDE",
    "L3_EMISSION_CHECKLIST",
    "get_dimension_prompt",
]
