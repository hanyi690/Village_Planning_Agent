"""
维度生成统计收集器

收集维度级别的生成数据：
- Prompt 字数
- LLM 生成时间
- 输出字数
- RAG 检索时间

支持并行执行：使用 (session_id, dimension_key) 作为唯一键
"""

import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import json
from pathlib import Path


@dataclass
class DimensionStats:
    """单个维度的生成统计"""
    dimension_key: str
    dimension_name: str
    layer: int
    prompt_chars: int = 0
    output_chars: int = 0
    llm_time_seconds: float = 0.0
    rag_time_ms: float = 0.0
    rag_chunks: int = 0
    start_time: str = ""
    end_time: str = ""


@dataclass
class LayerStats:
    """层级统计汇总"""
    layer: int
    layer_name: str
    dimension_count: int = 0
    total_prompt_chars: int = 0
    total_output_chars: int = 0
    total_llm_time_seconds: float = 0.0
    total_rag_time_ms: float = 0.0
    start_time: str = ""
    end_time: str = ""


@dataclass
class SessionStats:
    """会话级别完整统计"""
    session_id: str
    project_name: str
    start_time: str = ""
    end_time: str = ""
    total_time_seconds: float = 0.0
    dimensions: List[Dict[str, Any]] = field(default_factory=list)
    layers: List[Dict[str, Any]] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def add_dimension(self, dim_stats: DimensionStats):
        """添加维度统计"""
        self.dimensions.append(asdict(dim_stats))

    def finalize(self):
        """计算汇总统计"""
        # 按层汇总
        layer_data = {}
        for dim in self.dimensions:
            layer = dim["layer"]
            if layer not in layer_data:
                layer_data[layer] = {
                    "layer": layer,
                    "layer_name": f"Layer{layer}",
                    "dimension_count": 0,
                    "total_prompt_chars": 0,
                    "total_output_chars": 0,
                    "total_llm_time_seconds": 0.0,
                    "total_rag_time_ms": 0.0,
                }
            layer_data[layer]["dimension_count"] += 1
            layer_data[layer]["total_prompt_chars"] += dim["prompt_chars"]
            layer_data[layer]["total_output_chars"] += dim["output_chars"]
            layer_data[layer]["total_llm_time_seconds"] += dim["llm_time_seconds"]
            layer_data[layer]["total_rag_time_ms"] += dim["rag_time_ms"]

        self.layers = list(layer_data.values())

        # 总体汇总
        self.summary = {
            "total_dimensions": len(self.dimensions),
            "total_prompt_chars": sum(d["prompt_chars"] for d in self.dimensions),
            "total_output_chars": sum(d["output_chars"] for d in self.dimensions),
            "total_llm_time_seconds": sum(d["llm_time_seconds"] for d in self.dimensions),
            "avg_llm_time_per_dimension": (
                sum(d["llm_time_seconds"] for d in self.dimensions) / len(self.dimensions)
                if self.dimensions else 0
            ),
        }


