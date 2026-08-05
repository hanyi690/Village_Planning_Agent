"""SELECT Agent subpackage - re-exports for backward compatibility.

Wave M2: parse_agent.py has been deleted. parse/parse_async/ParseResult
now live in app.modules.parsing.text_parser. This file re-exports them
for backward compatibility with any code that imports from app.agent.select.
"""

from app.modules.parsing.text_parser import parse, parse_async, ParseResult
from .parse_state import ParseAgentState, SectionInfo

__all__ = ["parse", "parse_async", "ParseResult", "ParseAgentState", "SectionInfo"]
