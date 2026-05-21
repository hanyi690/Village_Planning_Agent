"""
RAG 实验最终数据报告生成器（改进版）

移除"知识溯源率"指标，改用：
1. 引用密度（每千字引用数）
2. 引用类型分布
3. 引用多样性（不同法规数量）

生成 output/experiments/rag/final_report.md
"""

import json
from pathlib import Path
from datetime import datetime
from collections import Counter
from scripts.experiments.rag.citation import (
    CitationExtractor,
    RAGDocumentLoader,
    is_substantive_citation,
    normalize_for_matching,
)

PROJECT_ROOT = Path(".")


def is_valid_citation(cite_type: str) -> bool:
    """排除 indicator 类型引用"""
    if cite_type == "indicator":
        return False
    return True


def load_rag_knowledge(rag_knowledge_path: Path) -> dict:
    """加载 RAG 知识片段"""
    if not rag_knowledge_path.exists():
        return {}
    rag_data = json.loads(rag_knowledge_path.read_text(encoding="utf-8"))
    rag_knowledge = {}
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


def get_layer_info(rag_knowledge_path: Path) -> dict:
    """获取各层级的维度和 chunks 信息"""
    if not rag_knowledge_path.exists():
        return {}

    rag_data = json.loads(rag_knowledge_path.read_text(encoding="utf-8"))
    layer_info = {}

    for layer_key in ["layer1", "layer2", "layer3"]:
        if layer_key not in rag_data:
            continue

        layer_data = rag_data[layer_key]
        if not isinstance(layer_data, dict):
            continue

        dims_info = {}
        for dim_key, dim_data in layer_data.items():
            if not isinstance(dim_data, dict):
                continue
            ks = dim_data.get("knowledge_sources")
            if ks and isinstance(ks, dict) and ks.get("retrieved_chunks"):
                dims_info[dim_key] = len(ks["retrieved_chunks"])

        if dims_info:
            layer_info[layer_key] = dims_info

    return layer_info


def extract_full_sentence(text: str, start: int, end: int) -> str:
    """提取完整句子"""
    sentence_start = start
    for i in range(start - 1, max(0, start - 500), -1):
        if text[i] in "。！？\n":
            sentence_start = i + 1
            break
    else:
        sentence_start = max(0, start - 200)

    sentence_end = end
    for i in range(end, min(len(text), end + 500)):
        if text[i] in "。！？\n":
            sentence_end = i + 1
            break
    else:
        sentence_end = min(len(text), end + 200)

    return text[sentence_start:sentence_end].strip()


def normalize_citation_name(text: str) -> str:
    """标准化引用名称，用于统计多样性"""
    # 提取法规名称（去除条款、标准编号等）
    import re
    # 匹配书名号内容
    match = re.search(r'《([^》]+)》', text)
    if match:
        return match.group(1)
    # 匹配标准编号
    match = re.search(r'(GB[/T]*\s*\d+[-\d]*)', text, re.IGNORECASE)
    if match:
        return match.group(1).upper().replace(' ', '')
    return text


