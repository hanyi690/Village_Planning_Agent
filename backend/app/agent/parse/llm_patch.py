"""PARSE LLM patch generation - REPAIR/REVISE mode (P2).

Wave N: activates the previously-dormant ``llm_patch`` route. Given the
compile result, its diagnostics, and the source PlanningProgram, the Flash
LLM (via Instructor schema enforcement) produces a list of CompilationPatch.
Any failure degrades to [] so the caller falls back to NEEDS_REVIEW (safe).
"""
from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from app.modules.schema.contracts.l3_contracts import PlanningProgram
from app.modules.schema.contracts.parse_result_contracts import (
    CompilationPatch,
    IntentCompilationResult,
    ParseDiagnostic,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MAX_LLM_PATCHES = 5
_MAX_PROGRAM_PREVIEW = 1500


class CompilationPatchList(BaseModel):
    """Instructor schema-enforced LLM output: a bounded list of patches."""

    patches: list[CompilationPatch] = Field(default_factory=list)


def _is_patchable_path(path: str) -> bool:
    """Only paths reachable on the compile result are patchable."""
    if not path:
        return False
    if path in ("project_requirements", "spatial_reference_specs"):
        return True
    return path.startswith("typed_intent.")


def _build_prompt(
    result: IntentCompilationResult,
    diagnostics: list[ParseDiagnostic],
    program: PlanningProgram,
) -> str:
    diag_lines = "\n".join(
        f"- [{d.severity}] {d.code}: {d.message}"
        + (f" (field: {d.field_path})" if d.field_path else "")
        for d in diagnostics
    ) or "（无诊断）"

    intervention_lines = "\n".join(
        f"- {i.intervention_id} | {i.category} | {i.name} | spatial={i.spatial_requirements}"
        for i in program.interventions
    ) or "（无干预项）"
    intervention_lines = intervention_lines[:_MAX_PROGRAM_PREVIEW]

    return f"""你是村庄规划的解析修复助手。给定一次确定性编译的歧义诊断，生成局部 CompilationPatch 列表修复编译结果。

可修补的字段路径（其余路径会失败，不要使用）:
- typed_intent.<字段>（如 typed_intent.project_targets.0.name）
- project_requirements（list 增删）
- spatial_reference_specs（list 增删）

要求:
- 每条 patch 对应一条明确的歧义诊断，最多 {_MAX_LLM_PATCHES} 条
- 只输出高置信修复（confidence >= 0.6），不确定则不要生成
- field_path 必须是可修补路径；before/after 为原值/新值
- rationale 用一句话说明判断依据（不保存推理链）
- 若无需修复，返回空列表

诊断:
{diag_lines}

干预项:
{intervention_lines}

编译结果摘要:
- 状态: {result.compilation_status.value}
- typed_intent 类型: {type(result.typed_intent).__name__ if result.typed_intent else 'None'}
- project_requirements: {len(result.project_requirements)}
- spatial_reference_specs: {len(result.spatial_reference_specs)}
"""


def _finalize_patches(
    patches: list[CompilationPatch],
    result: IntentCompilationResult,
) -> list[CompilationPatch]:
    """Stamp LLM patches with actor/base/ids and drop unsupported paths."""
    base_revision = result.artifact_id or result.base_revision_ref
    finalized: list[CompilationPatch] = []
    for index, patch in enumerate(patches):
        if not _is_patchable_path(patch.field_path):
            logger.debug("[parse:llm_patch] skipping unsupported path: %s", patch.field_path)
            continue
        finalized.append(
            patch.model_copy(
                update={
                    "patch_id": patch.patch_id or f"llm-{index}",
                    "actor": "llm",
                    "base_revision": base_revision,
                }
            )
        )
    return finalized[:_MAX_LLM_PATCHES]


async def generate_llm_patches(
    result: IntentCompilationResult,
    diagnostics: list[ParseDiagnostic],
    program: PlanningProgram,
) -> list[CompilationPatch]:
    """Generate CompilationPatch list from ambiguous compile diagnostics.

    Instructor schema-enforced Flash call, offloaded via ``asyncio.to_thread``.
    Any failure (missing client, network, schema) returns [] (safe fallback).
    """
    from app.core.instructor_client import get_flash_model, get_instructor_client

    try:
        client = get_instructor_client()
        model = get_flash_model()
    except Exception as e:
        logger.warning("[parse:llm_patch] instructor client unavailable: %s", e)
        return []

    prompt = _build_prompt(result, diagnostics, program)

    try:
        payload = await asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            max_tokens=800,
            temperature=0.1,
            max_retries=2,
            response_model=CompilationPatchList,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        logger.warning("[parse:llm_patch] LLM patch generation failed: %s", e)
        return []

    raw = getattr(payload, "patches", None)
    if not raw:
        return []
    return _finalize_patches(list(raw), result)


__all__ = ["CompilationPatchList", "generate_llm_patches"]
