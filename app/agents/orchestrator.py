"""
Agent 编排器
核心调度器，管理多 Agent 协作
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections import Counter
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

COMMON_DESTINATION_CANDIDATES = [
    "杭州", "北京", "上海", "成都", "西安", "桂林", "深圳", "广州", "厦门", "丽江",
    "苏州", "南京", "武汉", "重庆", "青岛", "大连", "三亚", "昆明", "哈尔滨", "长沙",
]


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
            "sub_agents": ["attraction"],
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
            "sub_agents": ["attraction"],
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
        route: Optional[str] = None,
    ) -> PlanSchema:
        """创建任务计划"""
        if route == "GENERAL_CHAT":
            return PlanSchema(
                intent=IntentType.GENERAL_CHAT,
                tasks=[],
                requires_clarification=False,
                requires_review=False,
            )

        if route == "FOLLOW_UP":
            follow_up_agents = self._select_follow_up_sub_agents(extracted_info)
            return PlanSchema(
                intent=IntentType.TRIP_PLANNING,
                tasks=self._build_tasks(follow_up_agents),
                requires_clarification=False,
                requires_review=True,
            )

        task_config = self.INTENT_TASK_MAP.get(
            intent,
            self.INTENT_TASK_MAP[IntentType.GENERAL_CHAT]
        )

        tasks = self._build_tasks(task_config.get("sub_agents", []))

        recommendation_intents = {
            IntentType.ATTRACTION_RECOMMENDATION,
            IntentType.ROUTE_CONSULTATION,
        }
        if intent in recommendation_intents and not tasks:
            tasks = self._build_tasks(["attraction"])

        # FULL_NEW_PLAN 不回填旧会话核心槽位，避免旧预算/旧天数污染新规划。
        allow_session_core_fallback = route != "FULL_NEW_PLAN"
        session_trip_context = session.trip_context if session and allow_session_core_fallback else None

        destination = extracted_info.get("destination") or (session_trip_context.destination if session_trip_context else None)
        duration = extracted_info.get("duration") or (session_trip_context.duration_days if session_trip_context else None)
        start_date = extracted_info.get("start_date") or (session_trip_context.start_date if session_trip_context else None)
        end_date = extracted_info.get("end_date") or (session_trip_context.end_date if session_trip_context else None)
        # 人数保持既有默认逻辑（默认 1 人），避免无必要追问。
        num_travelers = extracted_info.get("num_travelers") or (session.trip_context.num_travelers if session else None)

        clarification_questions: List[str] = []
        follow_up_questions: List[str] = []
        missing_fields: List[str] = []

        strict_planning_intents = {
            IntentType.TRIP_PLANNING,
            IntentType.ITINERARY_PLANNING,
            IntentType.WEATHER_ADJUSTMENT,
        }
        lightweight_recommendation_intents = {
            IntentType.ATTRACTION_RECOMMENDATION,
            IntentType.ROUTE_CONSULTATION,
        }

        # A 级核心字段，按优先级排序
        if not destination:
            missing_fields.append("destination")
            clarification_questions.append("你想去哪个城市或目的地旅游？")

        if intent in strict_planning_intents:
            if not duration and not start_date and not end_date:
                missing_fields.append("travel_time")
                clarification_questions.append("你计划玩几天，或者大概什么时候出发？")

            budget_session = session if allow_session_core_fallback else None
            if not self._has_budget_info(extracted_info, budget_session):
                missing_fields.append("budget")
                clarification_questions.append("预算大概是多少？")

            if not num_travelers:
                missing_fields.append("people")
                clarification_questions.append("几个人一起出行？")
        elif intent in lightweight_recommendation_intents:
            # 推荐类请求不因 budget / people / duration 缺失而阻塞
            pass

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

    def _build_tasks(self, agent_names: List[str]) -> List[TaskSchema]:
        tasks: List[TaskSchema] = []
        for idx, agent_name in enumerate(agent_names, 1):
            tasks.append(
                TaskSchema(
                    task_id=f"task_{idx}",
                    description=f"Execute {agent_name} agent",
                    agent_name=agent_name,
                    dependencies=[],
                    status="pending",
                )
            )
        return tasks

    def _select_follow_up_sub_agents(self, extracted_info: Dict[str, Any]) -> List[str]:
        needs_weather = bool(
            extracted_info.get("destination_changed")
            or extracted_info.get("travel_dates")
            or extracted_info.get("start_date")
            or extracted_info.get("end_date")
        )

        agents = ["attraction", "itinerary", "budget"]
        if needs_weather:
            agents.insert(1, "weather")
        return agents

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

        extracted_info = self._normalize_extracted_info(
            extracted_info,
            user_message=user_message,
            session=session,
        )
        extracted_info = self._enrich_extracted_info(user_message, extracted_info, session)
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
        elif route == "FOLLOW_UP":
            follow_up_delta = self._extract_follow_up_delta(user_message, extracted_info, session)
            extracted_info = self._merge_slots_for_follow_up(
                follow_up_delta,
                session.committed_trip_snapshot,
                session,
            )

        # 【本轮新增】根据路由处理 CLARIFICATION_ANSWER
        if route == "CLARIFICATION_ANSWER":
            # 消费 clarification latch
            latch = session.pending_clarification_latch
            partial_extracted = dict(latch.partial_extracted or {}) if latch else {}
            session.consume_clarification_latch()
            # 将回答值合并到 extracted_info
            answer_value = self._extract_clarification_answer(user_message, latch) if latch else {}
            merged_extracted = dict(partial_extracted)
            merged_extracted.update(extracted_info)
            if answer_value:
                merged_extracted.update(answer_value)
            extracted_info = merged_extracted

        extracted_info = self._normalize_extracted_info(
            extracted_info,
            user_message=user_message,
            session=session,
        )
        context.extracted_info = extracted_info

        # 更新会话上下文
        if route != "GENERAL_CHAT":
            self._update_session_context(session, extracted_info)

        if route in {"FOLLOW_UP", "GENERAL_CHAT"}:
            self._hydrate_context_from_snapshot(session, context)

        if route == "GENERAL_CHAT":
            side_question_content = self._answer_side_question(session, user_message, context)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self._record_stage_timing(stage_timings, "task_planning", 0.0, request_id=request_id, task_count=0)
            self._record_stage_timing(stage_timings, "total", elapsed_ms, request_id=request_id, outcome="side_question")
            self._log_stage_timing_summary(request_id, stage_timings)
            yield {
                "phase": ExecutionPhase.RESPONSE_SYNTHESIS.value,
                "status": "completed",
                "content": side_question_content,
                "execution_time_ms": elapsed_ms,
                "emotion": emotion.emotion.value,
                "suggestions": [],
                "thinking_steps": [s.to_dict() for s in context.thinking_steps],
            }
            return

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
            route=route,
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
            self._persist_partial_trip_context(session, extracted_info)
            session.set_pending_clarification(
                missing_slots=plan.missing_fields or [],
                origin_request_id=request_id,
                origin_intent=plan.intent.value if plan.intent else "unknown",
                partial_extracted=extracted_info,
            )
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
        if intent in {IntentType.ATTRACTION_RECOMMENDATION, IntentType.ROUTE_CONSULTATION}:
            execution_strategy = "1️⃣ 执行景点推荐：attraction"
        else:
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
        follow_up_lead_in = ""
        if route == "FOLLOW_UP":
            follow_up_lead_in = self._build_follow_up_lead_in(user_message, extracted_info, session).strip()

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
            if 0 <= newline_index < max_chars:
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
            if follow_up_lead_in:
                target_content = f"{follow_up_lead_in}\n\n{target_content}"
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
        child_agent_results: List[AgentResponse] = []

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

        while pending_tasks:
            done, _ = await asyncio.wait(
                list(pending_tasks.values()),
                timeout=_next_stream_tick_seconds(),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                continue
            for finished_task in done:
                agent_name = next(
                    name for name, pending in pending_tasks.items()
                    if pending is finished_task
                )
                pending_tasks.pop(agent_name, None)
                result = await await_agent_result(agent_name, finished_task)
                context.add_result(agent_name, result)
                child_agent_results.append(result)
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

                maybe_start_tasks()

        recommendation_intents = {
            IntentType.ATTRACTION_RECOMMENDATION,
            IntentType.ROUTE_CONSULTATION,
        }
        if intent in recommendation_intents:
            attraction_result = next(
                (r for r in child_agent_results if r.agent_name == "attraction" and r.success),
                None,
            )

            final_content = ""
            if attraction_result and attraction_result.content:
                final_content = attraction_result.content
            else:
                final_content = self._synthesize_response(child_agent_results, context)

            elapsed_time = (time.perf_counter() - start_time) * 1000
            self._record_stage_timing(stage_timings, "total", elapsed_time, request_id=request_id)
            self._log_stage_timing_summary(request_id, stage_timings)

            suggestions = self.mode_manager.get_suggestions(DialogMode.QA, emotion)

            context.add_thinking_step(
                agent_name="系统",
                step="完成",
                detail=f"🎉 任务完成！\n⏱️ 总耗时：{elapsed_time:.0f}ms",
                status="completed",
            )

            result = {
                "phase": ExecutionPhase.RESPONSE_SYNTHESIS.value,
                "status": "completed",
                "content": final_content,
                "final_content_already_streamed": False,
                "execution_time_ms": elapsed_time,
                "emotion": emotion.emotion.value,
                "suggestions": suggestions,
                "review": None,
                "budget": None,
                "itinerary": None,
                "attraction": self._serialize_attraction_result(context),
                "thinking_steps": [s.to_dict() for s in context.thinking_steps],
            }

            experiment_metrics = self._collect_experiment_metrics(context) if self.config.experiment_mode else None
            if self.config.experiment_mode and experiment_metrics:
                result["experiment_mode"] = True
                result["collaboration_mode"] = self.config.collaboration_mode
                result["review_mode"] = self._get_review_mode()
                result["experiment_case_id"] = self.config.experiment_case_id
                result["experiment_metrics"] = experiment_metrics

            yield result
            return
        # 【修复】在执行 Planner 前校验天数，不允许默认 3 天
        effective_duration = context.extracted_info.get("duration") or session.trip_context.duration_days
        if effective_duration and context.extracted_info.get("duration") is None:
            context.extracted_info["duration"] = effective_duration
            context.extracted_info["duration_days"] = effective_duration
        if not effective_duration:
            self._persist_partial_trip_context(session, context.extracted_info)
            session.set_pending_clarification(
                missing_slots=["travel_time"],
                origin_request_id=request_id,
                origin_intent=intent.value,
                partial_extracted=context.extracted_info,
            )
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

        planner_response = None
        planner_start = time.perf_counter()

        yield {
            "phase": ExecutionPhase.RESPONSE_SYNTHESIS.value,
            "status": "running",
            "message": "正在生成最终响应...",
            "thinking_steps": [s.to_dict() for s in context.thinking_steps],
        }

        try:
            if planner and hasattr(planner, "execute_stream"):
                if follow_up_lead_in:
                    lead_in_chunk = f"{follow_up_lead_in}\n\n"
                    planner_streaming_content += lead_in_chunk
                    yield {
                        "phase": ExecutionPhase.RESPONSE_SYNTHESIS.value,
                        "status": "running",
                        "content": lead_in_chunk,
                        "is_streaming": True,
                        "agent": "planner",
                        "thinking_steps": [s.to_dict() for s in context.thinking_steps],
                    }
                async for planner_item in planner.execute_stream(session, context):
                    if isinstance(planner_item, str):
                        if not planner_item:
                            continue
                        planner_streaming_content += planner_item
                        yield {
                            "phase": ExecutionPhase.RESPONSE_SYNTHESIS.value,
                            "status": "running",
                            "content": planner_item,
                            "is_streaming": True,
                            "agent": "planner",
                            "thinking_steps": [s.to_dict() for s in context.thinking_steps],
                        }
                        await asyncio.sleep(0)
                    else:
                        planner_response = planner_item
            else:
                planner_task = TaskSchema(
                    task_id="planner_main",
                    description="Execute planner agent",
                    agent_name="planner",
                    dependencies=[],
                )
                planner_response = await await_agent_result(
                    "planner",
                    asyncio.create_task(self._execute_single_task(planner_task, session, context)),
                )
        except Exception as exc:
            logger.exception(f"Planner streaming execution failed request_id={request_id}: {exc}")
            planner_response = AgentResponse(
                agent_name="planner",
                status=AgentStatus.FAILED,
                content="",
                error=str(exc),
            )
        if planner_response is None:
            planner_response = AgentResponse(
                agent_name="planner",
                status=AgentStatus.COMPLETED,
                content=planner_streaming_content,
            )
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
        
        final_content = planner_response.content if planner_response else planner_streaming_content
        if route == "FOLLOW_UP" and final_content:
            final_content = f"{self._build_follow_up_lead_in(user_message, extracted_info, session)}\n\n{final_content}"

        final_content_already_streamed = bool(
            isinstance(final_content, str)
            and final_content
            and planner_streaming_content == final_content
        )

        result = {
            "phase": phase.value,
            "status": "completed",
            "content": final_content,
            "final_content_already_streamed": final_content_already_streamed,
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
        preferences = self._merge_string_lists(
            extracted_info.get("preferences"),
            extracted_info.get("interests"),
            extracted_info.get("travel_styles"),
            session.preferences.interests,
            session.preferences.travel_style,
        )
        if extracted_info.get("pace") == "relaxed":
            preferences = self._merge_string_lists(preferences, ["relaxed_pace"])
        if extracted_info.get("indoor_preference"):
            preferences = self._merge_string_lists(preferences, [f"indoor_pref:{extracted_info.get('indoor_preference')}"])

        # 构建计划摘要
        plan_summary = {
            "itinerary": self._serialize_itinerary_result(context),
            "budget": self._serialize_budget_result(context),
            "attraction": self._serialize_attraction_result(context),
            "weather": context.get_result("weather").data if context.get_result("weather") and getattr(context.get_result("weather"), "data", None) else None,
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

        # 检测目的地
        destinations = COMMON_DESTINATION_CANDIDATES
        found_destination = None
        for dest in destinations:
            if dest in user_message:
                found_destination = dest
                break

        # 仅在“未出现新目的地/同目的地”的场景继承旧上下文，
        # 避免 FULL_NEW_PLAN 被旧预算、旧天数污染。
        is_follow_up = bool(session_destination) and (
            not found_destination or found_destination == session_destination
        )

        # 【本轮修复】如果消息没有新目的地，但 session 有目的地，则继承
        if found_destination:
            extracted_info["destination"] = found_destination
        elif is_follow_up and session_destination:
            # Follow-up 场景：继承 session 中的目的地
            extracted_info["destination"] = session_destination

        explicit_location_info = self._extract_origin_destination_from_text(user_message, session=session)
        if explicit_location_info.get("origin"):
            extracted_info["origin"] = explicit_location_info["origin"]
        if explicit_location_info.get("destination"):
            extracted_info["destination"] = explicit_location_info["destination"]

        # 【本轮修复】follow-up 场景下继承 session 的天数
        if is_follow_up and session.trip_context.duration_days:
            extracted_info["duration"] = session.trip_context.duration_days

        # 【本轮修复】follow-up 场景下继承 session 的预算
        if is_follow_up and session.trip_context.budget_amount:
            extracted_info["budget_amount"] = session.trip_context.budget_amount
            if session.preferences.budget_level:
                extracted_info["budget_level"] = session.preferences.budget_level

        duration_days = self._extract_duration_from_text(user_message)
        if duration_days is not None:
            extracted_info["duration"] = duration_days

        num_travelers = self._extract_num_travelers_from_text(user_message)
        if num_travelers is not None:
            extracted_info["num_travelers"] = num_travelers

        budget_amount = self._extract_budget_amount_from_text(user_message)
        if budget_amount is not None:
            extracted_info["budget_amount"] = budget_amount
            extracted_info["budget"] = int(budget_amount) if float(budget_amount).is_integer() else budget_amount
            extracted_info["budget_level"] = self._infer_budget_level_from_amount(budget_amount)

        stripped_message = user_message.strip()
        numeric_only_match = re.fullmatch(r"(\d{3,7})(?:\.0+)?", stripped_message)

        has_existing_trip_context = False
        if session is not None:
            trip_ctx = getattr(session, "trip_context", None)
            if trip_ctx:
                if (
                    getattr(trip_ctx, "destination", None)
                    or getattr(trip_ctx, "duration_days", None)
                    or getattr(trip_ctx, "start_date", None)
                    or getattr(trip_ctx, "end_date", None)
                ):
                    has_existing_trip_context = True

        if (
            numeric_only_match
            and extracted_info.get("budget") is None
            and extracted_info.get("budget_amount") is None
            and has_existing_trip_context
        ):
            numeric_budget = float(numeric_only_match.group(1))
            extracted_info["budget_amount"] = numeric_budget
            extracted_info["budget"] = numeric_budget

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
        recommendation_keywords = ("推荐", "适合", "哪里", "哪些地方", "景点", "散步地点")
        planning_keywords = ("规划", "行程", "计划", "攻略")

        has_recommendation_signal = any(keyword in user_message for keyword in recommendation_keywords)
        has_planning_signal = any(keyword in user_message for keyword in planning_keywords)

        duration_value = extracted_info.get("duration")
        has_budget_signal = extracted_info.get("budget") is not None or extracted_info.get("budget_amount") is not None
        has_multi_day_signal = bool(duration_value and int(duration_value) > 1)

        if found_destination or inherited_destination:
            if has_recommendation_signal and not has_planning_signal and not has_budget_signal and not has_multi_day_signal:
                intent = IntentType.ATTRACTION_RECOMMENDATION
            elif has_budget_signal or has_multi_day_signal or has_planning_signal:
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
            "interests": extracted_info.get("interests"),
            "preferences": extracted_info.get("preferences"),
            "pace": extracted_info.get("pace"),
            "indoor_preference": extracted_info.get("indoor_preference"),
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

    @staticmethod
    def _merge_string_lists(*groups: Any) -> List[str]:
        merged: List[str] = []
        seen = set()
        for group in groups:
            if not group:
                continue
            values = group if isinstance(group, list) else [group]
            for value in values:
                text = str(value or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                merged.append(text)
        return merged

    @staticmethod
    def _infer_budget_level_from_amount(amount: Optional[float]) -> Optional[str]:
        if amount is None:
            return None
        if amount < 3000:
            return "economy"
        if amount < 6000:
            return "medium"
        return "luxury"

    @staticmethod
    def _parse_chinese_number(value: Any) -> Optional[int]:
        text = str(value or "").strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)

        mapping = {
            "零": 0,
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        if text == "十":
            return 10
        if "十" in text:
            left, right = text.split("十", 1)
            tens = 1 if not left else mapping.get(left)
            ones = 0 if not right else mapping.get(right)
            if tens is None or ones is None:
                return None
            return tens * 10 + ones

        digits = [mapping.get(char) for char in text]
        if any(digit is None for digit in digits):
            return None

        result = 0
        for digit in digits:
            result = result * 10 + int(digit)
        return result if result > 0 else None

    @staticmethod
    def _normalize_budget_amount_value(amount: float, unit: str = "") -> float:
        unit_text = str(unit or "").strip().lower()
        if unit_text in {"万", "w"}:
            amount *= 10000
        elif unit_text in {"千", "k"}:
            amount *= 1000
        return round(amount, 2)

    def _match_known_destination(self, candidate: str, session: Optional[SessionContext] = None) -> str:
        text = str(candidate or "").strip()
        if not text:
            return ""

        known_candidates = list(COMMON_DESTINATION_CANDIDATES)
        if session:
            for extra in [session.trip_context.destination, session.trip_context.origin]:
                extra_text = str(extra or "").strip()
                if extra_text and extra_text not in known_candidates:
                    known_candidates.insert(0, extra_text)

        for item in known_candidates:
            if item and item in text:
                return item
        return text

    def _normalize_location_candidate(self, candidate: Any, session: Optional[SessionContext] = None) -> str:
        text = str(candidate or "").strip()
        if not text:
            return ""

        text = re.split(r"[，。；;,、\s]", text)[0]
        text = re.sub(r"^(从|由|去|到|在)", "", text)
        text = re.sub(r"(出发地|目的地|旅游|旅行|游玩|玩|逛|出发|前往|看看|走走)$", "", text)
        text = text.strip()
        if not text:
            return ""
        return self._match_known_destination(text, session=session)

    def _extract_origin_destination_from_text(
        self,
        user_message: str,
        session: Optional[SessionContext] = None,
    ) -> Dict[str, str]:
        text = str(user_message or "").strip()
        if not text:
            return {}

        result: Dict[str, str] = {}
        origin_patterns = [
            r"(?:从|由)\s*([^\s，。；,]{1,12}?)(?=\s*(?:出发|过去|前往|去|到|飞|乘|坐|自驾|高铁|火车|飞机|，|。|,|$))",
        ]
        destination_patterns = [
            r"(?:想去|准备去|计划去|去)\s*([^\s，。；,]{1,12}?)(?=\s*(?:玩|旅游|旅行|逛|看看|走走|待|住|打卡|，|。|,|$))",
            r"(?:前往)\s*([^\s，。；,]{1,12}?)(?=\s*(?:玩|旅游|旅行|逛|看看|走走|待|住|打卡|，|。|,|$))",
            r"(?:^|[，。；,\s])到\s*([^\s，。；,]{1,12}?)(?=\s*(?:玩|旅游|旅行|逛|看看|走走|待|住|打卡|，|。|,|$))",
            r"在\s*([^\s，。；,]{1,12}?)(?=\s*(?:玩|旅游|旅行|逛))",
        ]

        for pattern in origin_patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            origin = self._normalize_location_candidate(match.group(1), session=session)
            if origin:
                result["origin"] = origin
                break

        for pattern in destination_patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            destination = self._normalize_location_candidate(match.group(1), session=session)
            if destination:
                result["destination"] = destination
                break

        return result

    def _extract_duration_from_text(self, user_message: str) -> Optional[int]:
        text = str(user_message or "").strip()
        if not text:
            return None

        digit_night_day = re.search(r"(\d+)\s*晚\s*(\d+)\s*[天日]", text)
        if digit_night_day:
            return int(digit_night_day.group(2))

        cn_night_day = re.search(r"([一二两三四五六七八九十零]+)\s*晚\s*([一二两三四五六七八九十零]+)\s*[天日]", text)
        if cn_night_day:
            return self._parse_chinese_number(cn_night_day.group(2))

        digit_duration = re.search(r"(?:玩|待|住|逛|旅游|旅行)?\s*(\d+)\s*[天日]", text)
        if digit_duration:
            return int(digit_duration.group(1))

        cn_duration = re.search(r"(?:玩|待|住|逛|旅游|旅行)?\s*([一二两三四五六七八九十零]+)\s*[天日]", text)
        if cn_duration:
            return self._parse_chinese_number(cn_duration.group(1))

        return None

    def _extract_num_travelers_from_text(self, user_message: str) -> Optional[int]:
        text = str(user_message or "").strip()
        if not text:
            return None

        for pattern in [
            r"一家\s*([一二两三四五六七八九十零\d]+)\s*口",
            r"我们\s*([一二两三四五六七八九十零\d]+)\s*人",
            r"([一二两三四五六七八九十零\d]+)\s*(?:个人|人|位)",
        ]:
            match = re.search(pattern, text)
            if not match:
                continue
            return self._parse_chinese_number(match.group(1))
        return None

    def _extract_budget_amount_from_text(self, user_message: str) -> Optional[float]:
        text = str(user_message or "").strip()
        if not text:
            return None

        patterns = [
            r"预算(?:大概|大约|约|在|是|为|控制在|控制到|调到|调整到|到)?\s*(\d+(?:\.\d+)?)\s*(万|w|W|千|k|K|元|块)?",
            r"(\d+(?:\.\d+)?)\s*(万|w|W|千|k|K|元|块)(?:左右|以内|上下)?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            amount = float(match.group(1))
            unit = match.group(2) or ""
            return self._normalize_budget_amount_value(amount, unit)
        return None

    def _augment_special_requirements_from_text(self, normalized: Dict[str, Any], user_message: str) -> Dict[str, Any]:
        text = str(user_message or "").strip()
        if not text:
            return normalized

        has_elder_signal = any(keyword in text for keyword in ["爸妈", "老人", "长辈", "老年"])
        has_family_signal = any(keyword in text for keyword in ["亲子", "孩子", "小朋友", "宝宝", "带娃"])

        if not has_elder_signal and not has_family_signal:
            return normalized

        special_requirements = self._merge_string_lists(normalized.get("special_requirements"))
        if has_elder_signal:
            special_requirements = self._merge_string_lists(special_requirements, ["老人同行"])
        if has_family_signal:
            special_requirements = self._merge_string_lists(special_requirements, ["亲子出行"])
        normalized["special_requirements"] = special_requirements

        if not normalized.get("tourist_type"):
            if has_family_signal:
                normalized["tourist_type"] = "family"
            elif has_elder_signal:
                normalized["tourist_type"] = "senior"

        if not normalized.get("group_type") and (has_elder_signal or has_family_signal):
            normalized["group_type"] = "family"

        return normalized

    def _is_slot_only_update_turn(
        self,
        user_message: str,
        normalized: Dict[str, Any],
        explicit_destination: str = "",
    ) -> bool:
        if explicit_destination:
            return False

        slot_keys = ["origin", "duration", "duration_days", "budget", "budget_amount", "num_travelers", "start_date", "end_date"]
        if any(normalized.get(key) is not None for key in slot_keys):
            return True

        text = str(user_message or "").strip()
        slot_keywords = ["预算", "元", "块", "万", "人", "个人", "位", "天", "日", "晚", "出发", "爸妈", "老人", "长辈", "亲子", "孩子", "小朋友"]
        return any(keyword in text for keyword in slot_keywords)

    def _coerce_trip_datetime(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value

        text = str(value).strip()
        if not text:
            return None

        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass

        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%m月%d日", "%m/%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                if parsed.year == 1900:
                    parsed = parsed.replace(year=datetime.now().year)
                return parsed
            except ValueError:
                continue
        return None

    def _persist_partial_trip_context(
        self,
        session: SessionContext,
        extracted_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        partial = self._normalize_extracted_info(extracted_info, session=session)

        if destination := partial.get("destination"):
            session.trip_context.destination = destination

        origin = partial.get("origin") or partial.get("departure_place")
        if origin:
            session.trip_context.origin = origin

        duration_value = partial.get("duration")
        if duration_value is None:
            duration_value = partial.get("duration_days")
        if duration_value is not None:
            session.trip_context.duration_days = int(duration_value)

        budget_amount = partial.get("budget_amount")
        if budget_amount is None:
            budget_amount = partial.get("budget")
        if budget_amount is not None:
            session.trip_context.budget_amount = float(budget_amount)

        num_travelers = partial.get("num_travelers")
        if num_travelers is not None:
            session.trip_context.num_travelers = int(num_travelers)

        if start_date := self._coerce_trip_datetime(partial.get("start_date")):
            session.trip_context.start_date = start_date
        if end_date := self._coerce_trip_datetime(partial.get("end_date")):
            session.trip_context.end_date = end_date

        session.update_pending_clarification_partial(partial)
        return partial

    def _normalize_extracted_info(
        self,
        info: Dict[str, Any],
        user_message: str = "",
        session: Optional[SessionContext] = None,
    ) -> Dict[str, Any]:
        """
        标准化提取的信息，确保数据类型正确
        
        Args:
            info: 原始提取的信息字典
        
        Returns:
            标准化后的信息字典
        """
        normalized = dict(info or {})

        if normalized.get("origin") is None and normalized.get("departure_place") is not None:
            normalized["origin"] = normalized.get("departure_place")

        explicit_location_info = self._extract_origin_destination_from_text(user_message, session=session)
        explicit_origin = explicit_location_info.get("origin") or ""
        explicit_destination = explicit_location_info.get("destination") or ""
        if explicit_origin:
            normalized["origin"] = explicit_origin
            normalized["departure_place"] = explicit_origin
        if explicit_destination:
            normalized["destination"] = explicit_destination

        duration_from_text = self._extract_duration_from_text(user_message)
        if duration_from_text is not None:
            normalized["duration"] = duration_from_text
            normalized["duration_days"] = duration_from_text

        num_travelers_from_text = self._extract_num_travelers_from_text(user_message)
        if num_travelers_from_text is not None:
            normalized["num_travelers"] = num_travelers_from_text
            normalized["people_count"] = num_travelers_from_text

        budget_amount_from_text = self._extract_budget_amount_from_text(user_message)
        if budget_amount_from_text is not None:
            normalized["budget_amount"] = budget_amount_from_text
            normalized.setdefault(
                "budget",
                int(budget_amount_from_text) if float(budget_amount_from_text).is_integer() else budget_amount_from_text,
            )

        if normalized.get("duration") is None and normalized.get("duration_days") is not None:
            normalized["duration"] = normalized.get("duration_days")
        if normalized.get("num_travelers") is None and normalized.get("people_count") is not None:
            normalized["num_travelers"] = normalized.get("people_count")

        duration_value = normalized.get("duration")
        if duration_value is not None:
            try:
                duration_value = int(duration_value)
            except (ValueError, TypeError):
                duration_value = None
        normalized["duration"] = duration_value
        normalized["duration_days"] = duration_value

        num_travelers = normalized.get("num_travelers")
        if num_travelers is not None:
            try:
                num_travelers = int(num_travelers)
            except (ValueError, TypeError):
                num_travelers = 1
        normalized["num_travelers"] = num_travelers
        if num_travelers is not None:
            normalized["people_count"] = num_travelers

        budget = normalized.get("budget")
        if isinstance(budget, str):
            match = re.search(r"(\d+(?:\.\d+)?)", budget)
            budget = float(match.group(1)) if match else None
        elif isinstance(budget, (int, float)):
            budget = float(budget)
        else:
            budget = None

        budget_amount = normalized.get("budget_amount")
        if budget_amount is not None:
            try:
                budget_amount = float(budget_amount)
            except (ValueError, TypeError):
                budget_amount = None

        if budget_amount is None and budget is not None:
            budget_amount = budget
        if budget is None and budget_amount is not None:
            budget = budget_amount

        normalized["budget_amount"] = budget_amount
        normalized["budget"] = int(budget) if budget is not None and float(budget).is_integer() else budget

        level = normalized.get("budget_level")
        if isinstance(level, str) and level.lower() in {"economy", "medium", "luxury"}:
            normalized["budget_level"] = level.lower()
        else:
            normalized["budget_level"] = self._infer_budget_level_from_amount(budget_amount)

        for key in ["travel_styles", "special_requirements", "interests", "preferences"]:
            value = normalized.get(key)
            if value is None:
                normalized[key] = []
            elif isinstance(value, list):
                normalized[key] = self._merge_string_lists(value)
            else:
                normalized[key] = self._merge_string_lists([value])

        normalized = self._augment_special_requirements_from_text(normalized, user_message)

        for key in ["destination", "origin", "departure_place", "pace", "indoor_preference", "tourist_type", "group_type"]:
            value = normalized.get(key)
            if isinstance(value, str):
                normalized[key] = value.strip()

        session_destination = str(session.trip_context.destination or "").strip() if session else ""
        current_destination = str(normalized.get("destination") or "").strip()
        current_origin = str(normalized.get("origin") or "").strip()
        if explicit_origin and not normalized.get("departure_place"):
            normalized["departure_place"] = explicit_origin

        if session_destination and not explicit_destination:
            slot_only_update = self._is_slot_only_update_turn(user_message, normalized, explicit_destination=explicit_destination)
            destination_mismatch = bool(
                current_destination
                and current_destination != session_destination
                and current_destination == current_origin
            )
            if not current_destination and slot_only_update:
                normalized["destination"] = session_destination
            elif destination_mismatch:
                normalized["destination"] = session_destination
            elif (
                current_destination
                and current_destination != session_destination
                and slot_only_update
                and current_destination not in user_message
            ):
                normalized["destination"] = session_destination

        if normalized.get("origin") and not normalized.get("departure_place"):
            normalized["departure_place"] = normalized.get("origin")

        return normalized

    def _extract_message_preferences(self, user_message: str) -> Dict[str, Any]:
        text = str(user_message or "").strip()
        signals: Dict[str, Any] = {
            "preferences": [],
            "interests": [],
            "travel_styles": [],
            "special_requirements": [],
        }
        if not text:
            return signals

        if "美食" in text:
            signals["preferences"].extend(["food", "local_food"])
            signals["interests"].extend(["美食", "当地美食"])
            signals["travel_styles"].append("美食")

        if any(keyword in text for keyword in ["拍照", "出片", "摄影"]):
            signals["preferences"].extend(["photo", "photogenic"])
            signals["interests"].extend(["拍照", "摄影"])

        if "西湖" in text:
            signals["interests"].append("西湖")

        if "夜景" in text:
            signals["preferences"].append("night_view")
            signals["interests"].append("夜景")

        if any(keyword in text for keyword in ["少走路", "轻松点", "节奏轻松", "慢一点"]):
            signals["preferences"].extend(["less_walking", "relaxed_pace"])
            signals["travel_styles"].append("休闲")
            signals["special_requirements"].append("少走路")
            signals["pace"] = "relaxed"

        if any(keyword in text for keyword in ["室内多一点", "室内优先"]):
            signals["preferences"].extend(["indoor", "indoor_first"])
            signals["special_requirements"].append("室内优先")
            signals["indoor_preference"] = "indoor"

        if any(keyword in text for keyword in ["室外多一点", "室外优先"]):
            signals["preferences"].extend(["outdoor", "outdoor_first"])
            signals["indoor_preference"] = "outdoor"

        if any(keyword in text for keyword in ["更集中", "别太折腾", "交通太折腾"]):
            signals["preferences"].append("compact_route")
            signals["travel_styles"].append("休闲")
            signals["special_requirements"].append("交通更集中")

        budget_match = re.search(r"预算(?:改成|调整到|调到|变成|到)?\s*(\d+(?:\.\d+)?)", text)
        if budget_match:
            amount = float(budget_match.group(1))
            signals["budget_amount"] = amount
            signals["budget"] = int(amount) if amount.is_integer() else amount
            signals["budget_level"] = self._infer_budget_level_from_amount(amount)

        duration_match = re.search(r"(\d+)\s*[天日]", text)
        if duration_match:
            signals["duration"] = int(duration_match.group(1))
            signals["duration_days"] = int(duration_match.group(1))

        return {
            **signals,
            "preferences": self._merge_string_lists(signals["preferences"]),
            "interests": self._merge_string_lists(signals["interests"]),
            "travel_styles": self._merge_string_lists(signals["travel_styles"]),
            "special_requirements": self._merge_string_lists(signals["special_requirements"]),
        }

    def _enrich_extracted_info(
        self,
        user_message: str,
        extracted_info: Dict[str, Any],
        session: SessionContext,
    ) -> Dict[str, Any]:
        enriched = dict(extracted_info or {})
        message_signals = self._extract_message_preferences(user_message)
        for key in ["preferences", "interests", "travel_styles", "special_requirements"]:
            enriched[key] = self._merge_string_lists(enriched.get(key), message_signals.get(key))
        for scalar_key in ["budget", "budget_amount", "budget_level", "duration", "duration_days", "pace", "indoor_preference"]:
            if message_signals.get(scalar_key) is not None:
                enriched[scalar_key] = message_signals[scalar_key]
        return self._normalize_extracted_info(enriched, user_message=user_message, session=session)

    def _extract_follow_up_delta(
        self,
        user_message: str,
        extracted_info: Dict[str, Any],
        session: SessionContext,
    ) -> Dict[str, Any]:
        delta = dict(extracted_info or {})
        message_signals = self._extract_message_preferences(user_message)
        for key in ["preferences", "interests", "travel_styles", "special_requirements"]:
            delta[key] = self._merge_string_lists(delta.get(key), message_signals.get(key))
        for scalar_key in ["budget", "budget_amount", "budget_level", "duration", "duration_days", "pace", "indoor_preference"]:
            if message_signals.get(scalar_key) is not None:
                delta[scalar_key] = message_signals[scalar_key]
        snapshot = session.committed_trip_snapshot
        if not snapshot:
            return self._normalize_extracted_info(delta, user_message=user_message, session=session)

        if delta.get("budget_amount") is not None:
            delta["budget_changed"] = delta["budget_amount"] != snapshot.budget_amount
        if delta.get("duration_days") is not None:
            delta["duration_changed"] = delta["duration_days"] != snapshot.duration_days

        return self._normalize_extracted_info(delta, user_message=user_message, session=session)

    def _hydrate_context_from_snapshot(self, session: SessionContext, context: ExecutionContext) -> None:
        snapshot = session.committed_trip_snapshot
        plan_summary = snapshot.plan_summary if snapshot else None
        if not plan_summary:
            return

        for agent_name in ["attraction", "weather", "itinerary", "budget"]:
            data = plan_summary.get(agent_name)
            if data and not context.has_result(agent_name):
                context.add_result(
                    agent_name,
                    AgentResponse(
                        agent_name=agent_name,
                        status=AgentStatus.COMPLETED,
                        content="",
                        data=data,
                    ),
                )

    def _extract_regions_from_daily_plans(self, daily_plans: List[Dict[str, Any]]) -> List[str]:
        regions: List[str] = []
        for day in daily_plans or []:
            if day.get("region"):
                regions.append(str(day["region"]).strip())
            for item in day.get("items") or []:
                region = str(item.get("region") or "").strip()
                if region:
                    regions.append(region)
        return [region for region in regions if region]

    def _pick_primary_region(self, itinerary_summary: Dict[str, Any]) -> Optional[str]:
        daily_plans = itinerary_summary.get("daily_plans") or []
        regions = self._extract_regions_from_daily_plans(daily_plans)
        if not regions:
            return None
        return Counter(regions).most_common(1)[0][0]

    def _answer_side_question(
        self,
        session: SessionContext,
        user_message: str,
        context: ExecutionContext,
    ) -> str:
        snapshot = session.committed_trip_snapshot
        plan_summary = snapshot.plan_summary if snapshot and snapshot.plan_summary else {}
        itinerary_summary = plan_summary.get("itinerary") or {}
        budget_summary = plan_summary.get("budget") or {}
        attraction_summary = plan_summary.get("attraction") or {}
        weather_summary = plan_summary.get("weather") or {}
        question = str(user_message or "").strip()
        destination = snapshot.destination if snapshot and snapshot.destination else "这版行程"
        daily_plans = itinerary_summary.get("daily_plans") or []

        if question in {"谢谢", "多谢", "谢啦"}:
            return "不客气。如果你想，我也可以继续把这版行程再往美食、拍照或少走路的方向细调。"

        if "交通" in question or "方便吗" in question:
            cross_region_days = 0
            for day in daily_plans:
                day_regions = set(self._extract_regions_from_daily_plans([day]))
                if len(day_regions) > 1:
                    cross_region_days += 1
            primary_region = self._pick_primary_region(itinerary_summary)
            day_count = len(daily_plans)
            if day_count:
                if cross_region_days <= max(1, day_count // 2):
                    direct = "就你刚刚这版行程来说，整体交通还是比较方便的。"
                    if primary_region:
                        if cross_region_days == 0:
                            reason1 = f"大部分点位都在 {primary_region} 这一带，基本不用来回跨区。"
                        else:
                            reason1 = f"大部分点位都在 {primary_region} 附近，只有 {cross_region_days} 天会稍微跨区跑一下。"
                    else:
                        if cross_region_days == 0:
                            reason1 = "从每天的分区看，点位排得比较集中，基本不用来回换区。"
                        else:
                            reason1 = f"从每天的分区看，点位排得比较集中，只有 {cross_region_days} 天会跨区移动。"
                    reason2 = "按地铁配合短距离打车走，衔接一般没问题。"
                    advice = "如果你更在意少换乘/更顺路，我也可以把跨区那天的动线再压一压。"
                    follow = "你更在意少走路，还是少换乘？"
                    return f"{direct}{reason1}{reason2}{advice}{follow}"

                direct = "就你刚刚这版行程来说，能走通，但会稍微有点折腾。"
                if primary_region:
                    reason1 = f"这版里大概有 {cross_region_days} 天需要跨区跑，通勤时间会多一点。"
                    reason2 = f"把住宿放在 {primary_region} 或地铁枢纽附近，会省不少时间。"
                else:
                    reason1 = f"从每天的分区看，跨区的天数偏多（约 {cross_region_days} 天），通勤时间会拉长。"
                    reason2 = "如果你希望更省心，优先选地铁沿线/交通枢纽附近的住宿会更稳。"
                advice = "要是你想更顺路，我可以把跨区最折腾的那一天重新排一下，尽量把同一区域的点挪到同一天。"
                follow = "要不要我顺手把交通最折腾的那一天再优化一下？"
                return f"{direct}{reason1}{reason2}{advice}{follow}"

            direct = f"就你刚刚这版 {destination} 来看，整体交通是能比较顺地走下来的。"
            reason1 = "我这边暂时没拿到每天分区的细节，但核心点位看起来不会特别分散。"
            reason2 = "一般按地铁+短打车的方式走，会更省心。"
            advice = "如果你想尽量少换乘，我也可以按地铁线路把动线再微调一下。"
            follow = "你更在意少走路，还是少换乘？"
            return f"{direct}{reason1}{reason2}{advice}{follow}"

        if any(key in question for key in ("会不会太赶", "太赶", "赶不赶", "节奏紧不紧", "节奏怎么样")):
            day_count = len(daily_plans)
            core_counts: List[int] = []
            has_breaks = False
            for day in daily_plans:
                items = day.get("items") or []
                core = 0
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    category = str(item.get("category") or "").strip()
                    if category == "rest" or name in {"午餐 / 休息", "晚餐 / 休息"}:
                        has_breaks = True
                        continue
                    if name == "备选景点（未排入）":
                        continue
                    core += 1
                core_counts.append(core)

            max_core = max(core_counts) if core_counts else 0
            avg_core = round(sum(core_counts) / max(len(core_counts), 1), 1) if core_counts else 0
            cross_region_days = 0
            for day in daily_plans:
                day_regions = set(self._extract_regions_from_daily_plans([day]))
                if len(day_regions) > 1:
                    cross_region_days += 1

            if day_count and max_core <= 2 and cross_region_days <= max(1, day_count // 2):
                direct = "就你刚刚这版行程来说，节奏不算赶，属于比较舒服的强度。"
            elif day_count and max_core <= 3 and cross_region_days <= max(1, day_count // 2):
                direct = "就你刚刚这版行程来说，节奏偏适中，不会特别赶。"
            else:
                direct = "就你刚刚这版行程来说，整体能玩下来，但节奏会稍微紧一点。"

            if day_count:
                reason1 = f"大多数天大概是 {avg_core} 个主要点位左右"
                reason1 += "，中间也留了午餐/休息。" if has_breaks else "。"
                reason2 = f"另外大概有 {cross_region_days} 天会跨区移动，赶时间时主要就耗在路上。"
            else:
                reason1 = "我目前没拿到每天的点位细节，但行程可以按“少点位+多机动”的思路来放松节奏。"
                reason2 = "如果你希望更轻松，我可以把每天的点位再收一收。"

            advice = "要是你担心太赶，我可以把最满的那天减少一个点，或者把跨区那天拆得更顺一点。"
            follow = "你更想每天少一个景点，还是尽量少跨区/少换乘？"
            return f"{direct}{reason1}{reason2}{advice}{follow}"

        if any(key in question for key in ("累不累", "会不会累", "会很累吗", "体力", "走路多吗")):
            day_count = len(daily_plans)
            core_counts: List[int] = []
            has_breaks = False
            for day in daily_plans:
                items = day.get("items") or []
                core = 0
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    category = str(item.get("category") or "").strip()
                    if category == "rest" or name in {"午餐 / 休息", "晚餐 / 休息"}:
                        has_breaks = True
                        continue
                    if name == "备选景点（未排入）":
                        continue
                    core += 1
                core_counts.append(core)

            max_core = max(core_counts) if core_counts else 0
            cross_region_days = 0
            for day in daily_plans:
                day_regions = set(self._extract_regions_from_daily_plans([day]))
                if len(day_regions) > 1:
                    cross_region_days += 1

            if day_count and max_core <= 2 and cross_region_days <= max(1, day_count // 2):
                direct = "就你刚刚这版行程的强度来说，整体不会特别累，偏轻松。"
            else:
                direct = "就你刚刚这版行程的强度来说，能玩下来，但体力上会稍微有点累。"

            if day_count:
                reason1 = f"这版每天最多 {max_core} 个主要点位"
                reason1 += "，中间也安排了休息。" if has_breaks else "。"
                reason2 = f"如果跨区移动比较多（约 {cross_region_days} 天），那几天会更容易觉得累。"
            else:
                reason1 = "我现在没拿到每天点位细节，不过体力感受主要取决于“走路多不多”和“通勤长不长”。"
                reason2 = "你愿意的话，我可以把行程按少走路的思路再整理一版。"

            advice = "建议穿舒服的鞋，景点之间优先地铁+短打车，下午留一段弹性时间会更稳。"
            follow = "你更怕走路多，还是更怕来回坐车折腾？"
            return f"{direct}{reason1}{reason2}{advice}{follow}"

        if any(key in question for key in ("适合老人", "带老人", "长辈", "爸妈")):
            day_count = len(daily_plans)
            core_names: List[str] = []
            for day in daily_plans:
                for item in day.get("items") or []:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    category = str(item.get("category") or "").strip()
                    if category == "rest" or name in {"午餐 / 休息", "晚餐 / 休息", "备选景点（未排入）"}:
                        continue
                    if name:
                        core_names.append(name)

            strenuous_keywords = ("长城", "爬山", "登山", "徒步", "台阶", "爬坡")
            strenuous_pois = [name for name in core_names if any(k in name for k in strenuous_keywords)]

            direct = "就你刚刚这版行程来说，大体是适合带老人走的，但我建议把“少走路+多休息”放在第一位。"
            if day_count:
                reason1 = "这版每天点位不算多，中间也留了吃饭/休息的空档。"
            else:
                reason1 = "我现在没拿到每天点位细节，不过可以按更慢、更省体力的节奏来走。"
            if strenuous_pois:
                poi_name = strenuous_pois[0]
                reason2 = f"另外像「{poi_name}」这类台阶/爬坡比较多的点，老人可能会更吃力一些。"
                advice = "如果你愿意，我可以把这类强体力的点换成更平坦、出入口更友好的景点，并把当天动线调得更顺。"
                follow = "老人这边膝盖/走路方便吗？要不要我直接把那天改成更轻松的版本？"
                return f"{direct}{reason1}{reason2}{advice}{follow}"

            reason2 = "出行上尽量用地铁配合短打车，住宿选在地铁口附近，会省很多力气。"
            advice = "如果你告诉我老人更怕走路还是更怕早起，我可以按这个把节奏再调松一点。"
            follow = "你更想少走路，还是晚一点出门也可以？"
            return f"{direct}{reason1}{reason2}{advice}{follow}"

        if any(key in question for key in ("贵不贵", "值不值", "门票", "票价", "预算够", "预算够吗", "预算够不够", "预算够用")):
            total_budget = budget_summary.get("total_budget")
            budget_limit = budget_summary.get("budget_limit") or (snapshot.budget_amount if snapshot else None)
            budget_breakdown = budget_summary.get("budget_breakdown") or {}
            ticket_cost = budget_summary.get("ticket_cost")
            if ticket_cost is None and isinstance(budget_breakdown, dict):
                ticket_cost = budget_breakdown.get("ticket")
            pending_ticket_count = int(budget_summary.get("pending_ticket_count") or 0)

            if "门票" in question or "票价" in question:
                if isinstance(ticket_cost, (int, float)) and isinstance(total_budget, (int, float)) and total_budget > 0:
                    share = float(ticket_cost) / float(total_budget)
                    if share < 0.2:
                        direct = "就你刚刚这版行程来说，门票这块不会是大头，整体不算贵。"
                    elif share < 0.35:
                        direct = "就你刚刚这版行程来说，门票会占一部分，但还在可控范围内。"
                    else:
                        direct = "就你刚刚这版行程来说，门票占比会偏高一点，可能会有点肉疼。"
                    reason1 = f"按这版预算估算，门票大概 {ticket_cost:.0f} 元（总预算约 {total_budget:.0f} 元）。"
                elif isinstance(ticket_cost, (int, float)):
                    direct = "就你刚刚这版行程来说，门票整体在可控范围内。"
                    reason1 = f"按这版预算估算，门票大概 {ticket_cost:.0f} 元左右。"
                else:
                    direct = "就你刚刚这版行程来说，门票贵不贵主要看景点组合。"
                    reason1 = "我这边暂时没拿到完整的门票估算明细。"

                if pending_ticket_count:
                    reason2 = f"其中有 {pending_ticket_count} 个点的票价我先按保守值估了下，实际可能会略有浮动。"
                else:
                    reason2 = "如果你愿意，我也可以把每个景点的门票区间顺手标出来，方便你心里更有数。"

                advice = "想省一点的话，我可以优先把高门票的点换成免费/性价比更高的替代，或者帮你看看有没有通票/预约免费的组合。"
                follow = "你更想省门票，还是更在意体验别缩水？"
                return f"{direct}{reason1}{reason2}{advice}{follow}"

            if isinstance(total_budget, (int, float)) and isinstance(budget_limit, (int, float)):
                if total_budget <= budget_limit * 0.85:
                    direct = "就你刚刚这版行程来说，预算是够的，而且还比较宽松。"
                elif total_budget <= budget_limit:
                    direct = "就你刚刚这版行程来说，预算基本够用，属于贴着预算走的那种。"
                else:
                    direct = "就你刚刚这版行程来说，可能会略超一点预算。"
                reason1 = f"按这版估算总花费约 {total_budget:.0f} 元，你给的预算是 {budget_limit:.0f} 元。"

                reason2 = ""
                if isinstance(budget_breakdown, dict):
                    cn_map = {"hotel": "住宿", "ticket": "门票", "transport": "交通", "food": "吃饭", "other": "其他"}
                    parts = [
                        (key, float(value))
                        for key, value in budget_breakdown.items()
                        if key in cn_map and isinstance(value, (int, float))
                    ]
                    parts = sorted(parts, key=lambda x: x[1], reverse=True)[:2]
                    if parts:
                        top_text = "、".join(f"{cn_map.get(key, key)}约 {value:.0f} 元" for key, value in parts)
                        reason2 = f"里面占比比较大的通常是 {top_text}。"

                if total_budget > budget_limit:
                    advice = "如果你想把它压回预算内，我可以优先从住宿档位、门票组合或跨区交通这三块帮你省下来一部分。"
                    follow = "你更愿意从哪一块省：住宿、门票还是交通？"
                else:
                    advice = "如果你想花得更值，我也可以把预算重点放到你更在意的部分（比如住得舒服点/门票换更经典的）。"
                    follow = "你更在意住得舒服一点，还是景点更经典一点？"
                return f"{direct}{reason1}{reason2}{advice}{follow}"

            if isinstance(total_budget, (int, float)):
                direct = "就你刚刚这版行程来说，整体花费不算离谱。"
                reason1 = f"这版估算总花费大约 {total_budget:.0f} 元左右。"
                advice = "如果你告诉我你的预算上限，我可以立刻帮你把行程压到那个范围内。"
                follow = "你大概想控制在多少预算？"
                return f"{direct}{reason1}{advice}{follow}"

            return "就你刚刚这版行程来说，花费高不高主要取决于住宿档位、门票组合和交通方式。你给我一个预算上限，我可以帮你快速算一版更贴合的。你更想省门票，还是省住宿？"

        if "下雨" in question or "室内还是室外" in question:
            poi_list = attraction_summary.get("poi_list") or []
            indoor_count = sum(1 for poi in poi_list if str(poi.get("indoor_outdoor") or "").lower() == "indoor")
            outdoor_count = sum(1 for poi in poi_list if str(poi.get("indoor_outdoor") or "").lower() == "outdoor")
            if indoor_count >= outdoor_count:
                return "如果下雨，我会更建议优先室内。这版本身就有一些博物馆和室内点位，临场替换会更顺。"
            return "如果下雨，我还是更建议优先室内，再把西湖、湿地这类更吃天气的点位留给不下雨的时段。"

        if "住哪个区域" in question or "住哪" in question or "推荐住哪" in question:
            primary_region = self._pick_primary_region(itinerary_summary)
            if primary_region:
                return f"按这版行程，住在 {primary_region} 会更方便，能把主要景点和吃饭动线尽量压在一片区域里。"
            return f"如果你想住得更省心，我建议优先选这版 {destination} 行程里出现频率最高的核心活动区附近。"

        if "衣服" in question or "穿什么" in question or "需要带什么" in question:
            packing_list = weather_summary.get("packing_list") or []
            if packing_list:
                packing_text = "、".join(str(item) for item in packing_list[:4])
                return f"按现在这版天气建议，优先带上 {packing_text}。出发前一天再看一次实时温度会更稳。"
            return "衣服最好按可叠穿来准备，舒适步行鞋和一件方便增减的外套基本都用得上。"

        return f"我先按当前这版 {destination} 行程理解：整体是能继续细化的。如果你愿意，我可以直接基于这版再给你一个更具体的建议。"

    def _build_follow_up_lead_in(
        self,
        user_message: str,
        extracted_info: Dict[str, Any],
        session: SessionContext,
    ) -> str:
        destination = extracted_info.get("destination") or session.trip_context.destination or "这版"
        preferences = set(extracted_info.get("preferences") or [])
        interests = set(extracted_info.get("interests") or [])

        if {"food", "local_food"} & preferences or {"美食", "当地美食"} & interests:
            return f"好，我把这版 {destination} 行程往更偏美食的方向调了一下，尽量把更适合吃本地味道的点位和餐食安排串进去。下面给你更新版。"
        if {"photo", "photogenic"} & preferences or {"拍照", "摄影"} & interests:
            return f"好，我把这版 {destination} 行程里更适合拍照出片的权重提上来了，会优先保留更适合取景和卡时间段的点位。下面给你更新版。"
        if {"less_walking", "relaxed_pace"} & preferences or extracted_info.get("pace") == "relaxed":
            return f"好，我把这版 {destination} 行程往更轻松、少走路的方向收了一下，尽量减少来回折返。下面给你更新版。"
        if extracted_info.get("budget_amount") is not None and "预算" in user_message:
            return f"好，我按你新的预算重新校了一版，把整体花费和安排重新对齐后再给你更新方案。"
        return f"好，我按你刚补充的偏好把这版 {destination} 行程重新调了一下。下面给你更新版。"

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
        if interests := info.get("interests"):
            interests_str = ", ".join(interests) if isinstance(interests, list) else str(interests)
            lines.append(f"  - 🧩 偏好: {interests_str}")
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
            session.preferences.travel_style = []
            session.preferences.interests = []
            session.preferences.special_requirements = []
            session.preferences.pace_preference = "moderate"

        self._persist_partial_trip_context(session, extracted_info)

        # 更新预算
        if budget_level := extracted_info.get("budget_level"):
            session.preferences.budget_level = budget_level

        if tourist_type := extracted_info.get("tourist_type"):
            session.preferences.tourist_type = str(tourist_type).strip()

        if group_type := extracted_info.get("group_type"):
            session.preferences.group_type = str(group_type).strip()

        # 更新旅行风格
        if styles := extracted_info.get("travel_styles"):
            if isinstance(styles, list):
                session.preferences.travel_style = self._merge_string_lists(
                    session.preferences.travel_style,
                    styles,
                )

        if interests := extracted_info.get("interests"):
            session.preferences.interests = self._merge_string_lists(
                session.preferences.interests,
                interests,
            )

        if special_requirements := extracted_info.get("special_requirements"):
            session.preferences.special_requirements = self._merge_string_lists(
                session.preferences.special_requirements,
                special_requirements,
            )

        if pace := extracted_info.get("pace"):
            session.preferences.pace_preference = str(pace).strip()

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
        if self._looks_like_side_question(user_message, session):
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

    def _looks_like_side_question(
        self,
        user_message: str,
        session: SessionContext,
    ) -> bool:
        text = str(user_message or "").strip()
        if not text:
            return False
        if session.is_side_question(text):
            return True
        if not session.has_committed_trip():
            return False

        side_question_hints = (
            "交通", "方便吗", "贵不贵", "值不值", "住哪", "住哪个区域",
            "推荐住哪", "下雨怎么办", "如果下雨", "需要带什么", "穿什么", "天气",
        )
        if any(hint in text for hint in side_question_hints):
            return True

        looks_like_question = ("？" in text) or ("?" in text) or text.endswith("吗")
        if looks_like_question and not session.is_follow_up_message(text):
            lightweight_hints = ("预算", "交通", "酒店", "区域", "下雨", "住", "方便")
            return any(hint in text for hint in lightweight_hints)

        return False

    def _is_clarification_answer(
        self,
        user_message: str,
        latch: "PendingClarificationLatch",
    ) -> bool:
        """【本轮新增】检测消息是否是 clarification 的回答"""
        missing = set(latch.missing_slots)
        msg = user_message.strip()

        # 检查是否是数字类槽位回答
        if ("travel_time" in missing or "duration" in missing) and self._extract_duration_from_text(msg) is not None:
            return True

        if ("budget" in missing) and self._extract_budget_amount_from_text(msg) is not None:
            return True

        if ("people" in missing) and self._extract_num_travelers_from_text(msg) is not None:
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
        extracted: Dict[str, Any] = {}
        missing = set(latch.missing_slots)
        msg = user_message.strip()

        if "travel_time" in missing or "duration" in missing:
            duration = self._extract_duration_from_text(msg)
            if duration is not None:
                extracted["duration"] = duration

        if "budget" in missing:
            budget_amount = self._extract_budget_amount_from_text(msg)
            if budget_amount is not None:
                extracted["budget_amount"] = budget_amount
                extracted["budget"] = int(budget_amount) if float(budget_amount).is_integer() else budget_amount

        if "people" in missing:
            num_travelers = self._extract_num_travelers_from_text(msg)
            if num_travelers is not None:
                extracted["num_travelers"] = num_travelers

        return extracted

    def _merge_slots_for_full_new_plan(
        self,
        explicit_info: Dict[str, Any],
        committed_snapshot: Optional["CommittedTripSnapshot"],
        session: SessionContext,
    ) -> Dict[str, Any]:
        """
        【本轮新增】FULL_NEW_PLAN 的 slot 合并
        优先级: 当前消息显式值 > 当前消息解析值
        FULL_NEW_PLAN 不回填旧快照核心槽位。
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

        # 3. FULL_NEW_PLAN 禁止旧快照回填核心槽位，避免静默继承旧预算/旧天数。

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
        session: SessionContext,
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
            merged["num_travelers"] = committed_snapshot.people_count
            merged["preferences"] = list(committed_snapshot.preferences) if committed_snapshot.preferences else []
        if session.preferences.interests:
            merged["interests"] = list(session.preferences.interests)
        if session.preferences.travel_style:
            merged["travel_styles"] = list(session.preferences.travel_style)
        if session.preferences.special_requirements:
            merged["special_requirements"] = list(session.preferences.special_requirements)
        if getattr(session.preferences, "pace_preference", None):
            merged["pace"] = session.preferences.pace_preference

        # 2. follow-up delta 覆盖
        for key, value in follow_up_delta.items():
            if value is not None:
                if key == "duration":
                    merged["duration_days"] = value
                    merged["duration"] = value
                elif key == "budget":
                    merged["budget_amount"] = value
                    merged["budget"] = value
                elif key == "budget_amount":
                    merged["budget_amount"] = value
                    merged["budget"] = value
                else:
                    merged[key] = value

        # 3. 处理偏好增强
        for list_key in ["preferences", "interests", "travel_styles", "special_requirements"]:
            merged[list_key] = self._merge_string_lists(
                merged.get(list_key),
                follow_up_delta.get(list_key),
            )

        logger.info(
            f"[MULTITURN_TRACE] Merge for FOLLOW_UP: "
            f"destination={merged.get('destination')} "
            f"duration={merged.get('duration_days')} "
            f"budget={merged.get('budget_amount')} "
            f"preferences={merged.get('preferences')} "
            f"interests={merged.get('interests')}"
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
