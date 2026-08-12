"""报告 → KG 实体注解（多级增强入口，自 parse/agent.py extract_bindings 迁入）。

L1 级（wave1）：村名→gazetteer 绑定（Flash 双确认 + 空间校验）→ EntityAnnotation(cluster_uri)
L2/L3 级（wave2/3）：功能分区/项目实体语义注解（表格提取）
"""

from __future__ import annotations
import asyncio

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.data.model.village_name_registry import load_all_village_names
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_BSM_NUM_RE = re.compile(r"(\d{15,25})")

# The registry is the sole source of the closed set.  Load the configured
# data set union so this module does not silently bind every session to a
# hard-coded village key.
_KNOWN_NATURAL_VILLAGES = set(load_all_village_names())


# ── L1 INSTRUCTION 表 → LocationAnchor 提取 ─────────────────────────────

_INSTRUCTION_TYPE_CELLS = {"现状设施", "现状项目", "现状分区", "设施", "项目", "分区"}
_INSTRUCTION_NAME_HEADER_RE = re.compile(r"(名称|项目|工程|设施)")
_INSTRUCTION_LOCATION_HEADER_RE = re.compile(r"(位置|选址|所在位置|方位|位于)")
_INSTRUCTION_NAME_EXCLUDES = {"名称", "项目", "设施", "合计", "总数", "序号"}


@dataclass
class LocationAnchor:
    """L1 报告提取的'设施+位置'结构化地点条目。

    kind:
      - "facility"    现状设施（村委会/小学/广场…）
      - "project"     现状项目（种植基地/养殖基地…）
      - "zone"        现状分区（居民点/建设区…）
      - "landmark"    独立地物（古驿道/古檀树…）
    location: INSTRUCTION 表"位置"列原始文本（自然村名 / 方位描述 / 空）。
    """
    name: str
    kind: str = "facility"
    location: str = ""
    dim: str = ""
    description: str = ""


def _extract_instruction_anchors(instruction_texts: Dict[str, str]) -> List[LocationAnchor]:
    """从 L1 INSTRUCTION 段解析'设施+位置'锚点（复用 parsing.tables._iter_tables）。

    输入: {dim_key: instruction_section} — L1 各维度报告的【INSTRUCTION】剥离段。
    输出: LocationAnchor 列表（按维度去重，INSTRUCTION 表"位置"列保留原始文本）。
    """
    from app.data.ingestion.tables import _iter_tables

    anchors: List[LocationAnchor] = []
    seen: set = set()
    for dim_key, section in (instruction_texts or {}).items():
        if not section:
            continue
        try:
            tables = _iter_tables(section)
        except Exception as e:
            logger.debug("[Enrich:instruction] table parse failed for %s: %s", dim_key, e)
            continue
        for header, rows in tables:
            if not rows:
                continue
            name_idx = None
            loc_idx = None
            type_idx = None
            for idx, cell in enumerate(header):
                cell_l = str(cell).strip()
                if name_idx is None and _INSTRUCTION_NAME_HEADER_RE.search(cell_l):
                    name_idx = idx
                if loc_idx is None and _INSTRUCTION_LOCATION_HEADER_RE.search(cell_l):
                    loc_idx = idx
                if cell_l == "类型":
                    type_idx = idx
            if name_idx is None:
                continue
            for row in rows:
                if name_idx >= len(row):
                    continue
                name = str(row[name_idx]).strip()
                if not name or name in _INSTRUCTION_NAME_EXCLUDES or "|" in name:
                    continue
                if name in seen:
                    continue
                seen.add(name)
                kind = "facility"
                if type_idx is not None and type_idx < len(row):
                    cell_type = str(row[type_idx]).strip()
                    if "项目" in cell_type:
                        kind = "project"
                    elif "分区" in cell_type:
                        kind = "zone"
                location = ""
                if loc_idx is not None and loc_idx < len(row):
                    location = str(row[loc_idx]).strip()
                anchors.append(LocationAnchor(
                    name=name, kind=kind, location=location,
                    dim=dim_key,
                    description=f"{kind}「{name}」源自{dim_key}报告 INSTRUCTION 表",
                ))
    return anchors


