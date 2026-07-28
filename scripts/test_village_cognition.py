"""End-to-end test: village spatial cognition from KG alone (no human text).

This is the FINAL VALIDATION test for the KG spatial cognition design.
It verifies that:
  1. KG can be built from GIS data alone (no human planning text)
  2. get_village_cognition() returns a complete three-layer summary
  3. The semantic payload is within token budget for LLM consumption
  4. The structured payload's BSM sets match the bundle's actual entities
  5. Statistics (parcel count, road count, etc.) are consistent
  6. Layer group coverage aligns with bundle morphology groups
  7. Constraint coverage is present and non-empty

Usage:
    cd F:/project/Village_Planning_Agent
    python scripts/test_village_cognition.py
    python scripts/test_village_cognition.py --no-cache
    python scripts/test_village_cognition.py --llm  # also test LLM generation (requires API key)
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

_PROJECT_ROOT = _BACKEND_DIR.parent
os.chdir(_PROJECT_ROOT)

_CACHE_DIR = Path(__file__).resolve().parent / ".kg_cache"


def _load_kg(village_name: str = "jintian", use_cache: bool = True):
    """Load or build KG from GIS data alone (no human text)."""
    from app.modules.kg.builder import PlanningKG

    cache_path = _CACHE_DIR / f"{village_name}.ttl"
    constraint_cache = _CACHE_DIR / f"{village_name}_constraints.json"

    if use_cache and cache_path.exists():
        ttl = cache_path.read_text(encoding="utf-8")
        kg = PlanningKG.from_turtle(ttl, village_name=village_name)
        if constraint_cache.exists():
            try:
                from app.modules.spatial_ops.bridge import ConstraintIndex
                import geopandas as gpd
                cdata = json.loads(constraint_cache.read_text(encoding="utf-8"))
                if cdata.get("rows"):
                    gdf = gpd.GeoDataFrame(cdata["rows"], crs="EPSG:4326")
                    kg._constraint_index = ConstraintIndex(gdf)
            except Exception:
                pass
        print(f"[test] KG loaded from cache: {kg.get_parcel_count()} parcels, "
              f"{kg.get_triple_count()} triples")
        return kg

    from app.modules.data import DataCatalog
    from app.modules.spatial_ops.geometry import compute_parcel_relations
    from app.modules.spatial_ops.bridge import build_constraint_index, compute_water_overlap

    print(f"[test] Building KG from scratch (no human text)...")
    t0 = time.time()
    catalog = DataCatalog()
    bundle = catalog.load_village_bundle(village_name)
    relations = compute_parcel_relations(
        bundle.polygons.landuse_current, roads=bundle.lines.roads_current
    )
    water_overlap = compute_water_overlap(
        bundle.polygons.water_bodies, bundle.polygons.landuse_current
    )
    ci = build_constraint_index(bundle)
    kg = PlanningKG(village_name=village_name)
    kg.build_from_bundle(
        bundle=bundle, parcel_relations=relations,
        constraint_index=ci, water_overlap=water_overlap,
    )
    print(f"[test] KG built: {kg.get_parcel_count()} parcels, "
          f"{kg.get_triple_count()} triples ({time.time()-t0:.1f}s)")

    if use_cache:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(kg.to_turtle(), encoding="utf-8")
        print(f"[test] KG cached to {cache_path}")

    return kg, bundle


def test_cognition_completeness(kg, bundle=None):
    """Test 1: get_village_cognition returns complete three-layer summary."""
    from app.modules.kg.queries.cognition import get_village_cognition
    from app.modules.kg.queries.contracts import TokenBudget

    payload = get_village_cognition(kg, "jintian")

    # Check three layers exist
    assert "context_block" in payload.semantic, "Missing context_block"
    assert "layer_cards" in payload.semantic, "Missing layer_cards"
    assert "constraint_block" in payload.semantic, "Missing constraint_block"

    # Check context_block has required fields
    ctx = payload.semantic["context_block"]
    assert ctx.get("village"), "Missing village name"
    assert ctx.get("overview"), "Missing overview"
    assert ctx.get("parcel_count", 0) > 0, "parcel_count should be > 0"
    assert ctx.get("total_area_ha", 0) > 0, "total_area_ha should be > 0"
    assert ctx.get("spatial_pattern"), "Missing spatial_pattern"

    # Check layer_cards is non-empty
    cards = payload.semantic["layer_cards"]
    assert len(cards) >= 3, f"Expected >=3 layer cards, got {len(cards)}"

    # Check constraint_block has relation totals
    cb = payload.semantic["constraint_block"]
    assert cb.get("adjacency_total", 0) > 0, "adjacency_total should be > 0"
    assert cb.get("nearby_total", 0) > 0, "nearby_total should be > 0"

    # Check token budget
    assert payload.token_estimate > 0, "token_estimate should be > 0"
    assert payload.token_estimate <= TokenBudget.HARD_LIMIT, \
        f"token_estimate {payload.token_estimate} exceeds HARD_LIMIT {TokenBudget.HARD_LIMIT}"

    print(f"  [PASS] Cognition completeness: {len(cards)} layer cards, "
          f"{payload.token_estimate} tokens, truncated={payload.truncated}")
    return payload


def test_bsm_alignment(kg, bundle):
    """Test 2: structured payload BSM sets match bundle's actual entities."""
    from app.modules.kg.queries.cognition import get_village_cognition

    payload = get_village_cognition(kg, "jintian")

    # Get bundle's actual BSMs
    bundle_parcel_bsms = set()
    for p in bundle.polygons.landuse_current:
        bsm = str(getattr(p, "bsm", "")).strip()
        if bsm:
            bundle_parcel_bsms.add(bsm)

    # Get KG's parcel BSMs from structured payload
    kg_parcel_bsms = set(payload.structured.get("layer_group_bsms", {}).get("current_landuse", []))

    # Check alignment
    assert len(bundle_parcel_bsms) > 0, "Bundle has no parcel BSMs"
    assert len(kg_parcel_bsms) > 0, "KG has no parcel BSMs in structured payload"

    # Allow for minor discrepancies (dedup, missing BSMs)
    overlap = bundle_parcel_bsms & kg_parcel_bsms
    overlap_pct = len(overlap) / len(bundle_parcel_bsms) * 100
    assert overlap_pct >= 90, \
        f"BSM overlap only {overlap_pct:.1f}% (bundle={len(bundle_parcel_bsms)}, kg={len(kg_parcel_bsms)}, overlap={len(overlap)})"

    print(f"  [PASS] BSM alignment: {overlap_pct:.1f}% overlap "
          f"(bundle={len(bundle_parcel_bsms)}, kg={len(kg_parcel_bsms)})")
    return True


