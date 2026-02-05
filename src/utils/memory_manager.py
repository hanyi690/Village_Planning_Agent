"""
内存管理工具 (Memory Manager)

提供内存优化和清理功能，解决长时间运行后的内存泄漏问题：
1. 消息历史修剪 - 限制消息列表长度
2. 状态数据清理 - 清理已完成层级的状态数据
3. 黑板数据清理 - 定期清理黑板累积数据
4. RAG资源清理 - 清理向量数据库和LLM实例
5. 内存监控 - 提供内存使用情况监控

使用场景：
- 长时间运行的规划任务
- 多次回退/修复操作
- 大规模文档处理
"""

import gc
import sys
from typing import List, Dict, Any, Optional, Callable
from collections import deque
from datetime import datetime, timedelta

try:
    from langchain_core.messages import BaseMessage
except ImportError:
    BaseMessage = Any

from .logger import get_logger

logger = get_logger(__name__)


# ==========================================
# 消息历史修剪 (Priority 1)
# ==========================================

def trim_messages(
    messages: List[BaseMessage],
    max_count: int = 50,
    preserve_first: int = 5,
    preserve_system: bool = True
) -> List[BaseMessage]:
    """
    修剪消息历史，保留最近的消息

    策略：
    - 保留前N条消息（通常是初始prompt）
    - 保留所有SystemMessage
    - 保留最近N条消息
    - 中间的消息会被删除

    Args:
        messages: 消息列表
        max_count: 最大保留消息数量（默认50）
        preserve_first: 保留开头的消息数量（默认5）
        preserve_system: 是否保留所有SystemMessage（默认True）

    Returns:
        修剪后的消息列表
    """
    if not messages:
        return messages

    original_count = len(messages)
    if original_count <= max_count:
        return messages

    try:
        from langchain_core.messages import SystemMessage
    except ImportError:
        SystemMessage = None
        preserve_system = False

    result = []

    # 1. 保留开头的消息
    result.extend(messages[:preserve_first])

    # 2. 保留所有SystemMessage（从中间位置）
    if preserve_system and SystemMessage:
        start_idx = preserve_first
        end_idx = original_count - max_count + preserve_first

        for i in range(start_idx, max(start_idx, end_idx)):
            if isinstance(messages[i], SystemMessage):
                result.append(messages[i])

    # 3. 保留最近的消息
    recent_count = max_count - len(result)
    if recent_count > 0:
        result.extend(messages[-recent_count:])

    logger.info(f"[内存管理] 消息修剪: {original_count} -> {len(result)} "
                f"(节省 {original_count - len(result)} 条消息)")

    return result


def trim_state_messages(
    state: Dict[str, Any],
    max_count: int = 50,
    preserve_first: int = 5
) -> Dict[str, Any]:
    """
    修剪状态中的消息历史

    Args:
        state: 状态字典
        max_count: 最大保留消息数量
        preserve_first: 保留开头的消息数量

    Returns:
        更新后的状态字典
    """
    if "messages" in state and state["messages"]:
        original_count = len(state["messages"])
        state["messages"] = trim_messages(
            state["messages"],
            max_count=max_count,
            preserve_first=preserve_first
        )

        if original_count != len(state["messages"]):
            logger.info(f"[内存管理] 状态消息已修剪: {original_count} -> {len(state['messages'])}")

    return state


# ==========================================
# 状态数据清理 (Priority 2)
# ==========================================