def _split_location_villages(location: str) -> List[str]:
    """从 INSTRUCTION 位置列提取自然村名集合（顿号/逗号/空格分隔）。"""
    if not location:
        return []
    out: List[str] = []
    for tok in re.split(r"[、，,;/ 至和与]", location):
        tok = tok.strip()
        if not tok:
            continue
        base = tok
        if base.endswith("自然村"):
            base = base[:-3]
        elif base.endswith("村"):
            base = base[:-1]
        if base in _KNOWN_NATURAL_VILLAGES and base not in out:
            out.append(base)
    return out


def _commit_instruction_anchors(
    session_id: str,
    gazetteer: Any,
    kg: Any,
    instruction_texts: Optional[Dict[str, str]],
    wave: int,
) -> int:
    """把 L1 INSTRUCTION 表提取的 LocationAnchor 写入 gazetteer（组合名条目）。

    组合名 = f"{anchor.name}@{村名}"（如"村委会@园寨"），作为独立 gazetteer 条目，
    坐标继承该村 gazetteer entry 的 centroid；无村名命中的 anchor 仅在描述中记录
    方位文本（供 grounding 语义解析），不生成伪坐标条目。

    返回写入的条目数。
    """
    from app.infrastructure.kg.gazetteer import GazetteerEntry

    anchors = _extract_instruction_anchors(instruction_texts or {})
    if not anchors:
        return 0

    written = 0
    for anchor in anchors:
        villages = _split_location_villages(anchor.location)
        if not villages:
            # 无自然村命中（方位描述等）→ 记入语义 memory 描述，不建组合名坐标
            _get_semantic_memory().add_entity_annotation(
                __import__("app.infrastructure.kg", fromlist=["EntityAnnotation"]).EntityAnnotation(
                    entity_uri=f"pln:anchor_{anchor.kind}_{anchor.name}",
                    entity_type="LocationAnchor",
                    description=f"{anchor.description}；位置描述「{anchor.location}」（待 grounding 语义解析）",
                    source_text_refs=[anchor.dim],
                    round_added=wave,
                    valid_from_round=wave,
                    confidence=0.5,
                )
            )
            continue
        for v in villages:
            entry = gazetteer.resolve(v, fuzzy=False)
            base_centroid = list(entry.centroid) if entry and entry.centroid else None
            # 组合名条目（独立地名锚点，供 API 精确搜索 / PARSE 落位）
            combo_name = f"{anchor.name}@{v}"
            combo = GazetteerEntry(
                name=combo_name,
                aliases=[anchor.name],
                entity_uri=f"pln:anchor_{anchor.kind}_{anchor.name}_{v}",
                bsms=list(entry.bsms) if entry else [],
                centroid=base_centroid,
                source="l1_instruction",
                confidence=0.6,
                description=f"{anchor.description}；位于{v}",
            )
            gazetteer.upsert(combo)
            # Persist the geocoded facility/project/place binding.  The
            # process gazetteer is rebuilt at stage boundaries, so keeping
            # only the in-memory combo entry makes GROUND lose the exact
            # target anchor after PARSE.  Reuse the real village BSMs; do not
            # invent a point for a facility whose source row has no geometry.
            _get_semantic_memory().add_entity_annotation(
                __import__("app.infrastructure.kg", fromlist=["EntityAnnotation"]).EntityAnnotation(
                    entity_uri=combo.entity_uri,
                    entity_type="LocationAnchor",
                    description=f"{combo_name}（{anchor.description}；位于{v}）",
                    intent_refs=list(entry.bsms) if entry else [],
                    source_text_refs=[anchor.dim, anchor.location],
                    round_added=wave,
                    valid_from_round=wave,
                    confidence=0.6,
                )
            )
            written += 1
    logger.info(
        "[Enrich:instruction] %d anchors -> %d combo entries",
        len(anchors), written,
    )
    return written


