"""模拟Agent通过工具接口调用KG，构建金田村完整空间认知。

模拟方式：Agent 只能通过两个工具与 KG 交互：
  1. build_knowledge_graph  → 构建 KG，返回预计算结果到 state
  2. query_knowledge_graph  → 用 template_name 查询 KG（SPARQL 或语义查询）

Agent 无法直接调用 Python API，只能看到工具返回的 JSON 结果。
"""

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def red(text):
    return f"\033[91m{text}\033[0m"


def green(text):
    return f"\033[92m{text}\033[0m"


def yellow(text):
    return f"\033[93m{text}\033[0m"


def blue(text):
    return f"\033[94m{text}\033[0m"


def bold(text):
    return f"\033[1m{text}\033[0m"


def print_agent_thought(text):
    print(f"\n  {yellow('🤔 Agent 思考:')} {text}")


def print_tool_call(tool, params=""):
    print(f"\n  {blue('🔧 Tool Call:')} {bold(tool)}")
    if params:
        print(f"    {blue('参数:')} {params}")


def print_tool_result(label, data, max_items=5):
    print(f"    {green('← 返回:')} {label}")
    if isinstance(data, list):
        for i, item in enumerate(data):
            if i >= max_items:
                print(f"    {green('  ...')} 还有 {len(data) - max_items} 条")
                break
            line = json.dumps(item, ensure_ascii=False, default=str)
            if len(line) > 130:
                line = line[:130] + "..."
            print(f"    {green('  •')} {line}")
        print(f"    {green('  共')} {len(data)} 条")
    elif isinstance(data, dict):
        for k, v in data.items():
            v_str = json.dumps(v, ensure_ascii=False, default=str) if not isinstance(v, (int, float)) else str(v)
            if len(v_str) > 100:
                v_str = v_str[:100] + "..."
            print(f"    {green('  ')}{k}: {v_str}")
    elif isinstance(data, str):
        for line in data.strip().split("\n"):
            print(f"    {green('  ')}{line}")


