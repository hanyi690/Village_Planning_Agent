"""
对话记忆管理 (Conversation Memory)

支持：
- 对话历史存储
- 语义检索相关对话
- 摘要生成（超出长度限制时）

用于对话式 Agent 引用之前的对话内容。
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import math

from ..utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# 对话轮次数据类
# ==========================================

@dataclass
class ConversationTurn:
    """对话轮次"""
    turn_id: int
    role: str  # "user" / "assistant" / "tool"
    content: str
    timestamp: str
    phase: str = ""
    tools_used: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "phase": self.phase,
            "tools_used": self.tools_used,
            "metadata": self.metadata
        }


@dataclass
class ConversationSummary:
    """对话摘要"""
    turn_range: Tuple[int, int]
    summary: str
    key_points: List[str]
    created_at: str


# ==========================================
# 对话记忆类
# ==========================================

class ConversationMemory:
    """
    对话记忆管理

    功能：
    - 存储对话历史
    - 生成摘要（超出限制时）
    - 提供上下文检索

    注意：语义检索需要 Embeddings，这里提供接口但不强制依赖。
    """

    def __init__(
        self,
        max_turns: int = 50,
        max_tokens: int = 4000,
        enable_embeddings: bool = False
    ):
        """
        Args:
            max_turns: 最大保留轮次
            max_tokens: 最大 token 数（用于触发摘要）
            enable_embeddings: 是否启用语义检索
        """
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self.enable_embeddings = enable_embeddings

        self.turns: List[ConversationTurn] = []
        self.summaries: List[ConversationSummary] = []
        self._embeddings: List[Any] = []  # 存储嵌入向量
        self._embedder = None

        if enable_embeddings:
            self._init_embedder()

    def _init_embedder(self):
        """初始化嵌入模型"""
        try:
            from langchain_core.embeddings import Embeddings
            # 可以使用任何 LangChain 兼容的嵌入模型
            # 例如：OpenAIEmbeddings, HuggingFaceEmbeddings
            logger.info("[ConversationMemory] 嵌入模型功能已启用，但需要配置具体模型")
        except ImportError:
            logger.warning("[ConversationMemory] langchain_core 不可用，禁用语义检索")
            self.enable_embeddings = False

    def add_turn(
        self,
        role: str,
        content: str,
        phase: str = "",
        tools_used: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ConversationTurn:
        """
        添加对话轮次

        Args:
            role: 角色 (user/assistant/tool)
            content: 内容
            phase: 当前阶段
            tools_used: 使用的工具列表
            metadata: 额外元数据

        Returns:
            创建的 ConversationTurn
        """
        turn = ConversationTurn(
            turn_id=len(self.turns),
            role=role,
            content=content,
            timestamp=datetime.now().isoformat(),
            phase=phase,
            tools_used=tools_used or [],
            metadata=metadata or {}
        )

        self.turns.append(turn)

        # 计算嵌入（如果启用）
        if self.enable_embeddings and self._embedder:
            self._compute_embedding(turn)

        # 检查是否需要摘要
        if len(self.turns) > self.max_turns:
            self._summarize_old_turns()

        return turn

    def get_turn(self, turn_id: int) -> Optional[ConversationTurn]:
        """获取指定轮次"""
        if 0 <= turn_id < len(self.turns):
            return self.turns[turn_id]
        return None

    def get_recent_turns(self, n: int = 10) -> List[ConversationTurn]:
        """获取最近 n 轮对话"""
        return self.turns[-n:] if self.turns else []

    def get_turns_by_phase(self, phase: str) -> List[ConversationTurn]:
        """获取指定阶段的所有对话"""
        return [t for t in self.turns if t.phase == phase]

    def get_turns_with_tools(self) -> List[ConversationTurn]:
        """获取包含工具调用的对话"""
        return [t for t in self.turns if t.tools_used]

    def get_context_for_llm(
        self,
        max_tokens: Optional[int] = None,
        include_summaries: bool = True
    ) -> str:
        """
        构建用于 LLM 的上下文字符串

        Args:
            max_tokens: 最大 token 数
            include_summaries: 是否包含历史摘要

        Returns:
            格式化的上下文字符串
        """
        max_tokens = max_tokens or self.max_tokens
        parts = []

        # 添加历史摘要
        if include_summaries and self.summaries:
            parts.append("[历史对话摘要]")
            for summary in self.summaries:
                parts.append(f"- {summary.summary}")
            parts.append("")

        # 添加最近对话
        parts.append("[最近对话]")
        token_count = 0

        for turn in reversed(self.turns):
            turn_text = f"{turn.role}: {turn.content}"
            turn_tokens = self._estimate_tokens(turn_text)

            if token_count + turn_tokens > max_tokens:
                break

            parts.insert(-1, turn_text)  # 插入到 [最近对话] 标题后
            token_count += turn_tokens

        return "\n".join(parts)

    def search_similar(
        self,
        query: str,
        k: int = 3,
        min_similarity: float = 0.5
    ) -> List[Tuple[ConversationTurn, float]]:
        """
        语义检索相似对话

        Args:
            query: 查询文本
            k: 返回数量
            min_similarity: 最小相似度阈值

        Returns:
            (ConversationTurn, similarity) 列表
        """
        if not self.enable_embeddings or not self._embedder:
            # 回退到关键词匹配
            return self._keyword_search(query, k)

        try:
            import numpy as np

            query_embedding = self._embedder.embed_query(query)
            query_vec = np.array(query_embedding)

            similarities = []
            for i, turn_embedding in enumerate(self._embeddings):
                turn_vec = np.array(turn_embedding)
                # 余弦相似度
                sim = np.dot(query_vec, turn_vec) / (
                    np.linalg.norm(query_vec) * np.linalg.norm(turn_vec)
                )
                if sim >= min_similarity:
                    similarities.append((self.turns[i], float(sim)))

            # 按相似度排序
            similarities.sort(key=lambda x: x[1], reverse=True)
            return similarities[:k]

        except Exception as e:
            logger.error(f"[ConversationMemory] 语义检索失败: {e}")
            return self._keyword_search(query, k)

    def _keyword_search(
        self,
        query: str,
        k: int = 3
    ) -> List[Tuple[ConversationTurn, float]]:
        """关键词搜索（fallback）"""
        query_words = set(query.lower().split())
        results = []

        for turn in self.turns:
            turn_words = set(turn.content.lower().split())
            overlap = len(query_words & turn_words)
            if overlap > 0:
                similarity = overlap / len(query_words)
                results.append((turn, similarity))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:k]

    def _compute_embedding(self, turn: ConversationTurn):
        """计算并存储嵌入向量"""
        if self._embedder:
            try:
                embedding = self._embedder.embed_query(turn.content)
                self._embeddings.append(embedding)
            except Exception as e:
                logger.warning(f"[ConversationMemory] 计算嵌入失败: {e}")

    def _estimate_tokens(self, text: str) -> int:
        """估算 token 数量（简单实现）"""
        # 中文约 1.5 字符/token，英文约 4 字符/token
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + other_chars / 4)

    def _summarize_old_turns(self):
        """摘要旧的对话轮次"""
        # 保留最近的一半
        keep_count = self.max_turns // 2
        old_turns = self.turns[:keep_count]
        self.turns = self.turns[keep_count:]

        if not old_turns:
            return

        # 生成摘要
        summary_text = self._generate_summary(old_turns)

        summary = ConversationSummary(
            turn_range=(old_turns[0].turn_id, old_turns[-1].turn_id),
            summary=summary_text,
            key_points=self._extract_key_points(old_turns),
            created_at=datetime.now().isoformat()
        )

        self.summaries.append(summary)

        # 清理对应的嵌入
        if self._embeddings:
            self._embeddings = self._embeddings[keep_count:]

        logger.info(f"[ConversationMemory] 摘要了 {len(old_turns)} 轮对话")

    def _generate_summary(self, turns: List[ConversationTurn]) -> str:
        """生成对话摘要"""
        # 简单实现：提取关键信息
        topics = set()
        tools = set()

        for turn in turns:
            if turn.phase:
                topics.add(turn.phase)
            tools.update(turn.tools_used)

        parts = []
        if topics:
            parts.append(f"讨论阶段: {', '.join(topics)}")
        if tools:
            parts.append(f"使用工具: {', '.join(tools)}")

        return "; ".join(parts) if parts else "一般性对话"

    def _extract_key_points(self, turns: List[ConversationTurn]) -> List[str]:
        """提取关键点"""
        points = []
        for turn in turns:
            if turn.role == "user" and len(turn.content) > 50:
                # 提取用户的重要问题或请求
                points.append(turn.content[:100])
        return points[:5]

    def clear(self):
        """清空记忆"""
        self.turns = []
        self.summaries = []
        self._embeddings = []

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "turns": [t.to_dict() for t in self.turns],
            "summaries": [
                {
                    "turn_range": s.turn_range,
                    "summary": s.summary,
                    "key_points": s.key_points,
                    "created_at": s.created_at
                }
                for s in self.summaries
            ],
            "total_turns": len(self.turns),
            "total_summaries": len(self.summaries)
        }


__all__ = [
    "ConversationMemory",
    "ConversationTurn",
    "ConversationSummary",
]