def _get_semantic_memory():
    from app.infrastructure.kg import get_semantic_memory

    return get_semantic_memory()


_VILLAGE_ROLES = frozenset({"village", "natural_village", "settlement", "村庄", "自然村"})


def _location_fact_mentions(location_facts: Optional[List[Any]]) -> List[Dict[str, str]]:
    """Convert structured L1 location facts into KG enrichment mentions.

    Village facts keep the existing ``{base}村`` name suffix (the village-binding
    branch).  Non-village typed facts (facility/project/zone/landmark/...) are
    retained with their original name and an explicit ``role`` so downstream
    consumers can distinguish them without treating them as residential clusters.
    """
    mentions: List[Dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for fact in location_facts or []:
        role = str(getattr(fact, "role", "") or "").strip().lower()
        normalized = str(getattr(fact, "normalized_name", "") or "").strip()
        if not normalized:
            continue
        dim = str(getattr(fact, "dimension_key", "") or "l1_location_fact")
        hint = str(
            getattr(fact, "spatial_hint", "")
            or getattr(fact, "source_span", "")
            or normalized
        )[:160]
        for token in re.split(r"[、，,;/至和与\\s]+", normalized):
            token = token.strip()
            if not token:
                continue
            if role in _VILLAGE_ROLES:
                base = token.removesuffix("自然村").removesuffix("村").strip()
                if not base or (base, dim) in seen:
                    continue
                seen.add((base, dim))
                mentions.append({
                    "name": f"{base}村",
                    "role": "village",
                    "hints": hint,
                    "dim": dim,
                })
            else:
                if (token, dim) in seen:
                    continue
                seen.add((token, dim))
                mentions.append({
                    "name": token,
                    "role": role,
                    "hints": hint,
                    "dim": dim,
                })
    return mentions


def _feature_text(feature: Any) -> str:
    # Uploaded features are Pydantic models with ``extra=allow``.  Their
    # original GeoJSON properties are not exposed as ``properties``; aliases
    # such as ``地质灾害点名称`` may only be present in ``model_dump()``.
    # Reading only name/label therefore silently dropped real village names
    # before GROUND.  Keep the raw source values as evidence and include the
    # model's extra fields without inventing any geometry.
    raw = getattr(feature, "_raw", None)
    if not isinstance(raw, dict):
        raw = getattr(feature, "properties", None)
    if (not isinstance(raw, dict) or not raw) and hasattr(feature, "model_dump"):
        try:
            raw = feature.model_dump(by_alias=True)
        except Exception:
            raw = None
    if not isinstance(raw, dict):
        raw = vars(feature) if hasattr(feature, "__dict__") else {}
    values = [str(v) for v in raw.values() if v not in (None, "")]
    for attr in ("name", "label", "description", "text", "category", "layer_type"):
        value = getattr(feature, attr, None)
        if value:
            values.append(str(value))
    return " ".join(values)


def _feature_centroid(feature: Any) -> Optional[List[float]]:
    geometry = getattr(feature, "geometry", None)  # getattr intentional: heterogeneous feature objects
    if not geometry:
        return None
    try:
        from app.spatial.model.geometry import _compute_centroid

        return _compute_centroid({
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {}, "geometry": geometry}],
        })
    except Exception:
        return None


