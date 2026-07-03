"""Spike: 验证 GLM Flash via DashScope 对 with_structured_output(method="json_schema") 的支持。

跑 3 次 LocationSummary,若全部返回正确 Pydantic 实例则用 json_schema,
否则降级 method="function_calling"。

用法:
    cd backend && python scripts/spike_structured_output.py
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional, List

# 确保能 import app.*
backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))

# 加载根 .env (DASHSCOPE_API_KEY 等)
from dotenv import load_dotenv
project_root = backend_root.parent
load_dotenv(project_root / ".env")

from app.core.llm import create_flash_llm
from app.services.modules.parsing.schemas import LocationSummary, SocioEconomicSummary


SAMPLE_LOCATION_TEXT = """
梅州市梅县区梅南镇某村,位于梅县区东南部,距梅州城区约15公里。
对外连接道路:G205国道、县道X962。
行政区划:广东省梅州市梅县区梅南镇。
"""

SAMPLE_SOCIO_ECONOMIC_TEXT = """
户籍人口2350人,常住人口1980人,户数680户,劳动力1520人,外出务工420人。
老龄化率18.5%,人均纯收入18600元/年。
第一产业以水稻、柚子种植为主;第二产业以农产品加工为主;第三产业以乡村旅游为主。
"""


async def _try_method(method: str, schema_cls, sample_text: str, dimension_key: str) -> tuple[bool, str]:
    """试一种 method,返回 (成功, 描述)。"""
    llm = create_flash_llm(max_tokens=800, temperature=0.1)
    structured = llm.with_structured_output(schema_cls, method=method)
    try:
        result = await structured.ainvoke(
            f"分析以下规划报告,提取结构化摘要。维度: {dimension_key}\n\n报告内容:\n{sample_text}"
        )
        if isinstance(result, schema_cls):
            return True, f"OK: {type(result).__name__}, province={getattr(result, 'province', None)}, city={getattr(result, 'city', None)}"
        return False, f"返回类型不对: {type(result).__name__} != {schema_cls.__name__}"
    except Exception as e:
        return False, f"异常: {type(e).__name__}: {e}"


async def main():
    print("=" * 70)
    print("Spike: with_structured_output on GLM Flash via DashScope")
    print("=" * 70)

    for method in ("json_schema", "function_calling"):
        print(f"\n--- method={method} ---")
        for i in range(3):
            ok, desc = await _try_method(method, LocationSummary, SAMPLE_LOCATION_TEXT, "location")
            print(f"  LocationSummary 试 {i+1}: {'PASS' if ok else 'FAIL'} — {desc}")
        for i in range(2):
            ok, desc = await _try_method(method, SocioEconomicSummary, SAMPLE_SOCIO_ECONOMIC_TEXT, "socio_economic")
            print(f"  SocioEconomicSummary 试 {i+1}: {'PASS' if ok else 'FAIL'} — {desc}")


if __name__ == "__main__":
    asyncio.run(main())
