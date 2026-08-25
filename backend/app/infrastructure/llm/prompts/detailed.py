"""Production prompt for the typed L3 planning-claims pass.

L3 is deliberately a claims compiler boundary. It does not generate the
legacy report/table templates and it does not invent geometry. The only
production entry point in this module is :func:`get_dimension_prompt`.
"""


CLAIMS_OUTPUT_GUIDE = """
【L3 claims-only 输出契约】
本次只返回本维度的结构化 claims 数组；不要返回 report_body、Markdown 正文、坐标、BSM、候选几何、GeoJSON 或调试对象。报告正文由后续独立 synthesis pass 根据已确认 claims 生成，不能新增目标、位置、关系、数量或来源事实。

planning_role 只能是 evidence_statement、indicator、constraint、objective、
non_spatial_action、project_package、spatial_intervention。spatial_intervention
表示“这个目标最终需要空间候选/空间成果”，不是“它已经完成空间定位”。
稳定 project_package_ref 和 typed 参数描述目标语义；location_hints、source_fact_refs
和 evidence_refs 只在输入明确给出时填写。缺少定位线索或证据 lineage 时，仍然保留为
spatial_intervention，并让 GROUND 生成对应的 place/demand/network/parcel 前置任务，
不得把空间目标改写成 action，也不得让它在 admission 前静默消失。project_package_ref
只是跨维度管理身份，不是空间目标。保留类现状事实使用 evidence_statement。

【字段闭集与互斥关系；逐字段执行】
claims 数组中的每个对象只能使用 PlanningClaimDraft 字段：claim_id、dimension_key、statement、
planning_role、project_package_ref、affected_population、affected_parcel_refs、suggested_category、
suggested_output_kind、asset_kind、suggested_interventions、quantity、quantity_unit、
intervention_action、road_parameters、linear_parameters、facility_parameters、axis_parameters、
polygon_parameters、site_area_parameters、implementation_phase、location_hints、constraint_refs、
objective_refs、evidence_refs、source_fact_refs、source_refs、spatial_requirements、confidence、uncertainty。
intervention_action 只能是 preserve/new/expand/relocate/upgrade/widen/harden/repair/demolish；
asset_kind 只能是 none/facility/land_use/axis/road/water_supply/sewer/stormwater/power/communication/
drainage_channel/revetment；不要输出未声明的字段。
- suggested_category 只能是 site_area、facility、road、axis、restoration、protection、zone、action。
- suggested_output_kind 只能是 parcel、polygon、point、line、action（suggested_output_kind 只能是 parcel/polygon/point/line/action），绝不能写 none。
- asset_kind 的 none 只属于非线性或非空间 claim，不是 suggested_output_kind 的值。
- 没有空间干预的背景事实、指标、约束或管理行动统一使用 suggested_category=action、suggested_output_kind=action、asset_kind=none；所有 typed parameter 保持 null。不要为了保留地点名而把背景事实伪装成 spatial_intervention。
- facility 必须使用 facility+point，并填写 facility_parameters；service center、广场、停车场、观景点、污水处理设施等可定位服务节点均按此处理。
- road/线性工程必须使用 road+line。asset_kind=road 只能填写 road_parameters；asset_kind 为 water_supply、sewer、stormwater、power、communication、drainage_channel 或 revetment 时只能填写 linear_parameters。两类参数不能同时出现，也不能都为空。
- axis 必须使用 axis+line 并填写 axis_parameters；restoration/protection 必须使用对应 category+polygon 并填写 polygon_parameters。
- zone 使用 zone+polygon 并填写 polygon_parameters；site_area 只能使用 site_area+parcel 或 site_area+polygon，并填写 site_area_parameters。
- materialization_role 只能是 land_use_assignment、functional_overlay、protection_overlay、restoration_overlay、site_footprint 或 null。avoid_constraint、near、serve、connect_network 等只属于 spatial_requirements.relations[].relation_template，绝不能写入 materialization_role。

【跨字段硬约束；不能只满足单字段枚举】
- planning_role=spatial_intervention 且 asset_kind=sewer/water_supply/stormwater/power/communication/drainage_channel/revetment 时，suggested_category=road，suggested_output_kind=line，必须填写 linear_parameters；road_parameters 必须为 null。
- planning_role=spatial_intervention 且 asset_kind=road 时，suggested_category=road，suggested_output_kind=line，必须填写 road_parameters；linear_parameters 必须为 null。
- suggested_category=action 只允许 suggested_output_kind=action、asset_kind=none、所有 typed parameter=null，且不能与 planning_role=spatial_intervention 同时出现。工程动作 new/upgrade/repair 等应填写 intervention_action 或对应参数块的 action，不能把工程类别写成 action。
- 每条 spatial_intervention 只能填写一个与 category/asset_kind 对应的 typed parameter block；category、output、asset_kind、typed parameter block 不一致时，整条 claim 视为非法，不能通过把 output 改成 action 来修复。
- 以下输出非法：action + line + sewer + linear_parameters。正确输出是：road + line + sewer + linear_parameters。

每条 claim 至少包含 claim_id、statement、planning_role、project_package_ref、suggested_category、suggested_output_kind、suggested_interventions、quantity/quantity_unit（若有）、implementation_phase、location_hints、constraint_refs、objective_refs、evidence_refs、source_fact_refs、spatial_requirements 和 uncertainty。顶层 quantity 的类型只能是 JSON 数字或 null，quantity_unit 只能是字符串或 null；不得把 {"value": 数值, "unit": "..."} 放入顶层 quantity。只有 road_parameters、linear_parameters、facility_parameters、axis_parameters、polygon_parameters 或 site_area_parameters 内部的量值字段才使用各自 schema 声明的对象形式。implementation_phase 是必填闭集，只能是 "short"、"medium" 或 "long"，不得为 null、空字符串或其他值；无法判断时使用 "short"。空间目标即使没有 location_hints、evidence_refs 或 source_fact_refs，也必须保留完整的空间 category/output_kind；在 spatial_requirements.grounding_requirements 中列出需要 GROUND 补齐的前置条件。

source_fact_refs 只能逐字复制“已审计 L1 spatial facts”区块中的 L1Fact.fact_id；不能填写地点名、BSM、坐标或自由字符串。只有 L1 typed fact 直接支持时才填写，不能把 report、RAG 或外源文本的段落 ID 当作 source_fact_refs。没有直接 fact 仍可生成需要 GROUND 的语义候选，但要保留 location_hints，并在 uncertainty 中说明待核验。

空间 claim 的 location_hints 只是 EvidenceGraph/GROUND 的语义检索线索，不等于已经定位。不得从行政区划名单或模型常识补齐地点，不得在 L3 生成 BSM、坐标、地块或几何。spatial_requirements 只表达 GROUND 的语义输入：relations、shared_resource_refs、parcel_membership_refs、competing_parcel_refs、network_refs、required_input_refs 和 grounding_requirements（place_binding、candidate_geometry、demand_points、parcel_membership、network_snapshot、topology）。需要设施覆盖时，若上下文提供了 typed demand/network 身份，应在 serve relation 的参数中逐字填写 demand_ref、network_ref、facility_type、capacity 和覆盖阈值；需要道路、管线或连通时，应在 connect_network/provide_access/follow_alignment relation 中填写已知 network_ref 或明确留下 network_snapshot/endpoint 前置需求。未知身份留空并记录前置需求，不得编造 demand_ref、network_ref 或端点。关系参数可以包含 distance、capacity、network_ref 等规划量，但不能包含 geometry、coordinates、WKT、GeoJSON、BSM 或候选地块对象。

【关系端点和参数的闭集】
- 当前 claim 自己发起的 relation 可以省略 subject_ref；若填写，只能使用当前 claim_id，不能使用 project_package_ref、intervention 名称或自然语言项目名称。跨 claim relation 的 subject_ref/object_ref 只能使用上下文已经出现的 claim_id；已知的网络、需求、约束或地点可用其 typed evidence identity，不能把项目包名当成空间实体。
- relation 的 parameters 只能使用下表字段；不要把中文规划说明、`distance`/`coverage_threshold`/`alignment_name`/`network_type`/`total_length`/`location` 或 `{"unit": ..., "value": ...}` 这类自由字段放入参数。无法填满必需字段时使用空对象 `{}`，并在 grounding_requirements 中写明缺少的前置条件。
  - avoid_constraint：`constraint_refs`（非空数组）、可选 `buffer_m`；near：`max_distance_m`、`metric`（euclidean/network），network 时还要 `network_ref`。
  - serve：`demand_ref`、`facility_type`、`max_travel_time_min`、`min_coverage_ratio`、`capacity`、`capacity_unit`、`network_ref`；provide_access：`max_travel_time_min`、`network_ref`、`mode`。
  - connect_network：`network_kind`、`endpoint_tolerance_m`、`network_ref`；follow_alignment：`alignment_ref`、`max_deviation_m`；preserve_existing/upgrade_existing：`existing_ref`；part_of：`parent_ref`；co_locate：`max_distance_m`；mutually_exclusive：可选 `scope_ref`；precedes：`required_event`（start/complete）。数值必须是数值和合法单位，不把 null 或“全村/待定”当作数值。
- object_ref 为空或只有语义地点名时，关系仍保留为待 GROUND 解析的 relation；不能为了填字段而把地点名伪装成 claim_id、demand_ref 或 network_ref。

【参数块一一对应】
- road_parameters：action 只能 preserve/new/upgrade/widen/harden/repair；字段为 road_level、length、roadbed_width、pavement_width、alignment_refs、connects。长度、路基宽、路面宽分开填写，量值使用 {"value": 数值, "unit": "m|km"}。沿既有道路改造把道路名放入 alignment_refs；connects 只写原文明确的两端对象。
- linear_parameters：action 只能 preserve/new/upgrade/expand/repair；字段为 length、diameter、material、alignment_refs、connects。管径写 diameter，不能写入 roadbed_width 或 pavement_width。
- facility_parameters：action 只能 preserve/new/expand/relocate/repair；字段为 facility_type、service_radius、capacity、footprint_area，服务半径使用 m/km，占地使用 m2/ha。
- axis_parameters：action 只能 preserve/new/upgrade；axis_type 只能 primary/secondary/spatial_control，并填写 direction、reference_features、connects、corridor_width。
- polygon_parameters：使用 area_range（minimum、maximum、unit=m2|ha）和 materialization_role。只有真正改变土地用途的 zone 才用 land_use_assignment；功能结构用 functional_overlay，保护/修复用对应 overlay。
- site_area_parameters：填写 site_type、capacity、capacity_unit、footprint_area。设施点位不能写成 site_area；设施类型、服务半径、容量和占地使用 facility_parameters。

线性工程是“线性成果 + 地块用地变更”的双 worker 任务：road claim 只表达中心线/走廊和道路参数，不能在 claim 中填写 BSM、坐标、候选地块或几何；new/widen 的占用地块由真实线与现状地块相交后由 ROAD EXECUTE worker 计算，upgrade/harden/repair 不能自动改变地块性质。不要为同一条道路重复编造 site_area claim。

单位只使用面积（公顷/ha、亩、平方米/m2、㎡）、长度（米/m、千米/km）、容量/体积（立方米/m3、升/l、吨/t）、数量（个、处、座、条、棵、株、人、户、间、栋、根、套）或功率/电量（千瓦/kw、千瓦时/kwh）。写不出明确数值时留空并写 uncertainty；不要把“待定”或“无”当作单位。
claims pass 只写结构化判断，不写解释文字；report-synthesis pass 再解释已验证 claims。
"""