def _materialize_gis_village_entries(
    gazetteer: Any,
    bundle: Any,
    village_bases: List[str],
) -> int:
    """Bind report village facts to real GIS parcels through named features.

    This is deliberately evidence-first: a village entry is created only
    when an uploaded bundle feature contains the village name and has usable
    geometry.  Its BSMs come from the nearest existing KG residential
    cluster; no parcel or coordinate is fabricated for an unlocated village.
    """
    from app.infrastructure.kg.gazetteer import GazetteerEntry

    if gazetteer is None or bundle is None:
        return 0
    clusters = [
        entry for entry in getattr(gazetteer, "entries", [])
        if entry.source == "kg_cluster" and entry.bsms and entry.centroid
    ]
    if not clusters:
        return 0
    features: List[Any] = []
    for group_name in ("points", "lines", "polygons"):
        group = getattr(bundle, group_name, None)
        if group is None:
            continue
        try:
            features.extend(list(getattr(group, "all_features", []) or []))
        except Exception:
            continue

    written = 0
    for base in village_bases:
        village_name = f"{base}村"
        if gazetteer.resolve(village_name, fuzzy=False) is not None:
            existing = gazetteer.resolve(village_name, fuzzy=False)
            if existing is not None and existing.bsms:
                continue
        observations: List[List[float]] = []
        for feature in features:
            text = _feature_text(feature)
            if base not in text:
                continue
            point = _feature_centroid(feature)
            if point and len(point) >= 2:
                observations.append([float(point[0]), float(point[1])])
        if not observations:
            continue
        centroid = [
            sum(point[0] for point in observations) / len(observations),
            sum(point[1] for point in observations) / len(observations),
        ]
        cluster = min(
            clusters,
            key=lambda entry: (
                (float(entry.centroid[0]) - centroid[0]) ** 2
                + (float(entry.centroid[1]) - centroid[1]) ** 2
            ),
        )
        gazetteer.upsert(GazetteerEntry(
            name=village_name,
            aliases=[base, f"{base}自然村"],
            entity_uri=cluster.entity_uri,
            bsms=list(cluster.bsms),
            centroid=list(cluster.centroid),
            source="gis_name_binding",
            confidence=0.8,
            description=(
                f"{village_name}：由上传 GIS 属性名匹配 {len(observations)} 个真实要素，"
                f"绑定最近 KG 居民点 {cluster.name}。"
            ),
        ))
        # Persist the GIS-backed name binding as semantic memory.  The
        # in-process Gazetteer is rebuilt at PARSE/GROUND boundaries, so a
        # runtime-only upsert would otherwise disappear before grounding.
        _get_semantic_memory().add_entity_annotation(
            __import__("app.infrastructure.kg", fromlist=["EntityAnnotation"]).EntityAnnotation(
                entity_uri=f"pln:gis_village_binding:{base}",
                entity_type="GISVillageBinding",
                description=(
                    f"{village_name}（GIS 属性名绑定，真实要素 {len(observations)} 个；"
                    f"KG 居民点 {cluster.name}）"
                ),
                intent_refs=list(cluster.bsms),
                source_text_refs=["uploaded_gis_name_binding"],
                round_added=1,
                valid_from_round=1,
                confidence=0.8,
            )
        )
        written += 1
    if written:
        logger.info("[Enrich:GIS] materialized %d named village bindings", written)
    return written


_BATCH_CONFIRM_SIZE = 15  # 批量判定小批大小（单次 prompt 可读性优先，避免 104 对全量一次）
_BATCH_CONFIRM_TIMEOUT = 30


def _build_bsm_to_dlbm(kg: Any) -> Dict[str, str]:
    """预构建 bsm→dlbm 映射（一次全图扫描，逐 mention 共享）。"""
    from app.infrastructure.kg.ontology import PLN

    bsm_to_dlbm: Dict[str, str] = {}
    try:
        for s, _, o in kg.g.triples((None, PLN.bsm, None)):
            bsm = str(o)
            for _, _, d in kg.g.triples((s, PLN.dlbm, None)):
                bsm_to_dlbm[bsm] = str(d)
                break
    except Exception:
        pass
    return bsm_to_dlbm


def _cluster_dlbms(entry: Any, bsm_to_dlbm: Dict[str, str]) -> List[str]:
    return [bsm_to_dlbm[b] for b in (entry.bsms or []) if b in bsm_to_dlbm]


