"""Layer 4: PlanBlock (incremental change-set, versioned).

Sparse write strategy: only changed entities get L4 triples.
Unchanged parcels have no L4 triples; query falls back to L1.

All functions are module-level and assigned to PlanningKG in base.py.
"""
from typing import Any, Dict, List, Optional, Tuple

from rdflib import Literal, RDF, URIRef
from rdflib.namespace import XSD

from app.utils.logger import get_logger
from ..ontology import PLN, EntityTypes, Relations

logger = get_logger(__name__)


def _apply_plan_block(self, plan_block: Any) -> None:
    """Apply PlanBlock (change-set) to KG Layer 4.

    Sparse write: only changed entities get L4 triples.
    For split/merge, new bsm identifiers are created with derived_from
    linking back to parent L1 parcels.
    """
    from app.modules.schema.contracts.context_contracts import PlanBlock
    if isinstance(plan_block, dict):
        try:
            plan_block = PlanBlock(**plan_block)
        except Exception as e:
            logger.warning("plan_block dict parse failed: %s", e)
            return
    if not isinstance(plan_block, PlanBlock):
        return

    version = plan_block.version or "current"
    count = 0

    # ── Parcel changes (delta) ──
    for pc in plan_block.parcel_changes:
        p_uri = PLN[f"planned_parcel_{pc.bsm}_{version}"]
        self.g.add((p_uri, RDF.type, EntityTypes.PlannedParcel))
        self.g.add((p_uri, PLN.bsm, Literal(pc.bsm)))
        self.g.add((p_uri, PLN.change_action, Literal(pc.action)))
        self.g.add((p_uri, PLN.in_version, Literal(version)))
        # Only write changed fields (sparse)
        if pc.new_planning_land_use:
            self.g.add((p_uri, PLN.planning_land_use, Literal(pc.new_planning_land_use)))
        if pc.new_area_ha is not None:
            self.g.add((p_uri, PLN.planned_area_ha, Literal(pc.new_area_ha, datatype=XSD.double)))
        if pc.new_zone_type:
            self.g.add((p_uri, PLN.planning_zone_type, Literal(pc.new_zone_type)))
        # Link to L1 parents (derived_from)
        for parent_bsm in pc.derived_from_bsms:
            for s in self.g.subjects(PLN.bsm, Literal(parent_bsm)):
                if (s, RDF.type, PLN.Parcel) in self.g:
                    self.g.add((p_uri, PLN.derived_from, s))
                    break
        count += 1

    # ── Facility changes ──
    for fc in plan_block.facility_changes:
        f_uri = PLN[f"planned_facility_{fc.name}_{version}"]
        self.g.add((f_uri, RDF.type, PLN.Facility))
        self.g.add((f_uri, PLN.name, Literal(fc.name)))
        self.g.add((f_uri, PLN.change_action, Literal(fc.action)))
        self.g.add((f_uri, PLN.in_version, Literal(version)))
        if fc.facility_type:
            self.g.add((f_uri, PLN.facility_type, Literal(fc.facility_type)))
        if fc.area_sqm is not None:
            self.g.add((f_uri, PLN.area_sqm, Literal(fc.area_sqm, datatype=XSD.double)))
        if fc.center and len(fc.center) >= 2:
            self.g.add((f_uri, PLN.lon, Literal(fc.center[0], datatype=XSD.double)))
            self.g.add((f_uri, PLN.lat, Literal(fc.center[1], datatype=XSD.double)))
        if fc.derived_from_name:
            for s in self.g.subjects(PLN.name, Literal(fc.derived_from_name)):
                if (s, RDF.type, PLN.Facility) in self.g:
                    self.g.add((f_uri, PLN.derived_from, s))
                    break
        self.g.add((f_uri, Relations.located_in, PLN.village))
        count += 1

    # ── Road changes ──
    for rc in plan_block.road_changes:
        r_uri = PLN[f"planned_road_{rc.name}_{version}"]
        self.g.add((r_uri, RDF.type, PLN.Road))
        self.g.add((r_uri, PLN.name, Literal(rc.name)))
        self.g.add((r_uri, PLN.change_action, Literal(rc.action)))
        self.g.add((r_uri, PLN.in_version, Literal(version)))
        if rc.road_level:
            self.g.add((r_uri, PLN.road_level, Literal(rc.road_level)))
        if rc.width_m:
            self.g.add((r_uri, PLN.buffer_width_m, Literal(rc.width_m, datatype=XSD.double)))
        if rc.derived_from_name:
            for s in self.g.subjects(PLN.name, Literal(rc.derived_from_name)):
                if (s, RDF.type, PLN.Road) in self.g:
                    self.g.add((r_uri, PLN.derived_from, s))
                    break
        self.g.add((r_uri, Relations.located_in, PLN.village))
        count += 1

    # ── Settlement changes ──
    for sc in plan_block.settlement_changes:
        s_uri = PLN[f"planned_settlement_{sc.settlement_name}_{version}"]
        self.g.add((s_uri, RDF.type, EntityTypes.NaturalSettlement))
        self.g.add((s_uri, PLN.name, Literal(sc.settlement_name)))
        self.g.add((s_uri, PLN.change_action, Literal(sc.action)))
        self.g.add((s_uri, PLN.in_version, Literal(version)))
        if sc.new_population is not None:
            self.g.add((s_uri, PLN.population, Literal(sc.new_population, datatype=XSD.integer)))
        if sc.new_area_ha is not None:
            self.g.add((s_uri, PLN.planned_area_ha, Literal(sc.new_area_ha, datatype=XSD.double)))
        if sc.target_location and len(sc.target_location) >= 2:
            self.g.add((s_uri, PLN.lon, Literal(sc.target_location[0], datatype=XSD.double)))
            self.g.add((s_uri, PLN.lat, Literal(sc.target_location[1], datatype=XSD.double)))
        if sc.merge_into:
            self.g.add((s_uri, PLN.merged_into, Literal(sc.merge_into)))
        self.g.add((s_uri, Relations.located_in, PLN.village))
        count += 1

    # ── Summary metrics ──
    for metric_name, value in plan_block.summary_metrics.items():
        m_uri = PLN[f"planned_metric_{metric_name}_{version}"]
        self.g.add((m_uri, RDF.type, PLN.PlanningIndicator))
        self.g.add((m_uri, PLN.name, Literal(metric_name)))
        self.g.add((m_uri, PLN.value, Literal(value, datatype=XSD.double)))
        self.g.add((m_uri, PLN.in_version, Literal(version)))
        self.g.add((PLN.village, PLN.has_indicator, m_uri))

    if count:
        logger.info("Layer 4: applied %d changes (version=%s)", count, version)


