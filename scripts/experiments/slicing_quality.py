"""
Slicing Quality Assessment Module
切片质量评估模块

评估知识库切片质量，对比新旧切片器的改进效果。

核心指标：
- total_chunks: 切片总数
- avg_chunk_length: 平均长度
- chinese_ratio_avg: 中文比例平均值
- spine_text_count: 书脊文字残留数量
- toc_noise_count: 目录噪音残留数量
- short_chunk_count: 短切片数(<30字符)

使用方法:
    python scripts/experiments/slicing_quality.py [--kb-dir path]

输出:
    - slicing_quality_metrics.json
"""

import json
import logging
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ============================================
# Quality Metrics Data Class
# ============================================

@dataclass
class SlicingQualityMetrics:
    """切片质量指标"""
    total_chunks: int = 0
    avg_chunk_length: float = 0.0
    chinese_ratio_avg: float = 0.0
    spine_text_count: int = 0
    toc_noise_count: int = 0
    short_chunk_count: int = 0
    low_chinese_ratio_count: int = 0

    # Additional metrics
    min_chunk_length: int = 0
    max_chunk_length: int = 0
    median_chunk_length: float = 0.0
    std_chunk_length: float = 0.0

    # Source metadata
    kb_dir: str = ""
    evaluated_at: str = ""
    document_types: Dict[str, int] = {}


# ============================================
# Quality Detection Functions
# ============================================

def is_spine_text(text: str) -> bool:
    """
    Detect spine text pattern (single characters on separate lines).

    书脊文字特征：单字独占一行，超过40%的行。

    Args:
        text: Chunk content

    Returns:
        True if detected as spine text
    """
    lines = [l for l in text.split('\n') if l.strip()]
    if not lines:
        return False

    single_char_lines = sum(1 for l in lines if len(l.strip()) == 1)
    ratio = single_char_lines / len(lines)

    return ratio > 0.4


def is_toc_noise(text: str) -> bool:
    """
    Detect TOC (Table of Contents) noise pattern.

    目录噪音特征：大量短行（<8字符），超过60%。

    Args:
        text: Chunk content

    Returns:
        True if detected as TOC noise
    """
    lines = [l for l in text.split('\n') if l.strip()]
    if not lines:
        return False

    short_lines = sum(1 for l in lines if len(l.strip()) < 8)
    ratio = short_lines / len(lines)

    return ratio > 0.6


def calculate_chinese_ratio(text: str) -> float:
    """
    Calculate Chinese character ratio.

    Args:
        text: Chunk content

    Returns:
        Ratio of Chinese characters (0.0 - 1.0)
    """
    if not text:
        return 0.0

    chinese_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    return chinese_count / len(text)


def is_short_chunk(text: str, threshold: int = 30) -> bool:
    """
    Check if chunk is too short.

    Args:
        text: Chunk content
        threshold: Minimum length threshold

    Returns:
        True if chunk length < threshold
    """
    return len(text.strip()) < threshold


def has_low_chinese_ratio(text: str, threshold: float = 0.05) -> bool:
    """
    Check if Chinese ratio is too low.

    Args:
        text: Chunk content
        threshold: Minimum Chinese ratio

    Returns:
        True if Chinese ratio < threshold
    """
    return calculate_chinese_ratio(text) < threshold


# ============================================
# Evaluation Functions
# ============================================

def evaluate_chunk_quality(chunk: str) -> Dict[str, Any]:
    """
    Evaluate single chunk quality.

    Args:
        chunk: Chunk content

    Returns:
        Quality evaluation result
    """
    return {
        "length": len(chunk),
        "chinese_ratio": calculate_chinese_ratio(chunk),
        "is_spine_text": is_spine_text(chunk),
        "is_toc_noise": is_toc_noise(chunk),
        "is_short": is_short_chunk(chunk),
        "has_low_chinese": has_low_chinese_ratio(chunk),
    }