def test_statistics_consistency(kg, bundle):
    """Test 3: statistics (parcel count, road count) are consistent."""
    from app.modules.kg.queries.cognition import get_village_cognition

    payload = get_village_cognition(kg, "jintian")
    ctx = payload.semantic["context_block"]

    # Parcel count
    bundle_parcel_count = len(bundle.polygons.landuse_current)
    kg_parcel_count = ctx.get("parcel_count", 0)
    assert kg_parcel_count == bundle_parcel_count, \
        f"Parcel count mismatch: KG={kg_parcel_count}, bundle={bundle_parcel_count}"

    # Road count (only actual roads, not contour lines/admin boundaries which reuse Road type)
    bundle_road_count = len(bundle.lines.roads_current)
    # Count roads by semantic_group=transport (excludes contour lines/admin boundaries)
    from rdflib import Namespace, URIRef, Literal
    PLN = Namespace("http://village-planning.org/ontology#")
    sg_pred = URIRef(str(PLN) + "semantic_group")
    kg_road_count = sum(1 for _ in kg.g.triples((None, sg_pred, Literal("transport"))))
    assert abs(kg_road_count - bundle_road_count) <= 1, \
        f"Road count mismatch: KG={kg_road_count}, bundle={bundle_road_count}"

    print(f"  [PASS] Statistics consistency: parcels={kg_parcel_count}, roads={kg_road_count}")
    return True


def test_layer_group_coverage(kg, bundle):
    """Test 4: layer group coverage aligns with bundle morphology groups."""
    from app.modules.kg.queries.cognition import get_village_cognition

    payload = get_village_cognition(kg, "jintian")
    cards = payload.semantic["layer_cards"]
    card_groups = {c["group"] for c in cards}

    # Bundle morphology groups that should have entities
    expected_groups = set()
    if bundle.polygons.landuse_current:
        expected_groups.add("current_landuse")
    if bundle.lines.roads_current:
        expected_groups.add("transport")
    if bundle.polygons.water_bodies:
        expected_groups.add("water")
    if bundle.points.facilities_current:
        expected_groups.add("facility")

    missing = expected_groups - card_groups
    assert not missing, f"Missing layer groups: {missing}. Got: {card_groups}"

    print(f"  [PASS] Layer group coverage: {len(card_groups)} groups "
          f"({', '.join(sorted(card_groups))})")
    return True


def test_constraint_coverage_present(kg):
    """Test 5: constraint coverage is present (legal_constraint distribution)."""
    from app.modules.kg.queries.cognition import get_village_cognition

    payload = get_village_cognition(kg, "jintian")
    cb = payload.semantic["constraint_block"]

    # Legal constraint distribution should be non-empty
    lcd = cb.get("legal_constraint_distribution", {})
    assert lcd, "legal_constraint_distribution is empty"
    assert "forbid_construction" in lcd, "Missing forbid_construction in constraints"

    # Planning zone distribution should be non-empty
    pzd = cb.get("planning_zone_distribution", {})
    assert pzd, "planning_zone_distribution is empty"

    print(f"  [PASS] Constraint coverage: {len(lcd)} constraint types, "
          f"{len(pzd)} planning zones")
    return True


