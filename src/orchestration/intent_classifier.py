"""
意图分类器 (Intent Classifier)

使用 LLM 分类用户意图，支持：
- 规划控制：开始、继续、回滚
- 信息请求：提问、查看详情
- 工具调用：运行特定工具
- 反馈处理：批准、拒绝、修改

设计要点：
- LLM 分类提供高灵活性
- 缓存常用意图模式降低延迟
- Fallback 处理歧义情况
"""

from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
import re
import time

from ..core.llm_factory import create_llm
from ..core.config import LLM_MODEL
from ..utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# 意图枚举定义
# ==========================================

class UserIntent(Enum):
    """用户意图枚举"""
    # 规划控制
    START_PLANNING = "start_planning"       # 开始规划
    CONTINUE_PLANNING = "continue_planning"  # 继续下一步
    ROLLBACK = "rollback"                    # 回退

    # 信息请求
    ASK_QUESTION = "ask_question"           # 提问
    REQUEST_DETAILS = "request_details"     # 查看详情

    # 工具调用
    RUN_TOOL = "run_tool"                   # 运行工具

    # 反馈处理
    REQUEST_REVISION = "request_revision"   # 请求修改
    APPROVE = "approve"                     # 批准
    REJECT = "reject"                       # 拒绝

    # Fallback
    UNKNOWN = "unknown"                     # 未知意图


@dataclass
class IntentResult:
    """意图分类结果"""
    intent: UserIntent
    confidence: float
    parameters: Dict[str, Any]
    fallback: bool = False
    reason: str = ""


# ==========================================
# 规则模式（快速匹配，降低延迟）
# ==========================================

# 高置信度规则模式
INTENT_PATTERNS = {
    UserIntent.CONTINUE_PLANNING: [
        r"继续",
        r"下一步",
        r"继续规划",
        r"开始分析",
        r"开始规划",
        r"执行",
        r"进行",
    ],
    UserIntent.APPROVE: [
        r"^好$",
        r"^行$",
        r"^可以$",
        r"^确认$",
        r"^同意$",
        r"^没问题$",
        r"^批准$",
        r"^通过$",
    ],
    UserIntent.REJECT: [
        r"^不行$",
        r"^不好$",
        r"^拒绝$",
        r"^不通过$",
        r"^重来$",
        r"^修改$",
    ],
    UserIntent.REQUEST_REVISION: [
        r"修改.*",
        r"调整.*",
        r"改一下.*",
        r"重新.*",
        r"修改这个",
    ],
    UserIntent.RUN_TOOL: [
        r"运行.*工具",
        r"调用.*",
        r"执行.*分析",
        r"GIS.*分析",
        r"搜索.*",
    ],
    UserIntent.ASK_QUESTION: [
        r"为什么.*",
        r"怎么.*",
        r"如何.*",
        r"什么是.*",
        r"有什么.*",
        r"\?$",  # 以问号结尾
    ],
    UserIntent.REQUEST_DETAILS: [
        r"显示.*详情",
        r"展示.*",
        r"查看.*",
        r"看看.*",
        r"详细.*",
    ],
    UserIntent.ROLLBACK: [
        r"回退",
        r"撤销",
        r"恢复到.*",
        r"返回.*",
    ],
}


# ==========================================
# 意图缓存（降低 LLM 调用延迟）
# ==========================================

class IntentCache:
    """意图缓存 - 缓存常见意图模式"""

    def __init__(self, max_size: int = 100):
        self.cache: Dict[str, IntentResult] = {}
        self.max_size = max_size

    def get(self, message: str) -> Optional[IntentResult]:
        """获取缓存的意图"""
        normalized = self._normalize(message)
        return self.cache.get(normalized)

    def set(self, message: str, result: IntentResult):
        """缓存意图结果"""
        if len(self.cache) >= self.max_size:
            # 简单 LRU：清除一半
            keys = list(self.cache.keys())[:self.max_size // 2]
            for k in keys:
                del self.cache[k]

        normalized = self._normalize(message)
        self.cache[normalized] = result

    def _normalize(self, message: str) -> str:
        """标准化消息用于缓存键"""
        return message.strip().lower()[:50]


# 全局缓存实例
_intent_cache = IntentCache()


# ==========================================
# 意图分类主函数
# ==========================================

def classify_intent(
    user_message: str,
    state: Optional[Dict[str, Any]] = None,
    use_cache: bool = True
) -> UserIntent:
    """
    分类用户意图

    Args:
        user_message: 用户消息
        state: 当前状态（用于上下文感知）
        use_cache: 是否使用缓存

    Returns:
        UserIntent: 分类后的意图
    """
    start_time = time.time()

    # 1. 检查缓存
    if use_cache:
        cached = _intent_cache.get(user_message)
        if cached:
            logger.debug(f"[intent] 缓存命中: {cached.intent.value}")
            return cached.intent

    # 2. 规则快速匹配（高置信度模式）
    rule_result = _match_intent_patterns(user_message)
    if rule_result and rule_result.confidence > 0.9:
        if use_cache:
            _intent_cache.set(user_message, rule_result)
        logger.debug(f"[intent] 规则匹配: {rule_result.intent.value}")
        return rule_result.intent

    # 3. LLM 分类
    llm_result = _classify_with_llm(user_message, state)

    # 4. Fallback 处理
    if llm_result.confidence < 0.5:
        logger.warning(f"[intent] 低置信度: {llm_result.confidence:.2f}, 使用 fallback")
        # 根据上下文推断
        fallback_intent = _fallback_classification(user_message, state)
        llm_result = IntentResult(
            intent=fallback_intent,
            confidence=llm_result.confidence,
            parameters={},
            fallback=True,
            reason=f"LLM 置信度过低，fallback 到 {fallback_intent.value}"
        )

    # 缓存结果
    if use_cache:
        _intent_cache.set(user_message, llm_result)

    elapsed = (time.time() - start_time) * 1000
    logger.info(f"[intent] 分类完成: {llm_result.intent.value} (置信度: {llm_result.confidence:.2f}, 耗时: {elapsed:.0f}ms)")

    return llm_result.intent


# ==========================================
# 规则匹配
# ==========================================

def _match_intent_patterns(message: str) -> Optional[IntentResult]:
    """使用正则模式匹配意图"""
    message = message.strip()

    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, message, re.IGNORECASE):
                return IntentResult(
                    intent=intent,
                    confidence=0.95,
                    parameters={}
                )

    return None