def evaluate_chunks(chunks: List[str]) -> SlicingQualityMetrics:
    """
    Evaluate quality of chunk list.

    Args:
        chunks: List of chunk contents

    Returns:
        Aggregated quality metrics
    """
    if not chunks:
        return SlicingQualityMetrics()

    lengths = [len(c) for c in chunks]
    chinese_ratios = [calculate_chinese_ratio(c) for c in chunks]

    spine_count = sum(1 for c in chunks if is_spine_text(c))
    toc_count = sum(1 for c in chunks if is_toc_noise(c))
    short_count = sum(1 for c in chunks if is_short_chunk(c))
    low_chinese_count = sum(1 for c in chunks if has_low_chinese_ratio(c))

    # Calculate statistics
    import statistics
    avg_length = statistics.mean(lengths) if lengths else 0
    median_length = statistics.median(lengths) if lengths else 0
    std_length = statistics.stdev(lengths) if len(lengths) > 1 else 0

    return SlicingQualityMetrics(
        total_chunks=len(chunks),
        avg_chunk_length=avg_length,
        chinese_ratio_avg=statistics.mean(chinese_ratios) if chinese_ratios else 0,
        spine_text_count=spine_count,
        toc_noise_count=toc_count,
        short_chunk_count=short_count,
        low_chinese_ratio_count=low_chinese_count,
        min_chunk_length=min(lengths) if lengths else 0,
        max_chunk_length=max(lengths) if lengths else 0,
        median_chunk_length=median_length,
        std_chunk_length=std_length,
    )


def evaluate_kb_quality(kb_dir: Optional[Path] = None) -> SlicingQualityMetrics:
    """
    Evaluate knowledge base slicing quality.

    Loads all chunks from KB directory and evaluates quality metrics.

    Args:
        kb_dir: Knowledge base directory path (default: data/knowledge_base)

    Returns:
        Aggregated quality metrics
    """
    from datetime import datetime

    if kb_dir is None:
        kb_dir = Path(__file__).parent.parent.parent / "data" / "knowledge_base"

    logger.info(f"[SlicingQuality] Evaluating KB: {kb_dir}")

    if not kb_dir.exists():
        logger.warning(f"[SlicingQuality] KB directory not found: {kb_dir}")
        return SlicingQualityMetrics(
            kb_dir=str(kb_dir),
            evaluated_at=datetime.now().isoformat(),
        )

    # Load chunks from documents
    all_chunks: List[str] = []
    doc_types: Dict[str, int] = {}

    # Check for vector store files or raw documents
    vector_store_path = kb_dir / "vector_store"
    if vector_store_path.exists():
        # Try to load from vector store
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(vector_store_path))
            collections = client.list_collections()

            for collection in collections:
                docs = collection.get()["documents"]
                all_chunks.extend(docs)
                doc_types[collection.name] = len(docs)
                logger.info(f"[SlicingQuality] Loaded {len(docs)} chunks from collection: {collection.name}")

        except Exception as e:
            logger.warning(f"[SlicingQuality] Failed to load vector store: {e}")

    # Also check raw documents
    raw_docs_path = kb_dir / "raw_documents"
    if raw_docs_path.exists():
        for doc_file in raw_docs_path.glob("*.md"):
            with open(doc_file, "r", encoding="utf-8") as f:
                content = f.read()
            # Use slicer to get chunks for comparison
            try:
                from src.rag.slicing.slicer import UnifiedMarkdownSlicer
                slicer = UnifiedMarkdownSlicer()
                # Detect document type from filename
                doc_type = "guide"  # default
                if "政策" in doc_file.name or "policy" in doc_file.name.lower():
                    doc_type = "policy"
                elif "案例" in doc_file.name or "case" in doc_file.name.lower():
                    doc_type = "case"
                elif "标准" in doc_file.name or "standard" in doc_file.name.lower():
                    doc_type = "standard"
                elif "教材" in doc_file.name or "textbook" in doc_file.name.lower():
                    doc_type = "textbook"

                chunks = slicer.slice(content, doc_type)
                chunk_texts = [c.content for c in chunks]
                all_chunks.extend(chunk_texts)
                doc_types[doc_file.name] = len(chunk_texts)
                logger.info(f"[SlicingQuality] Sliced {doc_file.name}: {len(chunk_texts)} chunks")

            except Exception as e:
                logger.warning(f"[SlicingQuality] Failed to slice {doc_file.name}: {e}")
                # Add as single chunk
                all_chunks.append(content)
                doc_types[doc_file.name] = 1

    # Evaluate all chunks
    metrics = evaluate_chunks(all_chunks)
    metrics.kb_dir = str(kb_dir)
    metrics.evaluated_at = datetime.now().isoformat()
    metrics.document_types = doc_types

    logger.info(f"[SlicingQuality] Total chunks: {metrics.total_chunks}")
    logger.info(f"[SlicingQuality] Avg length: {metrics.avg_chunk_length:.1f}")
    logger.info(f"[SlicingQuality] Chinese ratio avg: {metrics.chinese_ratio_avg:.2%}")
    logger.info(f"[SlicingQuality] Spine text: {metrics.spine_text_count}")
    logger.info(f"[SlicingQuality] TOC noise: {metrics.toc_noise_count}")
    logger.info(f"[SlicingQuality] Short chunks: {metrics.short_chunk_count}")

    return metrics