def _gather_candidates(mention: Dict[str, str], gazetteer: Any, bsm_to_dlbm: Dict[str, str]) -> List[Any]:
    """候选生成：gazetteer 命中 → 单候选；否则按村名特征 hints 与聚类 dlbm 构成的空间校验。"""
    from app.infrastructure.kg.gazetteer import spatial_score

    # A report village reference is a contractual name, not a fuzzy search
    # query.  Fuzzy resolution here can silently turn ``田坑村`` into an
    # unrelated ``符坑村`` and then make GROUND appear spatially supported.
    # Keep candidate generation fail-closed; approximate matches belong in a
    # HUMAN review item with explicit evidence.
    entry = gazetteer.resolve(mention["name"], fuzzy=False)
    if entry is not None and entry.entity_uri:
        return [entry]
    return [
        e for e in gazetteer.entries
        if e.entity_uri
        and spatial_score(mention["hints"], _cluster_dlbms(e, bsm_to_dlbm)) > 0
    ]


def _deterministic_pick(mention: Dict[str, str], candidates: List[Any], bsm_to_dlbm: Dict[str, str]) -> Optional[Any]:
    """无 LLM / LLM 不可用时的确定性打分裁决：唯一最高分才绑定。"""
    from app.infrastructure.kg.gazetteer import spatial_score

    scored = sorted(
        ((spatial_score(mention["hints"], _cluster_dlbms(e, bsm_to_dlbm)), e) for e in candidates),
        key=lambda x: -x[0],
    )
    if scored and scored[0][0] > 0:
        top_score = scored[0][0]
        top = [e for s, e in scored if s == top_score]
        if len(top) == 1:
            return top[0]
    return None


async def confirm_batch_with_llm(
    llm: Any,
    pairs: List[Tuple[str, str, str]],
) -> Dict[Tuple[str, str], bool]:
    """小批量 LLM 判定（村名, 居民点, 描述）对 → {(村名, 聚类名): bool}。

    LLM 一次性逐项返回全部 match 判定，避免逐候选 N 次往返；
    单批 ≤ _BATCH_CONFIRM_SIZE 对，控制 prompt 长度与注意力质量。
    """
    if not pairs or llm is None:
        return {}
    results: Dict[Tuple[str, str], bool] = {}
    for start in range(0, len(pairs), _BATCH_CONFIRM_SIZE):
        chunk = pairs[start:start + _BATCH_CONFIRM_SIZE]
        lines = "\n".join(
            f"{i}. 村名：{m} | 居民点：{c}" + (f"（{d}）" if d else "")
            for i, (m, c, d) in enumerate(chunk, 1)
        )
        prompt = (
            "你是村庄地名匹配助手。逐项判断每组「村名」与「居民点」是否为同一自然村"
            f"（语义一致即 match:true）。\n{lines}\n"
            '只输出 JSON：{"results": [{"index": 1, "match": true}, ...]}（index 对应上面编号）'
        )
        try:
            resp = await asyncio.wait_for(llm.ainvoke(prompt), timeout=_BATCH_CONFIRM_TIMEOUT)
            content = getattr(resp, "content", "") or ""
        except Exception as e:
            logger.warning("[Enrich] LLM batch confirm failed: %s", e)
            continue
        stripped = content.strip().strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
        try:
            data = json.loads(stripped)
            for item in data.get("results", []) or []:
                idx = int(item.get("index", 0))
                if 1 <= idx <= len(chunk):
                    m, c, _ = chunk[idx - 1]
                    results[(m, c)] = bool(item.get("match"))
        except Exception as e:
            logger.warning("[Enrich] LLM batch confirm parse failed: %s", e)
            continue
    return results


