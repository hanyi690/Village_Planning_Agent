"""Village cognition aggregation queries — GIS-layer cognition summary.

[v4.8] Provides get_village_cognition() returning a DualPayload with:
  - context_block: village overview (name, area, spatial pattern)
  - layer_cards[]: per GisLayerSet entity card (group/geometry/count/dominant/distribution)
  - constraint_block: spatial relation totals + constraint coverage summary

This is the semantic aggregation layer (from RDF triples). Geometric computations
(clustering, overlap BSM lists) remain in app.spatial.query.context per the data
boundary: spatial geometry = geometry authority, KG = semantic authority.

Usage:
    from app.infrastructure.kg.queries.cognition import get_village_cognition
    payload = get_village_cognition(kg, "jintian")
    print(payload.semantic["context_block"]["overview"])
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from rdflib import RDF, Literal, URIRef

from app.utils.logger import get_logger
from ..ontology import (
    PLN, EntityTypes, Relations, SemanticPredicates, GeoPredicates,
    GEOMETRY_POLYGON,
)
from ..builder.geo_helpers import parse_wkt_bbox

# Predicate shortcuts (from SemanticPredicates)
gis_type_ref = SemanticPredicates.gis_type_ref
geometry_kind = SemanticPredicates.geometry_kind
semantic_group = SemanticPredicates.semantic_group
has_semantic_label = SemanticPredicates.has_semantic_label
contains_entity = SemanticPredicates.contains_entity
gis_description = SemanticPredicates.gis_description
entity_count = SemanticPredicates.entity_count
dominant_label = SemanticPredicates.dominant_label
taxonomic_parent = SemanticPredicates.taxonomic_parent
legal_constraint = SemanticPredicates.legal_constraint
allowed_operations = SemanticPredicates.allowed_operations
from .contracts import DualPayload, TokenBudget, TopKSampler

logger = get_logger(__name__)

PLN_NS = "http://village-planning.org/ontology#"


def _pred_name(p: Any) -> str:
    s = str(p)
    if "#" in s:
        return s.split("#")[-1]
    return s.split("/")[-1]


def _obj_name(o: Any) -> str:
    s = str(o)
    if s.startswith("http://") or s.startswith("https://"):
        if "#" in s:
            return s.split("#")[-1]
        return s.split("/")[-1]
    return s


def _to_uri(uri_or_str: str) -> Optional[URIRef]:
    if not uri_or_str:
        return None
    if isinstance(uri_or_str, URIRef):
        return uri_or_str
    if uri_or_str.startswith("pln:"):
        return URIRef(PLN_NS + uri_or_str[4:])
    if uri_or_str.startswith("http"):
        return URIRef(uri_or_str)
    return URIRef(PLN_NS + uri_or_str)


# ============================================================
# get_village_cognition - main entry point
# ============================================================

def get_village_cognition(
    kg,
    village_name: str = "",
    mode: str = "full",
    token_budget: int = TokenBudget.SOFT_LIMIT,
) -> DualPayload:
    """Build a three-layer cognition summary of the village from KG.

    Args:
        kg: PlanningKG instance (must have L1 built).
        village_name: village name (optional, read from KG if empty).
        mode: "full" = complete three-layer summary;
              "context_block" = only context_block (for ContextBlock generation);
              "layer_cards" = only layer_cards;
              "constraint_block" = only constraint_block.
        token_budget: soft token limit for the semantic payload.

    Returns:
        DualPayload with semantic (three-layer) + structured (BSM lists, bbox).
    """
    try:
        context_block = _build_context_block(kg, village_name)
        layer_cards = _build_layer_cards(kg)
        constraint_block = _build_constraint_block(kg)
        structured = _build_structured_payload(kg, layer_cards)

        # Assemble semantic payload based on mode
        semantic: Dict[str, Any] = {}
        if mode in ("full", "context_block"):
            semantic["context_block"] = context_block
        if mode in ("full", "layer_cards"):
            semantic["layer_cards"] = layer_cards
        if mode in ("full", "constraint_block"):
            semantic["constraint_block"] = constraint_block

        token_est = TokenBudget.estimate_dict(semantic)
        truncated = token_est > token_budget

        # If truncated and layer_cards is too large, apply TopK sampling
        if truncated and "layer_cards" in semantic:
            # Trim layer_cards to top groups by entity count
            sorted_cards = sorted(
                semantic["layer_cards"],
                key=lambda c: c.get("count", 0),
                reverse=True,
            )
            # Keep top 5 groups, summarize the rest
            if len(sorted_cards) > 5:
                top5 = sorted_cards[:5]
                rest_count = sum(c.get("count", 0) for c in sorted_cards[5:])
                top5.append({
                    "group": "_other",
                    "geometry": "mixed",
                    "count": rest_count,
                    "dominant_label": f"其余{len(sorted_cards)-5}个图层组",
                    "distribution": "",
                })
                semantic["layer_cards"] = top5
                token_est = TokenBudget.estimate_dict(semantic)

        return DualPayload(
            semantic=semantic,
            structured=structured,
            token_estimate=token_est,
            truncated=truncated or token_est > token_budget,
            next_cursor=structured.get("next_cursor"),
        )
    except Exception as e:
        logger.error("get_village_cognition failed: %s", e)
        return DualPayload(
            semantic={"error": str(e)},
            structured={},
            token_estimate=0,
        )


# ============================================================
# Layer 1: context_block (village overview)
# ============================================================

def _build_context_block(kg, village_name: str) -> Dict[str, Any]:
    """Build village-level overview: name, area, parcel count, spatial pattern."""
    # Village name
    v_uri = URIRef(PLN_NS + "village")
    name = village_name
    if not name:
        for _, _, o in kg.g.triples((v_uri, PLN.name, None)):
            name = str(o)
            break
    if not name:
        name = "未知村庄"

    # Parcel count
    parcel_count = sum(1 for _ in kg.g.subjects(RDF.type, EntityTypes.Parcel))

    # Total area (sum of parcel areas)
    total_area_ha = 0.0
    for s in kg.g.subjects(RDF.type, EntityTypes.Parcel):
        for _, _, o in kg.g.triples((s, PLN.area_ha, None)):
            try:
                total_area_ha += float(o)
            except (ValueError, TypeError):
                pass
    total_area_ha = round(total_area_ha, 2)

    # BBox
    bbox = None
    bbox_geom = kg.g.value(v_uri, GeoPredicates.hasBoundingBox)
    if bbox_geom:
        wkt_lit = kg.g.value(bbox_geom, GeoPredicates.asWKT)
        if wkt_lit:
            bbox = parse_wkt_bbox(str(wkt_lit))

    # Spatial pattern (derived from residential cluster distribution)
    spatial_pattern = _derive_spatial_pattern(kg)

    # Entity counts by type
    entity_counts: Dict[str, int] = {}
    for s, _, o in kg.g.triples((None, RDF.type, None)):
        t = _obj_name(o)
        if t in ("LayerGroup",):
            continue
        entity_counts[t] = entity_counts.get(t, 0) + 1

    overview = (
        f"{name}，总面积{total_area_ha}公顷，"
        f"共{parcel_count}个地块，"
        f"{entity_counts.get('Road', 0)}条道路，"
        f"{entity_counts.get('Facility', 0)}个设施，"
        f"{entity_counts.get('WaterBody', 0)}处水域。"
    )

    return {
        "village": name,
        "overview": overview,
        "spatial_pattern": spatial_pattern,
        "total_area_ha": total_area_ha,
        "parcel_count": parcel_count,
        "entity_counts": entity_counts,
        "bbox": bbox,
    }


def _derive_spatial_pattern(kg) -> str:
    """Derive a one-sentence spatial pattern from residential clusters."""
    clusters = []
    for s in kg.g.subjects(RDF.type, EntityTypes.ResidentialCluster):
        name = ""
        lon = lat = None
        for p, o in kg.g.predicate_objects(s):
            pn = _pred_name(p)
            if pn == "name":
                name = str(o)
            elif pn == "lon":
                try:
                    lon = float(o)
                except (ValueError, TypeError):
                    pass
            elif pn == "lat":
                try:
                    lat = float(o)
                except (ValueError, TypeError):
                    pass
        if lon is not None and lat is not None:
            clusters.append((name, lon, lat))

    if not clusters:
        return "居民点分布信息不足"

    # Compute centroid
    mean_lon = sum(c[1] for c in clusters) / len(clusters)
    mean_lat = sum(c[2] for c in clusters) / len(clusters)

    # Count clusters by quadrant relative to centroid
    nw = ne = sw = se = 0
    for _, lon, lat in clusters:
        if lon >= mean_lon and lat >= mean_lat:
            ne += 1
        elif lon >= mean_lon and lat < mean_lat:
            se += 1
        elif lon < mean_lon and lat >= mean_lat:
            nw += 1
        else:
            sw += 1

    parts = []
    if nw + ne > sw + se:
        parts.append("北部")
    else:
        parts.append("南部")
    if ne + se > nw + sw:
        parts.append("东部")
    else:
        parts.append("西部")

    return f"共{len(clusters)}个居民点，主要集中在{''.join(parts)}，呈{'集聚' if max(nw, ne, sw, se) > len(clusters) * 0.4 else '分散'}分布"


# ============================================================
# Layer cards (per GisLayerSet)
# ============================================================

def _build_layer_cards(kg) -> List[Dict[str, Any]]:
    """Build a card for each GisLayerSet entity in the KG."""
    cards: List[Dict[str, Any]] = []

    for lg in kg.g.subjects(RDF.type, EntityTypes.GisLayerSet):
        group_name = ""
        geom_kind = ""
        desc = ""
        enriched_desc = ""
        count = 0
        dom_label = ""

        for p, o in kg.g.predicate_objects(lg):
            pn = _pred_name(p)
            if pn == "semantic_group":
                group_name = str(o)
            elif pn == "geometry_kind":
                geom_kind = str(o)
            elif pn == "gis_description":
                desc = str(o)
            elif pn == "gis_description_enriched":
                enriched_desc = str(o)
            elif pn == "entity_count":
                try:
                    count = int(o)
                except (ValueError, TypeError):
                    pass
            elif pn == "dominant_label":
                dom_label = str(o)

        # Build distribution string from has_semantic_label of member entities
        distribution = ""
        if enriched_desc:
            distribution = enriched_desc
        elif desc:
            distribution = desc

        cards.append({
            "group": group_name,
            "geometry": geom_kind,
            "count": count,
            "dominant_label": dom_label,
            "distribution": distribution,
            "description": desc,
        })

    # Sort by count descending
    cards.sort(key=lambda c: c.get("count", 0), reverse=True)
    return cards


# ============================================================
# Layer 3: constraint_block (spatial relations + constraint coverage)
# ============================================================

def _build_constraint_block(kg) -> Dict[str, Any]:
    """Build constraint summary: relation totals, cross-layer overlaps, coverage."""
    # Count spatial relations
    touches_count = sum(1 for _ in kg.g.triples((None, PLN.sfTouches, None))) // 2  # bidirectional
    nearby_count = sum(1 for _ in kg.g.triples((None, PLN.nearby, None)))
    connected_count = sum(1 for _ in kg.g.triples((None, PLN.connected_via_road, None)))

    # Count legal_constraint distribution
    constraint_dist: Counter = Counter()
    for _, _, o in kg.g.triples((None, legal_constraint, None)):
        constraint_dist[str(o)] += 1

    # Count parcels in each planning_zone
    zone_dist: Counter = Counter()
    for _, _, o in kg.g.triples((None, PLN.planning_zone, None)):
        zone_dist[str(o)] += 1

    # Constraint coverage (via get_constraint_coverage module function)
    constraint_coverage = ""
    try:
        from .sparql import get_constraint_coverage
        coverage = get_constraint_coverage(kg)
        if coverage:
            constrained_count = len(coverage)
            constraint_coverage = f"{constrained_count}个地块与约束面重叠"
    except Exception:
        pass

    return {
        "adjacency_total": touches_count,
        "nearby_total": nearby_count,
        "connected_total": connected_count,
        "legal_constraint_distribution": dict(constraint_dist),
        "planning_zone_distribution": dict(zone_dist),
        "constraint_coverage": constraint_coverage,
    }


# ============================================================
# Structured payload (tool-consumable)
# ============================================================

def _build_structured_payload(kg, layer_cards: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build structured data: layer_group_bsms, geometry_kind_index, bbox, representatives."""
    # Collect BSMs per layer group
    layer_group_bsms: Dict[str, List[str]] = {}
    geometry_kind_index: Counter = Counter()

    for lg in kg.g.subjects(RDF.type, EntityTypes.GisLayerSet):
        group_name = ""
        for _, _, o in kg.g.triples((lg, semantic_group, None)):
            group_name = str(o)
            break
        if not group_name:
            continue

        bsms: List[str] = []
        for _, _, member in kg.g.triples((lg, contains_entity, None)):
            # Get BSM of member
            bsm = ""
            for _, _, o in kg.g.triples((member, PLN.bsm, None)):
                bsm = str(o)
                break
            if bsm:
                bsms.append(bsm)
            # Count geometry kind
            for _, _, o in kg.g.triples((member, geometry_kind, None)):
                geometry_kind_index[str(o)] += 1
                break

        layer_group_bsms[group_name] = bsms

    # Village bbox
    v_uri = URIRef(PLN_NS + "village")
    bbox = None
    bbox_geom = kg.g.value(v_uri, GeoPredicates.hasBoundingBox)
    if bbox_geom:
        wkt_lit = kg.g.value(bbox_geom, GeoPredicates.asWKT)
        if wkt_lit:
            bbox = parse_wkt_bbox(str(wkt_lit))

    # Representative BSMs (TopK sampled from parcels)
    all_parcels = _collect_parcel_entities(kg)
    representative = TopKSampler.sample(
        all_parcels,
        k_budget=40,
        area_field="area_ha",
        label_field="has_semantic_label",
        bbox=bbox,
    )
    rep_bsms = [p.get("bsm", "") for p in representative if p.get("bsm")]

    total_count = sum(len(v) for v in layer_group_bsms.values())

    return {
        "layer_group_bsms": layer_group_bsms,
        "geometry_kind_index": dict(geometry_kind_index),
        "bbox": bbox,
        "representative_bsms": rep_bsms,
        "total_count": total_count,
        "next_cursor": f"offset={len(rep_bsms)}" if len(rep_bsms) < total_count else None,
    }