# ============================================
# Comparison Functions
# ============================================

def compare_metrics(old: SlicingQualityMetrics, new: SlicingQualityMetrics) -> Dict[str, Any]:
    """
    Compare old and new slicing quality metrics.

    Args:
        old: Old metrics (before improvement)
        new: New metrics (after improvement)

    Returns:
        Comparison result with improvements
    """
    return {
        "total_chunks": {
            "old": old.total_chunks,
            "new": new.total_chunks,
            "change": new.total_chunks - old.total_chunks,
            "change_pct": (new.total_chunks - old.total_chunks) / old.total_chunks * 100 if old.total_chunks else 0,
        },
        "avg_chunk_length": {
            "old": old.avg_chunk_length,
            "new": new.avg_chunk_length,
            "change": new.avg_chunk_length - old.avg_chunk_length,
        },
        "spine_text_count": {
            "old": old.spine_text_count,
            "new": new.spine_text_count,
            "change": new.spine_text_count - old.spine_text_count,
            "improvement": "减少" if new.spine_text_count < old.spine_text_count else "增加",
        },
        "toc_noise_count": {
            "old": old.toc_noise_count,
            "new": new.toc_noise_count,
            "change": new.toc_noise_count - old.toc_noise_count,
            "improvement": "减少" if new.toc_noise_count < old.toc_noise_count else "增加",
        },
        "short_chunk_count": {
            "old": old.short_chunk_count,
            "new": new.short_chunk_count,
            "change": new.short_chunk_count - old.short_chunk_count,
            "improvement": "减少" if new.short_chunk_count < old.short_chunk_count else "增加",
        },
        "chinese_ratio_avg": {
            "old": old.chinese_ratio_avg,
            "new": new.chinese_ratio_avg,
            "change": new.chinese_ratio_avg - old.chinese_ratio_avg,
        },
    }


# ============================================
# Output Functions
# ============================================

def save_metrics(metrics: SlicingQualityMetrics, output_dir: Path, filename: str = "slicing_quality_metrics.json"):
    """
    Save metrics to JSON file.

    Args:
        metrics: Quality metrics
        output_dir: Output directory
        filename: Output filename
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(asdict(metrics), f, indent=2, ensure_ascii=False)

    logger.info(f"[SlicingQuality] Saved metrics to {output_path}")


# ============================================
# Main Entry Point
# ============================================

def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Evaluate slicing quality")
    parser.add_argument("--kb-dir", type=str, default=None, help="Knowledge base directory path")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory")
    args = parser.parse_args()

    kb_dir = Path(args.kb_dir) if args.kb_dir else None
    output_dir = Path(args.output_dir) if args.output_dir else Path(__file__).parent.parent.parent / "output" / "experiments" / "slicing_quality"

    metrics = evaluate_kb_quality(kb_dir)
    save_metrics(metrics, output_dir)

    print("\n" + "=" * 60)
    print("Slicing Quality Assessment Completed")
    print("=" * 60)
    print(f"Total chunks: {metrics.total_chunks}")
    print(f"Avg length: {metrics.avg_chunk_length:.1f} chars")
    print(f"Chinese ratio: {metrics.chinese_ratio_avg:.2%}")
    print(f"Spine text (filtered): {metrics.spine_text_count}")
    print(f"TOC noise (filtered): {metrics.toc_noise_count}")
    print(f"Short chunks (<30): {metrics.short_chunk_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()