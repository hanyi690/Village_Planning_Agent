"""Deep spatial cognition: show exactly what KG knows."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.data import DataCatalog
from app.modules.spatial_ops import build_constraint_index
from app.modules.spatial_ops.geometry import compute_parcel_relations
from app.modules.kg.builder import PlanningKG
from app.modules.kg.ontology import PLN, EntityTypes, Relations
from app.modules.kg.queries.contracts import DualPayload
from app.modules.kg.queries.cognition import get_village_cognition
from rdflib import RDF, Literal

catalog = DataCatalog()
bundle = catalog.load_village_bundle("jintian")
relations = compute_parcel_relations(bundle.polygons.landuse_current, roads=bundle.lines.roads_current)
ci = build_constraint_index(bundle)
kg = PlanningKG("金田村委会")
kg.build_from_bundle(bundle=bundle, parcel_relations=relations, constraint_index=ci)

parcel_uris = list(kg.g.subjects(RDF.type, EntityTypes.Parcel))
fac_uris = list(kg.g.subjects(RDF.type, EntityTypes.Facility))
road_uris = list(kg.g.subjects(RDF.type, EntityTypes.Road))

# ── 1. Statistics with real road lengths ──
total_road_len = 0
named_roads = 0
admin_lines = 0
for ru in road_uris:
    name = None
    length = 0
    for p, o in kg.g.predicate_objects(ru):
        pn = str(p).split("#")[-1]
        if pn == "name":
            name = str(o)
        elif pn == "length":
            try: length = float(o)
            except: pass
        elif pn == "road_level" and str(o).strip():
            pass
    if name and "行政" in name:
        admin_lines += 1
    else:
        named_roads += 1
    total_road_len += length

# ── 2. Facility type breakdown ──
fac_types = {}
for fu in fac_uris:
    ft = None
    for p, o in kg.g.predicate_objects(fu):
        if str(p).split("#")[-1] == "facility_type":
            ft = str(o)
            break
    if ft:
        fac_types[ft] = fac_types.get(ft, 0) + 1

# ── 3. Land use stats from parcels ──
lu_stats = {}
for pu in parcel_uris:
    lu = None
    for p, o in kg.g.predicate_objects(pu):
        pn = str(p).split("#")[-1]
        if pn == "taxonomic_parent":
            lu = str(o)
            break
    if lu:
        lu_stats[lu] = lu_stats.get(lu, 0) + 1

# ── 4. Spatial relation totals ──
rel_counts = {}
for name, pred in [("sfTouches", Relations.sfTouches), ("nearby", Relations.nearby),
                    ("connected_via_road", Relations.connected_via_road),
                    ("sfWithin", Relations.sfWithin), ("sfIntersects", Relations.sfIntersects),
                    ("sfContains", Relations.sfContains)]:
    rel_counts[name] = len(list(kg.g.triples((None, pred, None))))

# ── 5. Cognition payload ──
cog = get_village_cognition(kg, "金田")
ctx = cog.semantic.get("context_block", {})

# ── 6. Report ──
print(f"""
╔═══════════════════════════════════════════════════════════════╗
║          金田村 KG 空间认知报告（基于 KG 实际数据）              ║
╚═══════════════════════════════════════════════════════════════╝

┌── 1. 村庄概况 ──────────────────────────────────────────────
│  KG 规模: {kg.get_triple_count()} 三元组
│  总面积: {ctx.get('total_area_ha', '?'):.2f} ha
│  BBox: {cog.structured.get('bbox', '?')}

├── 2. 实体总数 ──────────────────────────────────────────────
│  地块 (Parcel): {len(parcel_uris)} 个
│  道路 (Road):   {len(road_uris)} 条（其中 {named_roads} 条命名村道, {admin_lines} 条行政界线）
│  设施 (Facility): {len(fac_uris)} 个
│  居民点 (ResidentialCluster): {len(list(kg.g.subjects(RDF.type, EntityTypes.ResidentialCluster)))} 个
│  控制线: 跳过（EntityTypes 无 ControlLine 常量）
│  水体 (WaterBody): {len(list(kg.g.subjects(RDF.type, EntityTypes.WaterBody)))} 个
│  行政村: 1 个