def _commit_village_binding(
    mention: Dict[str, str],
    chosen: Any,
    gazetteer: Any,
    bsm_to_dlbm: Dict[str, str],
    round_num: int,
) -> Optional[str]:
    """绑定落库：空间校验双闸门 → gazetteer upsert（l1_enrichment）→ EntityAnnotation。

    闸门 1（特征词）：spatial_check(hints, cluster_dlbms) — 现状特征词与聚类地类匹配。
    闸门 2（距离）：若 gazetteer 已有多源 API 提供的该村权威坐标（tencent/amap/baidu），
        则校验候选 cluster 质心与该坐标距离 < 200m，防止"多村名绑同 cluster"。
    """
    from app.infrastructure.kg import EntityAnnotation
    from app.infrastructure.kg.gazetteer import GazetteerEntry, spatial_check

    # 闸门 1：特征词空间校验
    if not spatial_check(mention["hints"], _cluster_dlbms(chosen, bsm_to_dlbm)):
        logger.info("[Enrich:L1] %s -> %s rejected (space)", mention["name"], chosen.name)
        return None

    # 闸门 2：多源 API 权威坐标距离校验（防"多村名绑同 cluster"）
    authoritative = gazetteer.resolve(mention["name"], fuzzy=False)
    if (authoritative is not None and authoritative.centroid
            and authoritative.source in _AUTHORITATIVE_SOURCES):
        chosen_centroid = chosen.centroid or authoritative.centroid
        if not _centroid_within_200m(authoritative.centroid, chosen_centroid):
            logger.info(
                "[Enrich:L1] %s -> %s rejected (distance: %s vs %s)",
                mention["name"], chosen.name, authoritative.centroid, chosen_centroid,
            )
            return None

    new_entry = GazetteerEntry(
        name=mention["name"],
        entity_uri=chosen.entity_uri,
        bsms=list(chosen.bsms),
        centroid=chosen.centroid,
        source="l1_enrichment",
        confidence=chosen.confidence,
        description=f"{mention['name']}（{chosen.name}，源自{mention['dim']}报告）",
    )
    gazetteer.upsert(new_entry)

    ann = EntityAnnotation(
        entity_uri=chosen.entity_uri,
        entity_type="ResidentialCluster",
        description=f"{mention['name']}（源自{mention['dim']}报告）",
        source_text_refs=[f"{mention['dim']}:{mention['hints'][:40]}"],
        round_added=round_num,
        valid_from_round=round_num,
        confidence=chosen.confidence,
    )
    _get_semantic_memory().add_entity_annotation(ann)
    return chosen.entity_uri


# 多源 API 权威来源（进入 bundle 前 enrichment 注入的自然村坐标）
_AUTHORITATIVE_SOURCES = frozenset({
    "tencent_map", "amap_poi", "baidu_v3", "tianditu_wfs",
})


def _centroid_within_200m(a: Optional[List[float]], b: Optional[List[float]]) -> bool:
    """两质心距离 < 200m 判定（haversine）。任一缺失视为通过（无距离证据）。"""
    if not a or not b or len(a) < 2 or len(b) < 2:
        return True
    try:
        from app.spatial.model.geo_utils import haversine_distance

        dist_m = haversine_distance((float(a[0]), float(a[1])), (float(b[0]), float(b[1])))
        return dist_m < 200.0
    except Exception:
        return True


