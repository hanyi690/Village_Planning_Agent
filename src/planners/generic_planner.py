"""
通用规划器 - Python Code-First 架构，支持所有 28 个维度

整合原有 UnifiedPlannerBase 的功能：
- LLM 调用（流式和非流式）
- 错误处理和降级
- LangSmith tracing
- RAG 知识检索（预加载模式）
- 基于反馈的修复执行
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage

from ..core.llm_factory import create_llm
from ..core.config import LLM_MODEL, MAX_TOKENS
from ..core.langsmith_integration import get_langsmith_manager
from ..core.message_builder import build_multimodal_message
from ..utils.logger import get_logger
from ..config.dimension_metadata import get_dimension_config, get_detailed_dimension_names

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
        self.accumulated_content += token
        if self.on_token_callback:
            try:
                self.on_token_callback(token, self.accumulated_content)
            except Exception as e:
                logger.warning(f"[StreamingCallback] callback failed: {e}")


class GenericPlanner:
    """
    通用规划器 - Python Code-First 架构，支持所有 28 个维度

    特性:
    1. Python 模块驱动（不再依赖 YAML）
    2. 动态状态筛选（根据层级自动选择）
    3. 灵活 Prompt 构建
    4. 工具钩子支持
    5. 专业数据 Hook（get_specialized_data）
    6. 统一架构（Layer 1/2/3 使用同一类）
    7. 流式输出支持
    8. RAG 知识检索（预加载模式）
    """

    # 需要原文的维度（涉及法规条文、技术指标）
    CRITICAL_DIMENSIONS = {
        "land_use",
        "historical_culture",
        "infrastructure",
        "ecological_green",
        "disaster_prevention"
    }

    def __init__(self, dimension_key: str):
        """
        初始化通用规划器

        Args:
            dimension_key: 维度标识（如 "location", "industry")
        """
        # 加载配置
        config = get_dimension_config(dimension_key)
        if not config:
            raise ValueError(f"未找到维度配置: {dimension_key}")

        # 保存完整配置（供工具钩子使用）
        self.config = config
        self.dimension_key = dimension_key
        self.dimension_name = config["name"]
        self.layer = config["layer"]
        self.dependencies = config["dependencies"]
        self.state_filter_type = config["state_filter"]
        self.prompt_key = config["prompt_key"]
        self.tool_name = config.get("tool")  # 工具钩子
        self.rag_enabled = config.get("rag_enabled", True) and RAG_AVAILABLE

        # 加载 Prompt 模板（根据 layer 动态加载）
        self.prompt_template = self._load_prompt_from_module(dimension_key)

        # RAG 组件延迟初始化（预加载模式下从状态缓存读取）
        self.context_manager = None  # type: ignore
        self.summary_system = None  # type: ignore

        if self.rag_enabled:
            logger.debug(f"[{self.dimension_name}] RAG enabled (preload mode)")

    # ==========================================
    # 核心执行流程（原 UnifiedPlannerBase.execute）
    # ==========================================

    def execute(
        self,
        state: dict[str, Any],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        enable_langsmith: bool = True,
        streaming: bool = False,
        on_token_callback: Callable[[str, str], None] | None = None,
        streaming_queue: Optional[Any] = None
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
            def queue_callback(token: str, accumulated: str) -> None:
                try:
                    streaming_queue.add_token(
                        dimension_key=self.dimension_key,
                        dimension_name=self.dimension_name,
                        layer=self.layer,
                        token=token,
                        accumulated=accumulated
                    )
                except Exception as e:
                    logger.warning(f"[{self.dimension_name}] streaming queue add token failed: {e}")

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
                        layer=self.layer
                    )
                    logger.debug(f"[{self.dimension_name}] streaming complete: {len(result)} chars")
                except Exception as e:
                    logger.warning(f"[{self.dimension_name}] mark complete failed: {e}")

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
        prompt: str | HumanMessage | List[HumanMessage],
        state: dict[str, Any],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        enable_langsmith: bool = True,
        streaming: bool = False,
        on_token_callback: Callable[[str, str], None] | None = None
    ) -> str:
        """
        调用LLM（支持流式和非流式，支持多模态）

        Args:
            prompt: 完整的prompt（str、单个HumanMessage 或多模态消息列表）
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
                langsmith = get_langsmith_manager()
                if langsmith.is_enabled():
                    metadata = langsmith.create_run_metadata(
                        project_name=state.get("project_name", "村庄"),
                        dimension=self.dimension_key,
                        layer=self.layer
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

        # 构建 prompt 参数（支持 str、HumanMessage 或 List[HumanMessage])
        prompt_arg: List[HumanMessage]
        if isinstance(prompt, str):
            prompt_arg = [HumanMessage(content=prompt)]
        elif isinstance(prompt, HumanMessage):
            prompt_arg = [prompt]
        else:
            # 已经是 List[HumanMessage]，直接使用
            prompt_arg = prompt

        # 调用LLM（流式或阻塞）
        if streaming:
            accumulated = ""
            chunk_count = 0
            logger.info(f"[{self.dimension_name}] streaming LLM, callback={'set' if on_token_callback else 'none'}")
            for chunk in llm.stream(prompt_arg):
                chunk_count += 1
                if hasattr(chunk, 'content') and chunk.content:
                    accumulated += chunk.content
                    if on_token_callback:
                        try:
                            on_token_callback(chunk.content, accumulated)
                        except Exception as cb_error:
                            logger.warning(f"[{self.dimension_name}] token callback failed: {cb_error}")
            logger.info(f"[{self.dimension_name}] streaming done, chunks={chunk_count}, len={len(accumulated)}")
            return accumulated
        else:
            response = llm.invoke(prompt_arg)
            return response.content

    def _build_error_result(self, error_message: str) -> dict[str, Any]:
        """构建标准化的错误结果"""
        return {
            "dimension_key": self.dimension_key,
            "dimension_name": self.dimension_name,
            self.get_result_key(): f"[执行失败] {error_message}",
            "success": False,
            "error": error_message
        }

    # ==========================================
    # 基于反馈的修复执行（原 UnifiedPlannerBase）
    # ==========================================

    def execute_with_feedback(
        self,
        state: Dict[str, Any],
        feedback: str,
        original_result: str,
        revision_count: int = 0,
        streaming: bool = False,
        on_token_callback: Callable[[str, str], None] | None = None,
        images: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        基于反馈重新执行（用于人工审核流程）

        Args:
            state: 当前状态
            feedback: 人工反馈意见
            original_result: 原始执行结果
            revision_count: 修改次数
            streaming: 是否启用流式输出（默认: False）
            on_token_callback: token回调函数，接收 (token, accumulated)
            images: 图片列表（用于多模态修复）

        Returns:
            修改后的结果
        """
        logger.info(f"[{self.dimension_name}] revision (#{revision_count + 1})")

        revision_prompt = self._build_revision_prompt(
            original_result=original_result,
            feedback=feedback,
            revision_count=revision_count
        )

        # 构建多模态消息
        llm_input: str | HumanMessage = revision_prompt
        if images:
            # Note: Currently only first image is processed
            if len(images) > 1:
                logger.warning(f"[{self.dimension_name}] {len(images)} images provided, only first will be used")
            first_image = images[0]
            llm_input = build_multimodal_message(
                text_content=revision_prompt,
                image_base64=first_image.get("image_base64"),
                image_format=first_image.get("image_format", "jpeg"),
                role="human"
            )
            logger.info(f"[{self.dimension_name}] revision with image")

        try:
            result = self._invoke_llm(
                prompt=llm_input,
                state=state,
                enable_langsmith=True,
                streaming=streaming,
                on_token_callback=on_token_callback
            )
            logger.info(f"[{self.dimension_name}] revision done, len: {len(result)}")
            return result
        except Exception as e:
            logger.error(f"[{self.dimension_name}] revision failed: {e}")
            return original_result

    def _build_revision_prompt(
        self,
        original_result: str,
        feedback: str,
        revision_count: int
    ) -> str:
        """构建修复用的prompt"""
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

        knowledge_cache = state.get("knowledge_cache", {})
        cached_knowledge = knowledge_cache.get(self.dimension_key, "")

        if cached_knowledge:
            logger.debug(f"[{self.dimension_name}] cached knowledge, len: {len(cached_knowledge)}")
            return cached_knowledge

        return ""

    def _is_critical_dimension(self, dimension: str) -> bool:
        """判断是否为关键维度（需要知识检索）"""
        return dimension in self.CRITICAL_DIMENSIONS

    # ==========================================
    # 状态验证和 Prompt 构建（原 GenericPlanner）
    # ==========================================

    def validate_state(self, state: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """根据层级动态验证状态"""
        if self.layer == 1:
            if "raw_data" not in state:
                return False, "缺少必需字段: raw_data"
            if not state.get("raw_data", "").strip():
                return False, "raw_data 为空"

        elif self.layer == 2:
            if "task_description" not in state:
                return False, "缺少必需字段: task_description"

        elif self.layer == 3:
            if not self._check_dependencies(state):
                return False, "依赖的前置维度未完成"

        return True, None

    def build_prompt(self, state: Dict[str, Any]) -> str:
        """根据层级动态构建 Prompt"""
        params = self._prepare_prompt_params(state)

        # 专业数据 Hook
        specialized_data = self._get_specialized_data_from_module(state)
        params.update(specialized_data)

        # 工具钩子逻辑
        tool_output = self._execute_tool_hook(state)
        params["tool_output"] = tool_output

        # RAG 知识上下文
        if self.rag_enabled:
            knowledge_context = self.get_cached_knowledge(state)
            params["knowledge_context"] = knowledge_context
        else:
            params["knowledge_context"] = ""

        if self.layer == 3:
            return self._build_layer3_prompt(state, params)

        try:
            return self.prompt_template.format(**params)
        except KeyError as e:
            logger.error(f"[{self.dimension_name}] Prompt 参数缺失: {e}")
            raise

    # ==========================================
    # Prompt 加载和构建辅助方法
    # ==========================================

    def _load_prompt_from_module(self, dimension_key: str) -> str:
        """从 Python 模块加载 Prompt 模板"""
        try:
            if self.layer == 1:
                from ..subgraphs.analysis_prompts import ANALYSIS_DIMENSIONS
                if dimension_key in ANALYSIS_DIMENSIONS:
                    return ANALYSIS_DIMENSIONS[dimension_key]["prompt"]
                else:
                    logger.warning(f"[GenericPlanner] Layer 1 dimension not found: {dimension_key}")
                    return ""

            elif self.layer == 2:
                from ..subgraphs.concept_prompts import (
                    RESOURCE_ENDOWMENT_PROMPT,
                    PLANNING_POSITIONING_PROMPT,
                    DEVELOPMENT_GOALS_PROMPT,
                    PLANNING_STRATEGIES_PROMPT
                )
                prompt_map = {
                    "resource_endowment": RESOURCE_ENDOWMENT_PROMPT,
                    "planning_positioning": PLANNING_POSITIONING_PROMPT,
                    "development_goals": DEVELOPMENT_GOALS_PROMPT,
                    "planning_strategies": PLANNING_STRATEGIES_PROMPT
                }
                return prompt_map.get(dimension_key, "")

            elif self.layer == 3:
                return ""  # Layer 3 在 build_prompt 中动态处理

            else:
                logger.error(f"[GenericPlanner] unknown layer: {self.layer}")
                return ""

        except ImportError as e:
            logger.error(f"[GenericPlanner] prompts import failed: {e}")
            return ""

    def _build_layer3_prompt(self, state: Dict[str, Any], params: Dict[str, Any]) -> str:
        """构建 Layer 3 的 Prompt（函数式）"""
        try:
            from ..subgraphs.detailed_plan_prompts import get_dimension_prompt
            from datetime import datetime

            # 生成当前日期
            current_date = datetime.now().strftime("%Y年%m月")

            project_name = params.get("project_name", "村庄")
            filtered_analysis = params.get("filtered_analysis", "")
            filtered_concept = params.get("filtered_concept", "")
            constraints = params.get("constraints", "无特殊约束")
            knowledge_context = params.get("knowledge_context", "")

            logger.info(f"[GenericPlanner-L3] {self.dimension_key} prompt build: "
                       f"analysis={len(filtered_analysis)}, concept={len(filtered_concept)}, "
                       f"knowledge={len(knowledge_context)}, key={self.prompt_key}")

            return get_dimension_prompt(
                dimension_key=self.prompt_key,
                project_name=project_name,
                analysis_report=filtered_analysis,
                planning_concept=filtered_concept,
                constraints=constraints,
                dimension_plans=params.get("dimension_plans", ""),
                knowledge_context=knowledge_context,
                current_date=current_date
            )

        except ImportError as e:
            logger.error(f"[GenericPlanner] get_dimension_prompt import failed: {e}")
            return ""
        except Exception as e:
            logger.error(f"[GenericPlanner] Layer 3 prompt build failed: {e}")
            raise

    def _get_specialized_data_from_module(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """从 Python 模块获取专业数据（Hook 模式）"""
        try:
            if self.layer == 1:
                from ..subgraphs.analysis_prompts import get_specialized_data
                return get_specialized_data(self.dimension_key, state)

            elif self.layer == 2:
                from ..subgraphs.concept_prompts import get_specialized_data
                return get_specialized_data(self.dimension_key, state)

            elif self.layer == 3:
                from ..subgraphs.detailed_plan_prompts import get_specialized_data
                return get_specialized_data(self.dimension_key, state)

            else:
                return {}

        except ImportError as e:
            logger.error(f"[GenericPlanner] get_specialized_data import failed: {e}")
            return {}

    def _execute_tool_hook(self, state: Dict[str, Any]) -> str:
        """执行工具钩子（如果配置了 tool）"""
        tool_name = self.config.get("tool")

        if not tool_name:
            return ""

        session_id = state.get("session_id", "unknown")

        try:
            from ..tools.registry import ToolRegistry

            tool_context = self._prepare_tool_context(state)
            tool_context["session_id"] = session_id

            # 检查 SSE 事件是否可用
            sse_available = False
            try:
                from backend.api.planning import (
                    append_tool_call_event,
                    append_tool_result_event
                )
                from ..tools.tools import TOOL_DISPLAY_NAMES
                sse_available = True
            except ImportError:
                pass

            if sse_available:
                display_name = TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
                append_tool_call_event(
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_display_name=display_name,
                    description=f"执行 {display_name} 为 {self.dimension_name} 维度提供数据支持",
                    estimated_time=3.0
                )

            tool_result = ToolRegistry.execute_tool(tool_name, tool_context)

            if sse_available:
                append_tool_result_event(
                    session_id=session_id,
                    tool_name=tool_name,
                    status="success",
                    summary=f"{display_name} 执行成功",
                    data_preview=tool_result[:200]
                )
                logger.info(f"[{self.dimension_name}] tool success (SSE): {tool_name}")
            else:
                logger.info(f"[{self.dimension_name}] tool success: {tool_name}")

            return f"\n【参考数据 - {tool_name}】\n{tool_result}\n"

        except ImportError:
            logger.warning(f"[{self.dimension_name}] ToolRegistry unavailable")
            return ""
        except Exception as e:
            logger.error(f"[{self.dimension_name}] tool failed: {e}")

            try:
                from backend.api.planning import append_tool_result_event
                append_tool_result_event(
                    session_id=session_id,
                    tool_name=tool_name,
                    status="error",
                    summary=f"工具执行失败: {str(e)}",
                    data_preview=str(e)
                )
            except ImportError:
                pass

            return f"\n【工具执行失败】\n{str(e)}\n"

    def _prepare_tool_context(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """为工具准备上下文数据"""
        context = {}

        context["raw_data"] = state.get("raw_data", "")
        context["project_name"] = state.get("project_name", "村庄")

        if self.layer >= 2:
            context["analysis_report"] = state.get("analysis_report", "")
            context["analysis_reports"] = state.get("analysis_reports", {})

        if self.layer >= 3:
            context["planning_concept"] = state.get("planning_concept", "")
            context["concept_reports"] = state.get("concept_reports", {})
            context["completed_plans"] = state.get("completed_plans", {})

        return context

    def _prepare_prompt_params(self, state: Dict[str, Any]) -> Dict[str, str]:
        """准备 Prompt 参数（根据层级差异化）"""
        params = {}

        if self.layer == 1:
            raw_data = state.get("raw_data", "")
            MAX_DATA_LENGTH = 50000
            if len(raw_data) > MAX_DATA_LENGTH:
                raw_data = raw_data[:MAX_DATA_LENGTH] + "\n\n...[数据已截断，原始数据过长]"
            params["raw_data"] = raw_data
            params["professional_data_section"] = ""
            params["task_description"] = state.get("task_description", "未提供具体规划任务")
            params["constraints"] = state.get("constraints", "无特殊约束")

        elif self.layer == 2:
            filtered_analysis = state.get("filtered_analysis", "")
            filtered_concept = state.get("filtered_concept", "")

            if filtered_concept:
                combined_report = f"{filtered_analysis}\n\n### 前序规划思路\n\n{filtered_concept}"
            else:
                combined_report = filtered_analysis

            params["analysis_report"] = combined_report
            params["task_description"] = state.get("task_description", "")
            params["constraints"] = state.get("constraints", "无特殊约束")
            params["professional_data_section"] = ""

            analysis_reports = state.get("analysis_reports", {})
            superior_planning_content = analysis_reports.get("superior_planning", "")
            if superior_planning_content:
                params["superior_planning_context"] = superior_planning_content
            else:
                params["superior_planning_context"] = "未提供上位规划数据"

            logger.debug(f"[GenericPlanner-L2] {self.dimension_key} params: "
                       f"filtered_analysis={len(filtered_analysis)}, "
                       f"filtered_concept={len(filtered_concept)}, "
                       f"combined={len(combined_report)}")

        elif self.layer == 3:
            params["project_name"] = state.get("project_name", "村庄")
            params["filtered_analysis"] = state.get("filtered_analysis", "")
            params["filtered_concept"] = state.get("filtered_concept", "")
            params["constraints"] = state.get("constraints", "无特殊约束")

            logger.debug(f"[GenericPlanner-L3] {self.dimension_key} params: "
                       f"filtered_analysis={len(params['filtered_analysis'])}, "
                       f"filtered_concept={len(params['filtered_concept'])}")

            if self.dimension_key == "project_bank":
                filtered_detail = state.get("filtered_detail", "")
                if filtered_detail:
                    params["dimension_plans"] = filtered_detail
                    logger.info(f"[GenericPlanner-L3] project_bank shadow cache: {len(filtered_detail)}")
                else:
                    params["dimension_plans"] = self._format_detailed_plans(
                        state.get("completed_plans", {})
                    )
                    logger.warning(f"[GenericPlanner-L3] project_bank fallback to full report")

        return params

    def _check_dependencies(self, state: Dict[str, Any]) -> bool:
        """检查 Layer 3 的依赖是否满足"""
        if self.layer != 3:
            return True

        completed = state.get("completed_plans", {})
        depends_on = self.dependencies.get("depends_on_detailed", [])

        return all(d in completed for d in depends_on)

    def _format_detailed_plans(self, plans: Dict[str, str]) -> str:
        """格式化详细规划结果（用于 project_bank）"""
        formatted = []
        for key, content in plans.items():
            name = get_detailed_dimension_names().get(key, key)
            formatted.append(f"## {name}\n\n{content}\n")

        return "\n".join(formatted)

    def get_layer(self) -> int:
        """返回规划层级"""
        return self.layer

    def get_result_key(self) -> str:
        """返回结果字典的键名"""
        return self.config.get("result_key", "dimension_result")

    def __repr__(self) -> str:
        return f"GenericPlanner({self.dimension_key}/{self.dimension_name})"


class GenericPlannerFactory:
    """
    通用规划器工厂 - 统一创建入口

    替代原有的 AnalysisPlannerFactory, ConceptPlannerFactory, DetailedPlannerFactory
    """

    @classmethod
    def create_planner(cls, dimension_key: str) -> GenericPlanner:
        """创建指定维度的规划器"""
        return GenericPlanner(dimension_key)

    @classmethod
    def create_all_planners(cls, layer: Optional[int] = None) -> Dict[str, GenericPlanner]:
        """批量创建规划器"""
        from ..config.dimension_metadata import DIMENSIONS_METADATA

        planners = {}

        for key, config in DIMENSIONS_METADATA.items():
            if layer is None or config["layer"] == layer:
                planners[key] = cls.create_planner(key)

        return planners


# 向后兼容别名
AnalysisPlannerFactory = GenericPlannerFactory
ConceptPlannerFactory = GenericPlannerFactory
DetailedPlannerFactory = GenericPlannerFactory


__all__ = [
    "GenericPlanner",
    "GenericPlannerFactory",
    "StreamingCallback",
    # 向后兼容
    "AnalysisPlannerFactory",
    "ConceptPlannerFactory",
    "DetailedPlannerFactory",
]