def cleanup_after_layer(
    state: Dict[str, Any],
    completed_layer: int,
    keep_final_reports: bool = True
) -> Dict[str, Any]:
    """
    层级完成后清理旧的状态数据

    清理策略：
    - Layer 2完成后：清理dimension_reports（保留最终报告）
    - Layer 3完成后：清理dimension_reports和concept_dimension_reports

    Args:
        state: 状态字典
        completed_layer: 已完成的层级 (1/2/3)
        keep_final_reports: 是否保留最终报告

    Returns:
        清理后的状态字典
    """
    logger.info(f"[内存管理] 开始清理Layer {completed_layer}完成后的状态数据")

    cleanup_count = 0

    # Layer 2完成后：清理Layer 1的维度报告（保留综合报告）
    if completed_layer >= 2:
        if "dimension_reports" in state:
            report_count = len(state["dimension_reports"])
            # 保留引用，但清理实际数据（如果想完全删除，使用pop）
            # 这里我们保留字典，但清空内容
            if not keep_final_reports:
                state.pop("dimension_reports", None)
                cleanup_count += report_count
                logger.info(f"[内存管理] 清理dimension_reports: {report_count}个报告")
            else:
                # 如果保留最终报告，只记录日志
                logger.debug(f"[内存管理] 保留dimension_reports: {report_count}个报告")

    # Layer 3完成后：清理所有维度报告（保留最终报告）
    if completed_layer >= 3:
        if "concept_dimension_reports" in state:
            report_count = len(state["concept_dimension_reports"])
            if not keep_final_reports:
                state.pop("concept_dimension_reports", None)
                cleanup_count += report_count
                logger.info(f"[内存管理] 清理concept_dimension_reports: {report_count}个报告")

        # 清理详细规划的维度报告
        for key in list(state.keys()):
            if key.endswith("_dimension_reports") and not keep_final_reports:
                report_count = len(state[key])
                state.pop(key, None)
                cleanup_count += report_count
                logger.info(f"[内存管理] 清理{key}: {report_count}个报告")

    logger.info(f"[内存管理] Layer {completed_layer}清理完成，共清理 {cleanup_count} 个报告")

    return state


# ==========================================
# 黑板数据清理 (Priority 3)
# ==========================================

def cleanup_blackboard(
    blackboard: Any,
    max_tool_results: int = 100,
    max_insights: int = 50,
    cleanup_old_days: int = 7
) -> None:
    """
    清理黑板中的旧数据

    Args:
        blackboard: BlackboardManager实例
        max_tool_results: 最大保留工具结果数量
        max_insights: 最大保留洞察数量
        cleanup_old_days: 清理N天前的旧数据
    """
    if blackboard is None:
        return

    try:
        # 获取状态
        status = blackboard.get_status()
        logger.info(f"[内存管理] 黑板清理开始 - 工具结果: {status['tool_results_count']}, "
                   f"洞察: {status['insights_count']}")

        # 清理工具结果（保留最近的）
        all_tool_results = blackboard.list_tool_results()
        if len(all_tool_results) > max_tool_results:
            # 按时间排序，保留最近的
            sorted_results = sorted(
                all_tool_results.items(),
                key=lambda x: x[1].timestamp,
                reverse=True
            )
            kept = dict(sorted_results[:max_tool_results])

            # 清空并重新添加
            blackboard._tool_results.clear()
            blackboard._tool_results.update(kept)

            logger.info(f"[内存管理] 工具结果清理: "
                       f"{len(all_tool_results)} -> {max_tool_results}")

        # 洞察数量限制（BlackboardManager已经有自动限制机制）
        if status['insights_count'] > max_insights:
            insights = blackboard.list_insights()
            blackboard._insights = insights[-max_insights:]
            logger.info(f"[内存管理] 洞察清理: "
                       f"{status['insights_count']} -> {max_insights}")

        # 清理旧数据（基于时间戳）
        if cleanup_old_days > 0:
            cutoff_date = datetime.now() - timedelta(days=cleanup_old_days)

            # 清理旧工具结果
            old_tool_ids = []
            for tool_id, result in all_tool_results.items():
                try:
                    result_time = datetime.fromisoformat(result.timestamp)
                    if result_time < cutoff_date:
                        old_tool_ids.append(tool_id)
                except:
                    continue

            for tool_id in old_tool_ids:
                del blackboard._tool_results[tool_id]

            # 清理旧洞察
            old_insights = []
            for i, insight in enumerate(blackboard._insights):
                try:
                    insight_time = datetime.fromisoformat(insight.timestamp)
                    if insight_time < cutoff_date:
                        old_insights.append(i)
                except:
                    continue

            # 从后往前删除，避免索引问题
            for i in reversed(old_insights):
                blackboard._insights.pop(i)

            if old_tool_ids or old_insights:
                logger.info(f"[内存管理] 清理旧数据: {len(old_tool_ids)}个工具结果, "
                           f"{len(old_insights)}个洞察")

    except Exception as e:
        logger.error(f"[内存管理] 黑板清理失败: {e}")


