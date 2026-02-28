"""Unified planner base class.

Provides common functionality for all planners, eliminating duplicate code:
- Standardized LLM invocation
- Unified error handling
- LangSmith tracing integration
- State validation
- Standardized return value structure
- Two-phase RAG integration for knowledge retrieval
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage

from ..core.llm_factory import create_llm
from ..core.config import LLM_MODEL, MAX_TOKENS
from ..utils.logger import get_logger

# RAG imports (conditional to avoid errors if RAG not available)
try:
    from ..rag.core.context_manager import DocumentContextManager, get_context_manager
    from ..rag.core.summarization import DocumentSummarizer
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False
    DocumentContextManager = None  # type: ignore
    DocumentSummarizer = None  # type: ignore
    get_context_manager = None  # type: ignore

logger = get_logger(__name__)


class StreamingCallback(BaseCallbackHandler):
    """Streaming callback for real-time token output.

    Invoked each time the LLM generates a new token, used for sending
    incremental content to the frontend in real-time.

    Args:
        on_token_callback: Callback function receiving (token: str, accumulated: str)
    """

    def __init__(self, on_token_callback: Callable[[str, str], None] | None = None):
        self.on_token_callback = on_token_callback
        self.accumulated_content = ""

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        """
        每次生成新 token 时调用

        Args:
            token: 新生成的token
            **kwargs: 其他参数
        """
        self.accumulated_content += token
        if self.on_token_callback:
            try:
                self.on_token_callback(token, self.accumulated_content)
            except Exception as e:
                logger.warning(f"[StreamingCallback] 回调执行失败: {e}")


class UnifiedPlannerBase(ABC):
    """
    统一规划器基类（集成两阶段RAG系统）

    所有规划器（Analysis, Concept, Detailed）都应该继承此类。
    提供标准化的执行流程和错误处理。
    支持两阶段RAG知识检索，根据层级智能选择检索策略。

    子类需要实现：
    - validate_state(): 验证状态是否包含必需字段
    - build_prompt(): 构建完整的prompt
    - get_layer(): 返回规划层级（1=分析, 2=思路, 3=详细）
    """

    # 需要原文的维度（涉及法规条文、技术指标）
    CRITICAL_DIMENSIONS = {
        "land_use",
        "historical_culture",
        "infrastructure",
        "ecological_green",
        "disaster_prevention"
    }

    def __init__(self, dimension_key: str, dimension_name: str, rag_enabled: bool = True) -> None:
        """
        初始化规划器

        Args:
            dimension_key: 维度标识（如 "location", "industry"）
            dimension_name: 维度名称（如 "区位分析", "产业规划"）
            rag_enabled: 是否启用RAG知识检索
        """
        self.dimension_key = dimension_key
        self.dimension_name = dimension_name
        self.rag_enabled = rag_enabled and RAG_AVAILABLE

        # RAG 组件延迟初始化（预加载模式下从状态缓存读取）
        # context_manager 和 summarizer 保留为 None，按需从 get_context_manager 获取
        self.context_manager = None  # type: ignore
        self.summary_system = None  # type: ignore
        
        if self.rag_enabled:
            logger.debug(f"[{self.dimension_name}] RAG已启用（预加载模式）")

    @abstractmethod
    def validate_state(self, state: dict[str, Any]) -> tuple[bool, str | None]:
        """
        验证状态是否包含必需的字段

        Args:
            state: 当前状态字典

        Returns:
            (is_valid, error_message): 验证结果和错误信息（如果失败）
        """
        pass

    @abstractmethod
    def build_prompt(self, state: dict[str, Any]) -> str:
        """
        构建完整的prompt

        Args:
            state: 当前状态字典（已通过验证）

        Returns:
            完整的prompt字符串
        """
        pass

    @abstractmethod
    def get_layer(self) -> int:
        """
        获取规划层级

        Returns:
            1: 现状分析
            2: 规划思路
            3: 详细规划
        """
        pass

    @abstractmethod
    def get_result_key(self) -> str:  # pragma: no cover
        """
        获取结果字典中的键名

        Returns:
            "analysis_result" (Layer 1)
            "concept_result" (Layer 2)
            "dimension_result" (Layer 3)
        """
        pass

    def execute(
        self,
        state: dict[str, Any],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        enable_langsmith: bool = True,
        streaming: bool = False,
        on_token_callback: Callable[[str, str], None] | None = None,
        streaming_queue: Optional[Any] = None  # StreamingQueueManager instance
    ) -> dict[str, Any]:
        """
        执行规划器的标准流程

        流程：
        1. 验证状态
        2. 构建prompt
        3. 调用LLM（带LangSmith tracing）
        4. 处理响应
        5. 错误处理和降级

        Args:
            state: 当前状态字典
            model: LLM模型名称（None则使用默认配置）
            temperature: 温度参数
            max_tokens: 最大token数
            enable_langsmith: 是否启用LangSmith tracing
            streaming: 是否启用流式输出（默认: False）
            on_token_callback: token回调函数，接收 (token, accumulated)
            streaming_queue: StreamingQueueManager实例，用于维度级流式推送

        Returns:
            {
                "dimension_key": str,
                "dimension_name": str,
                "<result_key>": str,  # 由get_result_key()决定
                "success": bool,
                "error": str | None
            }
        """
        logger.info(f"[{self.dimension_name}] 开始执行")

        # 1. 验证状态
        is_valid, error_msg = self.validate_state(state)
        if not is_valid:
            logger.error(f"[{self.dimension_name}] 状态验证失败: {error_msg}")
            return self._build_error_result(error_msg)

        # 2. 构建prompt
        try:
            prompt = self.build_prompt(state)
            logger.debug(f"[{self.dimension_name}] Prompt构建完成，长度: {len(prompt)}")
        except Exception as e:
            logger.error(f"[{self.dimension_name}] Prompt构建失败: {e}")
            return self._build_error_result(f"Prompt构建失败: {str(e)}")

        # 3. 处理流式队列回调
        final_token_callback = on_token_callback
        if streaming_queue and streaming:
            # 创建队列回调函数
            def queue_callback(token: str, accumulated: str) -> None:
                try:
                    streaming_queue.add_token(
                        dimension_key=self.dimension_key,
                        dimension_name=self.dimension_name,
                        layer=self.get_layer(),
                        token=token,
                        accumulated=accumulated
                    )
                except Exception as e:
                    logger.warning(f"[{self.dimension_name}] 流式队列添加token失败: {e}")

            # 组合回调：先调用队列回调，再调用原始回调（兼容性）
            if on_token_callback:
                def combined_callback(token: str, accumulated: str) -> None:
                    queue_callback(token, accumulated)
                    on_token_callback(token, accumulated)
                final_token_callback = combined_callback
            else:
                final_token_callback = queue_callback

        # 4. 调用LLM
        try:
            result = self._invoke_llm(
                prompt=prompt,
                state=state,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                enable_langsmith=enable_langsmith,
                streaming=streaming,
                on_token_callback=final_token_callback
            )

            # 如果使用流式队列，标记维度完成
            if streaming_queue and streaming:
                try:
                    streaming_queue.complete_dimension(
                        dimension_key=self.dimension_key,
                        layer=self.get_layer()
                    )
                    logger.debug(
                        f"[{self.dimension_name}] 维度流式完成: "
                        f"{len(result)} chars"
                    )
                except Exception as e:
                    logger.warning(f"[{self.dimension_name}] 标记维度完成失败: {e}")

            logger.info(f"[{self.dimension_name}] 执行成功，结果长度: {len(result)}")

            return {
                "dimension_key": self.dimension_key,
                "dimension_name": self.dimension_name,
                self.get_result_key(): result,
                "success": True,
                "error": None
            }

        except Exception as e:
            logger.error(f"[{self.dimension_name}] LLM调用失败: {e}")
            return self._build_error_result(f"LLM调用失败: {str(e)}")

    def _invoke_llm(
        self,
        prompt: str,
        state: dict[str, Any],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        enable_langsmith: bool = True,
        streaming: bool = False,
        on_token_callback: Callable[[str, str], None] | None = None
    ) -> str:
        """
        调用LLM（支持流式和非流式）

        Args:
            prompt: 完整的prompt
            state: 当前状态（用于LangSmith metadata）
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大token数
            enable_langsmith: 是否启用LangSmith
            streaming: 是否启用流式输出
            on_token_callback: token回调函数

        Returns:
            LLM响应内容（完整累积内容）
        """
        # 创建LangSmith metadata
        metadata = None
        if enable_langsmith:
            try:
                from ..core.langsmith_integration import get_langsmith_manager
                langsmith = get_langsmith_manager()
                if langsmith.is_enabled():
                    metadata = langsmith.create_run_metadata(
                        project_name=state.get("project_name", "村庄"),
                        dimension=self.dimension_key,
                        layer=self.get_layer()
                    )
            except Exception as e:
                logger.debug(f"[{self.dimension_name}] LangSmith metadata创建失败: {e}")

        # 创建回调处理器
        callback_handler = None
        if streaming and on_token_callback:
            callback_handler = StreamingCallback(on_token_callback)

        # 创建LLM实例
        llm = create_llm(
            model=model or LLM_MODEL,
            temperature=temperature,
            max_tokens=max_tokens or MAX_TOKENS,
            metadata=metadata,
            streaming=streaming,
            callbacks=[callback_handler] if callback_handler else None
        )

        # 调用LLM（流式或阻塞）
        if streaming:
            # 流式调用
            accumulated = ""
            for chunk in llm.stream([HumanMessage(content=prompt)]):
                if hasattr(chunk, 'content') and chunk.content:
                    accumulated += chunk.content
                    # 回调已经在StreamingCallback中处理
            return accumulated
        else:
            # 阻塞调用（原有逻辑）
            response = llm.invoke([HumanMessage(content=prompt)])
            return response.content

    def _build_error_result(self, error_message: str) -> dict[str, Any]:
        """
        构建标准化的错误结果

        Args:
            error_message: 错误信息

        Returns:
            标准错误结果字典
        """
        return {
            "dimension_key": self.dimension_key,
            "dimension_name": self.dimension_name,
            self.get_result_key(): f"[执行失败] {error_message}",
            "success": False,
            "error": error_message
        }

    def execute_with_feedback(
        self,
        state: Dict[str, Any],
        feedback: str,
        original_result: str,
        revision_count: int = 0
    ) -> str:
        """
        基于反馈重新执行（用于人工审核流程）

        Args:
            state: 当前状态
            feedback: 人工反馈意见
            original_result: 原始执行结果
            revision_count: 修改次数（用于追踪）

        Returns:
            修改后的结果
        """
        logger.info(f"[{self.dimension_name}] 基于反馈重新执行 (第{revision_count + 1}次)")

        # 构建修复prompt
        revision_prompt = self._build_revision_prompt(
            original_result=original_result,
            feedback=feedback,
            revision_count=revision_count
        )

        try:
            # 使用同样的LLM配置
            result = self._invoke_llm(
                prompt=revision_prompt,
                state=state,
                enable_langsmith=True
            )

            logger.info(f"[{self.dimension_name}] 修复完成，内容长度: {len(result)}")
            return result

        except Exception as e:
            logger.error(f"[{self.dimension_name}] 修复失败: {e}")
            # 返回原始结果
            return original_result

    def _build_revision_prompt(
        self,
        original_result: str,
        feedback: str,
        revision_count: int
    ) -> str:
        """
        构建修复用的prompt

        Args:
            original_result: 原始结果
            feedback: 反馈意见
            revision_count: 修改次数

        Returns:
            修复prompt
        """
        return f"""