# ==========================================
# LLM 分类
# ==========================================

INTENT_CLASSIFICATION_PROMPT = """分析用户消息，判断其意图。

当前规划阶段：{phase}
可用操作：{available_actions}

用户消息："{message}"

请以 JSON 格式返回分析结果：
{{
  "intent": "<意图类型>",
  "confidence": <0.0-1.0>,
  "parameters": {{}},
  "reason": "<判断理由>"
}}

有效意图类型：
- start_planning: 开始规划
- continue_planning: 继续下一步规划
- rollback: 回退到之前的状态
- ask_question: 提问（需要解答）
- request_details: 查看详情（展示已有数据）
- run_tool: 运行特定工具
- request_revision: 请求修改规划
- approve: 批准当前结果
- reject: 拒绝当前结果
- unknown: 无法判断

只返回 JSON，不要其他内容。"""


def _classify_with_llm(message: str, state: Optional[Dict[str, Any]] = None) -> IntentResult:
    """使用 LLM 分类意图"""
    try:
        llm = create_llm(model=LLM_MODEL, temperature=0.1, max_tokens=200)

        phase = state.get("current_phase", "init") if state else "init"
        pending_review = state.get("pending_review", False) if state else False

        # 根据状态确定可用操作
        available_actions = _get_available_actions(phase, pending_review)

        prompt = INTENT_CLASSIFICATION_PROMPT.format(
            phase=phase,
            available_actions=", ".join(available_actions),
            message=message
        )

        response = llm.invoke([{"role": "user", "content": prompt}])
        content = response.content if hasattr(response, "content") else str(response)

        # 解析 JSON
        import json
        # 尝试提取 JSON
        json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            intent_str = data.get("intent", "unknown")
            confidence = float(data.get("confidence", 0.5))

            try:
                intent = UserIntent(intent_str)
            except ValueError:
                intent = UserIntent.UNKNOWN

            return IntentResult(
                intent=intent,
                confidence=confidence,
                parameters=data.get("parameters", {}),
                reason=data.get("reason", "")
            )

    except Exception as e:
        logger.error(f"[intent] LLM 分类失败: {e}")

    return IntentResult(
        intent=UserIntent.UNKNOWN,
        confidence=0.0,
        parameters={},
        reason=f"LLM 分类异常: {str(e)}"
    )


# ==========================================
# Fallback 处理
# ==========================================

def _fallback_classification(message: str, state: Optional[Dict[str, Any]] = None) -> UserIntent:
    """
    Fallback 意图分类

    当规则匹配和 LLM 分类都无法确定时，根据上下文推断。
    """
    if not state:
        return UserIntent.ASK_QUESTION  # 默认当作提问

    pending_review = state.get("pending_review", False)
    phase = state.get("current_phase", "init")

    # 如果在审核阶段
    if pending_review:
        # 检查是否像批准
        if any(w in message for w in ["好", "行", "可以", "确认", "对"]):
            return UserIntent.APPROVE
        # 检查是否像拒绝
        if any(w in message for w in ["不", "改", "重新", "不行"]):
            return UserIntent.REQUEST_REVISION
        # 默认等待用户明确意图
        return UserIntent.ASK_QUESTION

    # 如果在执行阶段
    if "analysis" in phase or "concept" in phase or "detail" in phase:
        return UserIntent.CONTINUE_PLANNING

    # 初始化阶段默认开始规划
    if phase == "init":
        return UserIntent.START_PLANNING

    return UserIntent.ASK_QUESTION


def _get_available_actions(phase: str, pending_review: bool) -> List[str]:
    """根据状态获取可用操作"""
    if pending_review:
        return ["approve", "reject", "request_revision", "ask_question"]

    if phase == "init":
        return ["start_planning", "ask_question"]

    if phase == "completed":
        return ["rollback", "ask_question", "request_details"]

    return ["continue_planning", "run_tool", "ask_question", "request_details"]


# ==========================================
# 批量意图分类（优化性能）
# ==========================================

def classify_intents_batch(
    messages: List[str],
    state: Optional[Dict[str, Any]] = None
) -> List[UserIntent]:
    """
    批量分类意图

    对多条消息进行分类，共享 LLM 调用以优化性能。
    """
    results = []

    for message in messages:
        intent = classify_intent(message, state)
        results.append(intent)

    return results


__all__ = [
    "UserIntent",
    "IntentResult",
    "classify_intent",
    "classify_intents_batch",
    "IntentCache",
]