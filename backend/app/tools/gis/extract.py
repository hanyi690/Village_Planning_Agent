"""Tool: extract_structured_text — table text → structured JSON rows.

Split from parse_tools.py during Phase C refactor.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.utils.logger import get_logger
from app.tools.helpers import make_result

logger = get_logger(__name__)


class TableRow(BaseModel):
    """A single structured table row."""
    pass


class TableExtractionResult(BaseModel):
    """Structured output for table extraction."""
    rows: List[Dict[str, Any]] = []
    column_names: List[str] = []
    confidence: float = 1.0


@tool
async def extract_structured_text(
    section_content: str,
    table_type: str = "general",
) -> Dict[str, Any]:
    """Extract structured rows from table-containing section text.

    Uses LLM with structured output to parse markdown/plain tables
    into List[Dict] row data.

    Args:
        section_content: Text content containing tables
        table_type: Type hint for the table (land_use, indicator, facility, project, general)

    Returns:
        Dict with 'rows', 'column_names', and 'confidence'.
    """
    try:
        from app.core.llm import create_llm, create_flash_llm
        from app.modules.prompts.parse_prompts import EXTRACT_TABLES_PROMPT

        # Use thinking-enabled LLM via factory (includes request_timeout, api_key, streaming)
        # max_tokens=32768 must be >> thinking_budget=2000 (DashScope: max_tokens = thinking + output total)
        # thinking_budget=2000 caps thinking tokens, leaving ~30000 for JSON output
        llm = create_llm(
            temperature=0,
            max_tokens=32768,
            streaming=True,
            extra_body={"enable_thinking": True, "thinking_budget": 2000},
        )

        prompt = EXTRACT_TABLES_PROMPT.format(section_content=section_content)

        # Stage 1: json_schema structured output (qwen3.7-plus supports this natively)
        try:
            structured_llm = llm.with_structured_output(
                TableExtractionResult, method="json_schema"
            )
            result = await structured_llm.ainvoke([
                SystemMessage(content=f"{prompt}\n\nReturn JSON output."),
                HumanMessage(content=section_content),
            ])
            if result is not None:
                return make_result(
                    success=True,
                    data={
                        "rows": result.rows,
                        "column_names": result.column_names,
                        "confidence": result.confidence,
                    },
                )
        except Exception as parse_err:
            logger.debug("[extract_structured_text] Stage 1 failed: %s", parse_err)

        # Stage 2: Raw invoke + manual JSON parse
        raw = None
        try:
            from langchain_core.messages import AIMessage
            raw_response = await llm.ainvoke([
                SystemMessage(content=f"{prompt}\n\nReturn JSON output."),
                HumanMessage(content=section_content),
            ])
            raw = raw_response.content if hasattr(raw_response, 'content') else str(raw_response)

            # Manual JSON extraction
            import re
            json_str = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
            json_str = re.sub(r'\s*```$', '', json_str, flags=re.MULTILINE)

            obj_s = json_str.find('{')
            arr_s = json_str.find('[')
            if arr_s != -1 and (obj_s == -1 or arr_s < obj_s):
                # LLM returned a list — wrap as {"rows": [...]}
                depth, end = 0, arr_s
                for i in range(arr_s, len(json_str)):
                    if json_str[i] == '[': depth += 1
                    elif json_str[i] == ']':
                        depth -= 1
                        if depth == 0: end = i + 1; break
                parsed = json.loads(json_str[arr_s:end])
                result = TableExtractionResult(
                    rows=parsed if isinstance(parsed, list) else [parsed]
                )
            elif obj_s != -1:
                depth, end = 0, obj_s
                for i in range(obj_s, len(json_str)):
                    if json_str[i] == '{': depth += 1
                    elif json_str[i] == '}':
                        depth -= 1
                        if depth == 0: end = i + 1; break
                result = TableExtractionResult.model_validate_json(json_str[obj_s:end])
            else:
                raise parse_err

            return make_result(
                success=True,
                data={
                    "rows": result.rows,
                    "column_names": result.column_names,
                    "confidence": result.confidence,
                },
            )
        except Exception as e2:
            logger.debug("[extract_structured_text] Stage 2 failed: %s", e2)

        # Stage 3: Flash model JSON repair
        if raw:
            try:
                fast_llm = create_flash_llm(temperature=0)
                structured_fast = fast_llm.with_structured_output(
                    TableExtractionResult, method="json_mode"
                )
                result = await structured_fast.ainvoke([
                    SystemMessage(content="你是 JSON 格式修复专家。将以下文本修复为有效 JSON。仅输出 JSON。"),
                    HumanMessage(content=raw[:4000]),
                ])
                if result is not None:
                    return make_result(
                        success=True,
                        data={
                            "rows": result.rows,
                            "column_names": result.column_names,
                            "confidence": result.confidence,
                        },
                    )
            except Exception as e3:
                logger.warning("[extract_structured_text] Stage 3 (flash repair) failed: %s", e3)

        return make_result(success=False, error="All 3 stages failed")
    except Exception as e:
        logger.warning("[extract_structured_text] Failed: %s", e)
        return make_result(success=False, error=str(e))


__all__ = ["extract_structured_text"]