def cleanup_blackboard_state(
    state: Dict[str, Any],
    **cleanup_kwargs
) -> Dict[str, Any]:
    """
    清理状态中黑板数据的包装函数

    Args:
        state: 状态字典
        **cleanup_kwargs: 传递给cleanup_blackboard的参数

    Returns:
        更新后的状态字典
    """
    blackboard = state.get("blackboard")
    if blackboard:
        cleanup_blackboard(blackboard, **cleanup_kwargs)
    return state


# ==========================================
# 内存监控工具
# ==========================================

def get_memory_usage_mb() -> float:
    """
    获取当前进程的内存使用量（MB）

    Returns:
        内存使用量（MB）
    """
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024
    except ImportError:
        # 降级方案：使用sys模块
        import sys
        return sys.getsizeof([]) / 1024 / 1024  # 粗略估算


def log_memory_usage(context: str = "") -> None:
    """
    记录当前内存使用情况

    Args:
        context: 上下文描述
    """
    try:
        memory_mb = get_memory_usage_mb()
        logger.info(f"[内存监控] {context} - 当前内存使用: {memory_mb:.2f} MB")
    except Exception as e:
        logger.debug(f"[内存监控] 获取内存使用失败: {e}")


def get_detailed_memory_info() -> Dict[str, Any]:
    """
    获取详细的内存信息

    Returns:
        内存信息字典
    """
    result = {
        "rss_mb": 0,
        "vms_mb": 0,
        "percent": 0,
        "available_mb": 0
    }

    try:
        import psutil
        process = psutil.Process()
        mem_info = process.memory_info()
        sys_mem = psutil.virtual_memory()

        result["rss_mb"] = mem_info.rss / 1024 / 1024
        result["vms_mb"] = mem_info.vms / 1024 / 1024
        result["percent"] = sys_mem.percent
        result["available_mb"] = sys_mem.available / 1024 / 1024

    except ImportError:
        # 降级方案
        result["rss_mb"] = get_memory_usage_mb()

    return result


# ==========================================
# 垃圾回收辅助
# ==========================================

def force_garbage_collection() -> Dict[str, int]:
    """
    强制执行垃圾回收

    Returns:
        回收统计信息
    """
    logger.debug("[内存管理] 执行垃圾回收")

    before_objects = len(gc.get_objects())
    collected = gc.collect(generation=2)  # 完整回收
    after_objects = len(gc.get_objects())

    result = {
        "collected": collected,
        "before_objects": before_objects,
        "after_objects": after_objects,
        "freed_objects": before_objects - after_objects
    }

    logger.info(f"[内存管理] 垃圾回收完成: 回收{collected}个对象, "
               f"释放{result['freed_objects']}个对象引用")

    return result


# ==========================================
# 综合清理函数
# ==========================================

def comprehensive_cleanup(
    state: Dict[str, Any],
    completed_layer: Optional[int] = None,
    trim_messages: bool = True,
    max_messages: int = 50,
    cleanup_blackboard_enabled: bool = True,
    force_gc: bool = True
) -> Dict[str, Any]:
    """
    综合内存清理函数

    执行所有内存优化操作：
    1. 修剪消息历史
    2. 清理已完成层级的状态数据
    3. 清理黑板数据
    4. 强制垃圾回收

    Args:
        state: 状态字典
        completed_layer: 已完成的层级（可选）
        trim_messages: 是否修剪消息
        max_messages: 最大保留消息数量
        cleanup_blackboard_enabled: 是否清理黑板
        force_gc: 是否强制垃圾回收

    Returns:
        清理后的状态字典
    """
    logger.info("[内存管理] 开始综合内存清理")

    # 记录清理前内存
    log_memory_usage("清理前")

    # 1. 修剪消息历史
    if trim_messages and "messages" in state:
        state = trim_state_messages(state, max_count=max_messages)

    # 2. 清理已完成层级的状态数据
    if completed_layer is not None:
        state = cleanup_after_layer(state, completed_layer)

    # 3. 清理黑板数据
    if cleanup_blackboard_enabled:
        state = cleanup_blackboard_state(state)

    # 4. 强制垃圾回收
    if force_gc:
        force_garbage_collection()

    # 记录清理后内存
    log_memory_usage("清理后")

    logger.info("[内存管理] 综合内存清理完成")

    return state