# ── Query methods: effective state (L1 + L4 merge) ──


def get_effective_land_use(self, bsm: str, version: str = "current") -> Optional[str]:
    """Get effective land use: L4 if changed, else L1 fallback."""
    l4 = self.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?lu WHERE {{ '
        f'?p a pln:PlannedParcel ; pln:bsm "{bsm}" ; '
        f'pln:planning_land_use ?lu ; pln:in_version "{version}" . }}')
    if l4:
        return l4[0].get("lu")
    l1 = self.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?dlbm WHERE {{ '
        f'?p a pln:Parcel ; pln:bsm "{bsm}" ; pln:dlbm ?dlbm . }}')
    return l1[0].get("dlbm") if l1 else None


def get_effective_area_ha(self, bsm: str, version: str = "current") -> Optional[float]:
    """Get effective area: L4 if changed, else L1 fallback."""
    l4 = self.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?area WHERE {{ '
        f'?p a pln:PlannedParcel ; pln:bsm "{bsm}" ; '
        f'pln:planned_area_ha ?area ; pln:in_version "{version}" . }}')
    if l4:
        try:
            return float(l4[0].get("area", 0))
        except (ValueError, TypeError):
            return None
    l1 = self.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?area WHERE {{ '
        f'?p a pln:Parcel ; pln:bsm "{bsm}" ; pln:area_ha ?area . }}')
    if l1:
        try:
            return float(l1[0].get("area", 0))
        except (ValueError, TypeError):
            return None
    return None


def get_plan_changes(self, version: str = "current") -> List[Dict[str, Any]]:
    """Get all planning changes (delta) for a version."""
    return self.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?p ?bsm ?action ?lu ?area WHERE {{ '
        f'?p a pln:PlannedParcel ; pln:bsm ?bsm ; pln:change_action ?action ; '
        f'pln:in_version "{version}" . '
        f'OPTIONAL {{ ?p pln:planning_land_use ?lu . }} '
        f'OPTIONAL {{ ?p pln:planned_area_ha ?area . }} }}')


def get_split_parcels(self, version: str = "current") -> List[Dict[str, Any]]:
    """Get parcels created by split action (new bsm, derived from parent)."""
    return self.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?p ?bsm ?parent WHERE {{ '
        f'?p a pln:PlannedParcel ; pln:bsm ?bsm ; '
        f'pln:change_action "split" ; pln:in_version "{version}" ; '
        f'pln:derived_from ?parent . }}')


def get_merge_parcels(self, version: str = "current") -> List[Dict[str, Any]]:
    """Get parcels created by merge action (new bsm, derived from multiple parents)."""
    return self.query(
        f'PREFIX pln: <http://village-planning.org/ontology#> '
        f'SELECT ?p ?bsm ?parent WHERE {{ '
        f'?p a pln:PlannedParcel ; pln:bsm ?bsm ; '
        f'pln:change_action "merge" ; pln:in_version "{version}" ; '
        f'pln:derived_from ?parent . }}')


def get_planned_parcels_in_zone(self, zone_type: str, version: str = "current") -> List[Dict[str, Any]]:
    return self.query(
        f"PREFIX pln: <http://village-planning.org/ontology#> "
        f"SELECT ?bsm ?land_use ?area WHERE {{ "
        f"?p a pln:PlannedParcel ; pln:bsm ?bsm ; pln:planning_land_use ?land_use ; "
        f'pln:planning_zone_type "{zone_type}" ; pln:in_version "{version}" . '
        f"OPTIONAL {{ ?p pln:planned_area_ha ?area . }} }}"
    )


def check_constraint_violations(self, version: str = "current") -> List[Dict[str, Any]]:
    violations = []
    for pp in self.query(f"PREFIX pln: <http://village-planning.org/ontology#> "
                         f"SELECT ?p ?bsm ?land_use WHERE {{ "
                         f"?p a pln:PlannedParcel ; pln:bsm ?bsm ; "
                         f"pln:planning_land_use ?land_use ; pln:in_version \"{version}\" . }}"):
        bsm = pp.get("bsm", "")
        for pz in self.query(f"PREFIX pln: <http://village-planning.org/ontology#> "
                              f"SELECT ?zone ?name ?rule WHERE {{ "
                              f"?s pln:bsm \"{bsm}\" . ?s pln:within_zone ?zone . "
                              f"?zone a pln:ThreeLine ; pln:name ?name . "
                              f"OPTIONAL {{ ?zone pln:restriction ?rule . }} }}"):
            violations.append({"bsm": bsm, "planned_land_use": pp.get("land_use", ""),
                               "protected_zone": pz.get("name", "?"), "rule": pz.get("rule", "禁止建设"),
                               "version": version})
    return violations


def compare_versions(self, version_a: str, version_b: str) -> Dict[str, Any]:
    """Compare two PlanBlock versions - returns changes between delta sets."""
    a_map = {p["bsm"]: p for p in self.query(
        f"PREFIX pln: <http://village-planning.org/ontology#> "
        f"SELECT ?bsm ?land_use ?area ?action WHERE {{ "
        f"?p a pln:PlannedParcel ; pln:in_version \"{version_a}\" ; "
        f"pln:bsm ?bsm ; pln:change_action ?action . "
        f"OPTIONAL {{ ?p pln:planning_land_use ?land_use . }} "
        f"OPTIONAL {{ ?p pln:planned_area_ha ?area . }} }}") if p.get("bsm")}
    b_map = {p["bsm"]: p for p in self.query(
        f"PREFIX pln: <http://village-planning.org/ontology#> "
        f"SELECT ?bsm ?land_use ?area ?action WHERE {{ "
        f"?p a pln:PlannedParcel ; pln:in_version \"{version_b}\" ; "
        f"pln:bsm ?bsm ; pln:change_action ?action . "
        f"OPTIONAL {{ ?p pln:planning_land_use ?land_use . }} "
        f"OPTIONAL {{ ?p pln:planned_area_ha ?area . }} }}") if p.get("bsm")}
    changed = []
    for bsm, bp in b_map.items():
        if bsm in a_map:
            ap = a_map[bsm]
            if ap.get("land_use", "") != bp.get("land_use", ""):
                changed.append({"bsm": bsm, "from": ap.get("land_use", ""),
                                "to": bp.get("land_use", ""),
                                "action_a": ap.get("action", ""), "action_b": bp.get("action", "")})
        else:
            changed.append({"bsm": bsm, "from": None, "to": bp.get("land_use", ""),
                            "action": bp.get("action", "new_in_b")})
    a_keys = set(a_map.keys())
    b_keys = set(b_map.keys())
    return {"version_a": version_a, "version_b": version_b,
            "changed_parcels": changed,
            "added_parcels": list(b_keys - a_keys),
            "removed_parcels": list(a_keys - b_keys),
            "total_changes": len(changed) + len(b_keys - a_keys) + len(a_keys - b_keys)}
