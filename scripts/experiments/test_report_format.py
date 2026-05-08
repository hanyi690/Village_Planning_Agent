"""
测试报告格式规范化效果

验证新 Prompt 模板生成的报告是否符合法规文本格式规范。

使用方法：
    python scripts/experiments/test_report_format.py --layer 1
    python scripts/experiments/test_report_format.py --layer 2
    python scripts/experiments/test_report_format.py --layer 3
    python scripts/experiments/test_report_format.py --layer all

输出：
    - 格式验证结果（章节编号、表格编号、缺失表述次数等）
    - 输出到 output/experiments/format_test/
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Tuple
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.experiments.config import (
    load_status_report,
    JINTIAN_VILLAGE_DATA,
)
from src.utils.report_format_spec import (
    LAYER_FORMATS,
    MISSING_DATA_ALTERNATIVES,
    FORBIDDEN_MISSING_PHRASES,
    get_layer_config,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ============================================
# Output Configuration
# ============================================

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output" / "experiments" / "format_test"


def ensure_output_dir():
    """Ensure output directory exists."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================
# Format Validation Functions
# ============================================


# ============================================
# Validation Functions
# ============================================

def validate_title(content: str, layer: int) -> Dict[str, Any]:
    """Validate title format."""
    config = get_layer_config(layer)
    pattern = config.chapter_regex

    match = re.search(pattern, content)
    if match:
        return {
            "valid": True,
            "found": match.group(),
            "message": f"标题格式正确: {match.group()}",
        }
    return {
        "valid": False,
        "found": None,
        "message": f"标题格式不符合规范，应包含'{pattern}'",
    }


def validate_item_numbers(content: str, layer: int) -> Dict[str, Any]:
    """Validate item numbering (第一条、第二条...)."""
    config = get_layer_config(layer)
    pattern = config.item_regex

    matches = re.findall(pattern, content)
    if len(matches) > 0:
        return {
            "valid": True,
            "count": len(matches),
            "found": matches[:5],  # Show first 5
            "message": f"找到 {len(matches)} 个条目编号",
        }
    return {
        "valid": False,
        "count": 0,
        "found": [],
        "message": "未找到条目编号（第一条、第二条...）",
    }


def validate_subitem_numbers(content: str, layer: int) -> Dict[str, Any]:
    """Validate subitem numbering （一）、（二）..."""
    config = get_layer_config(layer)
    pattern = config.subitem_regex

    matches = re.findall(pattern, content)
    return {
        "valid": len(matches) > 0,
        "count": len(matches),
        "found": matches[:5],
        "message": f"找到 {len(matches)} 个分项编号（（一）、（二）...）",
    }


def validate_table_numbers(content: str, layer: int) -> Dict[str, Any]:
    """Validate table numbering."""
    config = get_layer_config(layer)
    pattern = config.table_regex or ""

    if not pattern:
        return {"valid": True, "count": 0, "message": "本层无表格编号要求"}

    matches = re.findall(pattern, content)
    return {
        "valid": len(matches) > 0,
        "count": len(matches),
        "found": matches,
        "message": f"找到 {len(matches)} 个表格编号",
    }


def validate_missing_phrases(content: str, layer: int) -> Dict[str, Any]:
    """Validate missing data phrase usage."""
    config = get_layer_config(layer)
    limit = config.missing_phrase_limit

    missing_count = 0
    found_phrases = []

    for phrase in FORBIDDEN_MISSING_PHRASES:
        matches = re.findall(phrase, content)
        if matches:
            missing_count += len(matches)
            found_phrases.extend(matches)

    alternative_count = 0
    for phrase in MISSING_DATA_ALTERNATIVES:
        matches = re.findall(phrase, content)
        if matches:
            alternative_count += len(matches)

    return {
        "valid": missing_count <= limit,
        "missing_count": missing_count,
        "alternative_count": alternative_count,
        "limit": limit,
        "found_missing": found_phrases[:5],
        "message": f"缺失表述次数: {missing_count} (限制: {limit}), 替代表述次数: {alternative_count}",
    }


def validate_strategy_format(content: str, layer: int) -> Dict[str, Any]:
    """Validate strategy format with 全角破折号."""
    config = get_layer_config(layer)
    if not config.strategy_required:
        return {"valid": True, "message": "本层无策略格式要求"}

    # Check for 全角破折号
    full_dash_count = len(re.findall("——", content))
    half_dash_count = len(re.findall("-", content))

    return {
        "valid": full_dash_count > 0,
        "full_dash_count": full_dash_count,
        "half_dash_count": half_dash_count,
        "message": f"全角破折号——次数: {full_dash_count}, 半横线-次数: {half_dash_count}",
    }


def validate_format(content: str, layer: int) -> Dict[str, Any]:
    """Run all format validations for a layer."""
    config = get_layer_config(layer)
    results = {
        "layer": layer,
        "layer_name": config.name,
        "timestamp": datetime.now().isoformat(),
        "content_length": len(content),
        "validations": {},
        "overall_valid": True,
    }

    validations = [
        ("title", validate_title),
        ("item_numbers", validate_item_numbers),
        ("subitem_numbers", validate_subitem_numbers),
        ("table_numbers", validate_table_numbers),
        ("missing_phrases", validate_missing_phrases),
        ("strategy_format", validate_strategy_format),
    ]

    for name, func in validations:
        result = func(content, layer)
        results["validations"][name] = result
        if not result.get("valid", True):
            results["overall_valid"] = False

    return results


# ============================================
# LLM Generation Functions
# ============================================

