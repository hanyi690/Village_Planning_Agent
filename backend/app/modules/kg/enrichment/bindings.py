"""报告 → KG 实体注解（多级增强入口，自 parse/agent.py extract_bindings 迁入）。

L1 级（wave1）：村名→gazetteer 绑定（Flash 双确认 + 空间校验）→ EntityAnnotation(cluster_uri)
L2/L3 级（wave2/3）：功能分区/项目实体语义注解（表格提取）
"""

from __future__ import annotations
import asyncio

import json
import re
from typing import Any, Dict, List, Optional, Tuple

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


_BATCH_CONFIRM_SIZE = 15  # 批量判定小批大小（单次 prompt 可读性优先，避免 104 对全量一次）
_BATCH_CONFIRM_TIMEOUT = 30


def _build_bsm_to_dlbm(kg: Any) -> Dict[str, str]:
    """预构建 bsm→dlbm 映射（一次全图扫描，逐 mention 共享）。"""
    from app.modules.kg.ontology import PLN

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
    from app.modules.kg.gazetteer import spatial_score

    entry = gazetteer.resolve(mention["name"])
    if entry is not None and entry.entity_uri:
        return [entry]
    return [
        e for e in gazetteer.entries
        if e.entity_uri
        and spatial_score(mention["hints"], _cluster_dlbms(e, bsm_to_dlbm)) > 0
    ]


def _deterministic_pick(mention: Dict[str, str], candidates: List[Any], bsm_to_dlbm: Dict[str, str]) -> Optional[Any]:
    """无 LLM / LLM 不可用时的确定性打分裁决：唯一最高分才绑定。"""
    from app.modules.kg.gazetteer import spatial_score

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
    """绑定落库：空间校验终审 → gazetteer upsert（l1_enrichment）→ EntityAnnotation。"""
    from app.modules.kg import EntityAnnotation
    from app.modules.kg.gazetteer import GazetteerEntry, save_gazetteer, spatial_check

    if not spatial_check(mention["hints"], _cluster_dlbms(chosen, bsm_to_dlbm)):
        logger.info("[Enrich:L1] %s -> %s rejected (space)", mention["name"], chosen.name)
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
        bsm_to_dlbm = _build_bsm_to_dlbm(kg)
        mentions = _extract_village_mentions(reports)
        direct_picks = []          # 候选==1（gazetteer 命中）直接绑定
        ambiguous = []             # 候选>1 → 批量 LLM 判定
        unresolved_amb = []
        for mention in mentions:
            candidates = _gather_candidates(mention, gazetteer, bsm_to_dlbm)
            if not candidates:
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
            max_retries=0,  # confirm 失败立即降级确定性裁决，避免重试泥潭拖死 wave
        )
    return await extract_bindings(session_id, wave, reports, llm=llm, bundle=bundle)


__all__ = ["extract_bindings", "run_wave"]
