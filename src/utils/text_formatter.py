"""
Text Formatting Utilities

Shared utility functions for formatting dimension reports and analyses.
Used across multiple subgraphs to maintain consistency and reduce code duplication.
"""

from typing import List, Dict, Tuple
import re


def clean_title_lines(text: str) -> str:
    """
    Clean markdown heading lines from text.

    Removes the # symbols from markdown headings while preserving the heading content.
    This is used to clean up dimension reports before combining them.

    Args:
        text: The text to clean

    Returns:
        Cleaned text with # symbols removed from headings
    """
    if not text:
        return text

    lines = text.split('\n')
    cleaned_lines = []

    # Match markdown heading lines (1-6 # symbols, optional space, then content)
    title_pattern = re.compile(r'^(\s*)(#{1,6})(\s+)(.*?)\s*$')

    for line in lines:
        match = title_pattern.match(line)
        if match:
            # Extract heading content (remove # symbols)
            content = match.group(4)
            # Preserve indentation
            cleaned_line = f"{match.group(1)}{content}"
            cleaned_lines.append(cleaned_line)
        else:
            cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)


def format_dimension_reports(
    analyses: List[Dict[str, str]],
    result_key: str = "dimension_result"
) -> Tuple[Dict[str, str], str]:
    """
    Format dimension analyses into reports dictionary and text.

    This utility function standardizes how dimension reports are formatted
    across different subgraphs (Layer 1, Layer 2, Layer 3).

    Args:
        analyses: List of analysis dictionaries, each containing:
            - dimension_key: The dimension identifier
            - dimension_name: The dimension display name
            - result_key: The analysis result (default: "dimension_result")
        result_key: The key name for the analysis result in the dictionaries

    Returns:
        Tuple of:
        - Dictionary mapping dimension keys to report text
        - Combined text with all dimension reports formatted with markdown headings

    Example:
        >>> analyses = [
        ...     {"dimension_key": "location", "dimension_name": "区位分析", "dimension_result": "..."},
        ...     {"dimension_key": "traffic", "dimension_name": "道路交通", "dimension_result": "..."}
        ... ]
        >>> reports_dict, reports_text = format_dimension_reports(analyses)
        >>> reports_dict["location"]
        '...'
        >>> reports_text
        '## 区位分析\\n\\n...\\n---\\n\\n## 道路交通\\n\\n...\\n---'
    """
    dimension_reports_dict = {}
    dimension_reports_text = []

    for analysis in analyses:
        dimension_key = analysis['dimension_key']
        dimension_name = analysis['dimension_name']
        analysis_text = analysis[result_key]

        # Store in dictionary
        dimension_reports_dict[dimension_key] = analysis_text

        # Add to formatted text
        dimension_reports_text.append(f"## {dimension_name}\n\n{analysis_text}\n---")

    return dimension_reports_dict, "\n".join(dimension_reports_text)


def format_dimension_reports_with_cleaning(
    analyses: List[Dict[str, str]],
    result_key: str = "dimension_result"
) -> Tuple[Dict[str, str], str]:
    """
    Format dimension analyses with title cleaning.

    Same as format_dimension_reports, but also cleans markdown heading lines
    from each dimension's analysis text before combining.

    Args:
        analyses: List of analysis dictionaries
        result_key: The key name for the analysis result

    Returns:
        Tuple of (reports dictionary, combined text with cleaned headings)
    """
    dimension_reports_dict = {}
    dimension_reports_text = []

    for analysis in analyses:
        dimension_key = analysis['dimension_key']
        dimension_name = analysis['dimension_name']
        analysis_text = analysis[result_key]

        # Clean the analysis text
        cleaned_text = clean_title_lines(analysis_text)

        # Store cleaned version in dictionary
        dimension_reports_dict[dimension_key] = cleaned_text

        # Add to formatted text
        dimension_reports_text.append(f"## {dimension_name}\n\n{cleaned_text}\n---")

    return dimension_reports_dict, "\n".join(dimension_reports_text)
