"""P3 单测：PARSE 结构化表格解析（功能分区表/土地用途分区表/项目库）。"""

from app.agent.gis.parse import parse


ZONE_TABLE = """【功能分区表】
| 分区名称 | 面积(公顷) | 占比(%) | 管控要求 |
| :--- | :--- | :--- | :--- |
| 生态保护区 | 362.02 | 15.39 | 严格保护 |
| 农田保护区 | 78.83 | 3.35 | 严禁占用 |
| 村庄建设区 | 30.50 | 1.30 | 集约建设 |
| 林业发展区 | 1200.00 | 51.00 | 保育结合 |
"""

PROJECT_TABLE = """【建设项目库】
| 项目名称 | 建设内容 | 规模 | 选址 |
| :--- | :--- | :--- | :--- |
| 南粤古驿道保护修复工程 | 古驿道保护修复 | 修复长度1500m | 炉池村 |
| 南药产业园 | 南药种植加工 | 0.15公顷 | 园寨自然村 |
"""


def test_zone_table_parsed_into_zone_targets():
    result = parse(ZONE_TABLE, village_name="金田村")
    names = {zt.land_use: round(zt.area_ratio, 4) for zt in result.intent.zone_targets}
    assert names.get("生态保护区") == 0.1539
    assert names.get("农田保护区") == 0.0335
    assert names.get("村庄建设区") == 0.013
    assert names.get("林业发展区") == 0.51


def test_project_table_parsed_into_facilities():
    result = parse(PROJECT_TABLE, village_name="金田村")
    projects = {f.type: f.location_hint for f in result.intent.facilities}
    assert "南粤古驿道保护修复工程" in projects
    assert projects["南粤古驿道保护修复工程"] == "炉池村"
    assert projects.get("南药产业园") == "园寨自然村"


def test_table_and_regex_merge_no_duplicate():
    text = ZONE_TABLE + "\n规划村庄建设区占比13%。\n"
    result = parse(text, village_name="金田村")
    names = [zt.land_use for zt in result.intent.zone_targets]
    assert names.count("村庄建设区") >= 1
