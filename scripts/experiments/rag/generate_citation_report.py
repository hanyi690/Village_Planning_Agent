"""
引用质量报告生成脚本

使用 citation.py 的完整功能：
1. 正则提取器（支持合并相邻引用）
2. RAG 文档库验证（验证引用存在性）
3. 知识溯源分析

生成 output/experiments/rag/citation_quality_report.md

Usage:
    python scripts/experiments/rag/generate_citation_report.py
"""

import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

# 添加项目路径
PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.experiments.rag.citation import (
    CitationExtractor,
    RAGDocumentLoader,
    Citation,
    is_substantive_citation,
    normalize_for_matching,
)

logger = logging.getLogger(__name__)


def extract_full_sentence(text: str, start: int, end: int) -> str:
    """提取包含引用的完整句子"""
    # 向前查找句子开始（句号、问号、感叹号、换行符）
    sentence_start = start
    for i in range(start - 1, max(0, start - 500), -1):
        if text[i] in '。！？\n':
            sentence_start = i + 1
            break
    else:
        sentence_start = max(0, start - 200)

    # 向后查找句子结束
    sentence_end = end
    for i in range(end, min(len(text), end + 500)):
        if text[i] in '。！？\n':
            sentence_end = i + 1
            break
    else:
        sentence_end = min(len(text), end + 200)

    return text[sentence_start:sentence_end].strip()


def load_rag_knowledge(rag_knowledge_path: Path) -> Dict[str, Dict]:
    """加载 RAG 知识片段，按维度组织"""
    if not rag_knowledge_path.exists():
        return {}

    rag_data = json.loads(rag_knowledge_path.read_text(encoding="utf-8"))
    rag_knowledge: Dict[str, Dict] = {}

    for layer_key, layer_data in rag_data.items():
        if not isinstance(layer_data, dict):
            continue
        for dim_key, dim_data in layer_data.items():
            if not isinstance(dim_data, dict):
                continue
            ks = dim_data.get("knowledge_sources")
            if ks and isinstance(ks, dict) and ks.get("retrieved_chunks"):
                rag_knowledge[dim_key] = ks
            elif ks and isinstance(ks, list) and ks:
                rag_knowledge[dim_key] = {"retrieved_chunks": ks, "rag_enabled": True}

    return rag_knowledge


def check_in_rag_knowledge(citation_text: str, knowledge_sources: Dict) -> Dict:
    """检查引用是否在 RAG 知识片段中出现"""
    if not knowledge_sources or not knowledge_sources.get("retrieved_chunks"):
        return {"found": False, "source": None, "preview": None, "score": None}

    normalized_citation = normalize_for_matching(citation_text)
    if not normalized_citation:
        return {"found": False, "source": None, "preview": None, "score": None}

    for chunk in knowledge_sources["retrieved_chunks"]:
        content_preview = chunk.get("content_preview", "") or chunk.get("content", "")
        normalized_content = normalize_for_matching(content_preview)

        if normalized_citation in normalized_content:
            return {
                "found": True,
                "source": chunk.get("source"),
                "preview": content_preview[:200] if content_preview else None,
                "score": chunk.get("score"),
            }

    return {"found": False, "source": None, "preview": None, "score": None}


def is_valid_citation(cite_type: str) -> bool:
    """判断是否为有效的法规引用（排除指标引用）"""
    # 排除 indicator 类型
    if cite_type == "indicator":
        return False
    # 保留 law, standard, clause 及其组合
    return True