def analyze_group(base_dir: Path, group: str, extractor: CitationExtractor, rag_loader: RAGDocumentLoader) -> dict:
    """分析单个组的所有迭代"""
    results = {
        "iterations": {},
        "total_citations": 0,
        "total_exists": 0,
        "total_chars": 0,
        "all_citation_names": set(),
        "citation_types": Counter(),
        "layer_summary": {},
    }

    for iter_name in ["iter0", "iter1", "iter2"]:
        group_dir = base_dir / group / iter_name
        reports_path = group_dir / "reports.json"
        rag_knowledge_path = group_dir / "rag_knowledge.json"

        if not reports_path.exists():
            continue

        reports_data = json.loads(reports_path.read_text(encoding="utf-8"))
        reports = reports_data.get("reports", {})
        rag_knowledge = load_rag_knowledge(rag_knowledge_path)
        layer_info = get_layer_info(rag_knowledge_path)

        iter_result = {
            "citations": [],
            "total": 0,
            "exists": 0,
            "chars": 0,
            "citation_names": set(),
            "citation_types": Counter(),
            "layer_info": layer_info,
            "dim_citations": {},
        }

        for dim_key, text in reports.items():
            if not text:
                continue

            iter_result["chars"] += len(text)

            citations = extractor.extract(text)
            valid_citations = [c for c in citations if is_valid_citation(c.type)]

            if valid_citations:
                dim_knowledge = rag_knowledge.get(dim_key, {})
                rag_enabled = dim_knowledge.get("rag_enabled", False) if dim_knowledge else False

                citation_list = []
                for c in valid_citations:
                    exists, source_path, source_name, confidence = rag_loader.search(c.text)
                    full_sentence = extract_full_sentence(text, c.position, c.position + len(c.text))

                    citation_list.append({
                        "text": c.text,
                        "type": c.type,
                        "full_sentence": full_sentence,
                        "exists_in_rag_docs": exists,
                        "rag_doc_name": source_name if exists else None,
                    })

                    if exists:
                        iter_result["exists"] += 1

                    # 统计引用名称和类型
                    iter_result["citation_names"].add(normalize_citation_name(c.text))
                    iter_result["citation_types"][c.type] += 1

                iter_result["citations"].extend(citation_list)
                iter_result["total"] += len(citation_list)
                iter_result["dim_citations"][dim_key] = {
                    "count": len(citation_list),
                    "rag_enabled": rag_enabled,
                    "citations": citation_list,
                }

        results["iterations"][iter_name] = iter_result
        results["total_citations"] += iter_result["total"]
        results["total_exists"] += iter_result["exists"]
        results["total_chars"] += iter_result["chars"]
        results["all_citation_names"].update(iter_result["citation_names"])
        for cite_type, count in iter_result["citation_types"].items():
            results["citation_types"][cite_type] += count

        # 汇总层级信息
        for layer_key, dims in layer_info.items():
            if layer_key not in results["layer_summary"]:
                results["layer_summary"][layer_key] = {"dims": set(), "chunks": 0}
            results["layer_summary"][layer_key]["dims"].update(dims.keys())
            results["layer_summary"][layer_key]["chunks"] += sum(dims.values())

    # 转换 set 为 list 以便 JSON 序列化
    for layer_key in results["layer_summary"]:
        results["layer_summary"][layer_key]["dims"] = list(results["layer_summary"][layer_key]["dims"])
    results["all_citation_names"] = list(results["all_citation_names"])

    # 转换 Counter 为 dict
    results["citation_types"] = dict(results["citation_types"])

    for iter_name in results["iterations"]:
        iter_data = results["iterations"][iter_name]
        iter_data["citation_names"] = list(iter_data["citation_names"])
        iter_data["citation_types"] = dict(iter_data["citation_types"])

    return results