# ==========================================
# 装饰器
# ==========================================

def with_memory_cleanup(
    max_messages: int = 50,
    cleanup_after_layer: bool = False,
    log_memory: bool = True
):
    """
    内存清理装饰器

    自动在函数执行后清理内存

    Args:
        max_messages: 最大保留消息数量
        cleanup_after_layer: 是否在层级完成后清理
        log_memory: 是否记录内存使用
    """
    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            # 记录执行前内存
            if log_memory:
                log_memory_usage(f"{func.__name__} 执行前")

            # 执行函数
            result = func(*args, **kwargs)

            # 如果返回的是状态字典，进行清理
            if isinstance(result, dict) and "messages" in result:
                # 修剪消息
                result = trim_state_messages(result, max_count=max_messages)

                # 层级完成后清理
                if cleanup_after_layer:
                    completed_layer = result.get("current_layer", 0)
                    if completed_layer > 1:
                        result = cleanup_after_layer(result, completed_layer - 1)

            # 记录执行后内存
            if log_memory:
                log_memory_usage(f"{func.__name__} 执行后")

            return result

        return wrapper
    return decorator


# ==========================================
# 监控类
# ==========================================

class MemoryMonitor:
    """
    内存监控类

    提供持续的内存监控和报告功能
    """

    def __init__(self, check_interval: int = 60):
        """
        初始化内存监控器

        Args:
            check_interval: 检查间隔（秒）
        """
        self.check_interval = check_interval
        self._baseline = None
        self._readings: deque = deque(maxlen=100)

    def set_baseline(self) -> float:
        """设置内存基线"""
        self._baseline = get_memory_usage_mb()
        logger.info(f"[内存监控] 设置内存基线: {self._baseline:.2f} MB")
        return self._baseline

    def check_memory(self, context: str = "") -> Dict[str, Any]:
        """
        检查当前内存使用

        Args:
            context: 上下文描述

        Returns:
            内存使用信息
        """
        current_mb = get_memory_usage_mb()
        info = get_detailed_memory_info()
        info["context"] = context
        info["current_mb"] = current_mb

        if self._baseline:
            info["baseline_mb"] = self._baseline
            info["delta_mb"] = current_mb - self._baseline
            info["delta_percent"] = (info["delta_mb"] / self._baseline * 100) if self._baseline > 0 else 0

        self._readings.append({
            "timestamp": datetime.now().isoformat(),
            **info
        })

        logger.info(f"[内存监控] {context} - 内存: {current_mb:.2f} MB "
                   f"(基线: {self._baseline:.2f} MB, "
                   f"变化: {info.get('delta_mb', 0):.2f} MB)")

        return info

    def get_readings(self, count: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取历史读数"""
        readings = list(self._readings)
        if count:
            return readings[-count:]
        return readings

    def detect_memory_leak(self, threshold_mb: float = 100) -> bool:
        """
        检测可能的内存泄漏

        Args:
            threshold_mb: 内存增长阈值（MB）

        Returns:
            True if 可能存在内存泄漏
        """
        if not self._baseline or len(self._readings) < 2:
            return False

        current_mb = get_memory_usage_mb()
        delta = current_mb - self._baseline

        if delta > threshold_mb:
            logger.warning(f"[内存监控] 检测到可能的内存泄漏: "
                          f"内存增长 {delta:.2f} MB (阈值: {threshold_mb} MB)")
            return True

        return False


__all__ = [
    "trim_messages",
    "trim_state_messages",
    "cleanup_after_layer",
    "cleanup_blackboard",
    "cleanup_blackboard_state",
    "get_memory_usage_mb",
    "log_memory_usage",
    "get_detailed_memory_info",
    "force_garbage_collection",
    "comprehensive_cleanup",
    "with_memory_cleanup",
    "MemoryMonitor"
]
