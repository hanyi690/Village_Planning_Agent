"""报告 → KG 实体注解（多级增强入口，自 parse/agent.py extract_bindings 迁入）。

L1 级（wave1）：村名→gazetteer 绑定（Flash 双确认 + 空间校验）→ EntityAnnotation(cluster_uri)
L2/L3 级（wave2/3）：功能分区/项目实体语义注解（表格提取）
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

_VLL_RE = re.compile(r"([\u4e00-\u9fff]{2,8}村)")
_BSM_NUM_RE = re.compile(r"(\d{15,25})")

# 金田村 12 个自然村（行政事实，规划文本 L160）— 用于过滤"金田村(村域)/个自然村(泛称)"等非村名
_KNOWN_NATURAL_VILLAGES = {
    "园寨", "田坑", "社前", "分水", "清明", "塘笃",
    "长塘", "炉池", "肩丰", "营仔", "新山", "黄竹",
}
_VIL_EXCLUDES = {"金田村", "自然村", "全村", "该村", "各村", "本村"}


def _is_village_name(name: str) -> bool:
    if name in _VIL_EXCLUDES:
        return False
    if name.endswith("自然村"):
        base = name[:-3]
    elif name.endswith("村"):
        base = name[:-1]
    else:
        base = name
    return base in _KNOWN_NATURAL_VILLAGES


def _get_semantic_memory():
    from app.modules.kg import get_semantic_memory

    return get_semantic_memory()


def _extract_village_mentions(reports: Dict[str, str]) -> List[Dict[str, str]]:
    """村名 + 特征窗口提取（L1 回流输入）。"""
    mentions: List[Dict[str, str]] = []
    seen = set()
    for dim_key, content in (reports or {}).items():
        for m in _VLL_RE.finditer(content or ""):
            name = m.group(1)
            if not _is_village_name(name) or name in seen:
                continue
            seen.add(name)
            window = (content or "")[m.start(): m.start() + 120]
            mentions.append({"name": name, "hints": window[:80], "dim": dim_key})
    return mentions


async def _bind_village_to_cluster(
    mention: Dict[str, str],
    gazetteer: Any,
    kg: Any,
    llm: Any,
    round_num: int,
) -> Optional[str]:
    """村名 → gazetteer → 聚类绑定；Flash 双确认（LLM ∧ 空间校验）。

    村名无 gazetteer 条目时（KG 聚类名是"居民点N"，无村名）：
      候选生成 — 按村名特征 hints 与各聚类地块 dlbm 构成的空间校验匹配；
      候选>1 时 Flash 确认；绑定后 upsert gazetteer 条目（source=l1_enrichment）。
    """
    from app.modules.kg import EntityAnnotation
    from app.modules.kg.gazetteer import confirm_with_llm, spatial_score
    from app.modules.kg.ontology import PLN

    # 预构建 bsm→dlbm 映射（一次全图扫描，避免逐候选重复扫）
    bsm_to_dlbm: Dict[str, str] = {}
    try:
        for s, _, o in kg.g.triples((None, PLN.bsm, None)):
            bsm = str(o)
            for _, _, d in kg.g.triples((s, PLN.dlbm, None)):
                bsm_to_dlbm[bsm] = str(d)
                break
    except Exception:
        pass

    def _cluster_dlbms(entry) -> List[str]:
        return [bsm_to_dlbm[b] for b in (entry.bsms or []) if b in bsm_to_dlbm]

    entry = gazetteer.resolve(mention["name"])
    candidates: List[Any] = []
    if entry is not None and entry.entity_uri:
        candidates = [entry]
    else:
        # 候选生成：特征 hints 与聚类 dlbm 构成的空间校验
        for e in gazetteer.entries:
            if not e.entity_uri:
                continue
            if spatial_score(mention["hints"], _cluster_dlbms(e)) > 0:
                candidates.append(e)

    if not candidates:
        return None

    # Flash 双确认：候选>1 时 LLM 判定；无 LLM 时确定性打分裁决（唯一最高分才绑定）
    chosen = None
    if len(candidates) == 1:
        chosen = candidates[0]
    elif llm is not None:
        for e in candidates:
            ok = await confirm_with_llm(llm, mention["name"], e.name, e.description or e.name)
            if ok:
                chosen = e
                break
    else:
        scored = sorted(
            ((spatial_score(mention["hints"], _cluster_dlbms(e)), e) for e in candidates),
            key=lambda x: -x[0],
        )
        if scored and scored[0][0] > 0:
            top_score = scored[0][0]
            top = [e for s, e in scored if s == top_score]
            if len(top) == 1:
                chosen = top[0]
    if chosen is None:
        logger.info("[Enrich:L1] %s -> %d candidates unresolved", mention["name"], len(candidates))
        return None

    # 空间校验终审（候选生成的已过；直接命中条目的补校验）
    if entry is not None:
        ok_space = spatial_check(mention["hints"], _cluster_dlbms(chosen))
        if not ok_space:
            logger.info("[Enrich:L1] %s -> %s rejected (space)", mention["name"], chosen.name)
            return None

    # upsert gazetteer 条目（村名 → 聚类，供 Binder/渲染解析）
    from app.modules.kg.gazetteer import GazetteerEntry, save_gazetteer
    from app.modules.kg.gazetteer.gazetteer import gazetteer_path

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
    try:
        save_gazetteer(gazetteer, "jintian")
    except Exception as e:
        logger.warning("[Enrich] gazetteer save failed: %s", e)

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


async def extract_bindings(
    session_id: str,
    wave: int,
    reports: Dict[str, str],
    llm: Any = None,
    kg: Any = None,
    bundle: Any = None,
) -> Dict[str, Any]:
    """实体语义增强：村名→gazetteer 绑定（L1）+ 分区/项目实体注解（L2/L3）。

    迁移自 app/agent/gis/parse/agent.py::extract_bindings（PARSE 职责纯净后）。
    """
    from app.modules.kg import require_session_kg
    from app.modules.kg.gazetteer import build_gazetteer
    from app.modules.kg.gazetteer.gazetteer import save_gazetteer
    from app.modules.kg.memory import save_memory_state

    kg = kg if kg is not None else require_session_kg(session_id)

    memory = _get_semantic_memory()
    gazetteer = build_gazetteer(kg, bundle, memory)
    if gazetteer.entries:
        try:
            save_gazetteer(gazetteer, "jintian")
        except Exception as e:
            logger.warning("[Enrich] gazetteer save failed: %s", e)

    bound_clusters = 0
    if wave in (1, 3):
        for mention in _extract_village_mentions(reports):
            uri = await _bind_village_to_cluster(mention, gazetteer, kg, llm, wave)
            if uri:
                bound_clusters += 1

    # L2/L3：分区/项目实体语义注解（复用表格提取）
    from app.modules.parsing.tables import _extract_project_tables as _ept, _extract_zone_tables as _ezt

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
            __import__("app.modules.kg", fromlist=["EntityAnnotation"]).EntityAnnotation(
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
        from app.modules.kg import get_kg_manager

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
        "semantic_entities": semantic_written,
    }
    logger.info("[Enrich] session=%s stats=%s", session_id, stats)
    return stats


async def run_wave(session_id: str, wave: int, reports: Dict[str, str], bundle: Any = None) -> Dict[str, Any]:
    """Wave 末尾入口（completion node 调用，bundle 由 agent 层传入）。"""
    from app.core.settings import GIS_EXPLORE_LLM_ENABLED

    llm = None
    if GIS_EXPLORE_LLM_ENABLED:
        from app.core.llm import create_llm
        from app.core.settings import (
            GIS_EXPLORE_MAX_TOKENS,
            GIS_EXPLORE_MODEL,
            GIS_EXPLORE_TEMPERATURE,
        )

        llm = create_llm(
            model=GIS_EXPLORE_MODEL,
            temperature=GIS_EXPLORE_TEMPERATURE,
            max_tokens=GIS_EXPLORE_MAX_TOKENS,
            streaming=False,
        )
    return await extract_bindings(session_id, wave, reports, llm=llm, bundle=bundle)


__all__ = ["extract_bindings", "run_wave"]
