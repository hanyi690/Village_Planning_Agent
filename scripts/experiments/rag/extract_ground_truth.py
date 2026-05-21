"""Ground Truth Extractor - Extract dimension-specific content from authoritative documents.

This script extracts content from the 4 authoritative planning documents
and creates Ground Truth files for each evaluation dimension.

IMPORTANT:
- 知识依据(knowledge): 来自现状报告，是忠实度评估的核心依据
- 质量参照(quality_reference): 来自规划文档，用于质量上限对照

Usage:
    python scripts/experiments/rag/extract_ground_truth.py

Output:
    output/experiments/rag/ground_truth/{dimension_key}_knowledge.md
    output/experiments/rag/ground_truth/{dimension_key}_quality_reference.md
"""

import logging
import re
from pathlib import Path
from typing import List, Optional

import sys

# Add project paths
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = _PROJECT_ROOT / "backend"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from scripts.experiments.rag.ground_truth_config import (
    DOCUMENTS,
    DIMENSION_MAPPINGS,
    DimensionMapping,
    SectionMapping,
    get_layer_dimensions,
)

logger = logging.getLogger(__name__)


class GroundTruthExtractor:
    """Extracts Ground Truth content from authoritative documents."""

    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or _PROJECT_ROOT / "output/experiments/rag/ground_truth"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._document_cache = {}

    def load_document(self, doc_key: str) -> str:
        """Load a document from disk."""
        if doc_key in self._document_cache:
            return self._document_cache[doc_key]

        doc_path = DOCUMENTS.get(doc_key)
        if not doc_path or not doc_path.exists():
            logger.warning("Document not found: %s", doc_key)
            return ""

        content = doc_path.read_text(encoding="utf-8")
        self._document_cache[doc_key] = content
        logger.info("Loaded document: %s (%d chars)", doc_key, len(content))
        return content

    def find_section_content(
        self,
        document: str,
        section_start: str,
        section_end: Optional[str] = None,
    ) -> str:
        """Extract content between section markers.

        Args:
            document: Full document text
            section_start: Section title to find start
            section_end: Section title to find end (None = until next major section)

        Returns:
            Extracted section content
        """
        # Find start position - try various heading formats
        # Handle both plain and bold (**text**) formats
        start_patterns = [
            f"# {section_start}",  # H1 heading
            f"## {section_start}",  # H2 heading
            f"### {section_start}",  # H3 heading
            f"# **{section_start}**",  # H1 bold
            f"## **{section_start}**",  # H2 bold (common in MinerU output)
            f"### **{section_start}**",  # H3 bold
            section_start,  # Plain text
        ]

        start_pos = -1
        for pattern in start_patterns:
            idx = document.find(pattern)
            if idx != -1:
                start_pos = idx
                break

        if start_pos == -1:
            logger.warning("Section start not found: %s", section_start)
            return ""

        # Find end position
        if section_end:
            end_patterns = [
                f"# {section_end}",
                f"## {section_end}",
                f"### {section_end}",
                f"# **{section_end}**",
                f"## **{section_end}**",
                f"### **{section_end}**",
                section_end,
            ]

            end_pos = len(document)
            for pattern in end_patterns:
                idx = document.find(pattern, start_pos + len(section_start))
                if idx != -1:
                    end_pos = idx
                    break
        else:
            # No end marker - take until next major section or end of file
            # For bracketed sections like "# 【xxx】", skip numbered subsections like "# 一、xxx"
            remaining = document[start_pos:]

            # Check if this is a bracketed section (e.g., "# 【xxx】")
            is_bracketed = bool(re.match(r'^#+\s*【[^】]+】', remaining))

            if is_bracketed:
                # For bracketed sections, find next bracketed section or end
                next_section_match = re.search(r'\n#+\s*【[^】]+】', remaining[1:])
                if next_section_match:
                    end_pos = start_pos + 1 + next_section_match.start()
                else:
                    end_pos = len(document)
            else:
                # For regular sections, find next section heading
                next_section_match = re.search(r'\n#+\s+', remaining[1:])
                if next_section_match:
                    end_pos = start_pos + 1 + next_section_match.start()
                else:
                    end_pos = len(document)

        content = document[start_pos:end_pos].strip()
        return content

    def extract_sections_content(
        self,
        sections: List[SectionMapping],
    ) -> str:
        """Extract content from multiple sections.

        Args:
            sections: List of section mappings

        Returns:
            Combined content from all sections
        """
        contents = []

        for section in sections:
            doc_content = self.load_document(section.doc_key)
            if not doc_content:
                continue

            section_content = self.find_section_content(
                doc_content,
                section.section_start,
                section.section_end,
            )

            if section_content:
                contents.append(section_content)

        if not contents:
            return ""

        return "\n\n---\n\n".join(contents)

    def extract_dimension(self, mapping: DimensionMapping) -> dict:
        """Extract both knowledge and quality reference for a dimension.

        Args:
            mapping: Dimension mapping configuration

        Returns:
            Dictionary with 'knowledge' and 'quality_reference' keys
        """
        result = {
            "knowledge": "",
            "quality_reference": "",
        }

        # Extract knowledge (from status report)
        if mapping.knowledge_sections:
            result["knowledge"] = self.extract_sections_content(mapping.knowledge_sections)

        # Extract quality reference (from planning documents)
        if mapping.quality_reference:
            result["quality_reference"] = self.extract_sections_content(mapping.quality_reference)

        return result

    def extract_all(self) -> dict:
        """Extract Ground Truth for all dimensions.

        Returns:
            Dictionary mapping dimension_key to {knowledge, quality_reference}
        """
        results = {}

        for dim_key, mapping in DIMENSION_MAPPINGS.items():
            logger.info("Extracting Ground Truth for: %s", dim_key)

            content = self.extract_dimension(mapping)
            results[dim_key] = content

            # Save knowledge file
            if content["knowledge"]:
                knowledge_file = self.output_dir / f"{dim_key}_knowledge.md"
                knowledge_file.write_text(content["knowledge"], encoding="utf-8")
                logger.info("  -> Knowledge: %s (%d chars)", knowledge_file.name, len(content["knowledge"]))

            # Save quality reference file
            if content["quality_reference"]:
                ref_file = self.output_dir / f"{dim_key}_quality_reference.md"
                ref_file.write_text(content["quality_reference"], encoding="utf-8")
                logger.info("  -> Quality Ref: %s (%d chars)", ref_file.name, len(content["quality_reference"]))

        return results

    def generate_summary(self, results: dict) -> str:
        """Generate a summary report of extracted Ground Truth.

        Args:
            results: Dictionary of extracted content

        Returns:
            Summary markdown text
        """
        lines = [
            "# Ground Truth Extraction Summary",
            "",
            "## 评估原则",
            "",
            "- **知识依据(knowledge)**: 来自现状报告，是忠实度评估的核心依据",
            "- **质量参照(quality_reference)**: 来自规划文档，用于质量上限对照",
            "",
            f"**Output Directory**: `{self.output_dir}`",
            "",
            "## L1 Dimensions (现状分析)",
            "",
            "| 维度 | 维度名称 | 知识依据字符数 | 质量参照字符数 |",
            "|------|----------|----------------|----------------|",
        ]

        for dim_key in get_layer_dimensions(1):
            content = results.get(dim_key, {})
            dim_name = DIMENSION_MAPPINGS[dim_key].dimension_name
            k_len = len(content.get("knowledge", ""))
            q_len = len(content.get("quality_reference", ""))
            lines.append(f"| {dim_key} | {dim_name} | {k_len} | {q_len if q_len else '-'} |")

        lines.extend([
            "",
            "## L3 Dimensions (详细规划)",
            "",
            "| 维度 | 维度名称 | 知识依据字符数 | 质量参照字符数 |",
            "|------|----------|----------------|----------------|",
        ])

        for dim_key in get_layer_dimensions(3):
            content = results.get(dim_key, {})
            dim_name = DIMENSION_MAPPINGS[dim_key].dimension_name
            k_len = len(content.get("knowledge", ""))
            q_len = len(content.get("quality_reference", ""))
            lines.append(f"| {dim_key} | {dim_name} | {k_len} | {q_len if q_len else '-'} |")

        # Statistics
        total_knowledge = sum(len(r.get("knowledge", "")) for r in results.values())
        total_quality = sum(len(r.get("quality_reference", "")) for r in results.values())

        lines.extend([
            "",
            "## Statistics",
            "",
            f"- Total dimensions: {len(results)}",
            f"- Total knowledge chars: {total_knowledge:,}",
            f"- Total quality reference chars: {total_quality:,}",
            "",
            "---",
            "",
            "*Generated by Ground Truth Extractor*",
        ])

        return "\n".join(lines)