class StatsCollector:
    """统计收集器 - 单例模式，支持并行执行"""

    _instance: Optional["StatsCollector"] = None

    def __init__(self):
        self._sessions: Dict[str, SessionStats] = {}
        # 使用 (session_id, dimension_key) 作为键，支持并行执行
        self._current_dimensions: Dict[Tuple[str, str], DimensionStats] = {}
        self._dimension_start_times: Dict[str, float] = {}

    @classmethod
    def get_instance(cls) -> "StatsCollector":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start_session(self, session_id: str, project_name: str = ""):
        """开始会话统计"""
        self._sessions[session_id] = SessionStats(
            session_id=session_id,
            project_name=project_name,
            start_time=datetime.now().isoformat(),
        )

    def end_session(self, session_id: str) -> Optional[SessionStats]:
        """结束会话统计"""
        if session_id in self._sessions:
            stats = self._sessions[session_id]
            stats.end_time = datetime.now().isoformat()
            if session_id in self._dimension_start_times:
                start = self._dimension_start_times.get(session_id, 0)
                if start:
                    stats.total_time_seconds = time.time() - start
            stats.finalize()
            return stats
        return None

    def start_dimension(self, session_id: str, dimension_key: str, dimension_name: str, layer: int):
        """开始维度统计 - 使用 (session_id, dimension_key) 作为唯一键"""
        if session_id not in self._sessions:
            self.start_session(session_id)

        key = (session_id, dimension_key)
        self._current_dimensions[key] = DimensionStats(
            dimension_key=dimension_key,
            dimension_name=dimension_name,
            layer=layer,
            start_time=datetime.now().isoformat(),
        )
        # 记录会话开始时间（首次维度）
        if session_id not in self._dimension_start_times:
            self._dimension_start_times[session_id] = time.time()

    def record_prompt(self, session_id: str, dimension_key: str, prompt_chars: int):
        """记录 Prompt 字数"""
        key = (session_id, dimension_key)
        if key in self._current_dimensions:
            self._current_dimensions[key].prompt_chars = prompt_chars

    def record_llm_time(self, session_id: str, dimension_key: str, elapsed_seconds: float, output_chars: int):
        """记录 LLM 生成时间和输出字数"""
        key = (session_id, dimension_key)
        if key in self._current_dimensions:
            dim = self._current_dimensions[key]
            dim.llm_time_seconds = elapsed_seconds
            dim.output_chars = output_chars
            dim.end_time = datetime.now().isoformat()

    def record_rag_time(self, session_id: str, dimension_key: str, elapsed_ms: float, chunk_count: int):
        """记录 RAG 检索时间"""
        key = (session_id, dimension_key)
        if key in self._current_dimensions:
            self._current_dimensions[key].rag_time_ms = elapsed_ms
            self._current_dimensions[key].rag_chunks = chunk_count

    def end_dimension(self, session_id: str, dimension_key: str) -> Optional[DimensionStats]:
        """结束维度统计，添加到会话"""
        key = (session_id, dimension_key)
        if key in self._current_dimensions:
            dim_stats = self._current_dimensions[key]
            if session_id in self._sessions:
                self._sessions[session_id].add_dimension(dim_stats)
            del self._current_dimensions[key]
            return dim_stats
        return None

    def get_session_stats(self, session_id: str) -> Optional[SessionStats]:
        """获取会话统计"""
        return self._sessions.get(session_id)

    def save_session_stats(self, session_id: str, output_path: Path) -> Optional[Path]:
        """保存会话统计到 JSON 文件"""
        stats = self.end_session(session_id)
        if stats:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(asdict(stats), ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            return output_path
        return None

    def clear_session(self, session_id: str):
        """清理会话数据"""
        if session_id in self._sessions:
            del self._sessions[session_id]
        # 清理所有该会话的维度数据
        keys_to_delete = [k for k in self._current_dimensions if k[0] == session_id]
        for k in keys_to_delete:
            del self._current_dimensions[k]
        if session_id in self._dimension_start_times:
            del self._dimension_start_times[session_id]


def format_stats_report(stats: SessionStats) -> str:
    """格式化统计报告为可读文本"""
    lines = [
        "=" * 60,
        f"会话统计报告: {stats.session_id}",
        f"项目名称: {stats.project_name}",
        f"统计时间: {stats.start_time} ~ {stats.end_time}",
        f"总耗时: {stats.total_time_seconds:.2f} 秒",
        "=" * 60,
        "",
        "层级汇总:",
        "-" * 40,
    ]

    for layer in stats.layers:
        lines.extend([
            f"  Layer {layer['layer']}: {layer['dimension_count']} 维度",
            f"    Prompt 总字数: {layer['total_prompt_chars']:,}",
            f"    输出总字数: {layer['total_output_chars']:,}",
            f"    LLM 总时间: {layer['total_llm_time_seconds']:.2f}s",
            f"    RAG 总时间: {layer['total_rag_time_ms']:.0f}ms",
            "",
        ])

    lines.extend([
        "维度详情:",
        "-" * 40,
    ])

    # 按层分组显示
    dims_by_layer = {}
    for dim in stats.dimensions:
        layer = dim["layer"]
        if layer not in dims_by_layer:
            dims_by_layer[layer] = []
        dims_by_layer[layer].append(dim)

    for layer in sorted(dims_by_layer.keys()):
        lines.append(f"\n  --- Layer {layer} ---")
        for dim in dims_by_layer[layer]:
            lines.extend([
                f"    {dim['dimension_key']}:",
                f"      Prompt: {dim['prompt_chars']:,} 字",
                f"      输出: {dim['output_chars']:,} 字",
                f"      LLM: {dim['llm_time_seconds']:.2f}s",
            ])

    lines.extend([
        "",
        "=" * 60,
        "总体统计:",
        "-" * 40,
        f"  总维度数: {stats.summary.get('total_dimensions', 0)}",
        f"  总 Prompt 字数: {stats.summary.get('total_prompt_chars', 0):,}",
        f"  总输出字数: {stats.summary.get('total_output_chars', 0):,}",
        f"  总 LLM 时间: {stats.summary.get('total_llm_time_seconds', 0):.2f}s",
        f"  平均每维度 LLM 时间: {stats.summary.get('avg_llm_time_per_dimension', 0):.2f}s",
        "=" * 60,
    ])

    return "\n".join(lines)