def generate_layer1_report(raw_data: str) -> str:
    """Generate Layer 1 report using new format."""
    # Layer 1 不再使用 SUMMARY_PROMPT，各维度独立生成
    # 测试时直接返回模拟的维度报告
    dimension_reports = """## 村庄现状

### 区位与对外交通分析
梅州市在广东省的位置：梅州市是广东省东北部地级市，位于粤东北山区。
平远县在梅州市的位置：平远县是梅州市下辖县，位于梅州市西北部。
泗水镇在平远县的位置：泗水镇位于平远县东北部山区。
金田村在泗水镇的位置：金田村位于泗水镇西北部，距镇中心约5公里。

### 社会经济分析
行政区划：金田村隶属广东省梅州市平远县泗水镇，下辖6个自然村。
人口情况：全村共有180户，户籍人口约500人，常住人口约200人。
"""

    logger.info("Layer 1 uses per-dimension prompts, returning simulated report for format test...")
    return f"# 广东省梅州市平远县泗水镇金田村 现状报告\n\n{dimension_reports}"


def generate_layer2_report(raw_data: str) -> str:
    """Generate Layer 2 report using new format."""
    # Layer 2 不再使用 SUMMARY_PROMPT，直接返回模拟的规划思路报告
    # 新架构中各维度独立生成，由下游节点合并
    dimension_reports = """
民俗资源：黄粄、船灯舞、仙人粄
自然资源：古檀林、山溪、杉木林
历史古迹：茶亭、古驿道、古桥
特色产业：杉木、中药材、南药

发展目标：梅州市特色南药综合开发示范村
"""

    logger.info("Layer 2 uses per-dimension prompts, returning simulated report for format test...")
    return f"# 广东省梅州市平远县泗水镇金田村 规划思路\n\n{dimension_reports}"


def generate_layer3_report(raw_data: str) -> str:
    """Generate Layer 3 report using new format."""
    # Layer 3 不再使用 SUMMARY_PROMPT，直接返回测试占位符
    # 新架构中各维度独立生成，由下游节点合并
    dimension_reports = """
【产业规划】
产业发展定位：长链条、多环节、高效益的特色产业示范基地

【道路交通规划】
路网规划：对外联系道路宽度7-9m，村干道宽度5-7m

【公共服务设施规划】
设施配置：村委会1个，文化中心1个，卫生室1个
"""

    logger.info("Layer 3 uses per-dimension prompts, returning placeholder for format test...")
    return f"[Layer 3 测试占位符]\n\n{dimension_reports}"


# ============================================
# Main Test Function
# ============================================

def test_layer(layer: int) -> Dict[str, Any]:
    """Test format for a specific layer."""
    ensure_output_dir()

    # Load input data
    raw_data = load_status_report()
    if not raw_data:
        logger.warning("No input data loaded, using placeholder")
        raw_data = "[测试数据] 金田村位于广东省梅州市平远县泗水镇..."

    # Generate report
    if layer == 1:
        content = generate_layer1_report(raw_data)
    elif layer == 2:
        content = generate_layer2_report(raw_data)
    elif layer == 3:
        content = generate_layer3_report(raw_data)
    else:
        raise ValueError(f"Unknown layer: {layer}")

    # Validate format
    results = validate_format(content, layer)
    results["content_preview"] = content[:1000] if len(content) > 1000 else content

    # Save results
    output_file = OUTPUT_DIR / f"layer{layer}_validation.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Save generated content
    content_file = OUTPUT_DIR / f"layer{layer}_generated.md"
    with open(content_file, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Results saved to {output_file}")

    return results


def test_all_layers() -> Dict[str, Any]:
    """Test format for all layers."""
    results = {}
    for layer in [1, 2, 3]:
        logger.info(f"\n{'='*50}")
        logger.info(f"Testing Layer {layer}: {get_layer_config(layer).name}")
        logger.info(f"{'='*50}")
        results[f"layer{layer}"] = test_layer(layer)

    # Summary
    summary = {
        "timestamp": datetime.now().isoformat(),
        "overall_valid": all(r.get("overall_valid", False) for r in results.values()),
        "layers": results,
    }

    # Save summary
    summary_file = OUTPUT_DIR / "all_layers_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary


def print_results(results: Dict[str, Any]):
    """Print validation results in readable format."""
    print("\n" + "="*60)
    print(f"格式验证结果 - {results.get('layer_name', 'Unknown')}")
    print("="*60)

    validations = results.get("validations", {})

    for name, result in validations.items():
        status = "✅ PASS" if result.get("valid", True) else "❌ FAIL"
        print(f"\n[{name}] {status}")
        print(f"  {result.get('message', 'No message')}")
        if result.get("found"):
            print(f"  Found: {result.get('found')[:3]}")

    print("\n" + "-"*60)
    overall = "✅ 所有检查通过" if results.get("overall_valid", True) else "❌ 存在格式问题"
    print(f"总体结果: {overall}")
    print("-"*60)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="测试报告格式规范化效果")
    parser.add_argument(
        "--layer",
        type=str,
        default="1",
        choices=["1", "2", "3", "all"],
        help="测试层级 (1, 2, 3, 或 all)"
    )

    args = parser.parse_args()

    if args.layer == "all":
        results = test_all_layers()
        for layer_key, layer_result in results.get("layers", {}).items():
            print_results(layer_result)
    else:
        layer = int(args.layer)
        results = test_layer(layer)
        print_results(results)


if __name__ == "__main__":
    main()