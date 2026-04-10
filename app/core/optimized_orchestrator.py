"""
优化版 Agent 编排器
减少 LLM 调用次数，提高缓存命中率
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from app.agents.base import AgentResponse, AgentStatus, BaseAgent
from app.agents.registry import get_registry
from app.core.agent_cache import AgentRequestCache, get_agent_cache, CachedAgentResult
from app.core.context import ExecutionContext, SessionContext
from app.core.llm.client import LLMManager, LLMMessage, ToolDefinition
from app.core.llm.emotion_detector import emotion_detector, EmotionDetector
from app.core.llm.mode_detector import mode_detector, DialogModeDetector
from app.core.logger import get_logger
from app.schemas import (
    DialogMode, EmotionSchema, IntentType, ModeContext, PlanSchema, TaskSchema,
)

logger = get_logger(__name__)


class OptimizedAgentOrchestrator:
    """
    优化版 Agent 编排器
    1. 优先使用规则解析意图，减少 LLM 调用
    2. 添加 Agent 结果缓存
    3. 支持并行 Agent 结果复用
    4. 合并相似任务减少调用次数
    """

    def __init__(
        self,
        llm: LLMManager,
        cache: Optional[AgentRequestCache] = None,
    ):
        self.llm = llm
        self.cache = cache or get_agent_cache()

        # 复用原有的模式检测
        self.mode_detector = mode_detector
        self.emotion_detector = emotion_detector

        # Agent 实例
        self._agent_instances: Dict[str, BaseAgent] = {}
        self._registry = get_registry()

        # 意图解析器（使用规则优先）
        self._use_llm_intent_parsing = True  # 可配置

        logger.info("OptimizedAgentOrchestrator initialized with caching support")

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
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理用户请求（优化版）
        """
        request_id = request_id or str(uuid.uuid4())

        try:
            # ========== 阶段 0: 模式检测 ==========
            mode_context = ModeContext(
                current_mode=forced_mode or DialogMode.PLANNING,
                mode_confidence=1.0,
                mode_reasoning="Default mode",
            )
            emotion = emotion_detector.detect(user_message)

            yield {
                "phase": "mode_detection",
                "status": "completed",
                "mode": mode_context.current_mode.value,
                "emotion": emotion.emotion.value,
            }

            # ========== 规划模式处理 ==========
            async for result in self._handle_planning_optimized(
                session, user_message, request_id, emotion
            ):
                yield result

        except Exception as e:
            logger.exception(f"Optimized orchestration failed: {e}")
            yield {
                "phase": "error",
                "status": "failed",
                "error": str(e),
            }

    async def _handle_planning_optimized(
        self,
        session: SessionContext,
        user_message: str,
        request_id: str,
        emotion,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        优化版规划处理
        1. 使用规则优先解析意图
        2. 检查缓存
        3. 合并子 Agent 执行
        """
        context = ExecutionContext(
            request_id=request_id,
            session_id=session.session_id,
            user_id=session.user_id,
        )

        start_time = time.time()

        # ========== 阶段 1: 意图解析（规则优先）==========
        yield {
            "phase": "intent_parsing",
            "status": "running",
            "message": "正在分析...",
        }

        intent, extracted_info = self._fast_intent_parse(user_message, session)

        # 如果规则解析置信度低，使用 LLM
        if intent == IntentType.UNKNOWN or not extracted_info.get("destination"):
            if self._use_llm_intent_parsing:
                intent, extracted_info = await self._llm_intent_parse(
                    user_message, session
                )

        context.extracted_info = extracted_info
        logger.info(f"Intent parsed: {intent.value}, info: {extracted_info}")

        yield {
            "phase": "intent_parsing",
            "status": "completed",
            "intent": intent.value,
            "extracted_info": extracted_info,
        }

        # 更新会话
        self._update_session_context(session, extracted_info)

        # ========== 阶段 2: 检查缓存 ==========
        cache_hit = False
        cached_result = None

        for agent_name in ["attraction", "weather", "itinerary", "budget", "planner"]:
            cached = self.cache.get(
                agent_name=agent_name,
                intent_type=intent.value,
                extracted_info=extracted_info,
            )
            if cached:
                cached_result = cached
                cache_hit = True
                logger.info(f"Cache hit for {agent_name}")

                # 直接返回缓存结果
                yield {
                    "phase": "cache_hit",
                    "status": "completed",
                    "agent": agent_name,
                    "content": cached.content,
                    "tokens_saved": cached.tokens_saved,
                    "cache_age": cached.age_seconds,
                }
                break

        if cache_hit:
            elapsed_time = (time.time() - start_time) * 1000
            yield {
                "phase": "completed",
                "status": "completed",
                "content": cached_result.content,
                "cache_hit": True,
                "execution_time_ms": elapsed_time,
            }
            return

        # ========== 阶段 3: 优化执行 ==========
        yield {
            "phase": "execution",
            "status": "running",
            "message": "正在生成规划...",
        }

        # 获取 Planner 执行
        planner = self.get_agent("planner")
        streaming_content = ""

        if planner:
            async for result in planner.execute_stream(session, context):
                if isinstance(result, str):
                    streaming_content += result
                    yield {
                        "phase": "streaming",
                        "status": "running",
                        "content": streaming_content,
                        "is_streaming": True,
                    }
                else:
                    # Planner 执行完成
                    # 缓存结果
                    if result.content:
                        self.cache.set(
                            agent_name="planner",
                            intent_type=intent.value,
                            extracted_info=extracted_info,
                            content=result.content,
                            data=result.data,
                        )

                    elapsed_time = (time.time() - start_time) * 1000

                    yield {
                        "phase": "completed",
                        "status": "completed",
                        "content": streaming_content or result.content,
                        "cache_hit": False,
                        "execution_time_ms": elapsed_time,
                        "tokens_used": result.tokens_used,
                    }

    def _fast_intent_parse(
        self,
        user_message: str,
        session: SessionContext,
    ) -> tuple[IntentType, Dict[str, Any]]:
        """
        快速意图解析 - 完全基于规则
        只有在规则无法确定时才返回 UNKNOWN
        """
        import re
        extracted_info: Dict[str, Any] = {}

        # 检测目的地
        destinations = [
            "杭州", "北京", "上海", "成都", "西安", "桂林", "深圳", "广州",
            "厦门", "丽江", "苏州", "南京", "武汉", "重庆", "青岛", "大连",
            "三亚", "昆明", "哈尔滨", "长沙", "天津", "郑州", "济南", "太原",
            "合肥", "福州", "南昌", "贵阳", "南宁", "海口", "拉萨", "兰州",
            "西宁", "银川", "乌鲁木齐", "呼和浩特", "沈阳", "长春", "石家庄"
        ]
        found_destination = None
        for dest in destinations:
            if dest in user_message:
                found_destination = dest
                break

        if found_destination:
            extracted_info["destination"] = found_destination

        # 检测天数
        days_match = re.search(r"(\d+)[天日]|[一二两三四五六七八九十]+天", user_message)
        if days_match:
            match = days_match.group(1) or days_match.group(0)
            if match.isdigit():
                extracted_info["duration"] = int(match)
            else:
                chinese_nums = {
                    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10
                }
                for cn, num in chinese_nums.items():
                    if cn in match:
                        extracted_info["duration"] = num
                        break

        # 检测人数
        people_match = re.search(r"(\d+)[个人位]", user_message)
        if people_match:
            extracted_info["num_travelers"] = int(people_match.group(1))

        # 检测预算
        budget_match = re.search(r"(\d+)(?:00)?[元块万]", user_message)
        if budget_match:
            amount = int(budget_match.group(1))
            if amount < 100:
                amount = amount * 100
            extracted_info["budget"] = amount
            if amount < 3000:
                extracted_info["budget_level"] = "economy"
            elif amount < 6000:
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
        if found_destination:
            if extracted_info.get("duration") or extracted_info.get("budget"):
                intent = IntentType.TRIP_PLANNING
            else:
                intent = IntentType.ATTRACTION_RECOMMENDATION
        else:
            intent = IntentType.UNKNOWN

        return intent, extracted_info

    async def _llm_intent_parse(
        self,
        user_message: str,
        session: SessionContext,
    ) -> tuple[IntentType, Dict[str, Any]]:
        """LLM 意图解析（仅在规则失败时调用）"""
        prompt = f"""分析用户输入，识别意图和关键信息。

意图类型：
- trip_planning: 综合旅游规划
- attraction_recommendation: 景点推荐
- itinerary_planning: 行程规划
- budget_control: 预算分析
- general_chat: 闲聊

提取信息：destination, duration, num_travelers, budget, budget_level, travel_styles

用户输入: {user_message}

输出 JSON 格式：{{"intent": "...", "extracted_info": {{...}}}}"""

        messages = [
            LLMMessage(role="system", content="你是一个JSON生成器，只输出JSON。"),
            LLMMessage(role="user", content=prompt),
        ]

        try:
            response = await self.llm.chat(messages)
            data = json.loads(response.content)
            intent_str = data.get("intent", "unknown")
            intent = IntentType(intent_str) if intent_str in [e.value for e in IntentType] else IntentType.UNKNOWN
            return intent, data.get("extracted_info", {})
        except Exception as e:
            logger.error(f"LLM intent parse failed: {e}")
            return IntentType.UNKNOWN, {}

    def _update_session_context(
        self,
        session: SessionContext,
        extracted_info: Dict[str, Any],
    ) -> None:
        """更新会话上下文"""
        if destination := extracted_info.get("destination"):
            session.trip_context.destination = destination
        if num := extracted_info.get("num_travelers"):
            session.trip_context.num_travelers = int(num)
        if budget_level := extracted_info.get("budget_level"):
            session.preferences.budget_level = budget_level
        if styles := extracted_info.get("travel_styles"):
            if isinstance(styles, list):
                session.preferences.travel_style = styles
        if duration := extracted_info.get("duration"):
            session.trip_context.duration_days = int(duration)

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return self.cache.get_stats()


# 合并执行器 - 单次 LLM 调用完成多个任务
class UnifiedAgentExecutor:
    """
    统一 Agent 执行器
    通过单次 LLM 调用完成多个子任务，减少调用次数
    """

    SYSTEM_PROMPT = """你是一个专业的旅游规划助手，可以同时完成景点推荐、行程规划、预算分析等多个任务。

你必须一次性输出所有任务的结果，不要分次输出。

输出格式：
## 景点推荐
[景点内容]

## 行程规划
[行程内容]

## 预算分析
[预算内容]

请确保每个部分都完整、专业。"""

    def __init__(self, llm: LLMManager):
        self.llm = llm

    async def execute_all(
        self,
        destination: str,
        duration: int,
        num_travelers: int,
        budget_level: str,
        travel_styles: List[str],
        session: SessionContext,
    ) -> Dict[str, str]:
        """
        执行所有子任务（单次 LLM 调用）

        Returns:
            Dict[str, str]: 各任务的执行结果
        """
        styles_str = ", ".join(travel_styles) if travel_styles else "综合"

        user_prompt = f"""请为以下旅行需求提供完整的规划方案：

**目的地**: {destination}
**天数**: {duration}天
**人数**: {num_travelers}人
**预算**: {budget_level}
**风格**: {styles_str}

请一次性输出以下所有内容：

## 景点推荐
推荐{destination}的5-8个景点，包括：
- 必去经典（Top 3）
- 特色景点
- 隐藏宝藏

## 行程规划
{duration}天行程安排，包括：
- 每日主题
- 景点顺序
- 用餐建议
- 交通指引

## 预算估算
详细的费用分解，包括：
- 各项费用占比
- 总预算范围
- 省钱技巧

## 实用贴士
- 行前准备
- 注意事项

请用 Markdown 格式输出，内容要丰富、美观。"""

        messages = [
            LLMMessage(role="system", content=self.SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

        try:
            response = await self.llm.chat(messages)

            # 解析结果
            results = self._parse_unified_response(response.content)

            return results
        except Exception as e:
            logger.error(f"Unified execution failed: {e}")
            return {}

    def _parse_unified_response(self, content: str) -> Dict[str, str]:
        """解析统一的响应内容"""
        results = {
            "attraction": "",
            "itinerary": "",
            "budget": "",
            "tips": "",
        }

        sections = content.split("## ")
        for section in sections:
            section = section.strip()
            if not section:
                continue

            lines = section.split("\n", 1)
            title = lines[0].lower()
            content_part = lines[1] if len(lines) > 1 else ""

            if "景点" in title:
                results["attraction"] = content_part
            elif "行程" in title:
                results["itinerary"] = content_part
            elif "预算" in title:
                results["budget"] = content_part
            elif "贴士" in title or "实用" in title:
                results["tips"] = content_part

        return results