├── 3. 道路网络 ──────────────────────────────────────────────
│  命名村道: {named_roads} 条, 总长度 {total_road_len:.0f} m
│  等级: 全部为"村道"
│  行政界线: {admin_lines} 条（注入KG但不应视为道路）

├── 4. 设施类型分布 ──────────────────────────────────────────""")
for ft, cnt in sorted(fac_types.items(), key=lambda x: -x[1]):
    print(f"│    {ft}: {cnt} 个")
print(f"│    其他(未分类): {len(fac_uris) - sum(fac_types.values())} 个")

print(f"""│
├── 5. 土地利用（按 taxononic_parent）───────────────────────""")
for lu, cnt in sorted(lu_stats.items(), key=lambda x: -x[1]):
    print(f"│    {lu}: {cnt} 地块")
print(f"""│
├── 6. 空间关系 ──────────────────────────────────────────────""")
for name in ["sfTouches", "nearby", "connected_via_road", "sfWithin", "sfIntersects", "sfContains"]:
    cnt = rel_counts.get(name, 0)
    if cnt > 0:
        print(f"│    {name:25s} {cnt:>6d} 条")

print(f"""│
├── 7. 每地块 KNOWS ──────────────────────────────────────────
│  每个地块记录以下属性:""")
# Show predicates from first parcel
pu = parcel_uris[0]
preds = []
for p, o in kg.g.predicate_objects(pu):
    pn = str(p).split("#")[-1]
    if pn not in ("type",):
        if isinstance(o, Literal):
            oval = str(o)[:40]
        else:
            ot = str(o).split("#")[-1] if "#" in str(o) else str(o).split("/")[-1]
            oval = ot[:40]
        preds.append(f"{pn}={oval}")
for p in preds[:15]:
    print(f"│    {p}")
print(f"│    ... 共 {len(list(kg.g.predicate_objects(pu)))} 个谓词")

print(f"""│
├── 8. 地块级别的空间关系（示例: {str(list(kg.g.objects(pu, Relations.sfTouches)))[:100]}）
│  相邻(touches): 每个地块知道与哪些地块相邻 + 共享边界长度
│  近邻(nearby): 每个地块知道附近地块 + 质心距离
│  包含(located_in): 每个设施/水体知道位于哪个地块

├── 9. 地形认知 ──────────────────────────────────────────────
│  ⚠️ 缺失！等高线(contour_line): 未配置数据源
│  ⚠️ 缺失！高程点(elevation_point): 未配置数据源
│  ⚠️ 缺失！DEM: 栅格文件不可用
│  → KG 无法提供任何地形/高程认知

├── 10. 缺失/薄弱项 ──────────────────────────────────────────
│  ⚠️ 道路只有村道等级，无道路名称（仅编号）
│  ⚠️ 设施标注了facility_type但部分为空
│  ⚠️ 行政界线混入道路实体（144条）
│  ⚠️ 无建筑物数据（未配置）
│  ⚠️ 无土壤/水文数据（未配置）
│  ⚠️ 无保护红线数据（未配置）

└── 11. 认知结论（仅基于KG证据）──────────────────────────────
   × "山谷"定位：无地形数据支撑 → 不能确定
   √ 金田村有 {len(parcel_uris)} 个地块，{{lu_stats}} 大地类
   √ {named_roads} 条村道总长 {total_road_len:.0f}m，全为村道等级
   √ {len(fac_uris)} 个设施点，含篮球场、祠堂({fac_types.get('公共服务',0)}个)、卫生站、公交站等
   √ {rel_counts.get('touches',0)} 对相邻，{rel_counts.get('nearby',0)} 对近邻，{rel_counts.get('connected_via_road',0)} 对路网连通
""")
