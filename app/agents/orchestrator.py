"""
Agent 编排器
核心调度器，管理多 Agent 协作
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.agents.base import AgentConfig, AgentResponse, AgentStatus, BaseAgent
from app.agents.registry import get_registry
from app.core.context import ExecutionContext, SessionContext
from app.core.experiment_metrics import (
    CollaborationMode,
    ExperimentContext,
    ReviewModeExperiment,
    build_experiment_metrics,
    metrics_to_dict,
)
from app.core.llm.client import LLMManager, LLMMessage, ToolDefinition
from app.core.llm.emotion_detector import emotion_detector, EmotionDetector
from app.core.llm.mode_detector import mode_detector, DialogModeDetector
from app.core.logger import get_logger
from app.schemas import (
    DialogMode, EmotionSchema, IntentType, ModeContext, PlanSchema, TaskSchema,
)

logger = get_logger(__name__)


class ExecutionPhase(str, Enum):
    """执行阶段"""
    INTENT_PARSING = "intent_parsing"
    TASK_PLANNING = "task_planning"
    PARALLEL_EXECUTION = "parallel_execution"
    RESULT_AGGREGATION = "result_aggregation"
    QUALITY_REVIEW = "quality_review"
    RESPONSE_SYNTHESIS = "response_synthesis"


@dataclass
class OrchestratorConfig:
    """编排器配置"""
    max_parallel_agents: int = 5
    planning_timeout: int = 30
    execution_timeout: int = 120
    review_enabled: bool = True
    max_retries: int = 3
    # 实验配置
    experiment_mode: bool = False
    collaboration_mode: str = CollaborationMode.STRUCTURED_COLLABORATION.value
    review_mode: str = ReviewModeExperiment.REVIEW_ONLY.value
    experiment_case_id: str = ""


class IntentParser:
    """
    意图解析器
    使用 LLM 分析用户意图
    """

    SYSTEM_PROMPT = """你是一个旅游规划助手，负责分析用户的旅行规划意图。

根据用户输入，识别以下意图类型：
- trip_planning: 综合旅游规划 (需要景点+行程+预算等)
- attraction_recommendation: 景点推荐
- itinerary_planning: 行程规划
- budget_control: 预算控制/分析
- weather_adjustment: 天气相关的行程调整
- destination_knowledge: 目的地知识问答
- route_consultation: 路线咨询
- general_chat: 闲聊
- unknown: 无法识别

同时提取关键信息：
- 目的地
- 出发地
- 出发日期
- 返程日期
- 人数
- 预算范围（economy/medium/luxury）
- 预算金额
- 旅行风格偏好（休闲/探险/文化/亲子/蜜月等）
- 兴趣爱好
- 特殊需求（老人/小孩/残障等）

请以JSON格式输出，包含 intent 和 extracted_info 两个字段。extracted_info 中包含所有提取到的信息。"""

    JSON_SCHEMA = """
输出格式（必须是有效JSON）：
{
  "intent": "trip_planning",
  "extracted_info": {
    "destination": "杭州",
    "origin": "上海",
    "duration": 3,
    "num_travelers": 2,
    "budget": "medium",
    "budget_amount": 5000,
    "travel_styles": ["休闲", "文化"],
    "interests": ["西湖", "古镇"],
    "special_requirements": []
  },
  "confidence": 0.95,
  "reasoning": "用户明确表达了目的地、时间和预算，属于综合规划意图"
}"""

    def __init__(self, llm: LLMManager):
        self.llm = llm

    async def parse(
        self,
        user_message: str,
        session: SessionContext,
    ) -> tuple[IntentType, Dict[str, Any]]:
        """
        解析用户意图

        Returns:
            (意图类型, 提取的信息)
        """
        # 构建提示词
        context = self._build_context(session)

        prompt = f"""{self.SYSTEM_PROMPT}

{self.JSON_SCHEMA}

用户输入: {user_message}

{context}

请输出JSON格式的解析结果。"""

        messages = [LLMMessage(role="system", content="你是一个JSON生成器，只输出JSON格式的回复，不要有其他内容。")]
        messages.append(LLMMessage(role="user", content=prompt))

        try:
            response = await self.llm.chat(messages)

            # 解析 JSON
            content = response.content.strip()
            # 移除可能的 markdown 代码块
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            data = json.loads(content)

            intent_str = data.get("intent", "unknown")
            intent = IntentType(intent_str) if intent_str in [e.value for e in IntentType] else IntentType.UNKNOWN

            return intent, data.get("extracted_info", {})

        except Exception as e:
            logger.error(f"Intent parsing failed: {e}")
            return IntentType.UNKNOWN, {}

    def _build_context(self, session: SessionContext) -> str:
        """构建上下文信息"""
        parts = []

        if session.trip_context.destination:
            parts.append(f"- 已确定目的地: {session.trip_context.destination}")

        if session.trip_context.start_date:
            parts.append(f"- 已确定出发日期: {session.trip_context.start_date}")

        if session.trip_context.num_travelers > 1:
            parts.append(f"- 已确定人数: {session.trip_context.num_travelers}")

        if session.preferences.budget_level != "medium":
            parts.append(f"- 预算级别: {session.preferences.budget_level}")

        if parts:
            return "当前已知的上下文:\n" + "\n".join(parts)

        return ""


class ModeContextManager:
    """
    模式上下文管理器
    管理对话模式的自动检测和切换
    """

    def __init__(self):
        self.mode_detector = mode_detector
        self.emotion_detector = emotion_detector

    def detect(
        self,
        message: str,
        session: SessionContext,
    ) -> tuple[ModeContext, EmotionSchema]:
        """
        检测对话模式和情感

        Args:
            message: 用户消息
            session: 会话上下文

        Returns:
            (模式上下文, 情感分析结果)
        """
        # 构建检测上下文
        context = {
            "current_mode": session.dialog_mode,
            "has_destination": bool(session.trip_context.destination),
            "is_clarifying": session.mode_confidence < 0.5,
        }

        # 检测模式
        mode_context = self.mode_detector.detect_mode(message, context)

        # 检测情感
        emotion = self.emotion_detector.detect(message, context)

        return mode_context, emotion

    def should_switch_mode(
        self,
        current: ModeContext,
        session: SessionContext,
    ) -> bool:
        """
        判断是否应该切换模式

        Args:
            current: 当前检测的模式
            session: 会话上下文

        Returns:
            bool: 是否切换
        """
        if not current.suggested_mode_switch:
            return False

        return self.mode_detector.should_switch_mode(
            DialogMode(session.dialog_mode),
            current.suggested_mode_switch,
            current.mode_confidence,
        )

    def get_suggestions(
        self,
        mode: DialogMode,
        emotion: EmotionSchema,
    ) -> List[str]:
        """
        获取回复建议

        Args:
            mode: 当前模式
            emotion: 当前情感

        Returns:
            List[str]: 建议列表
        """
        suggestions = []

        # 基于模式添加建议
        if mode == DialogMode.PLANNING:
            suggestions.extend([
                "您想什么时候出发？",
                "您的预算大概是多少？",
                "有什么特别想去的地方吗？",
            ])
        elif mode == DialogMode.QA:
            suggestions.extend([
                "您想了解更多信息吗？",
                "需要我推荐相关景点吗？",
            ])
        elif mode == DialogMode.CHAT:
            suggestions.extend([
                "最近有什么旅行计划吗？",
                "想去哪里玩？",
            ])

        # 基于情感添加建议
        emotion_suggestions = self.emotion_detector.get_suggestions(emotion.emotion)
        suggestions.extend(emotion_suggestions[:2])

        return suggestions[:3]  # 最多返回 3 个建议


class ChatModeHandler:
    """
    闲聊模式处理器
    处理轻松的对话场景
    """

    SYSTEM_PROMPT = """你是一个热情友好的旅游规划助手，名叫"旅游精灵"，可以和用户进行轻松的闲聊。

你的特点：
- 友好、亲切、幽默，像朋友一样交流
- 了解各地的旅游景点和旅行知识
- 可以分享一些旅行趣事和小贴士
- 适当引导用户进入正式的旅行规划
- 使用emoji增加亲和力

请用轻松友好的方式回复，保持对话的自然流畅。如果用户表达了旅行意向，适时引导到规划话题。"""

    RESPONSE_STRATEGIES = {
        "happy": {"tone": "热情洋溢", "emoji": "😊", "approach": "与用户一起分享喜悦"},
        "neutral": {"tone": "友好专业", "emoji": "🙂", "approach": "提供有用的信息"},
        "anxious": {"tone": "耐心安抚", "emoji": "🤗", "approach": "解答疑虑，给予信心"},
        "sad": {"tone": "温暖关心", "emoji": "💙", "approach": "表达理解，尝试帮助"},
        "confused": {"tone": "清晰解释", "emoji": "🤔", "approach": "耐心解答，举例说明"},
        "urgent": {"tone": "高效响应", "emoji": "⚡", "approach": "快速给出解决方案"},
    }

    def __init__(self, llm: LLMManager):
        self.llm = llm

    async def handle(
        self,
        message: str,
        session: SessionContext,
        emotion: EmotionSchema,
    ) -> str:
        """
        处理闲聊消息

        Args:
            message: 用户消息
            session: 会话上下文
            emotion: 检测到的情感

        Returns:
            str: 回复内容
        """
        # 获取响应策略
        emotion_key = emotion.emotion.value if hasattr(emotion.emotion, 'value') else str(emotion.emotion)
        strategy = self.RESPONSE_STRATEGIES.get(emotion_key, self.RESPONSE_STRATEGIES["neutral"])

        # 构建提示词
        prompt = f"""{self.SYSTEM_PROMPT}

当前情感状态: {emotion_key} (置信度: {emotion.confidence:.2f})
建议回复风格: {strategy['tone']}
回复策略: {strategy['approach']}

用户说: {message}

请用{strategy['tone']}的风格回复，适当使用emoji，保持友好亲切。"""

        messages = [
            LLMMessage(role="system", content=prompt),
            LLMMessage(role="user", content=message),
        ]

        try:
            response = await self.llm.chat(messages)
            return response.content
        except Exception as e:
            logger.error(f"Chat mode handling failed: {e}")
            return "抱歉，我现在有点走神了。要不我们聊聊您的旅行计划吧？🗺️"


class QAModeHandler:
    """
    问答模式处理器
    处理用户关于景点的直接问题
    """

    SYSTEM_PROMPT = """你是一个专业的旅游知识助手，专门回答用户关于景点、旅游目的地的问题。

你的职责：
- 回答关于景点的问题（位置、特色、门票、开放时间等）
- 提供实用的旅游信息和建议
- 给出详细的游览攻略
- 如果不确定，诚实说明并提供替代方案
- 适当使用emoji增加可读性

请给出准确、实用、详细的回答，使用Markdown格式适当分段。"""

    def __init__(self, llm: LLMManager):
        self.llm = llm

    async def handle(
        self,
        message: str,
        session: SessionContext,
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        """
        处理问答消息

        Args:
            message: 用户消息
            session: 会话上下文

        Returns:
            (回复内容, 相关数据)
        """
        # 构建上下文
        context_parts = []
        destination = session.trip_context.destination or "未确定"
        context_parts.append(f"当前目的地: {destination}")

        if session.trip_context.start_date:
            context_parts.append(f"出发日期: {session.trip_context.start_date}")
        if session.trip_context.num_travelers > 0:
            context_parts.append(f"出行人数: {session.trip_context.num_travelers}人")

        # 获取之前的对话历史作为上下文
        recent_messages = session.get_recent_messages(3)
        if recent_messages:
            context_parts.append("近期对话摘要:")
            for msg in recent_messages[-2:]:
                if msg.user_message:
                    context_parts.append(f"- 用户: {msg.user_message[:50]}...")

        known_info = "\n".join(context_parts) if context_parts else "暂无"

        # 判断是否在规划流程中
        planning_status = "正在规划" if session.trip_context.destination else "尚未开始规划"

        # 构建提示词
        system_prompt = f"""{self.SYSTEM_PROMPT}