async def extract_bindings(
    session_id: str,
    wave: int,
    reports: Dict[str, str],
    llm: Any = None,
    kg: Any = None,
    bundle: Any = None,
    instruction_texts: Optional[Dict[str, str]] = None,
    location_facts: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """实体语义增强：村名→gazetteer 绑定（L1）+ 分区/项目实体注解（L2/L3）。

    迁移自 app/agent/gis/parse/agent.py::extract_bindings（PARSE 职责纯净后）。
    """
    from app.infrastructure.kg import require_session_kg
    from app.infrastructure.kg.gazetteer import build_gazetteer
    from app.infrastructure.kg.memory import save_memory_state

    kg = kg if kg is not None else require_session_kg(session_id)

    memory = _get_semantic_memory()
    gazetteer = build_gazetteer(kg, bundle, memory)
    gis_village_entries = _materialize_gis_village_entries(
        gazetteer,
        bundle,
        list(dict.fromkeys([
            str(item.get("name", ""))[:-1]
            for item in _location_fact_mentions(location_facts)
            if str(item.get("name", "")).endswith("村")
        ])),
    )
    # The planning context is intentionally built once before L1.  Enrichment
    # updates the same in-memory gazetteer object consumed by later GROUND;
    # rebuilding the whole context here would violate the frozen context_ref.
    try:
        from app.infrastructure.registry import get_context_reader_default

        get_context = get_context_reader_default()
        cached_context = get_context(session_id) if get_context is not None else None
        if cached_context is not None:
            cached_context.gazetteer = gazetteer
            if getattr(cached_context, "ports", None) is not None:
                from app.infrastructure.kg.adapters.gazetteer_adapter import KGGazetteerAdapter

                cached_context.ports.gazetteer = KGGazetteerAdapter(gazetteer)
    except Exception as exc:
        logger.warning("[Enrich:GIS] cached context gazetteer update failed: %s", exc)

    bound_clusters = 0
    anchor_entries = 0
    if wave in (1, 3):
        bsm_to_dlbm = _build_bsm_to_dlbm(kg)
        mentions: List[Dict[str, str]] = _location_fact_mentions(location_facts)
        direct_picks = []          # 候选==1（gazetteer 命中）直接绑定
        ambiguous = []             # 候选>1 → 批量 LLM 判定
        unresolved_amb = []
        for mention in mentions:
            if mention.get("role", "village") not in _VILLAGE_ROLES:
                continue
            candidates = _gather_candidates(mention, gazetteer, bsm_to_dlbm)
            if not candidates:
                # Preserve the L1 fact in semantic KG even when GIS has no
                # named geometry yet.  An empty binding is explicit and
                # fail-closed; it must not be mistaken for a resolved parcel.
                _get_semantic_memory().add_entity_annotation(
                    __import__("app.infrastructure.kg", fromlist=["EntityAnnotation"]).EntityAnnotation(
                        entity_uri=f"pln:l1_location_fact:{mention['name']}",
                        entity_type="L1LocationFact",
                        description=(
                            f"{mention['name']}（L1 位置事实，尚无上传 GIS 要素完成空间绑定；"
                            f"来源：{mention.get('dim', '')}）"
                        ),
                        source_text_refs=[mention.get("dim", "")],
                        round_added=wave,
                        valid_from_round=wave,
                        confidence=0.5,
                    )
                )
                continue
            if len(candidates) == 1:
                direct_picks.append((mention, candidates[0]))
            else:
                ambiguous.append((mention, candidates))

        # 批量 Flash 判定（一次调用 N 对；失败/否决降级确定性裁决）
        pairs = [
            (mention["name"], e.name, e.description or e.name)
            for mention, cands in ambiguous
            for e in cands
        ]
        batch_results = await confirm_batch_with_llm(llm, pairs)

        for mention, candidates in ambiguous:
            chosen = None
            for e in candidates:
                if batch_results.get((mention["name"], e.name)):
                    chosen = e
                    break
            if chosen is None:
                chosen = _deterministic_pick(mention, candidates, bsm_to_dlbm)
            if chosen is None:
                logger.info(
                    "[Enrich:L1] %s -> %d candidates unresolved",
                    mention["name"], len(candidates),
                )
                unresolved_amb.append(mention["name"])
                continue
            uri = _commit_village_binding(mention, chosen, gazetteer, bsm_to_dlbm, wave)
            if uri:
                bound_clusters += 1

        for mention, chosen in direct_picks:
            uri = _commit_village_binding(mention, chosen, gazetteer, bsm_to_dlbm, wave)
            if uri:
                bound_clusters += 1
        if unresolved_amb:
            logger.info("[Enrich:L1] unresolved mentions: %s", unresolved_amb)

        # P0: L1 INSTRUCTION 表 → LocationAnchor → gazetteer 组合名条目
        # （消费 L1 各维度报告剥离的【INSTRUCTION】段，'设施+村名'结构化落地）
        try:
            anchor_entries = _commit_instruction_anchors(
                session_id, gazetteer, kg, instruction_texts, wave,
            )
        except Exception as e:
            logger.warning("[Enrich:L1] instruction anchors failed: %s", e)

    # L2/L3：分区/项目实体语义注解（复用表格提取）
    from app.data.ingestion.tables import _extract_project_tables as _ept, _extract_zone_tables as _ezt

    entities: list = []
    seen: set = set()
    for dim_key, content in (reports or {}).items():
        for zt in _ezt(content):
            key = ("FunctionalZone", zt.land_use)
            if key in seen:
                continue
            seen.add(key)
            entities.append({"entity_name": zt.land_use, "entity_type": "FunctionalZone", "description": f"功能分区{zt.land_use}（源自{dim_key}报告分区表）"})
        for ft in _ept(content):
            key = ("Project", ft.type)
            if key in seen:
                continue
            seen.add(key)
            entities.append({"entity_name": ft.type, "entity_type": "Project", "description": f"规划项目{ft.type}（源自{dim_key}报告项目库）"})

    semantic_written = 0
    for ent in entities:
        name = ent["entity_name"]
        refs = [k for k in (reports or {}) if name in (reports[k] or "")][:1]
        memory.add_entity_annotation(
            __import__("app.infrastructure.kg", fromlist=["EntityAnnotation"]).EntityAnnotation(
                entity_uri=f"pln:semantic_{ent['entity_type']}_{name}",
                entity_type=ent["entity_type"],
                description=ent["description"],
                source_text_refs=refs,
                round_added=wave,
                valid_from_round=wave,
                confidence=0.7,
            )
        )
        semantic_written += 1

    try:
        from app.infrastructure.kg import get_kg_manager

        get_kg_manager().bump_version(session_id)
    except Exception as e:
        logger.warning("[Enrich] version bump failed: %s", e)

    try:
        save_memory_state(session_id, wave)
    except Exception as e:
        logger.warning("[Enrich] memory state save failed: %s", e)

    stats = {
        "wave": wave,
        "village_bound": bound_clusters,
        "anchor_entries": anchor_entries,
        "gis_village_entries": gis_village_entries,
        "semantic_entities": semantic_written,
    }
    logger.info("[Enrich] session=%s stats=%s", session_id, stats)
    return stats


async def run_wave(session_id: str, wave: int, reports: Dict[str, str], bundle: Any = None,
                   instruction_texts: Optional[Dict[str, str]] = None,
                   location_facts: Optional[List[Any]] = None) -> Dict[str, Any]:
    """Wave 末尾入口（completion node 调用，bundle 由 agent 层传入）。"""
    from app.core.settings import GIS_EXPLORE_LLM_ENABLED

    llm = None
    # MiniMax is used for the primary planning stages.  Its optional batch
    # name-confirmation call is deliberately opt-in because a non-JSON answer
    # must not hold the KG enrichment wave for repeated 30s timeouts.  The
    # deterministic spatial gate remains authoritative for bindings.
    from app.core.llm import LLMProvider, get_provider
    semantic_confirm = os.getenv("GIS_ENRICH_LLM_CONFIRM", "").lower() in {"1", "true", "yes"}
    if GIS_EXPLORE_LLM_ENABLED and (get_provider() != LLMProvider.MINIMAX or semantic_confirm):
        from app.core.llm import create_llm
        from app.core.settings import (
            GIS_EXPLORE_MAX_TOKENS,
            GIS_EXPLORE_MODEL,
            GIS_EXPLORE_TEMPERATURE,
        )

        llm = create_llm(
            model=None,
            temperature=GIS_EXPLORE_TEMPERATURE,
            max_tokens=GIS_EXPLORE_MAX_TOKENS,
            streaming=False,
            max_retries=0,  # confirm 失败立即降级确定性裁决，避免重试泥潭拖死 wave
        )
    return await extract_bindings(
        session_id, wave, reports, llm=llm, bundle=bundle,
        instruction_texts=instruction_texts,
        location_facts=location_facts,
    )


__all__ = ["extract_bindings", "run_wave"]
