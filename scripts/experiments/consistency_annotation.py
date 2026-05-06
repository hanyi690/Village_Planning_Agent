"""
Consistency Annotation Script
语义一致性标注模板生成

生成用于人工复核的标注表格，包含关键词检出率计算。

使用方法:
    python scripts/experiments/consistency_annotation.py --scenario scenario1
    python scripts/experiments/consistency_annotation.py --scenario scenario2

输出:
    - consistency_annotation.xlsx
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.experiments.config import (
    SCENARIOS,
    ANNOTATION_FIELDS,
    get_scenario_config,
    get_output_dir,
    ensure_output_dirs,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ============================================
# Keyword Analysis
# ============================================

def analyze_keywords(content: str, keywords: Dict[str, List[str]]) -> Dict[str, Any]:
    """
    Analyze content for keyword presence.

    Args:
        content: Text content to analyze
        keywords: {"positive": [...], "negative": [...]}

    Returns:
        Analysis results with coverage rates
    """
    positive_keywords = keywords.get("positive", [])
    negative_keywords = keywords.get("negative", [])

    # Count positive keyword occurrences
    positive_found = []
    positive_coverage = 0.0
    if positive_keywords:
        for kw in positive_keywords:
            if kw in content:
                positive_found.append(kw)
        positive_coverage = len(positive_found) / len(positive_keywords) * 100

    # Count negative keyword occurrences (should be removed)
    negative_found = []
    negative_residual = ""
    if negative_keywords:
        for kw in negative_keywords:
            if kw in content:
                negative_found.append(kw)
        negative_residual = ", ".join(negative_found)

    return {
        "positive_found": positive_found,
        "positive_coverage": positive_coverage,
        "negative_found": negative_found,
        "negative_residual": negative_residual,
    }


# ============================================
# Annotation Table Generation
# ============================================

def generate_annotation_table(
    scenario_name: str,
    revision_history: List[Dict[str, Any]],
    baseline_reports: Dict[str, Dict[str, str]],
    updated_reports: Dict[str, Dict[str, str]],
) -> List[Dict[str, Any]]:
    """
    Generate annotation table for human review.

    Args:
        scenario_name: Scenario name
        revision_history: Revision history entries
        baseline_reports: Original reports
        updated_reports: Updated reports

    Returns:
        List of annotation rows
    """
    config = get_scenario_config(scenario_name)
    keywords = config.get("keywords", {})
    target_dimension = config["target_dimension"]

    annotation_rows = []

    for entry in revision_history:
        dim = entry.get("dimension")
        layer = entry.get("layer")
        wave = entry.get("wave", 0)
        is_target = entry.get("is_target", False)

        # Get old and new content
        layer_key = f"layer{layer}"
        old_content = baseline_reports.get(layer_key, {}).get(dim, "")
        new_content = updated_reports.get(layer_key, {}).get(dim, entry.get("new_content", ""))

        # Analyze keywords in new content
        # Use scenario-specific keywords only for target dimension
        analysis_keywords = keywords if is_target else {"positive": [], "negative": []}
        analysis = analyze_keywords(new_content, analysis_keywords)

        # Get dimension name
        from src.config.dimension_metadata import get_dimension_config
        dim_config = get_dimension_config(dim)
        dimension_name = dim_config.get("name", dim) if dim_config else dim

        row = {
            "dimension_key": dim,
            "dimension_name": dimension_name,
            "layer": layer,
            "wave": wave,
            "is_target_dimension": is_target,
            "positive_keywords_expected": ", ".join(analysis_keywords.get("positive", [])),
            "positive_keywords_found": ", ".join(analysis["positive_found"]),
            "positive_keyword_coverage": f"{analysis['positive_coverage']:.1f}%",
            "negative_keywords_expected": ", ".join(analysis_keywords.get("negative", [])),
            "negative_keyword_residual": analysis["negative_residual"],
            "old_content_preview": old_content[:200] if old_content else "",
            "new_content_preview": new_content[:200] if new_content else "",
            "human_judgment": "",  # To be filled by human
            "notes": "",  # To be filled by human
        }
        annotation_rows.append(row)

    return annotation_rows


def save_annotation_csv(annotation_rows: List[Dict[str, Any]], output_path: Path):
    """
    Save annotation table as CSV.

    Args:
        annotation_rows: Annotation row data
        output_path: Output file path
    """
    import csv

    # Get field names from first row
    if not annotation_rows:
        logger.warning("[Annotation] No rows to save")
        return

    fieldnames = list(annotation_rows[0].keys())

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(annotation_rows)

    logger.info(f"[Annotation] Saved CSV: {output_path}")


def save_annotation_json(annotation_rows: List[Dict[str, Any]], output_path: Path):
    """
    Save annotation table as JSON.

    Args:
        annotation_rows: Annotation row data
        output_path: Output file path
    """
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(annotation_rows, f, indent=2, ensure_ascii=False)

    logger.info(f"[Annotation] Saved JSON: {output_path}")


# ============================================
# Main Entry Point
# ============================================

def generate_consistency_annotation(scenario_name: str):
    """
    Generate consistency annotation template for a scenario.

    Args:
        scenario_name: Scenario name (scenario1 or scenario2)
    """
    ensure_output_dirs()

    if scenario_name not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario_name}")

    logger.info("=" * 60)
    logger.info(f"[Annotation] Generating annotation for {scenario_name}")
    logger.info("=" * 60)

    output_dir = get_output_dir(scenario_name)

    # Load revision history
    revision_file = output_dir / "revision_history.json"
    if not revision_file.exists():
        logger.error(f"[Annotation] Revision history not found: {revision_file}")
        raise FileNotFoundError(f"Please run scenario first: python scripts/experiments/run_scenario.py --scenario {scenario_name}")

    with open(revision_file, "r", encoding="utf-8") as f:
        revision_history = json.load(f)

    # Load baseline reports
    baseline_reports = {}
    baseline_dir = get_output_dir("baseline")
    for layer in [1, 2, 3]:
        layer_file = baseline_dir / f"layer{layer}_reports.json"
        if layer_file.exists():
            with open(layer_file, "r", encoding="utf-8") as f:
                layer_data = json.load(f)
            baseline_reports[f"layer{layer}"] = layer_data.get("reports", {})

    # Load updated reports (from dimension diffs)
    updated_reports = {}
    diffs_dir = output_dir / "dimension_diffs"
    if diffs_dir.exists():
        for dim_file in diffs_dir.glob("*.json"):
            with open(dim_file, "r", encoding="utf-8") as f:
                dim_data = json.load(f)
            dim = dim_data.get("dimension")
            layer = dim_data.get("layer")
            layer_key = f"layer{layer}"
            if layer_key not in updated_reports:
                updated_reports[layer_key] = {}
            updated_reports[layer_key][dim] = dim_data.get("new_content", "")

    # Generate annotation table
    annotation_rows = generate_annotation_table(
        scenario_name=scenario_name,
        revision_history=revision_history,
        baseline_reports=baseline_reports,
        updated_reports=updated_reports,
    )

    # Save results
    save_annotation_csv(annotation_rows, output_dir / "consistency_annotation.csv")
    save_annotation_json(annotation_rows, output_dir / "consistency_annotation.json")

    # Print summary
    logger.info("=" * 60)
    logger.info(f"[Annotation] Generated {len(annotation_rows)} annotation rows")
    logger.info("=" * 60)

    # Print table preview
    print("\n标注表格预览:")
    print("-" * 100)
    for row in annotation_rows[:5]:
        print(f"{row['dimension_name']} (Layer {row['layer']}, Wave {row['wave']}):")
        print(f"  正向关键词检出: {row['positive_keywords_found']}")
        print(f"  正向关键词覆盖率: {row['positive_keyword_coverage']}")
        print(f"  残留负面关键词: {row['negative_keyword_residual']}")
        print("-" * 100)

    return annotation_rows


def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Generate consistency annotation")
    parser.add_argument("--scenario", required=True, choices=["scenario1", "scenario2"], help="Scenario name")
    args = parser.parse_args()

    generate_consistency_annotation(args.scenario)


if __name__ == "__main__":
    main()