请根据以下人工反馈，修复对应的规划内容：

【原规划内容】
{original_result[:2000]}

【人工反馈】
{feedback}

【要求】
1. 针对反馈意见进行修改
2. 保持原有结构和格式
3. 修改部分要明确标注
4. 这是第{revision_count + 1}次修复
5. 如果这是多次修复，请确保之前的问题都已解决

请生成修复后的规划内容：
"""

    def __repr__(self) -> str:  # pragma: no cover
        return f"{self.__class__.__name__}({self.dimension_key}/{self.dimension_name})"

    # ==========================================
    # RAG 知识检索方法（预加载模式）
    # ==========================================

    def get_cached_knowledge(self, state: Dict[str, Any]) -> str:
        """
        从状态缓存获取预加载的知识上下文

        预加载模式下，知识由子图的 knowledge_preload_node 统一检索并缓存到状态中。
        本方法从缓存读取，避免每个维度重复调用 RAG。

        Args:
            state: 当前状态，包含 knowledge_cache 字段

        Returns:
            格式化的知识上下文字符串，无缓存时返回空字符串
        """
        if not self.rag_enabled:
            return ""

        # 从状态缓存读取
        knowledge_cache = state.get("knowledge_cache", {})
        cached_knowledge = knowledge_cache.get(self.dimension_key, "")

        if cached_knowledge:
            logger.debug(f"[{self.dimension_name}] 从缓存获取知识上下文，长度: {len(cached_knowledge)}")
            return cached_knowledge

        return ""

    def _build_knowledge_query(
        self,
        state: dict[str, Any],
        dimension: str,
        layer: int
    ) -> str:
        """
        构建知识检索查询（用于预加载节点）

        Args:
            state: 当前状态
            dimension: 维度标识
            layer: 层级

        Returns:
            查询字符串
        """
        village_data = state.get("village_data", state.get("raw_data", ""))

        # 处理字符串类型的 raw_data
        village_name = ""
        if isinstance(village_data, str):
            lines = village_data.split('\n')
            for line in lines[:10]:  # 只检查前10行
                if '村庄' in line or '名称' in line:
                    village_name = line.split('：')[-1].split(':')[-1].strip()
                    break
        elif isinstance(village_data, dict):
            village_name = village_data.get('name', '')

        # 根据层级构建查询
        dimension_name = self.dimension_name
        if layer == 1:
            return f"{dimension_name} 现状分析 标准 方法 调研要求"
        elif layer == 2:
            return f"{dimension_name} 规划定位 发展目标 思路"
        else:  # layer == 3
            return f"{dimension_name} 技术规范 标准 实施要求"

    def _is_critical_dimension(self, dimension: str) -> bool:
        """
        判断是否为关键维度（需要知识检索）

        Args:
            dimension: 维度标识

        Returns:
            是否为关键维度
        """
        return dimension in self.CRITICAL_DIMENSIONS


__all__ = ["UnifiedPlannerBase"]