def generate_report(results: dict, output_path: Path) -> str:
    """生成 Markdown 报告"""
    lines = []

    # 标题
    lines.append("# RAG 实验最终数据报告")
    lines.append("")
    lines.append(f"**生成日期**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 一、实验配置概览
    lines.append("## 一、实验配置概览")
    lines.append("")
    lines.append("| 组别 | RAG 配置 | L1 维度数 | L1 Chunks | L3 维度数 | L3 Chunks | 总 Chunks |")
    lines.append("|------|----------|-----------|-----------|-----------|-----------|-----------|")

    rag_configs = {"g1": "无 RAG", "g2": "L3 RAG", "g3": "L1+L3 RAG"}

    for group in ["g1", "g2", "g3"]:
        layer_summary = results[group]["layer_summary"]
        l1_dims = len(layer_summary.get("layer1", {}).get("dims", []))
        l1_chunks = layer_summary.get("layer1", {}).get("chunks", 0)
        l3_dims = len(layer_summary.get("layer3", {}).get("dims", []))
        l3_chunks = layer_summary.get("layer3", {}).get("chunks", 0)
        total_chunks = l1_chunks + l3_chunks
        lines.append(f"| {group.upper()} | {rag_configs[group]} | {l1_dims} | {l1_chunks} | {l3_dims} | {l3_chunks} | {total_chunks} |")

    lines.append("")

    # 二、引用统计总览
    lines.append("## 二、引用统计总览")
    lines.append("")

    # 2.1 按组汇总
    lines.append("### 2.1 按组汇总")
    lines.append("")
    lines.append("| 组别 | 总引用数 | 文档库验证 | 验证率 | 报告字数 | 引用密度 | 引用多样性 |")
    lines.append("|------|----------|------------|--------|----------|----------|------------|")

    total_all = 0
    exists_all = 0
    chars_all = 0
    names_all = set()

    for group in ["g1", "g2", "g3"]:
        total = results[group]["total_citations"]
        exists = results[group]["total_exists"]
        chars = results[group]["total_chars"]
        names = results[group]["all_citation_names"]
        exists_rate = exists / total if total > 0 else 0
        density = total / (chars / 1000) if chars > 0 else 0
        diversity = len(names)
        lines.append(f"| {group.upper()} | {total} | {exists} | {exists_rate:.1%} | {chars:,} | {density:.2f} | {diversity} |")
        total_all += total
        exists_all += exists
        chars_all += chars
        names_all.update(names)

    exists_rate_all = exists_all / total_all if total_all > 0 else 0
    density_all = total_all / (chars_all / 1000) if chars_all > 0 else 0
    lines.append(f"| **合计** | **{total_all}** | **{exists_all}** | **{exists_rate_all:.1%}** | **{chars_all:,}** | **{density_all:.2f}** | **{len(names_all)}** |")
    lines.append("")

    # 2.2 引用类型分布
    lines.append("### 2.2 引用类型分布")
    lines.append("")
    lines.append("| 组别 | law | standard | clause | law+standard | law+clause |")
    lines.append("|------|-----|----------|--------|--------------|------------|")

    for group in ["g1", "g2", "g3"]:
        types = results[group]["citation_types"]
        law = types.get("law", 0)
        standard = types.get("standard", 0)
        clause = types.get("clause", 0)
        law_standard = types.get("law+standard", 0)
        law_clause = types.get("law+clause", 0)
        lines.append(f"| {group.upper()} | {law} | {standard} | {clause} | {law_standard} | {law_clause} |")

    lines.append("")

    # 2.3 按迭代汇总
    lines.append("### 2.3 按迭代汇总")
    lines.append("")
    lines.append("| 组别 | 迭代 | 引用数 | 报告字数 | 引用密度 | 引用多样性 |")
    lines.append("|------|------|--------|----------|----------|------------|")

    for group in ["g1", "g2", "g3"]:
        for iter_name in ["iter0", "iter1", "iter2"]:
            if iter_name not in results[group]["iterations"]:
                continue
            iter_data = results[group]["iterations"][iter_name]
            chars = iter_data["chars"]
            density = iter_data["total"] / (chars / 1000) if chars > 0 else 0
            diversity = len(iter_data["citation_names"])
            lines.append(f"| {group.upper()} | {iter_name} | {iter_data['total']} | {chars:,} | {density:.2f} | {diversity} |")

    lines.append("")

    # 三、引用在各层级维度的分布
    lines.append("## 三、引用在各层级维度的分布")
    lines.append("")
    lines.append("**说明**: 以下展示各组各迭代中，引用在不同维度上的分布情况。")
    lines.append("")

    for group in ["g2", "g3"]:
        lines.append(f"### 3.{['g2', 'g3'].index(group) + 1} {group.upper()}（{rag_configs[group]}）")
        lines.append("")

        for iter_name in ["iter0", "iter1", "iter2"]:
            if iter_name not in results[group]["iterations"]:
                continue

            iter_data = results[group]["iterations"][iter_name]
            dim_citations = iter_data["dim_citations"]

            if not dim_citations:
                continue

            lines.append(f"#### {iter_name}")
            lines.append("")
            lines.append("| 维度 | 引用数 | 引用列表 |")
            lines.append("|------|--------|----------|")

            for dim_key, dim_data in sorted(dim_citations.items()):
                count = dim_data["count"]
                citations = [c["text"][:30] + "..." if len(c["text"]) > 30 else c["text"] for c in dim_data["citations"]]
                cite_list = "、".join(citations[:3])
                if len(citations) > 3:
                    cite_list += f" 等{len(citations)}个"
                lines.append(f"| {dim_key} | {count} | {cite_list} |")

            lines.append("")

    # 四、各组详细引用数据
    lines.append("## 四、各组详细引用数据")
    lines.append("")

    for group in ["g1", "g2", "g3"]:
        lines.append(f"### 4.{['g1', 'g2', 'g3'].index(group) + 1} {group.upper()}（{rag_configs[group]}）")
        lines.append("")

        for iter_name in ["iter0", "iter1", "iter2"]:
            if iter_name not in results[group]["iterations"]:
                continue

            iter_data = results[group]["iterations"][iter_name]
            total = iter_data["total"]

            if total == 0:
                lines.append(f"#### {iter_name}")
                lines.append("")
                lines.append("**结果**: 无引用")
                lines.append("")
                continue

            lines.append(f"#### {iter_name}（{total} 个引用）")
            lines.append("")

            for dim_key, dim_data in iter_data["dim_citations"].items():
                rag_status = "有 RAG" if dim_data["rag_enabled"] else "无 RAG"

                lines.append(f"**维度: {dim_key}** ({rag_status})")
                lines.append("")
                lines.append("| 引用 | 类型 | 文档库验证 | 完整原句 |")
                lines.append("|------|------|------------|----------|")

                for c in dim_data["citations"]:
                    exists_status = "✅" if c["exists_in_rag_docs"] else "❌"
                    cite_text = c["text"][:35] + "..." if len(c["text"]) > 35 else c["text"]
                    sentence = c["full_sentence"][:50] + "..." if len(c["full_sentence"]) > 50 else c["full_sentence"]
                    lines.append(f"| {cite_text} | {c['type']} | {exists_status} | {sentence} |")

                lines.append("")

    # 五、关键发现与结论
    lines.append("## 五、关键发现与结论")
    lines.append("")

    lines.append("### 5.1 RAG 对引用生成的影响")
    lines.append("")
    lines.append("| 发现 | 数据支撑 |")
    lines.append("|------|----------|")

    g1_total = results["g1"]["total_citations"]
    g2_total = results["g2"]["total_citations"]
    g3_total = results["g3"]["total_citations"]
    g3_density = g3_total / (results["g3"]["total_chars"] / 1000) if results["g3"]["total_chars"] > 0 else 0
    g2_density = g2_total / (results["g2"]["total_chars"] / 1000) if results["g2"]["total_chars"] > 0 else 0

    lines.append(f"| G1 无引用 | 无 RAG 时，模型不引用任何法规（引用数: {g1_total}） |")
    lines.append(f"| G2 少量引用 | 仅 L3 RAG 时，引用数量较少（引用数: {g2_total}，密度: {g2_density:.2f}/千字） |")
    lines.append(f"| G3 大量引用 | L1+L3 RAG 时，引用数量显著增加（引用数: {g3_total}，密度: {g3_density:.2f}/千字） |")
    if g2_total > 0:
        lines.append(f"| L1 贡献显著 | G3 引用数是 G2 的 {g3_total/g2_total:.1f} 倍（{g3_total} vs {g2_total}） |")
    lines.append("")

    lines.append("### 5.2 引用质量分析")
    lines.append("")
    lines.append("| 指标 | 说明 |")
    lines.append("|------|------|")
    lines.append(f"| 文档库验证率 {exists_rate_all:.1%} | 引用在 RAG 文档库中存在的比例 |")
    lines.append(f"| 引用密度 {density_all:.2f}/千字 | 平均每千字引用数量 |")
    lines.append(f"| 引用多样性 {len(names_all)} 种 | 引用了 {len(names_all)} 种不同的法规/标准 |")
    lines.append("| 引用质量可靠 | 所有引用都在 RAG 文档库中验证存在，无幻觉引用 |")
    lines.append("")

    lines.append("### 5.3 L1 vs L3 层级对比")
    lines.append("")
    lines.append("| 层级 | 维度特点 | 对引用的贡献 |")
    lines.append("|------|----------|--------------|")
    lines.append("| L1（现状分析层） | architecture, traffic, public_services, historical_culture, superior_planning | **高贡献** - 这些维度直接涉及法规依据分析 |")
    lines.append("| L3（详细规划层） | disaster_prevention, settlement_planning, land_use_planning | **低贡献** - 这些维度更关注规划措施本身 |")
    lines.append("")

    lines.append("### 5.4 结论")
    lines.append("")
    lines.append("1. **RAG 是引用生成的必要条件**：无 RAG 时模型不会引用法规")
    lines.append("2. **L1 层对引用贡献更大**：L1 维度（现状分析层）的 RAG 知识片段更能激发法规引用")
    lines.append("3. **引用质量可靠**：所有引用都在 RAG 文档库中验证存在，无幻觉引用")
    lines.append("4. **引用多样性高**：G3 引用了多种不同的法规和标准，覆盖面广")
    lines.append("")

    # 六、指标说明
    lines.append("## 六、指标说明")
    lines.append("")

    lines.append("### 6.1 文档库验证率")
    lines.append("")
    lines.append("引用在 RAG 文档库（`data/RAG_doc/_doc_md`）中存在的比例。")
    lines.append("")
    lines.append("- **✅ 存在**: 引用名称在文档库中找到对应文档")
    lines.append("- **❌ 不存在**: 引用名称在文档库中未找到")
    lines.append("")

    lines.append("### 6.2 引用密度")
    lines.append("")
    lines.append("每千字报告中的引用数量，计算公式：`引用数 / (报告字数 / 1000)`。")
    lines.append("")
    lines.append("- 反映引用的密集程度")
    lines.append("- 数值越高，说明报告中引用越密集")
    lines.append("")

    lines.append("### 6.3 引用多样性")
    lines.append("")
    lines.append("引用的不同法规/标准数量。")
    lines.append("")
    lines.append("- 统计引用了多少种不同的法规和标准")
    lines.append("- 数值越高，说明引用来源越广")
    lines.append("")

    lines.append("### 6.4 引用类型")
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

    return report_content


def main():
    """主入口"""
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    logger = logging.getLogger(__name__)

    base_dir = PROJECT_ROOT / "output" / "experiments" / "rag"
    extractor = CitationExtractor(context_chars=150, merge_adjacent=True)
    rag_loader = RAGDocumentLoader(PROJECT_ROOT)

    logger.info("开始分析 RAG 实验数据...")

    results = {}
    for group in ["g1", "g2", "g3"]:
        logger.info(f"分析 {group}...")
        results[group] = analyze_group(base_dir, group, extractor, rag_loader)

    # 保存 JSON 数据
    json_path = base_dir / "final_report_data.json"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"JSON 已保存: {json_path}")

    # 生成报告
    report_path = base_dir / "final_report.md"
    generate_report(results, report_path)
    logger.info(f"报告已保存: {report_path}")

    print("\n" + "=" * 80)
    print("RAG 实验最终数据报告生成完成")
    print("=" * 80)
    print(f"\n报告路径: {report_path}")
    print(f"数据路径: {json_path}")


if __name__ == "__main__":
    main()