def _collect_parcel_entities(kg) -> List[Dict[str, Any]]:
    """Collect all parcel entities with attributes for TopK sampling."""
    parcels: List[Dict[str, Any]] = []
    for s in kg.g.subjects(RDF.type, EntityTypes.Parcel):
        ent: Dict[str, Any] = {"uri": str(s)}
        for p, o in kg.g.predicate_objects(s):
            pn = _pred_name(p)
            if pn == "type":
                continue
            val = str(o)
            if pn in ("area_ha", "lon", "lat"):
                try:
                    ent[pn] = float(o)
                except (ValueError, TypeError):
                    ent[pn] = val
            else:
                ent[pn] = val
        parcels.append(ent)
    return parcels


# ============================================================
# get_layer_group_semantics - single group detail
# ============================================================

def get_layer_group_semantics(kg, group_name: str) -> DualPayload:
    """Get detailed semantics for a single layer group.

    Args:
        kg: PlanningKG instance.
        group_name: semantic_group value (e.g. "current_landuse", "transport").

    Returns:
        DualPayload with single layer card + member BSMs.
    """
    try:
        # Find the LayerGroup entity
        lg_uri = None
        for s in kg.g.subjects(RDF.type, EntityTypes.GisLayerSet):
            for _, _, o in kg.g.triples((s, semantic_group, None)):
                if str(o) == group_name:
                    lg_uri = s
                    break
            if lg_uri:
                break

        if lg_uri is None:
            return DualPayload(semantic={"error": f"LayerGroup not found: {group_name}"})

        # Build card
        cards = _build_layer_cards(kg)
        card = next((c for c in cards if c.get("group") == group_name), {})

        # Collect member BSMs
        member_bsms: List[str] = []
        for _, _, member in kg.g.triples((lg_uri, contains_entity, None)):
            for _, _, o in kg.g.triples((member, PLN.bsm, None)):
                member_bsms.append(str(o))
                break

        semantic = {
            "layer_card": card,
            "member_count": len(member_bsms),
        }

        structured = {
            "group": group_name,
            "member_bsms": member_bsms,
            "total_count": len(member_bsms),
        }

        return DualPayload(
            semantic=semantic,
            structured=structured,
            token_estimate=TokenBudget.estimate_dict(semantic),
            truncated=False,
        )
    except Exception as e:
        logger.error("get_layer_group_semantics failed: %s", e)
        return DualPayload(semantic={"error": str(e)})


__all__ = ["get_village_cognition", "get_layer_group_semantics"]