def extract_iteration(
    extractor: CitationExtractor,
    rag_loader: RAGDocumentLoader,
    base_dir: Path,
    group: str,
    iteration: str,
) -> List[Dict]:
    """提取单个迭代的引用（仅保留法规引用，排除指标引用）"""
    group_dir = base_dir / group / iteration
    reports_path = group_dir / "reports.json"

    if not reports_path.exists():
        logger.warning(f"[{group}/{iteration}] reports.json 不存在")
        return []

    reports_data = json.loads(reports_path.read_text(encoding="utf-8"))
    reports = reports_data.get("reports", {})

    # 加载 RAG 知识片段
    rag_knowledge_path = group_dir / "rag_knowledge.json"
    rag_knowledge = load_rag_knowledge(rag_knowledge_path)
    if rag_knowledge:
        logger.info(f"[{group}/{iteration}] 已加载 {len(rag_knowledge)} 个维度的 RAG 知识片段")

    results = []
    for dim_key, text in reports.items():
        if not text:
            continue

        # 使用 citation.py 的提取器
        citations = extractor.extract(text)
        if not citations:
            continue

        dim_knowledge = rag_knowledge.get(dim_key, {})
        rag_enabled = dim_knowledge.get("rag_enabled", False) if dim_knowledge else False

        citation_list = []
        for c in citations:
            # 排除指标引用（indicator）
            if not is_valid_citation(c.type):
                continue

            # 验证引用在 RAG 文档库中的存在性
            exists, source_path, source_name, confidence = rag_loader.search(c.text)

            # 检查引用是否在本次 RAG 检索的知识片段中
            rag_source = check_in_rag_knowledge(c.text, dim_knowledge)

            # 提取完整句子
            full_sentence = extract_full_sentence(text, c.position, c.position + len(c.text))

            citation_list.append({
                "text": c.text,
                "type": c.type,
                "full_sentence": full_sentence,
                "exists_in_rag_docs": exists,
                "rag_doc_name": source_name if exists else None,
                "rag_doc_confidence": confidence if exists else None,
                "in_rag_knowledge": rag_source["found"],
                "rag_knowledge_source": rag_source["source"] if rag_source["found"] else None,
                "is_substantive": is_substantive_citation(c.text),
            })

        if citation_list:
            results.append({
                "dimension": dim_key,
                "total": len(citation_list),
                "rag_enabled": rag_enabled,
                "citations": citation_list,
            })

    return results


def extract_all(base_dir: Path) -> Dict[str, Dict[str, List[Dict]]]:
    """提取所有组和迭代的引用"""
    results = {}
    extractor = CitationExtractor(context_chars=150, merge_adjacent=True)
    rag_loader = RAGDocumentLoader(PROJECT_ROOT)

    logger.info(f"已加载 {rag_loader.get_document_count()} 个 RAG 文档")

    for group in ["g1", "g2", "g3"]:
        results[group] = {}
        group_dir = base_dir / group

        if not group_dir.exists():
            continue

        for iter_dir in sorted(group_dir.iterdir()):
            if iter_dir.is_dir() and iter_dir.name.startswith("iter"):
                iteration = iter_dir.name
                logger.info(f"提取 {group}/{iteration}...")
                results[group][iteration] = extract_iteration(
                    extractor, rag_loader, base_dir, group, iteration
                )

                # 打印统计
                total = sum(r["total"] for r in results[group][iteration])
                exists_in_docs = sum(
                    sum(1 for c in r["citations"] if c.get("exists_in_rag_docs"))
                    for r in results[group][iteration]
                )
                in_knowledge = sum(
                    sum(1 for c in r["citations"] if c.get("in_rag_knowledge"))
                    for r in results[group][iteration]
                )
                logger.info(f"  引用: {total}, 文档库验证: {exists_in_docs}, 知识溯源: {in_knowledge}")

    return results