L3_EVIDENCE_PRIORITY_GUIDE = """
【证据优先级】
1. L1 report 只是现状背景；已审计的 L1 spatial facts、EvidenceGraph 的空间事实/候选/拓扑，以及本节明确标注的专业文本，才是对应判断的可用依据。
2. 当前模板中的项目数量、旧报告模板中的示例地点、示例数值和“至少列出”等文字不是生成指令；没有证据就不生成项目、地点、面积、长度或容量。
3. LLM 只输出规划语义和来源 fact_id。不得从名称、BSM、坐标、几何类型或道路宽度推导另一个实体，也不得在 claims 中制造空间标识。
4. 每条空间 claim 明确它是“L1 fact 已绑定”还是“语义候选、需要 GROUND 检索”。无法由 EvidenceGraph 闭合的候选由 GROUND/VALIDATE 返回证据缺口，不能用经验值或隐式回退掩盖。缺少证据不是把空间 claim 降级为 action 的理由。
"""


L3_EMISSION_CHECKLIST = """
【L3 逐条发射检查；优先于背景文本】
返回 claims 数组前逐条完成以下检查：
1. 只有 planning_role=spatial_intervention 或 project_package 的 claim 才必须有非空 project_package_ref。若输入没有现成包标识，创建一个稳定的语义包标识，并对同一交付物的相关 claim 原样复用；不得把坐标、BSM、地块或临时地点名当作包标识。evidence_statement、indicator、constraint、non_spatial_action 可以把 project_package_ref 留空。
2. 先选 category/output 的合法组合，再填写且只填写一个对应 typed 参数块：facility→facility_parameters；road+asset_kind=road→road_parameters；road+其他线性 asset_kind→linear_parameters；axis→axis_parameters；zone/restoration/protection→polygon_parameters；site_area→site_area_parameters。空间 claim 不能缺少该块；背景 action claim 的所有 typed 参数保持 null。不要用 point/line/action 去覆盖另一个 category 的参数语义。
3. lineage 按输入中出现的身份逐字复制：可直接支持该 claim 的 L1 planning fact_id→source_fact_refs（空间 claim 仅可用 fact_kind=spatial_observation/gis_observation/kg_canonical_fact）；typed facts 的 source_refs→source_refs；统一证据区块给出的证据 ID→evidence_refs。地点名、report 标题、BSM、坐标和模型自造 ID 都不是 lineage。没有明确 ID 时保持引用为空，不得编造；保留空间意图，并在 spatial_requirements.grounding_requirements 与 uncertainty 中说明待 GROUND 补齐的 lineage/证据前置条件。
4. 最后复核每条空间 claim：非空 package ref、合法 category/output 对、唯一且完整的 typed 参数块、可逐字追溯的 lineage（若输入存在）；缺证据只能进入 GROUND 待核验，不能静默改成 action 或删除。
"""