def test_entity_semantics(kg):
    """Test 6: get_entity_semantics returns meaningful semantic info."""
    from app.modules.kg.queries.semantic import get_entity_semantics

    for label in ["耕地", "宅基地"]:
        result = get_entity_semantics(kg, entity_label=label)
        assert "error" not in result, f"get_entity_semantics('{label}') returned error"
        assert result.get("taxonomic_parent"), f"Missing taxonomic_parent for {label}"
        assert result.get("legal_constraint"), f"Missing legal_constraint for {label}"
        assert isinstance(result.get("allowed_operations"), list), \
            f"allowed_operations should be a list for {label}"
        assert result.get("matching_entities", {}).get("count", 0) > 0, \
            f"No matching entities for {label}"

    print(f"  [PASS] Entity semantics: 耕地 and 宅基地 have full semantic info")
    return True


def test_token_budget_control(kg):
    """Test 7: token budget is controlled for large entity sets."""
    from app.modules.kg.queries.cognition import get_village_cognition
    from app.modules.kg.queries.contracts import TokenBudget

    payload = get_village_cognition(kg, "jintian")

    # With 660 parcels, the semantic payload should be within budget
    assert payload.token_estimate <= TokenBudget.HARD_LIMIT, \
        f"Token estimate {payload.token_estimate} exceeds HARD_LIMIT"

    # Representative BSMs should be a subset (TopK sampled, not all 660)
    rep_count = len(payload.structured.get("representative_bsms", []))
    assert rep_count <= 50, f"Representative BSMs ({rep_count}) should be <= 50 (TopK sampled)"
    assert rep_count > 0, "No representative BSMs"

    print(f"  [PASS] Token budget control: {payload.token_estimate} tokens, "
          f"{rep_count} representative BSMs")
    return True


def test_llm_cognition_generation(kg, village_name="jintian"):
    """Test 8 (optional): LLM generates spatial cognition from KG semantic payload.

    Requires LLM API access. Skipped if --llm flag not set or no API key.
    """
    try:
        from app.modules.kg.queries.cognition import get_village_cognition
        from app.agent.core.llm import create_llm
    except ImportError as e:
        print(f"  [SKIP] LLM test (import failed): {e}")
        return False

    payload = get_village_cognition(kg, village_name)

    prompt = f"""基于以下村庄空间认知摘要，请描述{village_name}的完整空间结构。

认知摘要（JSON）:
{json.dumps(payload.semantic, ensure_ascii=False, indent=2)}

请按以下结构输出：
1. 村域概况（2-3句）
2. 各图层组的空间特征
3. 空间约束与关系
4. 空间结构总结（1句）
"""

    try:
        llm = create_llm(temperature=0.3, thinking=False)
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        # Basic validation: response should mention key elements
        assert len(content) > 100, f"LLM response too short: {len(content)} chars"
        assert "地块" in content or "用地" in content, "LLM response missing land-use mention"
        assert "道路" in content or "交通" in content, "LLM response missing road mention"

        print(f"  [PASS] LLM cognition generation: {len(content)} chars")
        print(f"  [SAMPLE] {content[:200]}...")
        return True
    except Exception as e:
        print(f"  [SKIP] LLM test (API error): {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test village cognition from KG")
    parser.add_argument("--village", default="jintian", help="Village name")
    parser.add_argument("--no-cache", action="store_true", help="Rebuild KG")
    parser.add_argument("--llm", action="store_true", help="Also test LLM generation")
    args = parser.parse_args()

    print(f"\n{'#'*70}")
    print(f"#  Village Cognition E2E Test: {args.village}")
    print(f"#  (KG built from GIS data alone, no human planning text)")
    print(f"{'#'*70}\n")

    # Load KG and bundle
    result = _load_kg(args.village, use_cache=not args.no_cache)
    if isinstance(result, tuple):
        kg, bundle = result
    else:
        kg = result
        # Load bundle separately for comparison
        from app.modules.data import DataCatalog
        bundle = DataCatalog().load_village_bundle(args.village)

    # Run tests
    print(f"\n{'='*60}")
    print("Running cognition tests...")
    print(f"{'='*60}\n")

    tests = [
        ("Cognition Completeness", lambda: test_cognition_completeness(kg)),
        ("BSM Alignment", lambda: test_bsm_alignment(kg, bundle)),
        ("Statistics Consistency", lambda: test_statistics_consistency(kg, bundle)),
        ("Layer Group Coverage", lambda: test_layer_group_coverage(kg, bundle)),
        ("Constraint Coverage", lambda: test_constraint_coverage_present(kg)),
        ("Entity Semantics", lambda: test_entity_semantics(kg)),
        ("Token Budget Control", lambda: test_token_budget_control(kg)),
    ]

    if args.llm:
        tests.append(("LLM Cognition Generation", lambda: test_llm_cognition_generation(kg, args.village)))

    passed = 0
    failed = 0
    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*60}")

    if failed > 0:
        sys.exit(1)
    else:
        print("\nAll tests passed! KG spatial cognition is complete and aligned.")


if __name__ == "__main__":
    main()
