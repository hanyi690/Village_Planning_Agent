"""Production prompt for the semantic L3 claim-component pass.

The structured response model, relation catalog, and evidence registry own
closed-set validation. This prompt supplies planning context and explains the
semantic work that remains for the model; it deliberately does not duplicate
those executable contracts.
"""


CLAIMS_OUTPUT_GUIDE = """
【L3 claims-only semantic pass】
claims pass 只写结构化判断：claims-only 输出当前维度的 claims 数组，不生成 report_body、坐标、BSM 或 geometry。报告正文由后续 report-synthesis pass 根据已确认 claims 生成，不能新增目标、数量、位置、关系或证据来源。

【组件与项目包】
结构化 schema 是字段、组件类型和参数块的唯一约束来源。每条 claim 先表达一个语义组件，再填写该组件真正需要的规划量；不要把一个项目包的总体愿景、服务范围、道路/管线和保护/修复覆盖物塞进同一个组件。一个项目包含多个物质组件时分别输出并复用同一个 project_package_ref：例如“文化廊道连接村寨”可拆成 axis 与实际 road/linear；“服务中心服务居民点”可拆成 zone 与 facility。只有概念性“串联/服务/修复”而没有明确物质工程时，保留为 objective 或组件语义，不凭空增加 hard relation 或物理设施。

spatial_intervention 表示最终需要空间候选或空间成果，不表示已经完成空间定位。非空间事实、指标、约束和管理行动使用 schema 提供的非空间组件。缺少定位、证据或端点时保留语义意图，让 GROUND 接收 grounding requirement；不要把空间目标静默降级为 action，也不要编造身份。

【引用与关系】
candidate_context 是本轮可选的 source fact ID 和按主体类型分组的关系候选。source_fact_refs 只能逐字复制其中真实存在的 fact ID；空间 claim 还必须从 spatial_source_fact_options 中选择。EXPLORE 中的 L1_facts、source_refs、provenance、entity ref 和 bundle ref 只是 lineage/background，不能复制到 source_fact_refs。其他 ID、地点名、报告段落、BSM 和坐标也不是来源身份。关系只在当前语义明确且候选列表允许时声明；跨组件对象尚未进入 registry 时留空，并用 grounding requirement 描述 expected kind、查询语义和缺失槽位。未解析的引用不能改写成另一个 claim、项目包或地点字符串。

【证据边界】
L1 typed facts、EvidenceGraph 证据和本节明确提供的专业数据用于支持语义判断；报告背景和旧模板只作为背景。没有证据就不要补写项目数量、地点、面积、长度、容量或服务对象。L3 不生成空间几何，具体 place binding、network、parcel 和 topology 由 GROUND/VALIDATE 处理。
"""


L3_EVIDENCE_PRIORITY_GUIDE = """
【证据优先级】
1. 优先使用当前上下文中带稳定 ID 的 typed facts 和 evidence。
2. 只复制上下文出现的身份；没有合适身份就留空并声明 grounding requirement。
3. 规划语义可以不完整，但不能用常识、名称相似或旧模板补齐空间事实。
"""


L3_EMISSION_CHECKLIST = """
【发射前检查】
1. 先判断这是非空间语义、空间组件还是项目包的一部分。
2. 混合项目拆成独立组件；同一项目包只复用稳定 package ref，不复用空间实体身份。
3. 只选择当前 schema 和 candidate_context 提供的组件/关系/来源选项。
4. 未闭合的来源、对象、网络或位置形成 grounding requirement，并在 uncertainty 中保留待核验状态。
"""


LOCATION_EVIDENCE_GUIDE = """
【空间证据】
以下内容只提供可核验的上游证据和位置线索，不等于已经完成空间绑定：
{location_evidence}
只能复制其中真实出现且与当前对象直接相关的身份；没有直接关系时留空。
"""


def get_dimension_prompt(
    dimension_key: str,
    revision_instruction: str = "",
    **kwargs,
) -> str:
    """Build one bounded claims-only prompt for a dimension."""

    dimension_key = str(dimension_key or "").strip()
    if not dimension_key:
        return ""

    def _text(name: str) -> str:
        return str(kwargs.get(name) or "").strip()

    project_name = _text("project_name") or "村庄"
    semantic_contract = _text("semantic_contract")
    professional_data_section = _text("professional_data_section")
    if not professional_data_section and isinstance(kwargs.get("professional_data"), str):
        professional_data_section = str(kwargs["professional_data"]).strip()
    evidence_context = _text("evidence_context") or _text("knowledge_context")
    location_evidence = _text("location_evidence")
    candidate_context = _text("candidate_context")
    upstream_dimensions = _text("upstream_source_dimensions") or "未提供"

    sections = [
        f"【L3 claims-only production pass | dimension_key={dimension_key}】",
        f"项目：{project_name}",
        "本轮只生成可审计的结构化 claims，不生成法定报告正文、表格、几何或调试对象。",
        "旧报告模板中的表格和‘至少列出’只是背景，不能决定本轮项目数量或数值。",
        "非空间指标可以没有 locator；空间组件即使还没有 locator 也要保留语义，并交给 GROUND 生成待补齐任务。",
        "上游 L1 source dimensions：" + upstream_dimensions,
    ]
    if revision_instruction:
        sections.insert(0, revision_instruction)
    if semantic_contract:
        sections.append("【维度语义契约】\n" + semantic_contract)
    if professional_data_section:
        sections.append("【专业数据与探索上下文；仅作背景】\n" + professional_data_section)
    for label, value in (
        ("L1 现状分析背景", _text("analysis_report")),
        ("L2 规划思路背景", _text("planning_concept")),
        ("约束条件", _text("constraints")),
        ("同层规划背景", _text("dimension_plans")),
    ):
        if value:
            sections.append(f"【{label}；不得直接当作空间身份】\n{value}")
    if evidence_context:
        sections.append("【统一证据检索结果】\n" + evidence_context)
    if location_evidence:
        sections.append(LOCATION_EVIDENCE_GUIDE.format(location_evidence=location_evidence))
    if candidate_context:
        sections.append("【当前候选上下文；只可选择其中 ID/关系】\n" + candidate_context)
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
    "LOCATION_EVIDENCE_GUIDE",
    "get_dimension_prompt",
]