LOCATION_EVIDENCE_GUIDE = """
【空间位置证据闭集】
以下是上游报告与已绑定 GIS/KG 的可核验位置证据：
{location_evidence}

只能使用上面证据中出现、且与当前对象有直接关系的位置；不得从行政区划名单推断对象位置。证据没有支持的位置必须留空，不能为了让输出完整而补写地点名。位置实体可以是道路、水体、设施、地块、居民点、行政单元或其他已注册地点，但同一对象与该地点必须在上游证据中存在直接关系，仅出现名称不构成位置证据。
"""


def get_dimension_prompt(
    dimension_key: str,
    revision_instruction: str = "",
    **kwargs,
) -> str:
    """Build the one and only production L3 claims prompt.

    ``kwargs`` carries already assembled evidence sections. It is not an
    output-mode switch: every call uses the same claims-only contract.
    """

    dimension_key = str(dimension_key or "").strip()
    if not dimension_key:
        return ""

    def _text(name: str) -> str:
        return str(kwargs.get(name) or "").strip()

    project_name = _text("project_name") or "村庄"
    semantic_contract = _text("semantic_contract")
    professional_data_section = _text("professional_data_section")
    if not professional_data_section:
        professional_data = kwargs.get("professional_data")
        if isinstance(professional_data, str):
            professional_data_section = professional_data.strip()
    evidence_context = _text("evidence_context") or _text("knowledge_context")
    location_evidence = _text("location_evidence")
    upstream_dimensions = _text("upstream_source_dimensions") or (
        "未提供；按已审计 typed facts 的 dimension_key 判断"
    )

    sections = [
        f"【L3 claims-only production pass | dimension_key={dimension_key}】",
        f"项目：{project_name}",
        "本轮只生成可审计的结构化 claims 数组，不生成法定报告正文、Markdown 表格、坐标、BSM、候选几何或调试对象。",
        "旧报告模板中的表格和‘至少列出’不是本轮输出指令；它们不能决定项目数量、地点、面积、长度或容量。",
        "非空间指标可以没有 locator；事实陈述和管理行动也可以没有 locator。空间干预 claim 才需要 typed spatial kind 和对应参数，但它在 L3 不要求已经完成空间锚点或证据闭合。缺少 locator 时仍保留为 spatial_intervention，并由 GROUND 生成待补齐的语义候选和前置任务；只有本身不要求空间成果的内容才使用 action。不得臆造位置。",
        "上游 L1 source dimensions（只作为证据检索范围，不是每条 claim 的必填空间锚点）："
        + upstream_dimensions,
    ]
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
    if revision_instruction:
        sections.insert(0, revision_instruction)
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
