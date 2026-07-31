import sys
sys.path.insert(0, '.')
from scripts.kg_validation.kg_tool_cli import get_cached_kg, _run_tool
from app.modules.kg.ontology import PLN

kg = get_cached_kg()

# F01: Total area
rows = list(kg.g.query('PREFIX pln: <http://village-planning.org/ontology#> SELECT (SUM(?a) as ?t) WHERE { ?p a pln:Parcel ; pln:area_ha ?a . }'))
print(f'F01 Total area: {float(rows[0][0]):.2f} ha  (expected 2352.89)')

# F02: Agricultural land (dlbm 01/02/03)
rows = list(kg.g.query('''
PREFIX pln: <http://village-planning.org/ontology#>
SELECT (SUM(?a) as ?t) WHERE {
  ?p a pln:Parcel ; pln:dlbm ?dlbm ; pln:area_ha ?a .
  FILTER(STRSTARTS(?dlbm, "01") || STRSTARTS(?dlbm, "02") || STRSTARTS(?dlbm, "03"))
}'''))
print(f'F02 Agri area: {float(rows[0][0]):.2f} ha  (expected 1960.70)')

# F03: Construction land (dlbm 07)
rows = list(kg.g.query('''
PREFIX pln: <http://village-planning.org/ontology#>
SELECT (SUM(?a) as ?t) WHERE {
  ?p a pln:Parcel ; pln:dlbm ?dlbm ; pln:area_ha ?a .
  FILTER(STRSTARTS(?dlbm, "07"))
}'''))
print(f'F03 Construction area: {float(rows[0][0]):.2f} ha  (expected 30.17)')

# F08: Buildings (dlbm 07 count)
rows = list(kg.g.query('PREFIX pln: <http://village-planning.org/ontology#> SELECT (COUNT(?p) as ?c) WHERE { ?p a pln:Parcel ; pln:dlbm ?dlbm . FILTER(STRSTARTS(?dlbm, "07")) }'))
print(f'F08 Buildings: {rows[0][0]}  (expected 583)')

# Facilities
r = _run_tool('get_facilities_semantic_list', [])
items = r['result'].get('items', r['result']) if isinstance(r['result'], dict) else r['result']

squares = [i for i in items if '广场' in str(i)]
print(f'F18 Cultural squares: {len(squares)}  (expected 2)')

courts = [i for i in items if '篮球' in str(i)]
print(f'F19 Basketball: {len(courts)}  (expected 1)')

halls = [i for i in items if '祠' in str(i)]
print(f'F20 Ancestral halls: {len(halls)}  (expected 3)')

trans = [i for i in items if '变压' in str(i)]
print(f'F21 Transformers: {len(trans)}  (expected 9)')

buses = [i for i in items if '公交' in str(i)]
print(f'F15 Bus stops: {len(buses)}  (expected 3)')

parks = [i for i in items if '停车' in str(i)]
print(f'F17 Parking: {len(parks)}  (expected 1)')

# Roads
r2 = _run_tool('get_road_network_semantic', [])
roads = r2['result'].get('items', r2['result']) if isinstance(r2['result'], dict) else r2['result']
levels = {}
for ro in roads:
    lvl = ro.get('road_level', '未知')
    levels[lvl] = levels.get(lvl, 0) + 1
print(f'Road levels: {levels}')