def generate_report(results: Dict, output_path: Path) -> str:
    """生成 Markdown 格式的报告"""
    lines = []

    # 标题
    lines.append("# RAG 实验引用质量报告")
    lines.append("")
    lines.append(f"**生成日期**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("**提取方法**: 正则表达式提取器（支持合并相邻引用）")
    lines.append("**验证方法**: RAG 文档库全文检索验证")
    lines.append("")

    # 总体统计
    lines.append("## 一、总体统计")
    lines.append("")

    rag_configs = {"g1": "无RAG", "g2": "L3 RAG", "g3": "L1+L3 RAG"}

    # 按组汇总表
    lines.append("### 1.1 按组汇总")
    lines.append("")
    lines.append("| 组别 | RAG配置 | 总引用 | 文档库验证 | 验证率 | 知识溯源 | 溯源率 |")
    lines.append("|------|---------|--------|------------|--------|----------|--------|")

    total_all = 0
    exists_all = 0
    trace_all = 0

    for group in ["g1", "g2", "g3"]:
        group_total = sum(r["total"] for iter_data in results[group].values() for r in iter_data)
        group_exists = sum(
            sum(1 for c in r["citations"] if c.get("exists_in_rag_docs"))
            for iter_data in results[group].values() for r in iter_data
        )
        group_trace = sum(
            sum(1 for c in r["citations"] if c.get("in_rag_knowledge"))
            for iter_data in results[group].values() for r in iter_data
        )

        exists_rate = group_exists / group_total if group_total > 0 else 0
        trace_rate = group_trace / group_total if group_total > 0 else 0

        lines.append(f"| {group} | {rag_configs[group]} | {group_total} | {group_exists} | {exists_rate:.1%} | {group_trace} | {trace_rate:.1%} |")

        total_all += group_total
        exists_all += group_exists
        trace_all += group_trace

    # 合计行
    exists_rate_all = exists_all / total_all if total_all > 0 else 0
    trace_rate_all = trace_all / total_all if total_all > 0 else 0
    lines.append(f"| **合计** | - | **{total_all}** | **{exists_all}** | **{exists_rate_all:.1%}** | **{trace_all}** | **{trace_rate_all:.1%}** |")
    lines.append("")

    # 按迭代汇总表
    lines.append("### 1.2 按迭代汇总")
    lines.append("")
    lines.append("| 组别 | 迭代 | 总引用 | 文档库验证 | 验证率 | 知识溯源 | 溯源率 |")
    lines.append("|------|------|--------|------------|--------|----------|--------|")

    for group in ["g1", "g2", "g3"]:
        for iteration in sorted(results[group].keys()):
            iter_data = results[group][iteration]
            total = sum(r["total"] for r in iter_data)
            exists = sum(
                sum(1 for c in r["citations"] if c.get("exists_in_rag_docs"))
                for r in iter_data
            )
            trace = sum(
                sum(1 for c in r["citations"] if c.get("in_rag_knowledge"))
                for r in iter_data
            )
            exists_rate = exists / total if total > 0 else 0
            trace_rate = trace / total if total > 0 else 0
            lines.append(f"| {group} | {iteration} | {total} | {exists} | {exists_rate:.1%} | {trace} | {trace_rate:.1%} |")

    lines.append("")

    # 关键发现
    lines.append("## 二、关键发现")
    lines.append("")
    lines.append("### 2.1 RAG 对引用生成的影响")
    lines.append("")
    lines.append("| 发现 | 说明 |")
    lines.append("|------|------|")

    g1_total = sum(r["total"] for iter_data in results["g1"].values() for r in iter_data)
    g2_total = sum(r["total"] for iter_data in results["g2"].values() for r in iter_data)
    g3_total = sum(r["total"] for iter_data in results["g3"].values() for r in iter_data)

    lines.append(f"| G1 无引用 | 无 RAG 支撑时，模型不会引用任何法规或标准（引用数: {g1_total}） |")
    lines.append(f"| G2 少量引用 | 仅 L3 RAG 时，引用数量较少（引用数: {g2_total}） |")
    lines.append(f"| G3 大量引用 | L1+L3 RAG 时，引用数量显著增加（引用数: {g3_total}） |")
    lines.append(f"| 文档库验证率 {exists_rate_all:.1%} | 引用在 RAG 文档库中存在的比例 |")
    lines.append(f"| 知识溯源率 {trace_rate_all:.1%} | 引用在本次 RAG 检索的知识片段中出现的比例 |")
    lines.append("")

    # 各组详细引用
    lines.append("## 三、各组详细引用数据")
    lines.append("")

    for group in ["g1", "g2", "g3"]:
        lines.append(f"### 3.{['g1', 'g2', 'g3'].index(group) + 1} {group}（{rag_configs[group]}）")
        lines.append("")

        for iteration in sorted(results[group].keys()):
            iter_data = results[group][iteration]
            total = sum(r["total"] for r in iter_data)

            if total == 0:
                lines.append(f"#### {iteration}")
                lines.append("")
                lines.append("**结果**: 无引用")
                lines.append("")
                continue

            lines.append(f"#### {iteration}（{total} 个引用）")
            lines.append("")

            for dim_data in iter_data:
                dim_key = dim_data["dimension"]
                lines.append(f"**维度: {dim_key}**")
                lines.append("")
                lines.append("| 引用 | 类型 | 文档库验证 | 源文档 | 知识溯源 | 完整原句 |")
                lines.append("|------|------|------------|--------|----------|----------|")

                for c in dim_data["citations"]:
                    exists_status = "✅" if c["exists_in_rag_docs"] else "❌"
                    trace_status = "✅" if c["in_rag_knowledge"] else "❌"
                    source_doc = c["rag_doc_name"] or "-"
                    # 截断过长的引用和原句
                    cite_text = c["text"][:40] + "..." if len(c["text"]) > 40 else c["text"]
                    sentence = c["full_sentence"][:60] + "..." if len(c["full_sentence"]) > 60 else c["full_sentence"]
                    lines.append(f"| {cite_text} | {c['type']} | {exists_status} | {source_doc} | {trace_status} | {sentence} |")

                lines.append("")

    # 指标说明
    lines.append("## 四、指标说明")
    lines.append("")
    lines.append("### 4.1 文档库验证率")
    lines.append("")
    lines.append("引用在 RAG 文档库（`data/RAG_doc/_doc_md`）中存在的比例。")
    lines.append("")
    lines.append("- **✅ 存在**: 引用名称在文档库中找到对应文档")
    lines.append("- **❌ 不存在**: 引用名称在文档库中未找到")
    lines.append("")
    lines.append("### 4.2 知识溯源率")
    lines.append("")
    lines.append("引用在本次 RAG 检索的知识片段（`rag_knowledge.json`）中出现的比例。")
    lines.append("")
    lines.append("- **✅ 溯源**: 引用来自本次 RAG 检索的知识片段")
    lines.append("- **❌ 未溯源**: 引用来自模型内部知识或其他来源")
    lines.append("")
    lines.append("### 4.3 引用类型")
    lines.append("")
    lines.append("| 类型 | 说明 | 示例 |")
    lines.append("|------|------|------|")
    lines.append("| law | 法规名称 | 《镇规划标准》 |")
    lines.append("| standard | 标准编号 | GB 50188-2007 |")
    lines.append("| clause | 条款引用 | 第二十四条 |")
    lines.append("| law+standard | 法规名称+标准编号 | 《镇规划标准》GB50188 |")
    lines.append("| law+clause | 法规名称+条款 | 《广东省乡村振兴促进条例》第二十四条 |")
    lines.append("")

    # 保存报告
    report_content = "\n".join(lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_content, encoding="utf-8")
    logger.info(f"报告已保存: {output_path}")

    return report_content


def main():
    """主入口"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    base_dir = PROJECT_ROOT / "output" / "experiments" / "rag"

    logger.info("开始引用质量分析...")
    logger.info(f"项目根目录: {PROJECT_ROOT}")
    logger.info(f"数据目录: {base_dir}")

    # 提取引用
    results = extract_all(base_dir)

    # 保存 JSON 数据
    json_path = base_dir / "citations_quality.json"
    json_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"JSON 已保存: {json_path}")

    # 生成报告
    report_path = base_dir / "citation_quality_report.md"
    generate_report(results, report_path)

    # 打印汇总
    print("\n" + "=" * 80)
    print("引用质量分析完成")
    print("=" * 80)
    print(f"\n数据已保存至: {json_path}")
    print(f"报告已保存至: {report_path}")


if __name__ == "__main__":
    main()