def safe_float(val, default=0.0):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def main():
    t0 = time.time()

    print(f"\n{'=' * 72}")
    print(f"  {bold('模拟 Agent 通过工具接口调用 KG 构建金田村空间认知')}")
    print(f"{'=' * 72}")

    # ═══════════════════════════════════════════════════════════════════
    # 阶段 0: 加载数据（Agent 不可见，由工具内部完成）
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'─' * 72}")
    print(f"  {bold('阶段 0: 数据加载（工具内部，Agent 不可见）')}")
    print(f"{'─' * 72}")

    from app.modules.data import DataCatalog
    from app.modules.spatial_ops import build_constraint_index
    from app.modules.spatial_ops.geometry import compute_parcel_relations
    from app.modules.kg.builder import PlanningKG
    from app.modules.kg.queries import query_kg

    catalog = DataCatalog()
    bundle = catalog.load_village_bundle("jintian")
    parcel_relations = compute_parcel_relations(
        bundle.polygons.landuse_current,
        roads=bundle.lines.roads_current,
    )
    constraint_index = build_constraint_index(bundle)
    print(f"  ✓ 地块: {len(bundle.polygons.landuse_current)}")
    print(f"  ✓ 道路: {len(bundle.lines.roads_current)}")
    print(f"  ✓ 设施: {len(bundle.points.facilities_current)}")
    print(f"  ✓ 相邻: {len(parcel_relations.touches)} | 邻近: {len(parcel_relations.nearby)} | 道路连接: {len(parcel_relations.connected)}")

    # ═══════════════════════════════════════════════════════════════════
    # 阶段 1: Agent 调用 build_knowledge_graph
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 72}")
    print(f"  {bold('阶段 1: Agent 调用 build_knowledge_graph')}")
    print(f"{'=' * 72}")

    print_agent_thought("我需要先构建金田村的知识图谱，才能进行后续的空间分析。调用 build_knowledge_graph 工具。")

    print_tool_call("build_knowledge_graph", "(无参数 — 数据从 state 自动注入)")

    kg = PlanningKG(village_name="金田村委会")
    kg.build_from_bundle(bundle=bundle, parcel_relations=parcel_relations, constraint_index=constraint_index)

    print(f"\n  {green('← Tool 返回结果 (写入 state):')}")

    # 模拟 tool 预计算的结果
    state_update = {}
    state_update["triple_count"] = kg.get_triple_count()
    state_update["parcel_count"] = kg.get_parcel_count()
    state_update["constraint_count"] = 0
    try:
        state_update["constraint_count"] = len(kg.get_constraint_coverage()) if kg._constraint_index else 0
    except Exception:
        pass

    # get_adjacency_map
    adj = kg.get_adjacency_map()
    sample_adj = dict(list(adj.items())[:3]) if adj else {}
    print(f"  {green('  kg_adjacency_map:')} {len(adj)} 个地块有相邻关系")
    for bsm, nbrs in sample_adj.items():
        print(f"    {green('  ')}地块 {bsm} → 相邻 {len(nbrs)} 个地块: {list(nbrs)[:5]}")

    # count_by_planning_zone
    zone_stats = query_kg(kg, "count_by_planning_zone")
    print(f"  {green('  kg_count_by_planning_zone:')} {len(zone_stats)} 个分区")
    for z in zone_stats:
        print(f"    {green('  ')}{z.get('planning_zone', '?')}: {z.get('parcel_count', 0)} 地块, {z.get('total_area_ha', 0)} ha")

    # count_by_zone_type
    zt_stats = query_kg(kg, "count_by_zone_type")
    print(f"  {green('  kg_parcel_count_by_zone:')} 地类分布")
    for z in zt_stats:
        print(f"    {green('  ')}{z.get('zone_type', '?')}: {z.get('count', 0)} 地块, {z.get('total_area', 0)} ha")

    # three_zones / three_lines (deprecated templates -> get_constraint_coverage)
    constraint_coverage = kg.get_constraint_coverage()
    print(f"  {green('  kg_constraint_coverage:')} {len(constraint_coverage)} parcels with constraints")

    # village_anchors
    anchors = query_kg(kg, "get_village_anchors")
    print(f"  {green('  kg_village_anchors:')} {len(anchors)} 个锚点")
    for a in anchors[:4]:
        print(f"    {green('  ')}{a.get('name', '')} ({a.get('lon', '')}, {a.get('lat', '')})")
    if len(anchors) > 4:
        print(f"    {green('  ...')} 还有 {len(anchors) - 4} 个")

    # vne_summary
    vne_stats = query_kg(kg, "count_by_vne")
    print(f"  {green('  kg_vne_summary:')} {len(vne_stats)} 个 VNE 类别")

    print(f"\n  {green('← state 更新完成，KG 已就绪。')}")

    # ═══════════════════════════════════════════════════════════════════
    # 阶段 2: Agent 读取 state 中的预计算结果，形成初步认知
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 72}")
    print(f"  {bold('阶段 2: Agent 读取 state 预计算结果 — 初步认知')}")
    print(f"{'=' * 72}")

    print_agent_thought("从 state 中的 kg_parcel_count_by_zone 可以看到金田村的地类分布："
                        "农业用地最多(327块, 1965.92ha)，其次是居住用地(132块, 13.72ha)。"
                        "从 kg_village_anchors 看到有14个居民点。"
                        "让我进一步查询更多细节。")

    # ═══════════════════════════════════════════════════════════════════
    # 阶段 3: Agent 逐层调用 query_knowledge_graph 深入查询
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 72}")
    print(f"  {bold('阶段 3: Agent 逐层调用 query_knowledge_graph — 深入空间认知')}")
    print(f"{'=' * 72}")

    # ── 查询 1: 道路网络 ──
    print_agent_thought("先了解道路网络结构，这对理解村庄空间格局很重要。")
    print_tool_call("query_knowledge_graph", 'template_name="get_road_network"')
    roads = query_kg(kg, "get_road_network")
    road_levels = {}
    for r in roads:
        lv = r.get("road_level", "未知")
        road_levels[lv] = road_levels.get(lv, 0) + 1
    print_tool_result(f"道路网络: {len(roads)} 条道路", roads[:5])
    print(f"    {green('  道路等级分布:')}")
    for lv, cnt in sorted(road_levels.items()):
        print(f"    {green('    ')}{lv}: {cnt} 条")

    total_road_len = sum(safe_float(r.get("length_m", 0)) for r in roads)
    print(f"    {green('  道路总长度:')} {total_road_len:.0f} m")

    # ── 查询 2: 设施分布 ──
    print_agent_thought("了解公共服务设施的分布情况，评估村民生活便利性。")
    print_tool_call("query_knowledge_graph", 'template_name="get_facility_locations"')
    facilities = query_kg(kg, "get_facility_locations")
    fac_types = {}
    for f in facilities:
        ft = f.get("facility_type", "未知") or "未知"
        fac_types[ft] = fac_types.get(ft, 0) + 1
    print_tool_result(f"设施点: {len(facilities)} 个", facilities[:6])
    print(f"    {green('  设施类型分布:')}")
    for ft, cnt in sorted(fac_types.items(), key=lambda x: -x[1]):
        print(f"    {green('    ')}{ft}: {cnt} 个")

    # ── 查询 3: 语义化地块列表 ──
    print_agent_thought("现在获取所有地块的语义化描述，了解总体土地利用格局。")
    print_tool_call("query_knowledge_graph", 'template_name="get_village_parcels"')
    parcels_semantic = query_kg(kg, "get_village_parcels")
    print_tool_result(f"语义化地块列表: {len(parcels_semantic)} 个地块", parcels_semantic[:5])

    # 统计地类名称
    landuse_stats = {}
    for p in parcels_semantic:
        desc = p.get("description", "")
        name_part = desc.split(":")[1].split("(")[0].strip() if ":" in desc else "未知"
        landuse_stats[name_part] = landuse_stats.get(name_part, 0) + 1
    print(f"    {green('  土地利用类型分布:')}")
    for name, cnt in sorted(landuse_stats.items(), key=lambda x: -x[1])[:10]:
        print(f"    {green('    ')}{name}: {cnt} 地块")

    # ── 查询 4: 村庄锚点 ──
    print_agent_thought("查看14个居民点的空间分布，识别村庄聚落格局。")
    print_tool_call("query_knowledge_graph", 'template_name="get_village_anchors"')
    print_tool_result(f"村庄锚点: {len(anchors)} 个", anchors)

    # ── 查询 5: 按地类查询 ──
    print_agent_thought("具体查看居住用地的分布，了解宅基地情况。")
    print_tool_call("query_knowledge_graph", 'template_name="get_parcels_by_zone_type", zone_type="居住用地"')
    residential = query_kg(kg, "get_parcels_by_zone_type", zone_type="居住用地")
    print_tool_result(f"居住用地地块: {len(residential)} 个", residential[:3])

    # ── 查询 6: 相邻关系 ──
    print_agent_thought("查看地块之间的相邻关系，了解空间拓扑结构。")
    print_tool_call("query_knowledge_graph", 'template_name="get_adjacent_parcels"')
    adjacent = query_kg(kg, "get_adjacent_parcels")
    print_tool_result(f"相邻关系对: {len(adjacent)} 对", adjacent[:5])

    # ── 查询 7: 水体 ──
    print_agent_thought("查看村庄水系分布。")
    print_tool_call("query_knowledge_graph", 'template_name="get_water_bodies"')
    waters = query_kg(kg, "get_water_bodies")
    print_tool_result(f"水体: {len(waters)} 个", waters[:5] if waters else [{"info": "无水系数据"}])

    # ── 查询 8: 约束/保护相关 ──
    # 用 get_designated_zones 语义查询（替代已废弃的 get_protected_parcels_detail）
    print_agent_thought("查看看是否有地块受到保护约束。")
    print_tool_call("query_knowledge_graph", 'template_name="get_designated_zones"')
    designated = query_kg(kg, "get_designated_zones")
    print_tool_result(f"受保护约束的地块: {len(designated)} 个", designated[:5])

    # ── 查询 9: 语义化地块详情 ──
    # 取第一个地块查看详情
    first_bsm = parcels_semantic[0].get("bsm", "") if parcels_semantic else ""
    if first_bsm:
        print_agent_thought(f"查看具体地块 {first_bsm} 的详细信息，包括空间关系。")
        print_tool_call("query_knowledge_graph", f'template_name="get_parcel_detail", bsm="{first_bsm}"')
        detail = query_kg(kg, "get_parcel_detail", bsm=first_bsm)
        print_tool_result(f"地块 {first_bsm} 详情", detail)

        print_agent_thought(f"查看地块 {first_bsm} 的相邻地块，了解其周边环境。")
        print_tool_call("query_knowledge_graph", f'template_name="get_parcel_neighbors", bsm="{first_bsm}"')
        neighbors = query_kg(kg, "get_parcel_neighbors", bsm=first_bsm)
        print_tool_result(f"地块 {first_bsm} 的相邻地块", neighbors)

    # ═══════════════════════════════════════════════════════════════════
    # 阶段 4: Agent 整合信息，构建空间认知
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 72}")
    print(f"  {bold('阶段 4: Agent 整合信息 — 空间认知报告')}")
    print(f"{'=' * 72}")

    print_agent_thought("现在我已经收集了足够的信息，可以构建金田村的完整空间认知了。")

    # 计算统计数据
    type_counts = {}
    count_types = query_kg(kg, "count_entity_types")
    for r in count_types:
        t = str(r.get("type", ""))
        if "#" in t:
            t = t.split("#")[-1]
        elif "/" in t:
            t = t.split("/")[-1]
        type_counts[t] = safe_int(r.get("count", 0))

    total_area = sum(safe_float(z.get("total_area_ha", 0)) for z in zone_stats)
    road_len_total = sum(safe_float(r.get("length_m", 0)) for r in roads)

    CONSTRAINT_VIZ = "⚠️ 约束重叠检测未返回数据（ConstraintIndex API 需适配）"
    if designated:
        CONSTRAINT_VIZ = f"⚠️ {len(designated)} 个地块受保护约束"

    print(f"""
  ╔══════════════════════════════════════════════════════════════════════╗
  ║  {bold('金田村 空间认知报告')}                                           ║
  ║  {bold('(Agent 视角 — 仅通过工具调用获得的信息)')}                           ║
  ╚══════════════════════════════════════════════════════════════════════╝

  ┌─ {bold('1. 村庄概况')}
  │   村庄: 金田村委会 (平远县泗水镇)
  │   知识图谱规模: {kg.get_triple_count()} 个三元组
  │   总面积: {total_area:.2f} ha
  │
  ├─ {bold('2. 实体统计 (来自 count_entity_types)')}
  │   ├─ 地块 (Parcel):              {type_counts.get('Parcel', 0):>4d} 个
  │   ├─ 道路 (Road):                {type_counts.get('Road', 0):>4d} 条 (总长约 {road_len_total:.0f} m)
  │   ├─ 设施 (Facility):            {type_counts.get('Facility', 0):>4d} 个
  │   ├─ 居民点 (ResidentialCluster): {type_counts.get('ResidentialCluster', 0):>4d} 个
  │   ├─ 控制线 (ControlLine):        {type_counts.get('ControlLine', 0):>4d} 条
  │   └─ 行政村 (AdministrativeVillage): 1 个
  │
  ├─ {bold('3. 空间关系 (来自 build_knowledge_graph 预计算)')}
  │   ├─ touches (相邻):            {len(parcel_relations.touches):>4d} 对
  │   ├─ nearby (邻近):             {len(parcel_relations.nearby):>4d} 对
  │   └─ connected_via_road (道路连接): {len(parcel_relations.connected):>4d} 对
  │
  ├─ {bold('4. 地类分布 (来自 kg_parcel_count_by_zone)')}
""")
    for z in zt_stats:
        area_val = safe_float(z.get("total_area", 0))
        pct = area_val / total_area * 100 if total_area > 0 else 0
        print(f"  │    {str(z.get('zone_type', '?')):12s}: {safe_int(z.get('count', 0)):>4d} 地块, {area_val:>8.2f} ha ({pct:5.1f}%)")

    print(f"""  │
  ├─ {bold('5. 道路网络 (来自 get_road_network)')}
  │   道路等级分布:""")
    for lv, cnt in sorted(road_levels.items()):
        print(f"  │     {lv}: {cnt} 条")
    print(f"  │     总长度: {road_len_total:.0f} m")

    print(f"""  │
  ├─ {bold('6. 设施分布 (来自 get_facility_locations)')}""")
    for ft, cnt in sorted(fac_types.items(), key=lambda x: -x[1]):
        print(f"  │     {ft}: {cnt} 个")
    print(f"  │     总计: {len(facilities)} 个设施点")

    pcount = type_counts.get('Parcel', 0)
    print(f"""  │
  ├─ {bold('7. 居民点分布 (来自 kg_village_anchors)')}
  │     共 {len(anchors)} 个自然村/居民点""")
    for a in anchors:
        print(f"  │     {a.get('name', '')} ({a.get('lon', '')}, {a.get('lat', '')})")

    print(f"""  │
  ├─ {bold('8. 约束与保护')}
  │     {CONSTRAINT_VIZ}
  │
  └─ {bold('9. Agent 认知结论')}
     金田村是典型的粤东北山区村庄，以农业用地为主（{safe_int(zt_stats[0].get('count', 0))}块, {safe_float(zt_stats[0].get('total_area', 0)):.2f}ha），
     居住用地集中分布在{len(anchors)}个居民点中。道路网络以村道为主（{len(roads)}条, {road_len_total:.0f}m），
     基本覆盖各居民点。公共服务设施（{len(facilities)}个）包括卫生站、篮球场、公交站等，
     但缺乏教育、医疗等高级别设施。地块之间空间关系紧密（{len(parcel_relations.touches)}对相邻,
     {len(parcel_relations.connected)}对道路连接），具备良好的路网连通性。

  ╔══════════════════════════════════════════════════════════════════════╗
  ║  {green('✅ Agent 空间认知构建完成')}                                      ║
  ║  {green(f'   共调用 1 次 build_knowledge_graph + 9 次 query_knowledge_graph')}   ║
  ║  {green(f'   获取了 {pcount} 个地块, {len(roads)} 条道路, {len(facilities)} 个设施的信息')}     ║
  ╚══════════════════════════════════════════════════════════════════════╝
""")

    elapsed = time.time() - t0
    print(f"  {bold('模拟耗时:')} {elapsed:.2f}s")
    print(f"  {bold('总工具调用次数:')} 10 次 (1 build + 9 query)")
    print()


if __name__ == "__main__":
    main()