当前上下文：
- 目的地：{destination}
- 行程状态：{planning_status}
- 已知信息：{known_info}

用户问题: {message}

请给出准确、实用、详细的回答。回答要专业、有深度，必要时可以给出多个选项。"""

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=message),
        ]

        try:
            response = await self.llm.chat(messages)
            return response.content, None
        except Exception as e:
            logger.error(f"QA mode handling failed: {e}")
            return "抱歉，我暂时无法回答这个问题。", None


class TaskPlanner:
    """
    任务规划器
    根据意图分解任务
    """

    # 意图到任务配置的映射
    INTENT_TASK_MAP: Dict[IntentType, Dict[str, Any]] = {
        IntentType.TRIP_PLANNING: {
            "primary_agent": "planner",
            "sub_agents": ["attraction", "weather", "itinerary", "budget"],
            "requires_review": True,
        },
        IntentType.ATTRACTION_RECOMMENDATION: {
            "primary_agent": "attraction",
            "sub_agents": [],
            "requires_review": False,
        },
        IntentType.ITINERARY_PLANNING: {
            "primary_agent": "itinerary",
            "sub_agents": ["attraction"],
            "requires_review": True,
        },
        IntentType.BUDGET_CONTROL: {
            "primary_agent": "budget",
            "sub_agents": [],
            "requires_review": False,
        },
        IntentType.WEATHER_ADJUSTMENT: {
            "primary_agent": "weather",
            "sub_agents": ["itinerary"],
            "requires_review": True,
        },
        IntentType.ROUTE_CONSULTATION: {
            "primary_agent": "attraction",
            "sub_agents": [],
            "requires_review": False,
        },
        IntentType.GENERAL_CHAT: {
            "primary_agent": "planner",
            "sub_agents": [],
            "requires_review": False,
        },
    }

    def create_plan(
        self,
        intent: IntentType,
        extracted_info: Dict[str, Any],
        session: Optional[SessionContext] = None,
        user_message: str = "",
    ) -> PlanSchema:
        """创建任务计划"""
        task_config = self.INTENT_TASK_MAP.get(
            intent,
            self.INTENT_TASK_MAP[IntentType.GENERAL_CHAT]
        )

        tasks = []
        task_id = 1

        # 优化：只添加必要的子 Agent
        sub_agents = task_config.get("sub_agents", [])
        if sub_agents:
            for agent_name in sub_agents:
                tasks.append(
                    TaskSchema(
                        task_id=f"task_{task_id}",
                        description=f"Execute {agent_name} agent",
                        agent_name=agent_name,
                        dependencies=[],
                        status="pending",
                    )
                )
                task_id += 1

        destination = extracted_info.get("destination") or (session.trip_context.destination if session else None)
        duration = extracted_info.get("duration") or (session.trip_context.duration_days if session else None)
        start_date = extracted_info.get("start_date") or (session.trip_context.start_date if session else None)
        end_date = extracted_info.get("end_date") or (session.trip_context.end_date if session else None)
        num_travelers = extracted_info.get("num_travelers") or (session.trip_context.num_travelers if session else None)

        clarification_questions: List[str] = []
        follow_up_questions: List[str] = []
        missing_fields: List[str] = []

        # A 级核心字段，按优先级排序
        if not destination:
            missing_fields.append("destination")
            clarification_questions.append("你想去哪个城市或目的地旅游？")

        if not duration and not start_date and not end_date:
            missing_fields.append("travel_time")
            clarification_questions.append("你计划玩几天，或者大概什么时候出发？")

        if not self._has_budget_info(extracted_info, session):
            missing_fields.append("budget")
            clarification_questions.append("预算大概是多少？")

        if not num_travelers:
            missing_fields.append("people")
            clarification_questions.append("几个人一起出行？")

        # B/C 级次要偏好字段（不阻塞规划，但补充后更准确）
        if self._needs_special_requirements_follow_up(extracted_info, session, user_message):
            follow_up_questions.append("如果这次有老人或小朋友同行，是否需要低强度、婴儿车友好或无障碍安排？")

        requires_clarification = bool(clarification_questions)
        clarification_message = self._build_clarification_message(clarification_questions, follow_up_questions)

        return PlanSchema(
            intent=intent,
            tasks=tasks,
            requires_clarification=requires_clarification,
            clarification_message=clarification_message,
            clarification_questions=clarification_questions,
            missing_fields=missing_fields,
            follow_up_questions=follow_up_questions,
            requires_review=self._is_complex_planning_intent(intent, extracted_info, task_config),
        )

    def _has_budget_info(
        self,
        extracted_info: Dict[str, Any],
        session: Optional[SessionContext],
    ) -> bool:
        if extracted_info.get("budget_amount") is not None:
            return True
        if extracted_info.get("budget_level"):
            return True

        budget = extracted_info.get("budget")
        if isinstance(budget, (int, float)):
            return True
        if isinstance(budget, str) and budget.strip():
            return True

        return bool(session and session.trip_context.budget_amount is not None)

    def _needs_special_requirements_follow_up(
        self,
        extracted_info: Dict[str, Any],
        session: Optional[SessionContext],
        user_message: str,
    ) -> bool:
        special_requirements = extracted_info.get("special_requirements")
        if not special_requirements and session:
            special_requirements = session.preferences.special_requirements
        if special_requirements:
            return False

        travel_styles = extracted_info.get("travel_styles") or (session.preferences.travel_style if session else []) or []
        tourist_type = extracted_info.get("tourist_type") or (session.preferences.tourist_type if session else "")
        travel_text = f"{user_message} {' '.join(travel_styles)} {tourist_type}".lower()
        keywords = ["亲子", "带娃", "孩子", "小孩", "老人", "长辈", "婴儿", "宝宝", "senior", "family"]
        return any(keyword in travel_text for keyword in keywords)

    def _build_clarification_message(
        self,
        clarification_questions: List[str],
        follow_up_questions: List[str],
    ) -> Optional[str]:
        if not clarification_questions:
            if follow_up_questions:
                return "我可以先继续规划，不过还有一些信息补充后会更准确。" + follow_up_questions[0]
            return None

        # 自然组合追问：只保留有效问题，避免空字符串
        valid_questions = [q.strip() for q in clarification_questions if q.strip()]
        if not valid_questions:
            if follow_up_questions:
                return "我可以先继续规划，不过还有一些信息补充后会更准确。" + follow_up_questions[0]
            return None

        # 一句话引导 + 自然问题列表
        if len(valid_questions) == 1:
            message = f"为了帮你把行程安排得更准确，我还想确认一下：{valid_questions[0]}"
        elif len(valid_questions) == 2:
            message = f"为了帮你把行程安排得更准确，我还想确认两个信息：{valid_questions[0]}？{valid_questions[1]}？"
        else:
            questions_part = "、".join(f"{q}？" for q in valid_questions[:3])
            message = f"为了帮你把行程安排得更准确，我还想确认几个信息：{questions_part}"

        if follow_up_questions:
            message += "。" + follow_up_questions[0]
        return message

    def _is_complex_planning_intent(
        self,
        intent: IntentType,
        extracted_info: Dict[str, Any],
        task_config: Dict[str, Any],
    ) -> bool:
        if task_config.get("requires_review"):
            return True
        if intent in {IntentType.TRIP_PLANNING, IntentType.ITINERARY_PLANNING, IntentType.WEATHER_ADJUSTMENT}:
            return True
        return bool(extracted_info.get("duration") and int(extracted_info["duration"]) > 1)


class AgentOrchestrator:
    """
    Agent 编排器
    协调多个 Agent 完成复杂任务
    支持多模式对话和情感识别
    """

    def __init__(
        self,
        llm: LLMManager,
        config: Optional[OrchestratorConfig] = None,
    ):
        self.config = config or OrchestratorConfig()
        self.llm = llm

        # 组件
        self.intent_parser = IntentParser(llm)
        self.task_planner = TaskPlanner()
        self.mode_manager = ModeContextManager()

        # 模式处理器
        self.chat_handler = ChatModeHandler(llm)
        self.qa_handler = QAModeHandler(llm)

        # Agent 实例
        self._agent_instances: Dict[str, BaseAgent] = {}
        self._registry = get_registry()
        
        # 实验上下文
        self._experiment_ctx: Optional[ExperimentContext] = None
        self._experiment_metrics: Optional[Dict[str, Any]] = None
        
        # 如果启用了实验模式，创建实验上下文
        if self.config.experiment_mode:
            self._experiment_ctx = ExperimentContext(
                experiment_case_id=self.config.experiment_case_id,
                collaboration_mode=self.config.collaboration_mode,
                review_mode=self.config.review_mode,
                experiment_group="experiment_group",
            )

        logger.info("AgentOrchestrator initialized with multi-mode support")

    def register_agent(self, agent: BaseAgent) -> None:
        """注册 Agent 实例"""
        self._agent_instances[agent.name] = agent

    def get_agent(self, name: str) -> Optional[BaseAgent]:
        """获取 Agent 实例"""
        return self._agent_instances.get(name)

    async def process(
        self,
        session: SessionContext,
        user_message: str,
        request_id: Optional[str] = None,
        forced_mode: Optional[DialogMode] = None,
        abort_event: Optional[asyncio.Event] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理用户请求

        Args:
            session: 会话上下文
            user_message: 用户消息
            request_id: 请求 ID
            forced_mode: 强制模式（可选）
            abort_event: abort 信号事件，用于中止正在运行的请求

        Yields:
            各阶段的处理结果
        """
        # 【本轮修复】检查 abort 信号
        if abort_event and abort_event.is_set():
            logger.info(f"Request {request_id} was aborted before starting")
            return

        request_id = request_id or str(uuid.uuid4())
        user_message = str(user_message or "")
        normalized_message = user_message.strip()
        request_start = time.perf_counter()
        stage_timings: Dict[str, float] = {}

        try:
            if not normalized_message:
                session.dialog_mode = DialogMode.PLANNING.value
                session.mode_confidence = 1.0
                session.detected_emotion = "neutral"
                session.emotion_confidence = 1.0

                yield {
                    "phase": "mode_detection",
                    "status": "completed",
                    "mode": DialogMode.PLANNING.value,
                    "mode_confidence": 1.0,
                    "emotion": "neutral",
                    "emotion_confidence": 1.0,
                }

                yield {
                    "phase": "response_synthesis",
                    "status": "completed",
                    "content": "请先告诉我想去哪里、玩几天和预算，我就能开始帮你规划。",
                    "execution_time_ms": 0,
                    "emotion": "neutral",
                    "suggestions": [
                        "帮我规划一个北京3天游，预算3000元",
                        "想去北京玩",
                    ],
                }
                return

            user_message = normalized_message

            # ========== 阶段 0: 模式检测 ==========
            mode_duration_ms = 0.0
            detected_mode = forced_mode or DialogMode.PLANNING
            planning_override = False
            prefetched_intent: Optional[IntentType] = None
            prefetched_extracted_info: Optional[Dict[str, Any]] = None
            prefetched_intent_parse_ms = 0.0

            if forced_mode:
                mode_context = ModeContext(
                    current_mode=forced_mode,
                    mode_confidence=1.0,
                    mode_reasoning="User specified mode",
                )
                emotion = emotion_detector.detect(user_message)
            else:
                mode_start = time.perf_counter()
                mode_context, emotion = self.mode_manager.detect(user_message, session)
                mode_duration_ms = (time.perf_counter() - mode_start) * 1000
                detected_mode = mode_context.current_mode
                self._record_stage_timing(
                    stage_timings,
                    "mode_detection",
                    mode_duration_ms,
                    request_id=request_id,
                    detected_mode=detected_mode.value,
                )

                if mode_context.current_mode in {DialogMode.CHAT, DialogMode.QA}:
                    intent_probe_start = time.perf_counter()
                    prefetched_intent, prefetched_extracted_info = self._fast_intent_parse(user_message, session)
                    prefetched_intent_parse_ms = (time.perf_counter() - intent_probe_start) * 1000
                    planning_override, override_reason = self._should_force_planning(
                        user_message=user_message,
                        session=session,
                        parsed_intent=prefetched_intent,
                        extracted_info=prefetched_extracted_info,
                    )

                    if planning_override:
                        original_mode = mode_context.current_mode
                        mode_context = ModeContext(
                            current_mode=DialogMode.PLANNING,
                            mode_confidence=max(mode_context.mode_confidence, 0.9),
                            mode_reasoning=override_reason or mode_context.mode_reasoning,
                            suggested_mode_switch=DialogMode.PLANNING,
                            conversation_state=mode_context.conversation_state,
                        )
                        logger.info(
                            "Planning override triggered "
                            f"request_id={request_id} "
                            f"original_mode={original_mode.value} "
                            f"intent={prefetched_intent.value if prefetched_intent else IntentType.UNKNOWN.value} "
                            f"destination={(prefetched_extracted_info or {}).get('destination')} "
                            f"reason={override_reason}"
                        )

            # 更新会话模式
            session.dialog_mode = mode_context.current_mode.value
            session.mode_confidence = mode_context.mode_confidence
            session.detected_emotion = emotion.emotion.value
            session.emotion_confidence = emotion.confidence

            # 记录情感历史
            session.emotion_history.append({
                "emotion": emotion.emotion.value,
                "confidence": emotion.confidence,
                "timestamp": datetime.utcnow().isoformat(),
            })

            yield {
                "phase": "mode_detection",
                "status": "completed",
                "mode": mode_context.current_mode.value,
                "mode_confidence": mode_context.mode_confidence,
                "emotion": emotion.emotion.value,
                "emotion_confidence": emotion.confidence,
                "execution_time_ms": round(mode_duration_ms, 2),
                "detected_mode": detected_mode.value,
                "planning_override": planning_override,
            }
            logger.info(
                f"Mode decision request_id={request_id} "
                f"detected_mode={detected_mode.value} "
                f"current_mode={mode_context.current_mode.value} "
                f"planning_override={planning_override}"
            )

            # ========== 处理不同模式 ==========
            if mode_context.current_mode == DialogMode.CHAT:
                async for result in self._handle_chat_mode(session, user_message, emotion, mode_context):
                    yield result
                total_ms = (time.perf_counter() - request_start) * 1000
                self._record_stage_timing(stage_timings, "total", total_ms, request_id=request_id, final_mode=DialogMode.CHAT.value)
                self._log_stage_timing_summary(request_id, stage_timings)
                return

            elif mode_context.current_mode == DialogMode.QA:
                async for result in self._handle_qa_mode(session, user_message, mode_context):
                    yield result
                total_ms = (time.perf_counter() - request_start) * 1000
                self._record_stage_timing(stage_timings, "total", total_ms, request_id=request_id, final_mode=DialogMode.QA.value)
                self._log_stage_timing_summary(request_id, stage_timings)
                return

            # ========== 规划模式 ==========
            async for result in self._handle_planning_mode(
                session,
                user_message,
                request_id,
                mode_context,
                emotion,
                prefetched_intent=prefetched_intent,
                prefetched_extracted_info=prefetched_extracted_info,
                prefetched_intent_parse_ms=prefetched_intent_parse_ms,
                initial_stage_timings=stage_timings,
                request_start_time=request_start,
            ):
                yield result

        except Exception as e:
            logger.exception(f"Orchestration failed: {e}")
            yield {
                "phase": "error",
                "status": "failed",
                "error": str(e),
            }

    async def _handle_chat_mode(
        self,
        session: SessionContext,
        user_message: str,
        emotion,
        mode_context: ModeContext,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """处理闲聊模式"""
        yield {
            "phase": "chat_mode",
            "status": "running",
            "message": "正在回复...",
        }

        content = await self.chat_handler.handle(user_message, session, emotion)

        # 获取建议
        suggestions = self.mode_manager.get_suggestions(mode_context.current_mode, emotion)

        yield {
            "phase": "chat_mode",
            "status": "completed",
            "content": content,
            "emotion": emotion.emotion.value,
            "suggestions": suggestions,
        }

    async def _handle_qa_mode(
        self,
        session: SessionContext,
        user_message: str,
        mode_context: ModeContext,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """处理问答模式"""
        yield {
            "phase": "qa_mode",
            "status": "running",
            "message": "正在查询答案...",
        }

        content, data = await self.qa_handler.handle(user_message, session)

        yield {
            "phase": "qa_mode",
            "status": "completed",
            "content": content,
            "data": data,
            "suggestions": ["需要我推荐相关景点吗？", "想开始规划行程吗？"],
        }

    async def _handle_planning_mode(
        self,
        session: SessionContext,
        user_message: str,
        request_id: str,
        mode_context: ModeContext,
        emotion,
        prefetched_intent: Optional[IntentType] = None,
        prefetched_extracted_info: Optional[Dict[str, Any]] = None,
        prefetched_intent_parse_ms: float = 0.0,
        initial_stage_timings: Optional[Dict[str, float]] = None,
        request_start_time: Optional[float] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """处理规划模式 - 优化版 - 增强流式思考输出"""
        # 创建执行上下文
        context = ExecutionContext(
            request_id=request_id,
            session_id=session.session_id,
            user_id=session.user_id,
        )
        stage_timings = self._get_stage_timings(context, initial_stage_timings)

        # 设置流式回调 - 实时发送思考步骤到前端
        async def thinking_callback(step):
            """流式思考步骤回调"""
            yield_value = {
                "phase": "agent_step",
                "status": "running",
                "agent": step.agent_name,
                "thinking_step": step.to_dict(),
                "thinking_steps": [s.to_dict() for s in context.thinking_steps],
            }
            # 通过 yield 发送（需要在 async generator 中使用）
            # 这里我们不 yield，而是将步骤存储到队列
            context._pending_events.append({
                "type": "thinking_step",
                "data": step.to_dict(),
            })

        context.thinking_callback = thinking_callback

        start_time = request_start_time or time.perf_counter()
        phase = ExecutionPhase.INTENT_PARSING

        # ========== 阶段 1: 意图解析 (使用快速规则 + LLM) ==========
        yield {
            "phase": phase.value,
            "status": "running",
            "message": "正在分析您的意图...",
        }

        # 记录详细思考步骤：意图解析开始
        context.add_thinking_step(
            agent_name="系统",
            step="意图解析",
            detail="🔍 正在分析用户输入，提取关键信息...\n📝 输入内容：" + user_message[:50] + ("..." if len(user_message) > 50 else ""),
            status="running",
            reasoning_chain=[
                {"content": "接收用户消息: " + user_message, "reasoning_type": "fact"},
                {"content": "分析语言特征和关键词", "reasoning_type": "analysis"},
                {"content": "识别用户意图和需求", "reasoning_type": "inference"},
            ],
        )

        # 优先尝试快速规则解析，避免 LLM 调用
        intent_parse_duration_ms = prefetched_intent_parse_ms
        if prefetched_intent is not None and prefetched_extracted_info is not None:
            intent = prefetched_intent
            extracted_info = dict(prefetched_extracted_info)
        else:
            fast_parse_start = time.perf_counter()
            intent, extracted_info = self._fast_intent_parse(user_message, session)
            intent_parse_duration_ms += (time.perf_counter() - fast_parse_start) * 1000

        # 如果规则解析置信度低，使用 LLM
        if intent == IntentType.UNKNOWN or not extracted_info.get("destination"):
            llm_intent_start = time.perf_counter()
            intent, extracted_info = await self.intent_parser.parse(
                user_message, session
            )
            intent_parse_duration_ms += (time.perf_counter() - llm_intent_start) * 1000

        extracted_info = self._normalize_extracted_info(extracted_info)
        self._record_stage_timing(
            stage_timings,
            "intent_parsing",
            intent_parse_duration_ms,
            request_id=request_id,
            intent=intent.value,
        )
        logger.info(
            f"Planning intent parsed request_id={request_id} "
            f"intent={intent.value} "
            f"extracted_info={self._build_extracted_info_log_summary(extracted_info)}"
        )

        # 记录意图解析结果
        extracted_summary = self._summarize_extracted_info(extracted_info)
        context.add_thinking_step(
            agent_name="系统",
            step="意图解析",
            detail=f"✅ 意图识别完成\n🎯 意图类型：{intent.value}\n📋 提取信息：\n{extracted_summary}",
            status="completed",
            reasoning_chain=[
                {"content": f"识别意图: {intent.value}", "reasoning_type": "decision", "confidence": 0.95},
            ],
        )

        context.extracted_info = extracted_info
        context.current_phase = phase.value

        # 【本轮修复】调试日志
        logger.info(
            f"Intent parsed request_id={request_id} "
            f"intent={intent.value} "
            f"destination={extracted_info.get('destination')} "
            f"duration={extracted_info.get('duration')} "
            f"budget={extracted_info.get('budget')} "
            f"session_destination={session.trip_context.destination} "
            f"session_duration={session.trip_context.duration_days} "
            f"session_budget={session.trip_context.budget_amount}"
        )

        yield {
            "phase": phase.value,
            "status": "completed",
            "intent": intent.value,
            "extracted_info": extracted_info,
            "execution_time_ms": round(intent_parse_duration_ms, 2),
            "thinking_steps": [s.to_dict() for s in context.thinking_steps],
        }

        # 【本轮修复】在更新会话上下文之前，检测是否是 FULL_NEW_PLAN
        # FULL_NEW_PLAN 需要清除旧会话状态，确保显式字段优先级
        is_full_new_plan, full_new_reason = self._detect_full_new_plan(
            user_message, session, extracted_info
        )
        if is_full_new_plan:
            logger.info(
                f"FULL_NEW_PLAN detected request_id={request_id} "
                f"reason={full_new_reason}"
            )
            # 清除旧会话状态
            session.trip_context.planned_days = []
            session.conversation_history = []
            # 【本轮新增】抢占并清除旧 pending clarification latch
            session.preempt_clarification_latch()
            # 清除旧的 committed snapshot（因为是全新规划）
            session.committed_trip_snapshot = None

        # 【本轮新增】执行消息路由
        route = self._route_message(user_message, session, extracted_info)
        logger.info(f"[MULTITURN_TRACE] Route decision: {route} request_id={request_id}")

        # 【本轮新增】根据路由执行不同的 slot 合并
        if route == "FULL_NEW_PLAN":
            merged_slots = self._merge_slots_for_full_new_plan(
                extracted_info,
                session.committed_trip_snapshot,
                session,
            )
            extracted_info = merged_slots

        # 【本轮新增】根据路由处理 CLARIFICATION_ANSWER
        if route == "CLARIFICATION_ANSWER":
            # 消费 clarification latch
            session.consume_clarification_latch()
            # 将回答值合并到 extracted_info
            answer_value = self._extract_clarification_answer(user_message, session.pending_clarification_latch)
            if answer_value:
                extracted_info.update(answer_value)

        # 更新会话上下文
        self._update_session_context(session, extracted_info)

        # ========== 阶段 2: 任务规划 ==========
        phase = ExecutionPhase.TASK_PLANNING
        yield {
            "phase": phase.value,
            "status": "running",
            "message": "正在制定执行计划...",
        }

        context.add_thinking_step(
            agent_name="编排器",
            step="任务规划",
            detail="📋 正在根据意图规划任务...\n🤔 分析所需的专业Agent...",
            status="running",
            reasoning_chain=[
                {"content": f"意图: {intent.value}", "reasoning_type": "fact"},
                {"content": "确定需要的专业Agent", "reasoning_type": "analysis"},
            ],
        )

        task_planning_start = time.perf_counter()
        plan = self.task_planner.create_plan(
            intent,
            extracted_info,
            session=session,
            user_message=user_message,
        )
        task_planning_duration_ms = (time.perf_counter() - task_planning_start) * 1000
        self._record_stage_timing(
            stage_timings,
            "task_planning",
            task_planning_duration_ms,
            request_id=request_id,
            task_count=len(plan.tasks),
            requires_clarification=plan.requires_clarification,
        )
        logger.info(
            f"Planning tasks selected request_id={request_id} "
            f"tasks={[self._normalize_agent_name_for_log(task.agent_name) for task in plan.tasks]} "
            f"requires_clarification={plan.requires_clarification} "
            f"missing_fields={plan.missing_fields}"
        )

        # 检查是否需要追问
        if plan.requires_clarification:
            clarification_event = {
                "phase": phase.value,
                "status": "completed",
                "requires_clarification": True,
                "content": plan.clarification_message or "",
                "clarification_message": plan.clarification_message,
                "questions": plan.clarification_questions,
                "missing_fields": plan.missing_fields,
                "intent": intent.value,
                "execution_time_ms": round(task_planning_duration_ms, 2),
            }
            yield clarification_event
            # 【本轮新增】设置 pending clarification latch
            session.set_pending_clarification(
                missing_slots=plan.missing_fields or [],
                origin_request_id=request_id,
                origin_intent=plan.intent.value if plan.intent else "unknown",
                partial_extracted=extracted_info,
            )
            # 发送 final + done，让 SSE 流正常结束
            yield {
                "event": "final",
                "data": json.dumps({
                    "type": "final",
                    "content": plan.clarification_message or "",
                    "thinking_steps": [],
                    "execution_time_ms": 0,
                    "emotion": "neutral",
                    "suggestions": [],
                    "missing_fields": plan.missing_fields or [],
                    "clarification_questions": plan.clarification_questions or [],
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                }, ensure_ascii=False)
            }
            total_ms = (time.perf_counter() - start_time) * 1000
            self._record_stage_timing(stage_timings, "total", total_ms, request_id=request_id, outcome="clarification")
            self._log_stage_timing_summary(request_id, stage_timings)
            return

        context.current_phase = phase.value

        # 记录任务规划结果
        task_list = ", ".join([t.agent_name for t in plan.tasks])
        execution_strategy = self._generate_execution_strategy(plan.tasks)
        context.add_thinking_step(
            agent_name="编排器",
            step="任务规划",
            detail=f"📋 规划完成\n🎯 将执行 {len(plan.tasks)} 个子任务\n📜 任务列表：{task_list}\n⚡ 执行策略：\n{execution_strategy}",
            status="completed",
            reasoning_chain=[
                {"content": f"分解为 {len(plan.tasks)} 个子任务", "reasoning_type": "decision"},
                {"content": f"任务: {task_list}", "reasoning_type": "fact"},
            ],
        )

        yield {
            "phase": phase.value,
            "status": "completed",
            "plan": {
                "intent": plan.intent.value,
                "task_count": len(plan.tasks),
                "execution_strategy": execution_strategy,
                "requires_review": plan.requires_review,
            },
            "follow_up_questions": plan.follow_up_questions,
            "missing_fields": plan.missing_fields,
            "execution_time_ms": round(task_planning_duration_ms, 2),
            "thinking_steps": [s.to_dict() for s in context.thinking_steps],
        }

        # ========== 阶段 3: 并行执行子 Agent ==========
        phase = ExecutionPhase.PARALLEL_EXECUTION
        yield {
            "phase": phase.value,
            "status": "running",
            "message": "正在并行执行各模块任务...",
        }

        task_lookup = {task.agent_name: task for task in plan.tasks}
        data_tasks = [task_lookup[name] for name in ["attraction", "weather"] if name in task_lookup]
        planning_tasks = [task_lookup[name] for name in ["itinerary", "budget"] if name in task_lookup]

        # 记录并行执行开始
        if data_tasks:
            task_names = ", ".join([t.agent_name for t in data_tasks])
            context.add_thinking_step(
                agent_name="编排器",
                step="并行执行",
                detail=f"🚀 启动并行执行\n⚡ 第一批（并行）：{task_names}\n⏳ 同时运行以提高效率",
                status="running",
                reasoning_chain=[
                    {"content": "分析任务依赖关系", "reasoning_type": "analysis"},
                    {"content": f"并行任务: {task_names}", "reasoning_type": "decision"},
                ],
            )
            yield {
                "phase": "agent_execution",
                "status": "running",
                "message": f"正在并行执行: {task_names}",
                "parallel_agents": [t.agent_name for t in data_tasks],
                "thinking_steps": [s.to_dict() for s in context.thinking_steps],
            }

        if planning_tasks:
            task_names = ", ".join([t.agent_name for t in planning_tasks])
            context.add_thinking_step(
                agent_name="编排器",
                step="顺序执行",
                detail=f"📝 第二批（顺序）：{task_names}\n⏭️ 依赖已完成结果逐步推进",
                status="running",
                reasoning_chain=[
                    {"content": "数据收集结果会陆续回流", "reasoning_type": "fact"},
                    {"content": f"规划任务: {task_names}", "reasoning_type": "decision"},
                ],
            )

        planner = self.get_agent("planner")
        planner_streaming_content = ""
        # 维护一个绝对不倒退的 stable baseline
        planner_stream_stable_baseline = ""

        def _next_stream_tick_seconds() -> float:
            if "attraction" not in context.completed_agents:
                return 1.0
            if "budget" not in context.completed_agents:
                return 0.6
            return 0.4

        def _select_stream_chunk(text: str, max_chars: int) -> str:
            if not text:
                return ""
            leading_newlines = len(text) - len(text.lstrip("\n"))
            prefix = text[:leading_newlines]
            remaining = text[leading_newlines:]
            if not remaining:
                return prefix
            newline_index = remaining.find("\n")
            if newline_index >= 0:
                return prefix + remaining[: newline_index + 1]
            if len(remaining) <= max_chars:
                return prefix + remaining
            return prefix + remaining[:max_chars]

        def _next_stream_chunk_size() -> int:
            return 2048

        def refresh_stream_target() -> None:
            nonlocal planner_stream_stable_baseline
            if not planner or not hasattr(planner, "build_streaming_prefix"):
                return
            # 只要 attraction + itinerary 完成就构建流式前缀，不再强制要求 budget
            has_attraction = bool(context.get_result("attraction"))
            has_itinerary = bool(context.get_result("itinerary"))
            if not (has_attraction and has_itinerary):
                return
            destination = str(context.extracted_info.get("destination") or "").strip()
            duration = context.extracted_info.get("duration")
            if not destination or not duration:
                return
            try:
                target_content = planner.build_streaming_prefix(session, context)
            except Exception as exc:
                logger.exception(f"Planner streaming prefix failed: {exc}")
                return
            if not target_content:
                return
            # 只扩展已确认的稳定前缀，不允许倒退
            if (
                planner_stream_stable_baseline
                and not target_content.startswith(planner_stream_stable_baseline)
            ):
                logger.warning(
                    "Planner stream target regressed request_id=%s old_len=%d new_len=%d",
                    request_id,
                    len(planner_stream_stable_baseline),
                    len(target_content),
                )
                return
            planner_stream_stable_baseline = target_content

        def build_progressive_event() -> Optional[Dict[str, Any]]:
            nonlocal planner_streaming_content
            if len(planner_stream_stable_baseline) <= len(planner_streaming_content):
                return None
            suffix = planner_stream_stable_baseline[len(planner_streaming_content):]
            chunk = _select_stream_chunk(suffix, _next_stream_chunk_size())
            if not chunk:
                return None
            planner_streaming_content += chunk
            return {
                "phase": phase.value,
                "status": "running",
                "content": chunk,
                "is_streaming": True,
                "agent": "planner",
                "thinking_steps": [s.to_dict() for s in context.thinking_steps],
            }

        async def await_agent_result(agent_name: str, task: "asyncio.Task[AgentResponse]") -> AgentResponse:
            try:
                return await task
            except Exception as exc:
                logger.exception(f"Agent task failed request_id={request_id} agent={agent_name}: {exc}")
                return AgentResponse(
                    agent_name=agent_name,
                    status=AgentStatus.FAILED,
                    content="",
                    error=str(exc),
                )

        pending_tasks: Dict[str, asyncio.Task] = {}
        started_tasks: set[str] = set()
        planning_results: List[AgentResponse] = []

        def start_task(agent_name: str) -> None:
            if agent_name not in task_lookup or agent_name in started_tasks:
                return
            pending_tasks[agent_name] = asyncio.create_task(
                self._execute_single_task(task_lookup[agent_name], session, context)
            )
            started_tasks.add(agent_name)

        def maybe_start_tasks() -> None:
            if "attraction" in task_lookup and "attraction" not in started_tasks:
                start_task("attraction")
            if "weather" in task_lookup and "weather" not in started_tasks:
                start_task("weather")
            if (
                "itinerary" in task_lookup
                and "itinerary" not in started_tasks
                and ("attraction" not in task_lookup or "attraction" in context.completed_agents)
            ):
                start_task("itinerary")
            if (
                "budget" in task_lookup
                and "budget" not in started_tasks
                and ("attraction" not in task_lookup or "attraction" in context.completed_agents)
                and ("itinerary" not in task_lookup or "itinerary" in context.completed_agents)
                and ("weather" not in task_lookup or "weather" in context.completed_agents)
            ):
                start_task("budget")

        maybe_start_tasks()
        refresh_stream_target()
        draft_event = build_progressive_event()
        if draft_event:
            yield draft_event

        while pending_tasks:
            done, _ = await asyncio.wait(
                list(pending_tasks.values()),
                timeout=_next_stream_tick_seconds(),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                refresh_stream_target()
                draft_event = build_progressive_event()
                if draft_event:
                    yield draft_event
                continue
            for finished_task in done:
                agent_name = next(
                    name for name, pending in pending_tasks.items()
                    if pending is finished_task
                )
                pending_tasks.pop(agent_name, None)
                result = await await_agent_result(agent_name, finished_task)
                context.add_result(agent_name, result)
                self._log_agent_result_summary(request_id, agent_name, result)
                if agent_name in {"itinerary", "budget"}:
                    planning_results.append(result)
                for ts in context.thinking_steps:
                    if ts.agent_name == agent_name.capitalize():
                        yield {
                            "phase": "agent_step",
                            "status": "running",
                            "agent": agent_name,
                            "thinking_step": ts.to_dict(),
                            "thinking_steps": [s.to_dict() for s in context.thinking_steps],
                        }

                if agent_name in {"attraction", "itinerary", "budget", "weather"}:
                    refresh_stream_target()

                maybe_start_tasks()

            refresh_stream_target()
            draft_event = build_progressive_event()
            if draft_event:
                yield draft_event

        # 【修复】在执行 Planner 前校验天数，不允许默认 3 天
        if not context.extracted_info.get("duration"):
            # 天数缺失，不执行 planner，直接追问
            yield {
                "phase": "task_planning",
                "status": "completed",
                "requires_clarification": True,
                "content": "为了帮你把行程安排得更准确，我还想确认一下：你计划玩几天？",
                "clarification_message": "为了帮你把行程安排得更准确，我还想确认一下：你计划玩几天？",
                "questions": ["你计划玩几天？"],
                "missing_fields": ["travel_time"],
                "intent": intent.value,
            }
            yield {
                "event": "final",
                "data": json.dumps({
                    "type": "final",
                    "content": "为了帮你把行程安排得更准确，我还想确认一下：你计划玩几天？",
                    "thinking_steps": [],
                    "execution_time_ms": 0,
                    "emotion": "neutral",
                    "suggestions": [],
                    "missing_fields": ["travel_time"],
                    "clarification_questions": ["你计划玩几天？"],
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                }, ensure_ascii=False)
            }
            total_ms = (time.perf_counter() - start_time) * 1000
            self._record_stage_timing(stage_timings, "total", total_ms, request_id=request_id, outcome="clarification")
            self._log_stage_timing_summary(request_id, stage_timings)
            return

        refresh_stream_target()
        draft_event = build_progressive_event()
        if draft_event:
            yield draft_event

        # 执行主 Planner（正式结果）
        context.add_thinking_step(
            agent_name="编排器",
            step="综合整理",
            detail="📝 启动 Planner Agent，整合所有结果...\n🔄 综合景点、天气、行程、预算信息",
            status="running",
            reasoning_chain=[
                {"content": "所有子任务完成", "reasoning_type": "fact"},
                {"content": "调用 Planner 综合整理", "reasoning_type": "decision"},
            ],
        )

        planner_task = TaskSchema(
            task_id="planner_main",
            description="Execute planner agent",
            agent_name="planner",
            dependencies=[],
        )

        # 获取 planner 实例
        planner_response = None
        planner_start = time.perf_counter()

        planner_task_future = asyncio.create_task(
            self._execute_single_task(planner_task, session, context)
        )
        while True:
            done, _ = await asyncio.wait(
                [planner_task_future],
                timeout=_next_stream_tick_seconds(),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if done:
                break
            refresh_stream_target()
            draft_event = build_progressive_event()
            if draft_event:
                yield draft_event
        planner_response = await await_agent_result("planner", planner_task_future)
        planning_results.append(planner_response)

        if planner_response:
            self._log_agent_result_summary(request_id, "planner", planner_response)

        planner_duration_ms = (time.perf_counter() - planner_start) * 1000
        self._record_stage_timing(
            stage_timings,
            "planner",
            planner_duration_ms,
            request_id=request_id,
            streamed=bool(planner_streaming_content),
        )
        agent_results = planning_results
        review_result = None

        if (
            plan.requires_review
            and self.config.review_enabled
            and planner_response
            and planner_response.success
        ):
            phase = ExecutionPhase.QUALITY_REVIEW
            
            # 根据实验模式决定 review_mode
            review_mode = self._get_review_mode()
            
            if review_mode != ReviewModeExperiment.NO_REVIEW.value:
                yield {
                    "phase": phase.value,
                    "status": "running",
                    "message": "正在审查规划结果...",
                }

                review_agent = self.get_agent("review")
                if review_agent:
                    # 设置 review mode 到 context（execute 方法会从这里读取）
                    if "extracted_info" not in context.__dict__ or context.extracted_info is None:
                        context.extracted_info = {}
                    context.extracted_info["review_mode"] = review_mode
                    
                    review_start = time.perf_counter()
                    review_task_future = asyncio.create_task(review_agent.run(session, context))
                    while True:
                        done, _ = await asyncio.wait(
                            [review_task_future],
                            timeout=_next_stream_tick_seconds(),
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if done:
                            break
                        refresh_stream_target()
                        draft_event = build_progressive_event()
                        if draft_event:
                            yield draft_event
                    review_result = await await_agent_result("review", review_task_future)
                    review_duration_ms = (time.perf_counter() - review_start) * 1000
                    self._record_stage_timing(stage_timings, "review", review_duration_ms, request_id=request_id)
                    agent_results.append(review_result)

                yield {
                    "phase": phase.value,
                    "status": "completed",
                    "review": self._serialize_review_result(review_result),
                    "thinking_steps": [s.to_dict() for s in context.thinking_steps],
                }

            phase = ExecutionPhase.PARALLEL_EXECUTION

        # 记录所有 Agent 完成
        # 获取执行指标摘要
        metrics_summary = []
        for name, m in context.agent_metrics.items():
            metrics_summary.append(f"  • {name}: {m.execution_time_ms:.0f}ms, {m.tokens_used} tokens")

        context.add_thinking_step(
            agent_name="编排器",
            step="执行完成",
            detail=f"✅ 所有 Agent 执行完成\n📊 执行摘要：\n" + "\n".join(metrics_summary),
            status="completed",
            reasoning_chain=[
                {"content": f"共执行 {len(agent_results)} 个Agent", "reasoning_type": "fact"},
            ],
        )

        yield {
            "phase": phase.value,
            "status": "completed",
            "results": [
                {
                    "agent": r.agent_name,
                    "status": r.status.value,
                    "success": r.success,
                    "execution_time_ms": r.execution_time_ms,
                }
                for r in agent_results
            ],
            "agent_metrics": {name: m.to_dict() for name, m in context.agent_metrics.items()},
            "review": self._serialize_review_result(review_result),
            "budget": self._serialize_budget_result(context),
            "itinerary": self._serialize_itinerary_result(context),
            "attraction": self._serialize_attraction_result(context),
            "thinking_steps": [s.to_dict() for s in context.thinking_steps],
        }

        # ========== 阶段 4: 响应合成 - 前面已输出草稿，这里返回正式完整方案 ==========
        phase = ExecutionPhase.RESPONSE_SYNTHESIS
        elapsed_time = (time.perf_counter() - start_time) * 1000
        self._record_stage_timing(stage_timings, "total", elapsed_time, request_id=request_id)
        self._log_stage_timing_summary(request_id, stage_timings)
        suggestions = self.mode_manager.get_suggestions(DialogMode.PLANNING, emotion)

        context.add_thinking_step(
            agent_name="系统",
            step="完成",
            detail=f"🎉 任务完成！\n⏱️ 总耗时：{elapsed_time:.0f}ms",
            status="completed",
        )

        # 前面已经持续输出正文草稿，这里发送正式完整方案
        # 收集实验指标
        experiment_metrics = self._collect_experiment_metrics(context) if self.config.experiment_mode else None
        
        result = {
            "phase": phase.value,
            "status": "completed",
            "content": planner_response.content if planner_response else planner_streaming_content,
            "execution_time_ms": elapsed_time,
            "emotion": emotion.emotion.value,
            "suggestions": suggestions,
            "review": self._serialize_review_result(review_result),
            "budget": self._serialize_budget_result(context),
            "itinerary": self._serialize_itinerary_result(context),
            "attraction": self._serialize_attraction_result(context),
            "thinking_steps": [s.to_dict() for s in context.thinking_steps],
        }
        
        # 如果是实验模式，添加实验指标
        if self.config.experiment_mode and experiment_metrics:
            result["experiment_mode"] = True
            result["collaboration_mode"] = self.config.collaboration_mode
            result["review_mode"] = self._get_review_mode()
            result["experiment_case_id"] = self.config.experiment_case_id
            result["experiment_metrics"] = experiment_metrics

        yield result

        # 【本轮新增】成功完成后提交 committed trip snapshot
        self._commit_trip_on_completion(session, context, extracted_info, request_id)

    def _commit_trip_on_completion(
        self,
        session: SessionContext,
        context: ExecutionContext,
        extracted_info: Dict[str, Any],
        request_id: str,
    ) -> None:
        """【本轮新增】规划成功完成后提交 trip snapshot"""
        destination = extracted_info.get("destination") or session.trip_context.destination
        duration_days = extracted_info.get("duration") or extracted_info.get("duration_days") or session.trip_context.duration_days
        budget_amount = extracted_info.get("budget_amount") or extracted_info.get("budget") or session.trip_context.budget_amount
        people_count = extracted_info.get("num_travelers") or session.trip_context.num_travelers

        # 提取偏好
        preferences = []
        if travel_styles := extracted_info.get("travel_styles"):
            if isinstance(travel_styles, list):
                preferences.extend(travel_styles)
            else:
                preferences.append(travel_styles)
        if session.preferences.travel_style:
            preferences.extend(session.preferences.travel_style)

        # 构建计划摘要
        plan_summary = {
            "itinerary": self._serialize_itinerary_result(context),
            "budget": self._serialize_budget_result(context),
            "attraction": self._serialize_attraction_result(context),
        }

        # 提交快照
        if destination and duration_days:
            session.commit_trip_snapshot(
                destination=destination,
                duration_days=duration_days,
                budget_amount=budget_amount,
                people_count=people_count or 1,
                preferences=preferences,
                plan_summary=plan_summary,
                last_committed_turn_id=request_id,
            )
            logger.info(
                f"[MULTITURN_TRACE] Trip snapshot committed on completion: "
                f"request_id={request_id} destination={destination} duration={duration_days}"
            )

    def _generate_execution_strategy(self, tasks: List[TaskSchema]) -> str:
        """生成执行策略描述"""
        data_tasks = [t for t in tasks if t.agent_name in ["attraction", "weather"]]
        planning_tasks = [t for t in tasks if t.agent_name in ["itinerary", "budget"]]

        strategy_parts = []
        if data_tasks:
            strategy_parts.append(f"1️⃣ 第一阶段（并行）：{', '.join([t.agent_name for t in data_tasks])}")
        if planning_tasks:
            strategy_parts.append(f"2️⃣ 第二阶段（顺序）：{', '.join([t.agent_name for t in planning_tasks])}")
        strategy_parts.append("3️⃣ 综合阶段：Planner 整合所有结果")
        return "\n".join(strategy_parts)

    def _get_stage_timings(
        self,
        context: ExecutionContext,
        initial_stage_timings: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        stage_timings = getattr(context, "_stage_timings", None)
        if stage_timings is None:
            stage_timings = {}
            context._stage_timings = stage_timings
        if initial_stage_timings:
            stage_timings.update(initial_stage_timings)
        return stage_timings

    def _record_stage_timing(
        self,
        stage_timings: Dict[str, float],
        stage: str,
        duration_ms: float,
        request_id: Optional[str] = None,
        **metadata: Any,
    ) -> None:
        stage_timings[stage] = round(duration_ms, 2)
        metadata_text = " ".join(
            f"{key}={value}"
            for key, value in metadata.items()
            if value is not None and value != ""
        )
        if request_id:
            logger.info(
                f"Timing request_id={request_id} stage={stage} "
                f"duration_ms={duration_ms:.2f} {metadata_text}".rstrip()
            )
        else:
            logger.info(
                f"Timing stage={stage} duration_ms={duration_ms:.2f} {metadata_text}".rstrip()
            )

    def _log_stage_timing_summary(
        self,
        request_id: str,
        stage_timings: Dict[str, float],
    ) -> None:
        if not stage_timings:
            return

        sorted_items = sorted(stage_timings.items(), key=lambda item: item[1], reverse=True)
        slowest_non_total = next(
            (item for item in sorted_items if item[0] != "total"),
            sorted_items[0],
        )
        summary = ", ".join(f"{name}={duration:.2f}ms" for name, duration in sorted_items)
        logger.info(
            f"Timing summary request_id={request_id} "
            f"slowest_stage={slowest_non_total[0]} "
            f"slowest_duration_ms={slowest_non_total[1]:.2f} "
            f"stages=[{summary}]"
        )

    def _should_force_planning(
        self,
        user_message: str,
        session: SessionContext,
        parsed_intent: Optional[IntentType],
        extracted_info: Optional[Dict[str, Any]],
    ) -> tuple[bool, Optional[str]]:
        import re

        info = extracted_info or {}
        destination = str(info.get("destination") or "").strip()
        normalized_message = str(user_message or "").strip()
        has_constraint = self._has_planning_constraint_signal(normalized_message, info)
        planning_keywords = ("规划", "行程", "旅游", "旅行", "攻略", "出行", "安排", "计划")
        has_planning_keyword = any(keyword in normalized_message for keyword in planning_keywords)

        if destination and has_planning_keyword and has_constraint:
            return True, f"explicit_planning_request destination={destination}"

        if destination:
            travel_intent_patterns = [
                rf"想去{re.escape(destination)}",
                rf"(打算|准备|计划)去{re.escape(destination)}",
                rf"去{re.escape(destination)}(?:玩|旅游|旅行|逛|游)",
            ]
            if any(re.search(pattern, normalized_message) for pattern in travel_intent_patterns):
                return True, f"travel_intent_with_destination destination={destination}"

        session_destination = str(session.trip_context.destination or "").strip()
        session_in_planning = session.dialog_mode == DialogMode.PLANNING.value
        if session_destination and session_in_planning and has_constraint:
            return True, f"planning_follow_up destination={session_destination}"

        if parsed_intent == IntentType.TRIP_PLANNING and destination:
            return True, f"trip_planning_intent destination={destination}"

        return False, None

    def _detect_full_new_plan(
        self,
        user_message: str,
        session: SessionContext,
        extracted_info: Dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        """
        【本轮修复】检测是否是完整新规划请求
        完整新规划 = 有明确新目的地 + 至少有一个约束条件（天数/预算/时间）

        优先级最高，会清除旧会话状态
        """
        import re

        info = extracted_info or {}
        new_destination = info.get("destination")
        old_destination = session.trip_context.destination

        # 必须是新目的地
        if not new_destination:
            return False, None

        # 必须是不同的目的地
        if new_destination == old_destination:
            return False, None

        # 必须有至少一个约束条件
        has_constraints = (
            info.get("duration") is not None or
            info.get("budget") is not None or
            info.get("budget_amount") is not None or
            info.get("num_travelers") is not None or
            info.get("start_date") is not None
        )

        # 或者消息中有明确的规划关键词
        planning_keywords = ("规划", "行程", "计划", "攻略", "安排")
        has_planning_keyword = any(kw in user_message for kw in planning_keywords)

        # 周末/节假日时间信号
        time_patterns = [
            r"(周末|节假日|五一|十一|国庆|春节|清明|中秋|端午)",
            r"\d+天.*?(旅行|旅游|游玩|游玩)",
        ]
        has_time_signal = any(re.search(p, user_message) for p in time_patterns)

        is_full_new = (has_constraints or has_planning_keyword or has_time_signal)

        if is_full_new:
            return True, f"full_new_plan new_destination={new_destination}"

        return False, None

    def _has_planning_constraint_signal(
        self,
        user_message: str,
        extracted_info: Dict[str, Any],
    ) -> bool:
        import re

        if extracted_info.get("duration") or extracted_info.get("num_travelers"):
            return True
        if extracted_info.get("budget") is not None or extracted_info.get("budget_amount") is not None:
            return True
        if extracted_info.get("start_date") or extracted_info.get("end_date"):
            return True

        patterns = [
            r"\d+\s*[天日]",
            r"(预算|￥|¥|\d+\s*(?:元|块|万))",
            r"\d+\s*(?:个人|人|位)",
            r"\d{1,2}月\d{1,2}日",
            r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}(?:日)?",
            r"(今天|明天|后天|周末|下周|五一|十一|国庆|春节)",
        ]
        return any(re.search(pattern, user_message) for pattern in patterns)

    def _fast_intent_parse(
        self,
        user_message: str,
        session: SessionContext,
    ) -> tuple[IntentType, Dict[str, Any]]:
        """
        快速意图解析 - 基于规则的快速匹配
        只有在规则无法确定时才返回 UNKNOWN
        【本轮修复】follow-up 场景下继承 session 的目的地和天数
        """
        import re
        extracted_info: Dict[str, Any] = {}

        # 【本轮修复】检测是否是 follow-up：当前有 session destination 且消息不包含新目的地
        session_destination = session.trip_context.destination if session else None
        is_follow_up = bool(session_destination)

        # 检测目的地
        destinations = ["杭州", "北京", "上海", "成都", "西安", "桂林", "深圳", "广州", "厦门", "丽江", "苏州", "南京", "武汉", "重庆", "青岛", "大连", "三亚", "昆明", "哈尔滨", "长沙"]
        found_destination = None
        for dest in destinations:
            if dest in user_message:
                found_destination = dest
                break

        # 【本轮修复】如果消息没有新目的地，但 session 有目的地，则继承
        if found_destination:
            extracted_info["destination"] = found_destination
        elif is_follow_up and session_destination:
            # Follow-up 场景：继承 session 中的目的地
            extracted_info["destination"] = session_destination

        # 【本轮修复】follow-up 场景下继承 session 的天数
        if is_follow_up and session.trip_context.duration_days:
            extracted_info["duration"] = session.trip_context.duration_days

        # 【本轮修复】follow-up 场景下继承 session 的预算
        if is_follow_up and session.trip_context.budget_amount:
            extracted_info["budget_amount"] = session.trip_context.budget_amount
            if session.preferences.budget_level:
                extracted_info["budget_level"] = session.preferences.budget_level

        # 检测天数
        days_match = re.search(r"(\d+)[天日]|[一二三四五六七八九十]+天", user_message)
        if days_match:
            match = days_match.group(1)
            if match.isdigit():
                extracted_info["duration"] = int(match)
            else:
                # 中文数字转换
                chinese_nums = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
                for cn, num in chinese_nums.items():
                    if cn in match:
                        extracted_info["duration"] = num
                        break

        # 检测人数
        people_match = re.search(r"(\d+)[个人位]|[一两二三四五六七八九十]+个人", user_message)
        if people_match:
            match = people_match.group(1)
            if match.isdigit():
                extracted_info["num_travelers"] = int(match)
            else:
                chinese_nums = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5}
                for cn, num in chinese_nums.items():
                    if cn in match:
                        extracted_info["num_travelers"] = num
                        break

        # 检测预算
        budget_match = re.search(r"(\d+)(?:00)?[元块万]|预算[是为]*(\d+)", user_message)
        if budget_match:
            amount = budget_match.group(1) or budget_match.group(2)
            if amount:
                amount_int = int(amount)
                # 转换为元
                if amount_int < 100:  # 可能是 "5000" 写成 "5000"
                    amount_int = amount_int * 100 if amount_int > 100 else amount_int
                extracted_info["budget"] = amount_int
                if amount_int < 3000:
                    extracted_info["budget_level"] = "economy"
                elif amount_int < 6000:
                    extracted_info["budget_level"] = "medium"
                else:
                    extracted_info["budget_level"] = "luxury"

        # 检测旅行风格
        style_keywords = {
            "休闲": ["休闲", "放松", "度假", "慢节奏"],
            "探险": ["探险", "冒险", "刺激", "徒步", "登山"],
            "文化": ["文化", "历史", "古迹", "博物馆"],
            "亲子": ["亲子", "带孩子", "小孩", "家庭"],
            "蜜月": ["蜜月", "浪漫", "情侣", "二人世界"],
        }
        detected_styles = []
        for style, keywords in style_keywords.items():
            if any(kw in user_message for kw in keywords):
                detected_styles.append(style)
        if detected_styles:
            extracted_info["travel_styles"] = detected_styles

        # 确定意图
        # 【本轮修复】follow-up 场景下，即使消息中没有新目的地，只要有 session 目的地就视为有效规划
        inherited_destination = extracted_info.get("destination")
        if found_destination or inherited_destination:
            if extracted_info.get("duration") or extracted_info.get("budget"):
                intent = IntentType.TRIP_PLANNING
            else:
                intent = IntentType.ATTRACTION_RECOMMENDATION
        else:
            intent = IntentType.UNKNOWN

        return intent, extracted_info

    async def _execute_tasks(
        self,
        tasks: List[TaskSchema],
        session: SessionContext,
        context: ExecutionContext,
    ) -> List[AgentResponse]:
        """执行任务列表"""
        results = []

        # 找出可以并行执行的任务 (没有依赖的任务)
        ready_tasks = [t for t in tasks if not t.dependencies]
        remaining_tasks = [t for t in tasks if t.dependencies]

        while ready_tasks or remaining_tasks:
            # 并发执行准备好的任务
            if ready_tasks:
                batch_results = await asyncio.gather(
                    *[self._execute_single_task(t, session, context) for t in ready_tasks],
                    return_exceptions=True,
                )

                for task, result in zip(ready_tasks, batch_results):
                    if isinstance(result, Exception):
                        results.append(
                            AgentResponse(
                                agent_name=task.agent_name,
                                status=AgentStatus.FAILED,
                                content="",
                                error=str(result),
                            )
                        )
                    else:
                        results.append(result)

                    # 将完成的任务从剩余中移除
                    remaining_tasks = [
                        t for t in remaining_tasks
                        if task.task_id not in t.dependencies
                        or any(r.agent_name in [t.agent_name for r in results] for r in results)
                    ]

                # 清空已执行的任务
                ready_tasks = []

            # 添加可以执行的新任务
            if remaining_tasks:
                # 检查哪些任务的依赖已完成
                completed_agents = [r.agent_name for r in results]
                newly_ready = [
                    t for t in remaining_tasks
                    if all(
                        dep in completed_agents
                        for dep in self._get_dependency_agents(t.dependencies, tasks)
                    )
                ]

                ready_tasks.extend(newly_ready)
                remaining_tasks = [t for t in remaining_tasks if t not in newly_ready]

            # 防止无限循环
            if not ready_tasks and remaining_tasks:
                logger.warning("Possible circular dependency detected")
                break

        return results

    def _get_dependency_agents(
        self,
        dependencies: List[str],
        all_tasks: List[TaskSchema],
    ) -> List[str]:
        """获取依赖的任务对应的 Agent"""
        agents = []
        for dep in dependencies:
            for task in all_tasks:
                if task.task_id == dep:
                    agents.append(task.agent_name)
                    break
        return agents

    async def _execute_single_task(
        self,
        task: TaskSchema,
        session: SessionContext,
        context: ExecutionContext,
    ) -> AgentResponse:
        """执行单个任务"""
        agent = self.get_agent(task.agent_name)

        if agent is None:
            logger.warning(f"Agent not found: {task.agent_name}")

            # 创建简单的响应
            return AgentResponse(
                agent_name=task.agent_name,
                status=AgentStatus.COMPLETED,
                content=f"[模拟响应] {task.description}",
            )

        task_start = time.perf_counter()
        response = await agent.run(session, context)
        task_duration_ms = (time.perf_counter() - task_start) * 1000

        stage_timings = self._get_stage_timings(context)
        self._record_stage_timing(
            stage_timings,
            task.agent_name,
            task_duration_ms,
            request_id=context.request_id,
            status=response.status.value,
        )

        return response

    def _build_extracted_info_log_summary(self, extracted_info: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "destination": extracted_info.get("destination"),
            "duration": extracted_info.get("duration"),
            "budget": extracted_info.get("budget"),
            "budget_amount": extracted_info.get("budget_amount"),
            "budget_level": extracted_info.get("budget_level"),
            "num_travelers": extracted_info.get("num_travelers"),
            "travel_styles": extracted_info.get("travel_styles"),
            "start_date": str(extracted_info.get("start_date")) if extracted_info.get("start_date") else None,
            "end_date": str(extracted_info.get("end_date")) if extracted_info.get("end_date") else None,
        }

    def _log_agent_result_summary(
        self,
        request_id: Optional[str],
        agent_name: str,
        result: AgentResponse,
    ) -> None:
        log_agent_name = self._normalize_agent_name_for_log(agent_name)
        data = result.data if isinstance(result.data, dict) else {}
        poi_list = data.get("poi_list")
        pois = data.get("pois")
        daily_plans = data.get("daily_plans")
        budget_breakdown = data.get("budget_breakdown")
        logger.info(
            f"Agent result summary request_id={request_id} "
            f"agent={log_agent_name} "
            f"success={result.success} "
            f"status={result.status.value} "
            f"content_len={len(result.content or '')} "
            f"data_keys={sorted(data.keys()) if data else []} "
            f"poi_list_len={len(poi_list) if isinstance(poi_list, list) else 0} "
            f"pois_len={len(pois) if isinstance(pois, list) else 0} "
            f"daily_plans_len={len(daily_plans) if isinstance(daily_plans, list) else 0} "
            f"budget_breakdown_keys={sorted(budget_breakdown.keys()) if isinstance(budget_breakdown, dict) else []} "
            f"error={result.error or ''}"
        )

    def _normalize_agent_name_for_log(self, agent_name: Any) -> str:
        return str(getattr(agent_name, "value", agent_name))

    def _normalize_extracted_info(self, info: Dict[str, Any]) -> Dict[str, Any]:
        """
        标准化提取的信息，确保数据类型正确
        
        Args:
            info: 原始提取的信息字典
        
        Returns:
            标准化后的信息字典
        """
        normalized = info.copy()
        
        # 确保数字字段是正确类型
        if "duration" in normalized:
            try:
                normalized["duration"] = int(normalized["duration"])
            except (ValueError, TypeError):
                normalized["duration"] = None
        
        if "num_travelers" in normalized:
            try:
                normalized["num_travelers"] = int(normalized["num_travelers"])
            except (ValueError, TypeError):
                normalized["num_travelers"] = 1
        
        # 处理预算字段
        if "budget" in normalized:
            budget = normalized["budget"]
            if isinstance(budget, str):
                # 尝试从字符串提取数字
                import re
                match = re.search(r'(\d+)', budget)
                if match:
                    normalized["budget"] = int(match.group(1))
                else:
                    normalized["budget"] = None
        
        if "budget_amount" in normalized:
            try:
                normalized["budget_amount"] = float(normalized["budget_amount"])
            except (ValueError, TypeError):
                normalized["budget_amount"] = None
        
        # 确保 budget_level 有效
        valid_levels = ["economy", "medium", "luxury"]
        if "budget_level" in normalized:
            level = normalized["budget_level"]
            if isinstance(level, str) and level.lower() in valid_levels:
                normalized["budget_level"] = level.lower()
            elif isinstance(budget, (int, float)) and budget is not None:
                # 根据预算金额自动推断等级
                if budget < 3000:
                    normalized["budget_level"] = "economy"
                elif budget < 6000:
                    normalized["budget_level"] = "medium"
                else:
                    normalized["budget_level"] = "luxury"
        
        # 确保 travel_styles 是列表
        if "travel_styles" in normalized and not isinstance(normalized["travel_styles"], list):
            if isinstance(normalized["travel_styles"], str):
                normalized["travel_styles"] = [normalized["travel_styles"]]
            else:
                normalized["travel_styles"] = []
        
        # 确保 special_requirements 是列表
        if "special_requirements" in normalized and not isinstance(normalized["special_requirements"], list):
            if isinstance(normalized["special_requirements"], str):
                normalized["special_requirements"] = [normalized["special_requirements"]]
            else:
                normalized["special_requirements"] = []
        
        # 确保 interests 是列表
        if "interests" in normalized and not isinstance(normalized["interests"], list):
            if isinstance(normalized["interests"], str):
                normalized["interests"] = [normalized["interests"]]
            else:
                normalized["interests"] = []
        
        # 确保字符串字段没有多余空白
        for key in ["destination", "origin"]:
            if key in normalized and isinstance(normalized[key], str):
                normalized[key] = normalized[key].strip()
        
        return normalized

    def _summarize_extracted_info(self, info: Dict[str, Any]) -> str:
        """将提取的信息格式化为可读字符串"""
        lines = []
        if dest := info.get("destination"):
            lines.append(f"  - 📍 目的地: {dest}")
        if dur := info.get("duration"):
            lines.append(f"  - 📅 天数: {dur}天")
        if num := info.get("num_travelers"):
            lines.append(f"  - 👥 人数: {num}人")
        if budget := info.get("budget"):
            lines.append(f"  - 💰 预算: {budget}")
        if styles := info.get("travel_styles"):
            styles_str = ", ".join(styles) if isinstance(styles, list) else str(styles)
            lines.append(f"  - 🎯 风格: {styles_str}")
        return "\n".join(lines) if lines else "  - 无额外信息"

    async def _review_results(
        self,
        results: List[AgentResponse],
        session: SessionContext,
        context: ExecutionContext,
    ) -> bool:
        """审查结果质量"""
        # 检查是否有失败的任务
        failed = [r for r in results if not r.success]

        if failed:
            logger.warning(f"Review found {len(failed)} failed agents: {[r.agent_name for r in failed]}")
            return False

        return True

    def _synthesize_response(
        self,
        results: List[AgentResponse],
        context: ExecutionContext,
    ) -> str:
        """合成最终响应"""
        # 按 Agent 名称排序
        sorted_results = sorted(results, key=lambda r: r.agent_name)

        # 收集所有成功的内容
        contents = []
        for result in sorted_results:
            if result.success and result.content:
                contents.append(result.content)

        return "\n\n".join(contents) if contents else "抱歉，暂时无法处理您的请求。"

    async def _synthesize_response_stream(
        self,
        results: List[AgentResponse],
        context: ExecutionContext,
        emotion,
    ) -> AsyncGenerator[str, None]:
        """
        流式合成最终响应 - 边生成边输出
        优先使用 planner 的流式结果，否则回退到聚合所有 agent 结果
        """
        # 查找 planner 的流式结果（通过 context 获取）
        planner_streaming = context.get_result("_planner_stream")
        if planner_streaming:
            async for token in planner_streaming:
                yield token
            return

        # 回退：收集所有成功的内容
        sorted_results = sorted(results, key=lambda r: r.agent_name)
        contents = []
        for result in sorted_results:
            if result.success and result.content:
                contents.append(result.content)

        final_text = "\n\n".join(contents) if contents else "抱歉，暂时无法处理您的请求。"

        # 添加情感前缀
        if emotion.emotion.value != "neutral":
            strategy = emotion_detector.get_response_strategy(emotion.emotion)
            expressions = strategy.get("expressions", [])
            if emotion.intensity > 0.7 and expressions:
                final_text = f"{expressions[0]} {final_text}"

        # 模拟流式输出（将完整文本逐句 yield）
        lines = final_text.split("\n")
        for line in lines:
            yield line + "\n"
            # 小延迟让前端有时间渲染，但不要太大以免影响感知速度
            await asyncio.sleep(0.01)

    def _update_session_context(
        self,
        session: SessionContext,
        extracted_info: Dict[str, Any],
        user_message: str = "",
    ) -> None:
        """
        更新会话上下文
        【本轮修复】区分新规划与 follow-up：新目的地时清除旧行程状态
        """
        new_destination = extracted_info.get("destination")
        old_destination = session.trip_context.destination

        # 检测是否是新规划请求：新目的地出现时，清除旧行程状态
        is_new_planning = new_destination and new_destination != old_destination

        if is_new_planning:
            logger.info(
                f"New destination detected, clearing old trip state: "
                f"old={old_destination} new={new_destination}"
            )
            # 清除旧行程状态，避免新旧规划混染
            session.trip_context.planned_days = []
            session.conversation_history = []

        # 更新目的地
        if destination := extracted_info.get("destination"):
            session.trip_context.destination = destination

        # 更新人数
        if num := extracted_info.get("num_travelers"):
            session.trip_context.num_travelers = int(num)

        # 更新预算
        if budget_level := extracted_info.get("budget_level"):
            session.preferences.budget_level = budget_level

        # 更新旅行风格
        if styles := extracted_info.get("travel_styles"):
            if isinstance(styles, list):
                session.preferences.travel_style = styles

        # 更新天数与预算，兼容 duration/duration_days、budget/budget_amount 两套字段名。
        duration = extracted_info.get("duration")
        if duration is None:
            duration = extracted_info.get("duration_days")
        if duration is not None:
            session.trip_context.duration_days = int(duration)

        budget_amount = extracted_info.get("budget_amount")
        if budget_amount is None:
            budget_amount = extracted_info.get("budget")
        if budget_amount is not None:
            session.trip_context.budget_amount = float(budget_amount)

    # ========== 【本轮新增】消息路由优先级检测 ==========

    def _route_message(
        self,
        user_message: str,
        session: SessionContext,
        extracted_info: Dict[str, Any],
    ) -> str:
        """
        【本轮新增】消息路由优先级检测
        返回: FULL_NEW_PLAN | FOLLOW_UP | GENERAL_CHAT | CLARIFICATION_ANSWER | INCOMPLETE_PLANNING
        """
        # 0. NEW_SEND_TRANSPORT_GUARD - 由前端处理，这里只做后端路由

        # 1. FULL_NEW_PLAN（优先级最高）
        is_full_new, reason = self._detect_full_new_plan(user_message, session, extracted_info)
        if is_full_new:
            logger.info(f"[MULTITURN_TRACE] Route: FULL_NEW_PLAN reason={reason}")
            return "FULL_NEW_PLAN"

        # 2. FOLLOW_UP_ON_COMMITTED_TRIP
        if session.has_committed_trip() and session.is_follow_up_message(user_message):
            logger.info("[MULTITURN_TRACE] Route: FOLLOW_UP_ON_COMMITTED_TRIP")
            return "FOLLOW_UP"

        # 3. GENERAL_CHAT_OR_SIDE_QUESTION
        if session.is_side_question(user_message):
            logger.info("[MULTITURN_TRACE] Route: GENERAL_CHAT_OR_SIDE_QUESTION")
            return "GENERAL_CHAT"

        # 4. CLARIFICATION_ANSWER（检查 pending latch）
        if session.pending_clarification_latch and session.pending_clarification_latch.is_active():
            # 检查消息是否像是在补槽位
            if self._is_clarification_answer(user_message, session.pending_clarification_latch):
                logger.info("[MULTITURN_TRACE] Route: CLARIFICATION_ANSWER")
                return "CLARIFICATION_ANSWER"

        # 5. INCOMPLETE_PLANNING_REQUIRING_CLARIFICATION
        # 如果没有新目的地且没有 committed snapshot，需要追问
        if not extracted_info.get("destination") and not session.has_committed_trip():
            logger.info("[MULTITURN_TRACE] Route: INCOMPLETE_PLANNING (no destination)")
            return "INCOMPLETE_PLANNING"

        # 如果有目的地但缺天数或预算，也进入追问
        if extracted_info.get("destination") and not extracted_info.get("duration"):
            logger.info("[MULTITURN_TRACE] Route: INCOMPLETE_PLANNING (no duration)")
            return "INCOMPLETE_PLANNING"

        # 默认按 FOLLOW_UP 处理（基于已有 session 状态继续）
        if session.has_committed_trip():
            logger.info("[MULTITURN_TRACE] Route: FOLLOW_UP (default with committed snapshot)")
            return "FOLLOW_UP"

        logger.info("[MULTITURN_TRACE] Route: INCOMPLETE_PLANNING (default)")
        return "INCOMPLETE_PLANNING"

    def _is_clarification_answer(
        self,
        user_message: str,
        latch: "PendingClarificationLatch",
    ) -> bool:
        """【本轮新增】检测消息是否是 clarification 的回答"""
        import re

        missing = set(latch.missing_slots)
        msg = user_message.strip()

        # 检查是否是数字类槽位回答
        if "travel_time" in missing or "duration" in missing:
            if re.search(r"\d+\s*[天日]", msg):
                return True
            chinese_days = ["一", "二", "两", "三", "四", "五", "六", "七", "八", "九", "十"]
            if any(cn + "天" in msg for cn in chinese_days):
                return True

        if "budget" in missing:
            if re.search(r"\d+\s*[元块万]", msg) or re.search(r"预算\s*[:是为]*\s*\d+", msg):
                return True

        if "people" in missing:
            if re.search(r"\d+\s*[个人位]", msg):
                return True

        # 检查是否是日期类槽位回答
        if "travel_time" in missing or "start_date" in missing:
            date_patterns = [
                r"\d{1,2}月\d{1,2}日",
                r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}",
                r"(今天|明天|后天|五一|十一|国庆|春节)",
            ]
            if any(re.search(p, msg) for p in date_patterns):
                return True

        return False

    def _extract_clarification_answer(
        self,
        user_message: str,
        latch: "PendingClarificationLatch",
    ) -> Dict[str, Any]:
        """【本轮新增】从 clarification 回答中提取值"""
        import re

        extracted: Dict[str, Any] = {}
        missing = set(latch.missing_slots)
        msg = user_message.strip()

        if "travel_time" in missing or "duration" in missing:
            # 提取天数
            days_match = re.search(r"(\d+)\s*[天日]", msg)
            if days_match:
                extracted["duration"] = int(days_match.group(1))
            else:
                chinese_map = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
                for cn, num in chinese_map.items():
                    if cn + "天" in msg:
                        extracted["duration"] = num
                        break

        if "budget" in missing:
            # 提取预算
            budget_match = re.search(r"(\d+)(?:00)?\s*[元块万]?", msg)
            if budget_match:
                amount = int(budget_match.group(1))
                if amount < 100:
                    amount *= 100
                extracted["budget"] = amount

        if "people" in missing:
            # 提取人数
            people_match = re.search(r"(\d+)\s*[个人位]", msg)
            if people_match:
                extracted["num_travelers"] = int(people_match.group(1))

        return extracted

    def _merge_slots_for_full_new_plan(
        self,
        explicit_info: Dict[str, Any],
        committed_snapshot: Optional["CommittedTripSnapshot"],
        session: SessionContext,
    ) -> Dict[str, Any]:
        """
        【本轮新增】FULL_NEW_PLAN 的 slot 合并
        优先级: 显式值 > session 提取值 > committed snapshot 兜底 > 默认值
        """
        merged: Dict[str, Any] = dict(explicit_info or {})

        # 1. 显式值直接覆盖
        for key in ["destination", "duration_days", "budget_amount", "num_travelers", "start_date"]:
            if explicit_info.get(key) is not None:
                merged[key] = explicit_info[key]

        # 保留原始提取字段，并补齐 canonical 别名，避免完整请求在后续判定时被误判缺槽。
        if explicit_info.get("duration") is not None:
            merged["duration"] = explicit_info["duration"]
            merged["duration_days"] = explicit_info["duration"]

        if explicit_info.get("budget") is not None:
            merged["budget"] = explicit_info["budget"]
            merged["budget_amount"] = explicit_info["budget"]

        # 2. 转换 destination 字段名
        if "destination" not in merged and explicit_info.get("destination"):
            merged["destination"] = explicit_info["destination"]

        # 3. committed snapshot 兜底（只有显式值为空时才用）
        if committed_snapshot:
            if "destination" not in merged:
                merged["destination"] = committed_snapshot.destination
            if "duration_days" not in merged:
                merged["duration_days"] = committed_snapshot.duration_days
            if "budget_amount" not in merged:
                merged["budget_amount"] = committed_snapshot.budget_amount
            if "num_travelers" not in merged:
                merged["num_travelers"] = committed_snapshot.people_count

        logger.info(
            f"[MULTITURN_TRACE] Merge for FULL_NEW_PLAN: "
            f"destination={merged.get('destination')} "
            f"duration={merged.get('duration_days')} "
            f"budget={merged.get('budget_amount')}"
        )
        return merged

    def _merge_slots_for_follow_up(
        self,
        follow_up_delta: Dict[str, Any],
        committed_snapshot: Optional["CommittedTripSnapshot"],
    ) -> Dict[str, Any]:
        """
        【本轮新增】FOLLOW_UP 的 slot 合并
        优先级: follow-up delta > committed snapshot
        """
        merged: Dict[str, Any] = {}

        # 1. 从 committed snapshot 继承
        if committed_snapshot:
            merged["destination"] = committed_snapshot.destination
            merged["duration_days"] = committed_snapshot.duration_days
            merged["budget_amount"] = committed_snapshot.budget_amount
            merged["people_count"] = committed_snapshot.people_count
            merged["preferences"] = list(committed_snapshot.preferences) if committed_snapshot.preferences else []

        # 2. follow-up delta 覆盖
        for key, value in follow_up_delta.items():
            if value is not None:
                if key == "duration":
                    merged["duration_days"] = value
                elif key == "budget":
                    merged["budget_amount"] = value
                elif key == "budget_amount":
                    merged["budget_amount"] = value
                else:
                    merged[key] = value

        # 3. 处理偏好增强
        if "preferences" in follow_up_delta:
            prefs = merged.get("preferences", [])
            new_prefs = follow_up_delta["preferences"]
            if isinstance(new_prefs, list):
                prefs.extend(new_prefs)
                merged["preferences"] = list(set(prefs))

        logger.info(
            f"[MULTITURN_TRACE] Merge for FOLLOW_UP: "
            f"destination={merged.get('destination')} "
            f"duration={merged.get('duration_days')} "
            f"budget={merged.get('budget_amount')}"
        )
        return merged

    def _serialize_review_result(self, review_result) -> Optional[Dict[str, Any]]:
        """序列化 review 结果（包含结构化字段）"""
        if not review_result:
            return None
        data = getattr(review_result, "data", None) or {}
        return {
            "content": getattr(review_result, "content", ""),
            "status": getattr(review_result, "status", None),
            "review_mode": data.get("review_mode"),
            "review_scores": data.get("review_scores"),
            "review_summary": data.get("review_summary"),
            "review_issues": data.get("review_issues"),
            "review_warnings": data.get("review_warnings"),
            "review_suggestions": data.get("review_suggestions"),
            "has_been_fixed": data.get("has_been_fixed"),
            "fixed_result": data.get("fixed_result"),
            "experiment_meta": data.get("experiment_meta"),
        }

    def _serialize_budget_result(self, context: ExecutionContext) -> Optional[Dict[str, Any]]:
        """序列化 budget 结果（包含结构化字段）"""
        budget_result = context.get_result("budget")
        if not budget_result:
            return None
        data = getattr(budget_result, "data", None) or {}
        return {
            "total_budget": data.get("total_budget"),
            "per_day_budget": data.get("per_day_budget"),
            "transport_cost": data.get("transport_cost"),
            "hotel_cost": data.get("hotel_cost"),
            "food_cost": data.get("food_cost"),
            "ticket_cost": data.get("ticket_cost"),
            "other_cost": data.get("other_cost"),
            "buffer_cost": data.get("buffer_cost"),
            "is_over_budget": data.get("is_over_budget"),
            "budget_limit": data.get("budget_limit"),
            "budget_gap": data.get("budget_gap"),
            "budget_breakdown": data.get("budget_breakdown"),
            "estimated_by": data.get("estimated_by"),
            "optimization_suggestions": data.get("optimization_suggestions"),
        }

    def _serialize_itinerary_result(self, context: ExecutionContext) -> Optional[Dict[str, Any]]:
        """序列化 itinerary 结果（包含结构化字段）"""
        itinerary_result = context.get_result("itinerary")
        if not itinerary_result:
            return None
        data = getattr(itinerary_result, "data", None) or {}
        return {
            "daily_plans": data.get("daily_plans"),
            "day_count": data.get("day_count"),
            "selected_pois": data.get("selected_pois"),
            "unscheduled_pois": data.get("unscheduled_pois"),
            "optimized_plan": data.get("optimized_plan"),
            "itinerary_summary": data.get("itinerary_summary"),
        }

    def _serialize_attraction_result(self, context: ExecutionContext) -> Optional[Dict[str, Any]]:
        """序列化 attraction 结果（包含结构化 poi_list）"""
        attraction_result = context.get_result("attraction")
        if not attraction_result:
            return None
        data = getattr(attraction_result, "data", None) or {}
        return {
            "poi_list": data.get("poi_list"),
            "poi_count": data.get("poi_count"),
            "recommended_pois": data.get("recommended_pois"),
            "attraction_summary": data.get("attraction_summary"),
        }

    def _get_review_mode(self) -> str:
        """
        获取实验配置的 Review 模式
        
        Returns:
            str: Review 模式
        """
        if self.config.experiment_mode:
            return self.config.review_mode
        return ReviewModeExperiment.REVIEW_ONLY.value

    def _collect_experiment_metrics(self, context: ExecutionContext) -> Optional[Dict[str, Any]]:
        """
        收集实验指标（用于实验模式）
        
        Args:
            context: 执行上下文
        
        Returns:
            Dict: 实验指标字典
        """
        if not self.config.experiment_mode:
            return None
        
        # 收集各 Agent 结果
        attraction_result = context.get_result("attraction")
        itinerary_result = context.get_result("itinerary")
        budget_result = context.get_result("budget")
        review_result = context.get_result("review")
        
        # 构建实验指标
        from app.core.experiment_metrics import build_experiment_metrics, metrics_to_dict
        
        metrics = build_experiment_metrics(
            attraction_result=attraction_result,
            itinerary_result=itinerary_result,
            budget_result=budget_result,
            review_result=review_result,
            experiment_ctx=self._experiment_ctx,
        )
        
        return metrics_to_dict(metrics)