def main():
    """Run Ground Truth extraction."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    logger.info("=" * 60)
    logger.info("Ground Truth Extraction")
    logger.info("=" * 60)

    extractor = GroundTruthExtractor()

    # Extract all dimensions
    results = extractor.extract_all()

    # Generate and save summary
    summary = extractor.generate_summary(results)
    summary_file = extractor.output_dir / "extraction_summary.md"
    summary_file.write_text(summary, encoding="utf-8")

    logger.info("Summary saved to: %s", summary_file)

    # Print summary
    print("\n" + "=" * 60)
    print("Ground Truth Extraction Complete")
    print("=" * 60)
    print(f"\nOutput directory: {extractor.output_dir}")
    print(f"Total dimensions: {len(results)}")

    # Print per-layer stats
    l1_knowledge = sum(len(results.get(k, {}).get("knowledge", "")) for k in get_layer_dimensions(1))
    l3_knowledge = sum(len(results.get(k, {}).get("knowledge", "")) for k in get_layer_dimensions(3))
    l3_quality = sum(len(results.get(k, {}).get("quality_reference", "")) for k in get_layer_dimensions(3))

    print(f"\nL1 (现状分析): {len(get_layer_dimensions(1))} dimensions, knowledge: {l1_knowledge:,} chars")
    print(f"L3 (详细规划): {len(get_layer_dimensions(3))} dimensions, knowledge: {l3_knowledge:,} chars, quality_ref: {l3_quality:,} chars")


if __name__ == "__main__":
    main()
