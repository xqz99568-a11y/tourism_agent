"""
Planner Agent
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.agents.base import AgentCapability, AgentConfig, AgentResponse, AgentStatus, BaseAgent
from app.core.context import ExecutionContext, SessionContext
from app.core.llm.client import LLMMessage
from app.core.logger import get_logger

logger = get_logger(__name__)


PLANNER_CONFIG = AgentConfig(
    name="planner",
    description="主规划 Agent，负责协调其他 Agent 并整合最终方案",
    instructions="""你是一位资深旅游规划专家。
输入中已经包含经过结构化整合、基础冲突检查和决策摘要的内容。
你的职责不是重新自由生成方案，而是基于这些已校验信息输出清晰、完整、自然的最终旅游建议，
并保留“为什么这么安排”的解释与风险提示。
""",
    capabilities=[
        AgentCapability.PLANNING,
        AgentCapability.REASONING,
        AgentCapability.EXECUTION,
    ],
    max_retries=3,
    timeout_seconds=60,
)


class PlannerAgent(BaseAgent):
    """负责接收用户请求、整合子 Agent 结果并生成最终规划。"""

    PLAN_ASSISTANT_TITLE = "旅游规划助手"
    STREAM_CANONICAL_PLAN_MARKER = "【最终规划正文】"

    GENERIC_ASSISTANT_MARKERS = (
        "您好！看起来您可能",
        "您好！我是您的智能旅行规划助手",
        "作为您的助手，我可以帮助解答各种问题",
        "请告诉我您具体需要了解什么",
        "请告诉我您想了解的内容或需要帮助的地方",
        "请告诉我您想了解的内容或需要解决的问题",
        "需要一些帮助或信息",
    )

    DAY_EMOJIS = {
        1: "1️⃣",
        2: "2️⃣",
        3: "3️⃣",
        4: "4️⃣",
        5: "5️⃣",
        6: "6️⃣",
        7: "7️⃣",
        8: "8️⃣",
        9: "9️⃣",
        10: "🔟",
    }
    WEATHER_SOURCE_PATTERNS = (
        r"^\s*[-*]?\s*数据来源[:：].*$",
        r"^\s*[-*]?\s*天气来源[:：].*$",
        r"^\s*[-*]?\s*来源[:：].*QWeather.*$",
        r"^\s*[-*]?\s*天气类型[:：].*$",
        r"^\s*[-*]?\s*风险等级[:：].*$",
        r"^\s*[-*]?\s*weather_type[:：=].*$",
        r"^\s*[-*]?\s*risk_level[:：=].*$",
    )

    def __init__(self, llm=None, **kwargs):
        super().__init__(PLANNER_CONFIG, llm)

    async def plan(self, session: SessionContext, context: ExecutionContext) -> List[str]:
        tasks: List[str] = []
        extracted = context.extracted_info

        if extracted.get("destination"):
            tasks.append("search_attractions")
        if extracted.get("duration") or extracted.get("start_date"):
            tasks.append("plan_itinerary")
        if (
            extracted.get("budget_amount") is not None
            or extracted.get("budget_level")
            or extracted.get("budget")
        ):
            tasks.append("analyze_budget")
        if extracted.get("start_date"):
            tasks.append("check_weather")

        logger.info(f"Planner tasks: {tasks}")
        return tasks

    async def execute(self, session: SessionContext, context: ExecutionContext) -> AgentResponse:
        destination = context.extracted_info.get("destination", "未知目的地")
        # 【修复】不允许使用默认值，必须明确获取天数
        duration = context.extracted_info.get("duration")
        if duration is None:
            raise ValueError("行程天数缺失，无法生成正式规划。请先确认行程天数。")
        num_travelers = context.extracted_info.get("num_travelers", 2)
        budget = self._resolve_budget_summary(session, context)
        travel_styles = context.extracted_info.get("travel_styles", ["休闲"])

        planner_context = self._build_planner_context(session, context)
        self._record_thinking_steps(context, destination, duration, num_travelers, budget, travel_styles, planner_context)
        final_content = planner_context["final_content"]

        try:
            self._record_thinking_reasoning(
                context,
                step_name="结构拼装",
                reasoning_content=(
                    "Planner 不再调用 LLM 重写完整方案，"
                    "仅按 attraction → itinerary → budget → weather 的固定顺序整合已有内容。"
                ),
                reasoning_type="decision",
            )
            self._record_thinking_reasoning(
                context,
                step_name="规划完成",
                reasoning_content=(
                    f"已完成结构化整合、冲突检查与最终拼装。\n"
                    f"识别风险 {len(planner_context['conflicts'])} 项，形成安排依据 {len(planner_context['planning_rationale'])} 条。"
                ),
                reasoning_type="decision",
            )
            return AgentResponse(
                agent_name=self.name,
                status=AgentStatus.COMPLETED,
                content=final_content,
                tokens_used=0,
                data=self._build_planner_result_data(planner_context),
                metadata={
                    "destination": destination,
                    "duration": duration,
                    "num_travelers": num_travelers,
                },
            )
        except Exception as e:
            logger.exception(f"Planner execution failed: {e}")
            self._record_thinking_complete(
                context,
                step_name="规划失败",
                result_summary=f"生成失败: {str(e)}",
            )
            return AgentResponse(agent_name=self.name, status=AgentStatus.FAILED, content="", error=str(e))

    async def execute_stream(
        self,
        session: SessionContext,
        context: ExecutionContext,
    ) -> AsyncGenerator[str, AgentResponse]:
        destination = context.extracted_info.get("destination", "未知目的地")
        # 【修复】不允许使用默认值，必须明确获取天数
        duration = context.extracted_info.get("duration")
        if duration is None:
            raise ValueError("行程天数缺失，无法生成正式规划。请先确认行程天数。")
        num_travelers = context.extracted_info.get("num_travelers", 2)
        budget = self._resolve_budget_summary(session, context)
        travel_styles = context.extracted_info.get("travel_styles", ["休闲"])

        planner_context = self._build_planner_context(session, context)
        self._record_thinking_steps(context, destination, duration, num_travelers, budget, travel_styles, planner_context)

        # 【本轮核心修复】用原生 LLM stream 渲染最终正文，不再从预拼文本做 chunk 切片
        llm_stream_prompt = self._build_llm_stream_prompt(
            session=session,
            context=context,
            planner_context=planner_context,
            destination=destination,
            duration=duration,
            num_travelers=num_travelers,
            budget=budget,
            travel_styles=travel_styles,
        )

        try:
            self._record_thinking_reasoning(
                context,
                step_name="原生流式生成",
                reasoning_content=(
                    "正在通过原生 LLM stream 渲染最终方案，内容来源于 attraction / itinerary / budget / weather "
                    "结构化事实，不再从预拼文本切 chunk。"
                ),
                reasoning_type="decision",
            )

            accumulated: List[str] = []
            # 【本轮修复】优先使用原生 LLM stream；若 LLM 未配置（如测试环境），优雅降级到 chunk 方式
            try:
                async for token in self.chat_stream(llm_stream_prompt):
                    accumulated.append(token)
                    yield token
            except (ValueError, TypeError) as llm_err:
                if "LLM not configured" in str(llm_err) or self.llm is None:
                    logger.warning(f"LLM not available, falling back to chunked output: {llm_err}")
                    final_fallback = planner_context["final_content"]
                    for chunk in self._iter_content_chunks(final_fallback):
                        accumulated.append(chunk)
                        yield chunk
                        await asyncio.sleep(0.03)
                else:
                    raise

            final_content = "".join(accumulated)

            self._record_thinking_reasoning(
                context,
                step_name="规划完成",
                reasoning_content=(
                    f"原生 LLM stream 渲染完成，已完成结构化整合、冲突检查与最终合成。\n"
                    f"识别风险 {len(planner_context['conflicts'])} 项，形成安排依据 {len(planner_context['planning_rationale'])} 条。"
                ),
                reasoning_type="decision",
            )

            yield AgentResponse(
                agent_name=self.name,
                status=AgentStatus.COMPLETED,
                content=final_content,
                tokens_used=0,
                data=self._build_planner_result_data(planner_context),
                metadata={"destination": destination, "duration": duration},
            )
        except Exception as e:
            logger.exception(f"Planner stream failed: {e}")
            self._record_thinking_complete(
                context,
                step_name="规划失败",
                result_summary=f"生成失败: {str(e)}",
            )
            yield AgentResponse(agent_name=self.name, status=AgentStatus.FAILED, content="", error=str(e))

    def _build_llm_stream_prompt(
        self,
        session: SessionContext,
        context: ExecutionContext,
        planner_context: Dict[str, Any],
        destination: str,
        duration: int,
        num_travelers: int,
        budget: str,
        travel_styles: List[str],
    ) -> List[LLMMessage]:
        """构建用于原生流式渲染的系统提示 + 用户消息。"""
        final_content = str(planner_context.get("final_content") or "").strip()
        system_prompt = f"""你是旅游规划助手的流式展示渲染器。
你的唯一任务，是把用户提供的最终旅游规划文本逐字输出为流式内容。

严格要求：
1. 必须逐字输出，不得增删改任何标题、emoji、Day 行、小标题、表格列名、标点、空行或换行
2. 不要补充解释、前言、后记、代码块、调试信息或字段名
3. 第一行必须是“{self.PLAN_ASSISTANT_TITLE}”
4. 第二行必须是“# 🧭 {destination} 旅行规划”
"""
        user_content = (
            "请从第一行开始，原样输出下面这份最终旅游规划，不要做任何改写。\n\n"
            f"{self.STREAM_CANONICAL_PLAN_MARKER}\n"
            f"{final_content}"
        )

        return [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_content),
        ]

    def build_progressive_draft(
        self,
        session: SessionContext,
        context: ExecutionContext,
        *,
        include_weather: bool = False,
    ) -> str:
        destination = context.extracted_info.get("destination", "目的地")
        duration = self._safe_int(context.extracted_info.get("duration"), default=3)
        num_travelers = self._safe_int(context.extracted_info.get("num_travelers"), default=1)
        progressive_context = self._build_progressive_context(session, context)
        structured_summary = progressive_context["structured_summary"]
        agent_results = progressive_context["agent_results"]
        conflicts = progressive_context["conflicts"]
        sanitized_contents = {
            agent_name: self._sanitize_agent_content(str(result.get("content") or ""))
            for agent_name, result in agent_results.items()
            if isinstance(result, dict)
        }
        has_attraction = context.has_result("attraction")
        has_itinerary = context.has_result("itinerary")
        has_budget = context.has_result("budget")
        has_weather = context.has_result("weather")

        sections = self._build_plan_sections(
            destination=destination,
            duration=duration,
            num_travelers=num_travelers,
            structured_summary=structured_summary,
            agent_results=agent_results,
            sanitized_contents=sanitized_contents,
            conflicts=conflicts,
            include_daily=has_attraction or has_itinerary or has_weather,
            include_budget=has_itinerary or has_budget or has_weather,
            include_tips=has_itinerary or has_budget or has_weather,
            include_weather=include_weather and has_weather,
            include_closing=has_budget and has_weather,
        )
        text = "\n\n".join(section for section in sections if section)
        text = self._strip_internal_display_fields(text)
        text = self._dedupe_consecutive_lines(text)
        return self._normalize_spacing(text)

    def build_streaming_prefix(
        self,
        session: SessionContext,
        context: ExecutionContext,
    ) -> str:
        """Build a stable prefix for /chat/stream so emitted text only grows by suffix."""
        destination = context.extracted_info.get("destination", "目的地")
        duration = self._safe_int(context.extracted_info.get("duration"), default=3)
        num_travelers = self._safe_int(context.extracted_info.get("num_travelers"), default=1)
        progressive_context = self._build_progressive_context(session, context)
        structured_summary = progressive_context["structured_summary"]
        agent_results = progressive_context["agent_results"]
        conflicts = progressive_context["conflicts"]
        sanitized_contents = {
            agent_name: self._sanitize_agent_content(str(result.get("content") or ""))
            for agent_name, result in agent_results.items()
            if isinstance(result, dict)
        }

        has_attraction = context.has_result("attraction")
        has_itinerary = context.has_result("itinerary")
        has_budget = context.has_result("budget")
        has_weather = context.has_result("weather")
        all_sections_ready = has_attraction and has_itinerary and has_budget and has_weather

        if all_sections_ready:
            return self._assemble_final_content(
                context=context,
                agent_results=agent_results,
                structured_summary=structured_summary,
                conflicts=conflicts,
            )

        if not (has_attraction and has_itinerary):
            return ""

        sections = self._build_plan_sections(
            destination=destination,
            duration=duration,
            num_travelers=num_travelers,
            structured_summary=structured_summary,
            agent_results=agent_results,
            sanitized_contents=sanitized_contents,
            conflicts=conflicts,
            include_daily=True,
            include_budget=has_budget,
            include_tips=True,
            include_weather=has_weather,
            include_closing=has_weather,
        )
        text = "\n\n".join(section for section in sections if section)
        text = self._strip_internal_display_fields(text)
        text = self._dedupe_consecutive_lines(text)
        return self._normalize_spacing(text)

    def _render_progressive_opening(
        self,
        destination: str,
        duration: int,
        budget: Any,
        travel_styles: List[str],
        structured_summary: Dict[str, Any],
    ) -> str:
        styles = "、".join(str(style).strip() for style in travel_styles if str(style).strip()) or "综合"
        profile = structured_summary.get("profile", {})
        if profile.get("relaxed_mode"):
            pace = "整体会优先控制单日节奏，尽量少折返，并给午间休息和机动调整留出空间。"
        else:
            pace = "整体会按经典主线串联重点区域，让每天都有明确主题，同时保留一定机动时间。"
        return (
            f"这次 {destination} {duration} 天游建议先按“每天一条主线、尽量少折返”的方式来安排，"
            f"预算先以 {budget} 为控制线，体验上兼顾 {styles}。{pace}"
        )

    def _render_progressive_daily_plan_section(
        self,
        destination: str,
        duration: int,
        structured_summary: Dict[str, Any],
    ) -> str:
        itinerary_data = structured_summary.get("itinerary", {}).get("data", {})
        plans = itinerary_data.get("daily_plans") or []
        if not isinstance(plans, list):
            plans = []
        days = max(duration, len(plans), 1)
        sections: List[str] = [f"## 📆 2️⃣ 每日行程骨架（{days}天）"]

        for day_index in range(days):
            plan = plans[day_index] if day_index < len(plans) and isinstance(plans[day_index], dict) else {}
            items = plan.get("items") if isinstance(plan.get("items"), list) else []
            non_rest_items = [
                item for item in items
                if isinstance(item, dict) and item.get("name") and item.get("category") != "rest"
            ]
            theme = str(plan.get("theme") or "").strip() or self._build_day_theme(destination, non_rest_items)
            region = str(plan.get("region") or self._first_non_empty_region(non_rest_items) or destination).strip()
            morning_text = self._render_progressive_day_slot(
                non_rest_items,
                "morning",
                region,
                f"先在 {region} 一带安排轻量热身或自由活动。",
            )
            afternoon_text = self._render_progressive_day_slot(
                non_rest_items,
                "afternoon",
                region,
                f"下午继续把 {region} 周边的主线点位串起来。",
            )
            evening_text = self._render_progressive_day_slot(
                non_rest_items,
                "evening",
                region,
                f"晚上适合在 {region} 周边慢逛、用餐或轻松收尾。",
            )
            sections.extend(
                [
                    "",
                    f"### Day {day_index + 1} - {theme}",
                    f"- 上午：{morning_text}",
                    f"- 下午：{afternoon_text}",
                    f"- 晚上：{evening_text}",
                    f"- 当日节奏：以 {region} 一带为主，减少反复换乘。",
                ]
            )

        return "\n".join(sections)

    def _render_progressive_day_slot(
        self,
        items: List[Dict[str, Any]],
        time_slot: str,
        region: str,
        fallback: str,
    ) -> str:
        slot_items = self._dedupe_day_items(items, time_slot)
        names = self._dedupe_preserve_order(
            [str(item.get("name") or "").strip() for item in slot_items if str(item.get("name") or "").strip()]
        )
        if not names:
            return fallback

        reason = self._clean_inline_text(slot_items[0].get("notes")) if slot_items else ""
        if reason:
            return f"{'、'.join(names)}，{reason}"
        return f"{'、'.join(names)}，优先围绕 {region} 周边顺路展开。"

    def _resolve_budget_summary(self, session: SessionContext, context: ExecutionContext) -> Any:
        budget_amount = context.extracted_info.get("budget_amount")
        budget_level = context.extracted_info.get("budget_level") or session.preferences.budget_level
        budget_text = context.extracted_info.get("budget")

        if isinstance(budget_amount, (int, float)):
            if budget_level:
                return f"{int(budget_amount)}元（{budget_level}）"
            return f"{int(budget_amount)}元"
        if isinstance(budget_amount, str) and budget_amount.strip():
            if budget_level:
                return f"{budget_amount.strip()}（{budget_level}）"
            return budget_amount.strip()
        if isinstance(budget_text, str) and budget_text.strip():
            return budget_text.strip()
        if budget_level:
            return budget_level
        return "中等"

    def _record_thinking_steps(
        self,
        context: ExecutionContext,
        destination: Any,
        duration: Any,
        num_travelers: Any,
        budget: Any,
        travel_styles: List[str],
        planner_context: Dict[str, Any],
    ) -> None:
        styles_text = ", ".join(travel_styles) if travel_styles else "综合"
        self._record_thinking_reasoning(
            context,
            step_name="理解需求",
            reasoning_content=(
                f"用户需求：去{destination}旅行{duration}天，{num_travelers}人，预算{budget}，风格：{styles_text}"
            ),
            reasoning_type="analysis",
        )
        self._record_thinking_reasoning(
            context,
            step_name="收集数据",
            reasoning_content="\n".join(planner_context["agent_status"]),
            reasoning_type="fact",
        )
        self._record_thinking_reasoning(
            context,
            step_name="规划策略",
            reasoning_content=planner_context["decision_summary"],
            reasoning_type="decision",
        )

    def _build_progressive_context(self, session: SessionContext, context: ExecutionContext) -> Dict[str, Any]:
        agent_results = self._collect_agent_results(context)
        structured_summary = self._build_structured_summary(session, context, agent_results)
        conflicts = self._check_conflicts(session, context, structured_summary)
        return {
            "agent_results": agent_results,
            "structured_summary": structured_summary,
            "conflicts": conflicts,
        }

    def _build_planner_context(self, session: SessionContext, context: ExecutionContext) -> Dict[str, Any]:
        progressive_context = self._build_progressive_context(session, context)
        agent_results = progressive_context["agent_results"]
        structured_summary = progressive_context["structured_summary"]
        conflicts = progressive_context["conflicts"]
        planning_rationale = self._build_planning_rationale(structured_summary, conflicts)
        decision_summary = self._build_decision_summary(structured_summary, conflicts, planning_rationale)
        other_results_text = self._build_other_results_text(agent_results)
        final_content = self._assemble_final_content(context, agent_results, structured_summary, conflicts)
        logger.info(
            f"Planner context summary request_id={getattr(context, 'request_id', '')} "
            f"sections={self._build_section_presence_summary(agent_results, structured_summary)} "
            f"final_content_len={len(final_content or '')}"
        )

        return {
            **progressive_context,
            "planning_rationale": planning_rationale,
            "decision_summary": decision_summary,
            "other_results_text": other_results_text,
            "final_content": final_content,
            "agent_status": self._build_agent_status(agent_results),
        }

    def _collect_agent_results(self, context: ExecutionContext) -> Dict[str, Dict[str, Any]]:
        results: Dict[str, Dict[str, Any]] = {}
        for agent_name in ["attraction", "itinerary", "budget", "weather"]:
            result = context.get_result(agent_name)
            if not result:
                continue
            results[agent_name] = {
                "content": result.content or "",
                "data": result.data or {},
                "status": result.status,
            }
        return results

    def _build_agent_status(self, agent_results: Dict[str, Dict[str, Any]]) -> List[str]:
        status_lines: List[str] = []
        for agent_name in ["attraction", "itinerary", "budget", "weather"]:
            if agent_name in agent_results:
                status_lines.append(f"{agent_name}：已完成")
            else:
                status_lines.append(f"{agent_name}：无结果")
        return status_lines

    def _assemble_final_content(
        self,
        context: ExecutionContext,
        agent_results: Dict[str, Dict[str, Any]],
        structured_summary: Optional[Dict[str, Any]] = None,
        conflicts: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        sanitized_contents: Dict[str, str] = {}
        content_lengths: Dict[str, int] = {}
        for agent_name in ["attraction", "itinerary", "budget", "weather"]:
            result = agent_results.get(agent_name)
            if not result:
                content_lengths[agent_name] = 0
                continue
            content = self._sanitize_agent_content(str(result.get("content") or ""))
            content_lengths[agent_name] = len(content)
            sanitized_contents[agent_name] = content

        destination = (
            str(context.extracted_info.get("destination") or context.extracted_info.get("city") or "").strip()
            or str((structured_summary or {}).get("weather", {}).get("data", {}).get("destination") or "").strip()
            or "目的地"
        )
        duration = self._safe_int(
            (structured_summary or {}).get("itinerary", {}).get("days"),
            default=self._safe_int(context.extracted_info.get("duration"), default=3),
        )
        num_travelers = self._safe_int(context.extracted_info.get("num_travelers"), default=1)

        final_content = self._render_rich_plan(
            destination=destination,
            duration=duration,
            num_travelers=num_travelers,
            structured_summary=structured_summary or {},
            agent_results=agent_results,
            sanitized_contents=sanitized_contents,
            conflicts=conflicts or [],
        )
        if final_content:
            return final_content

        fallback_parts = [
            sanitized_contents.get(agent_name, "")
            for agent_name in ["attraction", "itinerary", "budget", "weather"]
            if sanitized_contents.get(agent_name)
        ]
        if fallback_parts:
            fallback_text = "\n\n".join(fallback_parts)
            fallback_text = self._strip_internal_display_fields(fallback_text)
            fallback_text = self._dedupe_consecutive_lines(fallback_text)
            return self._normalize_spacing(fallback_text)
        logger.warning(
            f"Planner fallback triggered request_id={getattr(context, 'request_id', '')} "
            f"reason=no_nonempty_agent_content "
            f"content_lengths={content_lengths} "
            f"agent_statuses={self._build_agent_status(agent_results)}"
        )
        return "暂时没有可整合的旅行内容。"

    def _sanitize_agent_content(self, content: str) -> str:
        text = self._strip_internal_display_fields(str(content or "")).strip()
        if not text:
            return ""

        if not any(marker in text[:220] for marker in self.GENERIC_ASSISTANT_MARKERS):
            return text

        travel_start = re.search(
            r"(#{1,6}\s*(第[一二三四五六七八九十0-9]+天|预算|天气)|第[一二三四五六七八九十0-9]+天|Day\s*\d+|上午[:：]|中午[:：]|下午[:：]|晚上[:：])",
            text,
        )
        if travel_start and travel_start.start() > 0:
            return self._strip_internal_display_fields(text[travel_start.start():]).lstrip()

        return ""

    def _render_rich_plan(
        self,
        destination: str,
        duration: int,
        num_travelers: int,
        structured_summary: Dict[str, Any],
        agent_results: Dict[str, Dict[str, Any]],
        sanitized_contents: Dict[str, str],
        conflicts: List[Dict[str, str]],
    ) -> str:
        sections = self._build_plan_sections(
            destination=destination,
            duration=duration,
            num_travelers=num_travelers,
            structured_summary=structured_summary,
            agent_results=agent_results,
            sanitized_contents=sanitized_contents,
            conflicts=conflicts,
        )
        text = "\n\n".join(section for section in sections if section)
        text = self._strip_internal_display_fields(text)
        text = self._dedupe_consecutive_lines(text)
        return self._normalize_spacing(text)

    def _build_plan_sections(
        self,
        *,
        destination: str,
        duration: int,
        num_travelers: int,
        structured_summary: Dict[str, Any],
        agent_results: Dict[str, Dict[str, Any]],
        sanitized_contents: Dict[str, str],
        conflicts: List[Dict[str, str]],
        include_daily: bool = True,
        include_budget: bool = True,
        include_tips: bool = True,
        include_weather: bool = True,
        include_closing: bool = True,
    ) -> List[str]:
        sections = [
            f"{self.PLAN_ASSISTANT_TITLE}\n# 🧭 {destination} 旅行规划",
            self._render_overview_section(destination, structured_summary, agent_results, sanitized_contents),
        ]
        if include_daily:
            sections.append(self._render_daily_plan_section(destination, duration, structured_summary))
        if include_budget:
            sections.append(self._render_budget_section(duration, num_travelers, structured_summary, sanitized_contents))
        if include_tips:
            sections.append(self._render_tips_section(destination, duration, structured_summary, conflicts))
        if include_weather:
            sections.append(self._render_weather_section(structured_summary, sanitized_contents))
        if include_closing:
            sections.append(f"祝您旅途愉快！期待您的{destination}之行！")
        return [section for section in sections if section]

    def _render_overview_section(
        self,
        destination: str,
        structured_summary: Dict[str, Any],
        agent_results: Dict[str, Dict[str, Any]],
        sanitized_contents: Dict[str, str],
    ) -> str:
        attraction = structured_summary.get("attraction", {})
        profile = structured_summary.get("profile", {})
        attraction_data = agent_results.get("attraction", {}).get("data", {}) if isinstance(agent_results.get("attraction"), dict) else {}
        attraction_text = sanitized_contents.get("attraction", "")
        pois = attraction.get("pois") or []
        highlights = self._dedupe_preserve_order(
            [str(poi.get("name") or "").strip() for poi in pois if isinstance(poi, dict)]
        )[:4]
        regions = list(attraction.get("regions") or [])
        if not highlights:
            itinerary_plans = structured_summary.get("itinerary", {}).get("data", {}).get("daily_plans") or []
            for plan in itinerary_plans:
                if not isinstance(plan, dict):
                    continue
                items = plan.get("items") if isinstance(plan.get("items"), list) else []
                for item in items:
                    if not isinstance(item, dict) or item.get("category") == "rest":
                        continue
                    name = str(item.get("name") or "").strip()
                    region = str(item.get("region") or item.get("city") or "").strip()
                    if name:
                        highlights.append(name)
                    if region:
                        regions.append(region)
        highlight_text = "、".join(self._dedupe_preserve_order(highlights)[:3]) if highlights else f"{destination} 的老城街区与在地体验"
        region_text = "、".join(self._dedupe_preserve_order(regions)[:3]) if regions else f"{destination} 核心区域"
        attraction_summary = self._strip_internal_display_fields(
            str(attraction_data.get("attraction_summary") or "").strip()
        )
        if attraction_summary:
            intro = attraction_summary
        else:
            rhythm = "整体节奏偏舒适、少折返。" if profile.get("relaxed_mode") else "整体节奏兼顾经典打卡与灵活机动。"
            intro = f"{destination} 这次行程会围绕 {highlight_text} 展开，重点活动区域集中在 {region_text}，{rhythm}"

        best_season = self._extract_labeled_value(attraction_text, ["最佳旅行季节", "最佳季节"]) or "建议优先选择气温更舒适、便于长时间步行的时段出行。"
        climate = self._extract_labeled_value(attraction_text, ["气候特点"]) or "出行前建议再次确认实时天气，尤其留意早晚温差与降雨变化。"
        peak_offpeak = self._extract_labeled_value(attraction_text, ["淡旺季", "旺季", "避峰"]) or "节假日和热门景区周边通常更拥挤，工作日或错峰时段体验会更从容。"

        food_items = self._extract_section_items(attraction_text, ["必吃美食", "美食推荐", "当地美食"])
        if not food_items:
            food_items = self._build_food_items_from_pois(pois)
        if not food_items:
            food_items = [f"优先把 {destination} 的老街、夜市或口碑餐厅安排在午餐或夜游时段，体验更完整。"]

        souvenir_items = self._extract_section_items(attraction_text, ["必买特产", "特产推荐", "伴手礼"])
        if not souvenir_items:
            souvenir_items = [
                f"{destination} 的景区文创与博物馆文创适合作为轻量纪念品。",
                f"{destination} 的老街、夜市和综合商圈更适合集中挑选当地伴手礼。",
            ]

        # 【修复】构建可读的推荐景点概览，替代"高优先级 0 / 室内 0 / 室外 0"统计句
        poi_highlights = self._build_poi_highlights(pois, destination)

        food_lines = [f"- {item}" for item in self._dedupe_preserve_order(food_items)[:4]]
        souvenir_lines = [f"- {item}" for item in self._dedupe_preserve_order(souvenir_items)[:4]]

        return "\n".join(
            [
                "## 🌟 1️⃣ 目的地概览",
                intro,
                "",
                "### 📍 推荐景点速览",
                *poi_highlights,
                "",
                "### 🌸 最佳旅行季节",
                f"- ⭐ **最佳季节**：{best_season}",
                f"- 🌡️ **气候特点**：{climate}",
                f"- 🎫 **淡旺季**：{peak_offpeak}",
                "",
                "### 🍜 必吃美食",
                *food_lines,
                "",
                "### 🎁 必买特产",
                *souvenir_lines,
            ]
        )

    def _build_poi_highlights(self, pois: List[Dict[str, Any]], destination: str) -> List[str]:
        """构建可读的景点推荐概览，替代统计数字句。"""
        if not pois:
            return ["- 建议根据当地特色安排核心景点，建议咨询当地人或查看最新攻略。"]

        lines: List[str] = []
        shown_names: set = set()

        for poi in pois[:6]:
            if not isinstance(poi, dict):
                continue
            name = str(poi.get("name") or "").strip()
            if not name or name in shown_names:
                continue
            shown_names.add(name)

            # 收集标签和特征
            tags = poi.get("tags") or []
            if isinstance(tags, list):
                tags = [str(t).strip() for t in tags if str(t).strip()]
            category = str(poi.get("category") or "").strip()
            indoor_outdoor = str(poi.get("indoor_outdoor") or "").strip()
            description = str(poi.get("description") or "").strip()

            # 【修复】推断景点特色看点
            features: List[str] = []
            combined_text = " ".join([name, category, " ".join(tags), description, indoor_outdoor]).lower()

            if any(kw in combined_text for kw in ["博物馆", "美术馆", "展馆", "纪念馆"]):
                features.append("室内场馆")
            elif any(kw in combined_text for kw in ["公园", "湖", "河", "山", "景区", "古镇", "遗址"]):
                features.append("户外景区")
            if any(kw in combined_text for kw in ["夜景", "灯光", "夜游"]):
                features.append("夜景")
            if any(kw in combined_text for kw in ["文化", "历史", "古迹", "博物馆"]):
                features.append("文化")
            if any(kw in combined_text for kw in ["老街", "古镇", "古城", "胡同", "市井"]):
                features.append("老街")
            if any(kw in combined_text for kw in ["小吃", "美食", "夜市", "餐饮"]):
                features.append("美食")
            if any(kw in combined_text for kw in ["亲子", "家庭", "乐园"]):
                features.append("亲子")

            # 生成一句话特色描述
            if description and len(description) > 5:
                # 截取描述的前80个字符作为特色说明
                feature_text = description[:80].strip()
                if not feature_text.endswith(("。", ".", "！", "?")):
                    feature_text += "..."
            elif features:
                feature_map = {
                    "室内场馆": "适合了解当地历史与文化，室内为主，建议安排在上午或下午。",
                    "户外景区": "适合慢慢走、拍照，建议上午或傍晚前往体验最佳。",
                    "夜景": "灯光亮起时最美，建议傍晚或晚间前往。",
                    "文化": "有深厚文化底蕴，建议配合导览或提前做功课。",
                    "老街": "街区氛围浓郁，建议边走边吃边感受当地生活。",
                    "美食": "是品尝当地美食的好去处，建议安排在用餐时段。",
                    "亲子": "适合家庭出行，设施相对完善。",
                }
                # 取前两个特征
                key_features = features[:2]
                feature_text_parts = [feature_map.get(f, f) for f in key_features if f in feature_map]
                feature_text = " ".join(feature_text_parts) if feature_text_parts else f"{name}值得一去。"
            else:
                feature_text = f"{name}是当地特色景点，建议根据当天节奏灵活安排。"

            lines.append(f"- **{name}**：{feature_text}")

        # 【修复】如果所有 POI 都去重后为空，降级处理
        if not lines:
            lines = [f"- 建议根据当地特色安排{destination}核心景点，提前关注天气和人流。"]

        return lines

    def _render_daily_plan_section(
        self,
        destination: str,
        duration: int,
        structured_summary: Dict[str, Any],
    ) -> str:
        itinerary_data = structured_summary.get("itinerary", {}).get("data", {})
        weather_data = structured_summary.get("weather", {}).get("data", {})
        budget_data = structured_summary.get("budget", {})
        plans = itinerary_data.get("daily_plans") or []
        if not isinstance(plans, list):
            plans = []
        days = max(duration, len(plans), 1)
        food_pois = self._extract_food_pois(structured_summary.get("attraction", {}).get("pois") or [])
        used_food_names: List[str] = []
        sections: List[str] = [f"## 📆 2️⃣ 每日行程安排（{days}天）"]

        for day_index in range(days):
            plan = plans[day_index] if day_index < len(plans) and isinstance(plans[day_index], dict) else {}
            items = plan.get("items") if isinstance(plan.get("items"), list) else []
            non_rest_items = [
                item for item in items
                if isinstance(item, dict) and item.get("name") and item.get("category") != "rest"
            ]
            theme = str(plan.get("theme") or "").strip() or self._build_day_theme(destination, non_rest_items)
            region = str(plan.get("region") or self._first_non_empty_region(non_rest_items) or destination).strip()
            day_emoji = self.DAY_EMOJIS.get(day_index + 1, str(day_index + 1))
            morning_items = self._dedupe_day_items(non_rest_items, "morning")
            afternoon_items = self._dedupe_day_items(non_rest_items, "afternoon")
            evening_items = self._dedupe_day_items(non_rest_items, "evening")
            lunch_spot = self._pick_food_spot(region, food_pois, used_food_names)
            if lunch_spot:
                used_food_names.append(str(lunch_spot.get("name")))

            sections.extend(
                [
                    "",
                    f"Day {day_emoji} - {theme}",
                    self._render_day_slot("🌅 上午安排", morning_items, "09:00-11:30", region, "适合用来开启当天主线景点，避开后续高峰。"),
                    self._render_lunch_slot(lunch_spot, region, budget_data, destination),
                    self._render_day_slot("🌇 下午安排", afternoon_items, "14:00-17:00", region, "把同一区域景点放在同一时段，更省通勤时间。"),
                    self._render_day_slot("🌃 晚间活动", evening_items, "19:00-21:00", region, "晚间适合安排夜景、休闲散步或轻松收尾。"),
                    self._render_day_tips(region, non_rest_items, weather_data),
                ]
            )

        return "\n".join(sections)

    def _render_budget_section(
        self,
        duration: int,
        num_travelers: int,
        structured_summary: Dict[str, Any],
        sanitized_contents: Dict[str, str],
    ) -> str:
        budget = structured_summary.get("budget", {})
        total = self._coerce_float(budget.get("total_budget"))
        confirmed_total = self._coerce_float(budget.get("confirmed_total_cost"))
        if confirmed_total is None:
            confirmed_total = total
        transport = self._coerce_float(budget.get("transport_cost"))
        hotel = self._coerce_float(budget.get("hotel_cost"))
        food = self._coerce_float(budget.get("food_cost"))
        ticket = self._coerce_float(budget.get("ticket_cost"))
        confirmed_ticket = self._coerce_float(budget.get("confirmed_ticket_cost"))
        if confirmed_ticket is None:
            confirmed_ticket = ticket
        other = self._coerce_float(budget.get("other_cost"))
        buffer = self._coerce_float(budget.get("buffer_cost"))
        pending_ticket_count = self._safe_int(budget.get("pending_ticket_count"), default=0)
        free_ticket_count = self._safe_int(budget.get("free_ticket_count"), default=0)
        pending_ticket_pois = budget.get("pending_ticket_pois") if isinstance(budget.get("pending_ticket_pois"), list) else []
        has_pending_ticket_cost = bool(budget.get("has_pending_ticket_cost")) or pending_ticket_count > 0

        if has_pending_ticket_cost:
            ticket_note_parts: List[str] = []
            if free_ticket_count > 0:
                ticket_note_parts.append(f"{free_ticket_count} 个免费")
            ticket_note_parts.append(f"{pending_ticket_count} 个待确认")
            ticket_note = "，".join(ticket_note_parts)
        elif (confirmed_ticket or 0.0) <= 0:
            ticket_note = "当前已选景点中未识别到额外门票支出"
        else:
            ticket_note = "按已确认景点门票统计"

        rows: List[tuple[str, Any, str]] = [
            ("交通", transport, "城市内交通与跨区通勤"),
            ("住宿", hotel, "按当前人数与天数估算"),
            ("餐饮", food, "包含正餐与轻食补给"),
            ("景点门票（已确认）" if has_pending_ticket_cost else "景点门票", confirmed_ticket, ticket_note),
            ("购物/其他", other, "零散消费与机动支出"),
            ("机动缓冲", buffer, "预留临时变化空间"),
        ]
        if has_pending_ticket_cost:
            rows.insert(
                4,
                (
                    "待确认门票",
                    f"{pending_ticket_count} 个景点",
                    self._format_pending_ticket_pois(pending_ticket_pois, pending_ticket_count),
                ),
            )
        available_rows = [(name, amount, note) for name, amount, note in rows if amount is not None]
        if confirmed_total is None:
            confirmed_total = sum(
                amount for _, amount, _ in available_rows if isinstance(amount, (int, float))
            )
        if total is None:
            total = confirmed_total

        table_lines = [
            "| 类别 | 预计费用 | 说明 |",
            "| --- | ---: | --- |",
        ]
        for name, amount, note in available_rows:
            amount_text = self._format_money(amount) if isinstance(amount, (int, float)) else str(amount)
            table_lines.append(f"| {name} | {amount_text} | {note} |")
        total_label = "**合计（已确认）**" if has_pending_ticket_cost else "**合计**"
        total_note = (
            f"**约 {duration} 天 / {num_travelers} 人；不含待确认门票**"
            if has_pending_ticket_cost
            else f"**约 {duration} 天 / {num_travelers} 人**"
        )
        table_lines.append(f"| {total_label} | **{self._format_money(confirmed_total)}** | {total_note} |")

        savings = self._build_budget_saving_tips(budget, sanitized_contents.get("budget", ""))
        saving_lines = [f"- {item}" for item in savings]
        if has_pending_ticket_cost:
            intro = (
                f"当前已确认预算为 {self._format_money(confirmed_total)}，"
                f"另有 {pending_ticket_count} 个景点门票待确认，最终预算可能上浮。"
            )
            pending_snapshot = self._format_pending_ticket_pois(pending_ticket_pois, pending_ticket_count)
            if pending_snapshot:
                intro += f" 待确认景点：{pending_snapshot}。"
        else:
            intro = f"这份预算按 {duration} 天、{num_travelers} 人进行整理，可作为出发前的控制线。"
        if budget.get("budget_limit") is not None:
            if has_pending_ticket_cost:
                if budget.get("is_over_budget"):
                    intro += " 当前已确认支出已高于预算上限，且仍有部分景点门票待确认，最终支出可能进一步增加。"
                else:
                    intro += " 当前已确认支出低于预算上限，但部分景点门票待确认，最终支出可能增加。"
            elif budget.get("is_over_budget"):
                intro += " 当前估算略高于预算上限，建议优先压缩弹性支出。"

        return "\n".join(
            [
                "## 💰 3️⃣ 预算估算",
                intro,
                "",
                "### 💵 📊 费用总览",
                *table_lines,
                "",
                "### 💡 省钱技巧",
                *saving_lines,
            ]
        )

    def _render_tips_section(
        self,
        destination: str,
        duration: int,
        structured_summary: Dict[str, Any],
        conflicts: List[Dict[str, str]],
    ) -> str:
        attraction_pois = structured_summary.get("attraction", {}).get("pois") or []
        weather_data = structured_summary.get("weather", {}).get("data", {})
        packing_list = weather_data.get("packing_list") if isinstance(weather_data.get("packing_list"), list) else []
        has_weather_forecast = bool(weather_data.get("forecast_available")) or bool(weather_data.get("daily_forecasts"))
        prep_items = [
            "证件、订单截图和必要预约信息",
            "舒适步行鞋、轻便背包和常用充电设备",
        ]
        if has_weather_forecast:
            prep_items.extend(str(item).strip() for item in packing_list[:4] if str(item).strip())
        if duration >= 3:
            prep_items.append("按天分装的随身物品与换洗衣物")
        prep_items.append("移动支付、少量现金和常备药品")
        prep_lines = [f"- {item}" for item in self._dedupe_preserve_order(prep_items)]

        etiquette_items = [
            "进入寺庙、博物馆或纪念性场馆时保持安静，先确认拍照规则。",
            "热门景点和老街高峰时段人流较大，排队和拍照时尽量礼让他人。",
            "夜市或景区周边消费前先确认价格、营业时间和支付方式。",
        ]
        if any("寺" in str(poi.get("name") or "") for poi in attraction_pois if isinstance(poi, dict)):
            etiquette_items.append("宗教场所尽量着装得体，不高声喧哗。")
        etiquette_lines = [f"- {item}" for item in self._dedupe_preserve_order(etiquette_items)]

        safety_items = [self._naturalize_conflict_message(conflict.get("message", "")) for conflict in conflicts]
        safety_items = [item for item in safety_items if item]
        if not safety_items:
            safety_items = [
                f"{destination} 的热门区域建议错峰出行，返程和换乘时间尽量多预留一点。",
                "人流密集区域请保管好证件、手机和随身贵重物品。",
            ]
        if any(tag in (weather_data.get("risk_tags") or []) for tag in ["rain", "storm"]):
            safety_items.append("如遇降雨或路面湿滑，优先选择官方开放的室内替代方案。")
        safety_lines = [f"- {item}" for item in self._dedupe_preserve_order(safety_items)[:5]]

        return "\n".join(
            [
                "## ⚠️ 4️⃣ 实用贴士",
                "",
                "### 🧳 行前准备清单",
                *prep_lines,
                "",
                "### 🙏 当地礼仪和禁忌",
                *etiquette_lines,
                "",
                "### 🔐 安全提示",
                *safety_lines,
            ]
        )

    def _render_weather_section(
        self,
        structured_summary: Dict[str, Any],
        sanitized_contents: Dict[str, str],
    ) -> str:
        weather = structured_summary.get("weather", {}).get("data", {})
        if not isinstance(weather, dict):
            weather = {}
        forecasts = weather.get("daily_forecasts") if isinstance(weather.get("daily_forecasts"), list) else []
        current = weather.get("current") if isinstance(weather.get("current"), dict) else {}
        warnings = weather.get("warnings") if isinstance(weather.get("warnings"), list) else []
        alternatives = weather.get("alternatives") if isinstance(weather.get("alternatives"), list) else []
        has_current = self._has_current_weather(current)
        has_forecast = bool(weather.get("forecast_available")) or bool(forecasts)
        available_flag = weather.get("available")
        weather_available = (bool(available_flag) if available_flag is not None else (has_current or has_forecast)) and (has_current or has_forecast)

        overall_points = self._build_weather_overview_points(current, forecasts, warnings)
        overall_lines = [f"- {item}" for item in overall_points]

        table_lines = [
            "| 日期 | 天气 | 温度 | 出行提示 |",
            "| --- | --- | --- | --- |",
        ]
        if has_forecast:
            for item in forecasts:
                date_text = str(item.get("date") or "待确认").strip() or "待确认"
                weather_text = str(item.get("day_weather") or item.get("weather") or "待确认").strip() or "待确认"
                weather_text = self._format_daily_weather_text(item)
                temp_text = self._format_temp_band(item.get("min_temp"), item.get("max_temp"))
                advice_text = self._build_weather_day_advice(item)
                table_lines.append(f"| {date_text} | {weather_text} | {temp_text} | {advice_text} |")
        else:
            table_lines.append("| 暂无可靠预报 | 暂未获取 | 暂未获取 | 出发前请关注实时天气预报 |")

        outfit_items = self._build_outfit_suggestions(forecasts, weather_available=weather_available and has_forecast)
        outfit_lines = [f"- {item}" for item in outfit_items]

        practical_items = ["天气数据暂不可用，建议出行前关注实时天气以获取准确建议。"] if not weather_available else [str(item).strip() for item in warnings if str(item).strip()]
        practical_items.extend(
            str(item.get("action") or "").strip()
            for item in alternatives
            if isinstance(item, dict) and str(item.get("action") or "").strip()
        )
        if not practical_items:
            practical_items = self._extract_section_items(sanitized_contents.get("weather", ""), ["实用建议", "天气替代方案"])
        if not practical_items:
            practical_items = ["建议在出发前 24 小时再次确认实时天气，再决定是否调整户外时段。"]
        practical_items = self._filter_distinct_items(practical_items, overall_points + outfit_items)
        if not practical_items:
            practical_items = ["建议在出发前 24 小时再次确认实时天气，再决定是否调整户外时段。"]
        practical_lines = [f"- {item}" for item in self._dedupe_structured_items(practical_items)[:4]]

        return "\n".join(
            [
                "## 🌤️ 5️⃣ 天气信息",
                "",
                "### 📊 整体天气概况",
                *overall_lines,
                "",
                "### 📅 每日天气详情",
                *table_lines,
                "",
                "### 👗 穿搭建议",
                *outfit_lines,
                "",
                "### 📝 实用建议",
                *practical_lines,
            ]
        )

    def _get_day3_fallback_suggestions(self, region: str, time_slot: str) -> str:
        """【本轮修复】为空闲 slot 提供具体片区建议，避免整天自由活动。"""
        region = str(region or "").strip()

        # morning 空白时：给出该城市知名晨间片区
        if time_slot in ("09:00-11:30", "morning"):
            morning_map = {
                "北京": "早起逛什刹海/鼓楼，晨练、遛鸟、看胡同烟火气。",
                "杭州": "清晨走白堤/苏堤，看西湖日出，呼吸新鲜空气。",
                "上海": "晨起漫步外滩/苏州河畔，看晨光中的万国建筑。",
                "成都": "早起逛宽窄巷子/锦里，晨间游客少、体验更好。",
                "西安": "清晨登城墙骑行或慢跑，晨风舒适、视野开阔。",
                "重庆": "早起走洪崖洞周边，看嘉陵江晨景，尝一碗小面。",
                "广州": "早茶体验：点都德/陶陶居，一盅两件地道广式早晨。",
                "深圳": "晨间逛深圳湾公园，看海景与日出，慢跑骑行皆宜。",
                "厦门": "清晨走中山路/鹭江道，尝花生汤和沙茶面开启一天。",
                "南京": "早起游玄武湖公园，湖边晨练、看市民生活。",
                "青岛": "清晨栈桥海边漫步，看日出、海鸥飞舞。",
                "苏州": "早起平江路散步，尝苏式早点（生煎、蟹粉小笼）。",
            }
            for city, suggestion in morning_map.items():
                if city in region:
                    return suggestion
            return f"早起在 {region} 核心街区漫步，感受当地清晨生活氛围。"

        # afternoon 空白时
        if time_slot in ("14:00-17:00", "afternoon"):
            afternoon_map = {
                "北京": "午后逛胡同深处：王府井附近东郊民巷、五道营胡同，感受老城生活。",
                "杭州": "下午探访河坊街/南宋御街，逛百年老店、尝手工点心。",
                "上海": "午后漫步梧桐区：武康路/衡山路，逛小店、喝咖啡，感受海派风情。",
                "成都": "下午逛东郊记忆/玉林路，找一间茶馆坐下，喝茶聊天。",
                "西安": "午后游大唐不夜城（大雁塔周边），看雕塑群与文化演出。",
                "重庆": "下午穿梭解放碑商圈，逛大型商场、尝重庆酸辣粉。",
                "广州": "午后逛沙面岛/北京路步行街，看近代建筑，品广式甜品。",
                "南京": "下午游夫子庙/老门东，秦淮河畔慢走、尝盐水鸭。",
                "厦门": "下午漫步鼓浪屿（若未去），或逛中山路骑楼建筑。",
                "青岛": "下午信号山/小鱼山观景，俯瞰红瓦绿树碧海蓝天。",
                "苏州": "下午游平江路/山塘街，沿河喝茶、听评弹。",
            }
            for city, suggestion in afternoon_map.items():
                if city in region:
                    return suggestion
            return f"下午在 {region} 周边安排一个轻量文化体验或步行慢逛。"

        # evening 空白时：必须是夜景/休闲类
        if time_slot in ("19:00-21:00", "evening"):
            evening_map = {
                "北京": "夜晚逛三里屯/后海酒吧街，感受京城夜生活；或鸟巢水立方灯光秀。",
                "杭州": "夜游西湖（音乐喷泉/湖滨步道），看雷峰塔夜景灯光。",
                "上海": "夜游外滩万国建筑博览群，看浦东陆家嘴灯光夜景。",
                "成都": "锦江夜游（339电视塔周边），或宽窄巷子夜市逛吃。",
                "西安": "夜晚大唐不夜城灯光秀（19:30/21:00 演出），再现盛世长安。",
                "重庆": "夜游洪崖洞（现实版千与千寻），看嘉陵江两岸夜景。",
                "广州": "夜游珠江（天字码头/大沙头），看小蛮腰灯光秀。",
                "南京": "夜游夫子庙秦淮河，乘画舫、看灯笼，感受六朝烟月。",
                "厦门": "夜逛中山路步行街，尝沙坡尾海鲜排档。",
                "青岛": "五四广场/奥帆中心夜景灯光，看浮山湾灯光秀。",
                "苏州": "山塘街夜景，乘船夜游姑苏水巷，感受江南夜色。",
            }
            for city, suggestion in evening_map.items():
                if city in region:
                    return suggestion
            return f"晚上在 {region} 附近找一处夜市或步行街，感受当地夜生活。"

        return ""

    def _render_day_slot(
        self,
        title: str,
        items: List[Dict[str, Any]],
        time_slot: str,
        region: str,
        fallback_reason: str,
    ) -> str:
        if not items:
            # 【本轮修复】空白 slot 不再用"自由探索为主"泛泛带过，而是给出具体片区推荐
            area_fallbacks = self._get_day3_fallback_suggestions(region, time_slot)
            if area_fallbacks:
                return "\n".join(
                    [
                        f"#### {title}",
                        f"- ⏰ **建议时段**：{time_slot}",
                        f"- 📍 **推荐安排**：{area_fallbacks}",
                    ]
                )
            return "\n".join(
                [
                    f"#### {title}",
                    f"- ⏰ **建议时段**：{time_slot}",
                    f"- 📍 **安排建议**：以 {region} 一带自由探索为主。",
                    "- 📝 **说明**：保留弹性时间，可顺路发掘当地街区和市井小店。",
                ]
            )

        names = self._dedupe_preserve_order(
            [str(item.get("name") or "").strip() for item in items if str(item.get("name") or "").strip()]
        )
        note_parts = self._dedupe_preserve_order(
            [self._clean_inline_text(item.get("notes")) for item in items if self._clean_inline_text(item.get("notes"))]
        )
        region_text = self._first_non_empty_region(items) or region
        reason = note_parts[0] if note_parts else fallback_reason

        # 【修复】时段适配：根据景点类型动态调整时段标签和时段描述
        time_hint, dynamic_reason = self._get_adaptive_time_hint(time_slot, names, items, region)

        # 【修复】去除 reason 中可能重复的前缀标签
        reason = self._clean_recommended_reason(reason)

        return "\n".join(
            [
                f"#### {title}",
                f"- ⏰ **建议时段**：{time_hint}",
                f"- 📍 **推荐地点**：{'、'.join(names)}",
                f"- 🗺️ **所在区域**：{region_text}",
                f"- ✨ **推荐理由**：{dynamic_reason}",
            ]
        )

    def _get_adaptive_time_hint(
        self,
        slot: str,
        names: List[str],
        items: List[Dict[str, Any]],
        region: str,
    ) -> tuple[str, str]:
        """根据景点类型动态适配时段和推荐理由。"""
        names_text = " ".join(names)
        first_item = items[0] if items else {}
        open_hours = str(first_item.get("opening_hours") or "").strip()
        category = str(first_item.get("category") or "").strip()
        tags_text = " ".join(str(t) for t in (first_item.get("tags") or []) if str(t).strip())
        combined = f"{names_text} {category} {tags_text} {open_hours}".lower()

        # 【修复】识别典型白天型景点，禁止排到晚间
        day_only_keywords = ["博物馆", "美术馆", "展馆", "故宫", "天坛", "天安门", "纪念馆", "图书馆", "寺庙主体", "石窟", "宫殿", "城墙", "钟楼", "鼓楼"]
        if slot == "evening" and any(kw in combined for kw in day_only_keywords):
            slot = "afternoon"

        # 【修复】识别夜间更合适的景点
        night_keywords = ["夜景", "夜游", "灯光", "夜市", "酒吧", "演出", "游船", "江景"]
        if slot != "evening" and any(kw in combined for kw in night_keywords):
            slot = "evening"

        # 【修复】时段映射
        slot_map = {
            "morning": ("09:00-11:30", "适合用来开启当天主线，避开高峰排队，体验更从容。"),
            "afternoon": ("14:00-17:00", "把同一区域景点放在同一时段，更省通勤时间。"),
            "evening": ("19:00-21:00", "晚间适合安排夜景、休闲散步或轻松收尾。"),
        }
        time_hint, base_reason = slot_map.get(slot, (slot, "灵活安排"))

        # 【修复】根据景点类型调整推荐理由
        if any(kw in combined for kw in ["博物馆", "美术馆", "展馆"]):
            dynamic_reason = "室内场馆体验丰富，建议上午前往，光线好且人流相对较少。"
        elif any(kw in combined for kw in ["公园", "湖", "河", "山"]):
            dynamic_reason = "自然景区适合慢慢走，建议上午或傍晚光线好时游览。"
        elif any(kw in combined for kw in ["夜市", "老街", "小吃街", "美食街"]):
            dynamic_reason = "街区类景点早晚人流不同，可根据当天节奏灵活安排。"
        elif any(kw in combined for kw in ["夜景", "夜游", "灯光", "江景"]):
            dynamic_reason = "夜景类景点建议傍晚或晚间前往，灯光亮起时体验最佳。"
        elif any(kw in combined for kw in ["寺庙", "宗教", "教堂"]):
            dynamic_reason = "宗教场所建议上午前往，光线好且更清静。"
        elif any(kw in combined for kw in ["古镇", "古城", "老城"]):
            dynamic_reason = "古镇老街早晚氛围不同，可根据当天行程节奏灵活安排。"
        else:
            dynamic_reason = base_reason

        return time_hint, dynamic_reason

    def _clean_recommended_reason(self, reason: str) -> str:
        """去除推荐理由中可能重复的前缀标签。"""
        if not reason:
            return reason
        # 去除常见的前缀标签（只保留第一次出现后的内容）
        prefixes = ["推荐理由：", "推荐理由: ", "推荐理由 ", "理由：", "理由: "]
        cleaned = reason
        for prefix in prefixes:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].lstrip("：: ")
        # 如果去掉后重复，再去掉一次
        for prefix in prefixes:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].lstrip("：: ")
        return cleaned if cleaned else reason

    def _build_localized_lunch_name(self, region: str, destination: str = "") -> str:
        """根据区域和目的地给出更本地化的午餐推荐名称和美食类别。"""
        region = str(region or "").strip()
        destination = str(destination or "").strip()

        # 【修复】针对常见城市/区域给出更具体的本地化建议 + 美食类别
        mapping = {
            # 北京
            ("前门", "大栅栏", "天安门", "故宫", "王府井", "北京"): {
                "area": "前门/大栅栏一带",
                "food": "京味小吃（炸酱面、卤煮、豆汁）"
            },
            ("什刹海", "鼓楼", "南锣鼓巷", "胡同"): {
                "area": "什刹海/鼓楼片区",
                "food": "老北京胡同小馆（铜锅涮肉、炸酱面）"
            },
            ("三里屯", "国贸", "CBD"): {
                "area": "三里屯/国贸商圈",
                "food": "商圈多元餐饮（各国料理、精品咖啡）"
            },
            ("颐和园", "圆明园", "中关村", "海淀"): {
                "area": "中关村/海淀黄庄一带",
                "food": "高校周边简餐（面馆、盖饭）"
            },
            # 杭州
            ("西湖", "断桥", "灵隐", "龙井", "河坊街", "南宋御街", "杭州"): {
                "area": "西湖东线/河坊街一带",
                "food": "杭帮特色（片儿川、叫化鸡、定胜糕）"
            },
            ("千岛湖", "淳安"): {
                "area": "千岛湖镇周边",
                "food": "湖鲜特色（剁椒鱼头、鱼头煲）"
            },
            # 上海
            ("豫园", "城隍庙", "黄浦", "上海老城"): {
                "area": "豫园/城隍庙周边",
                "food": "本帮小吃（南翔小笼、蟹壳黄、生煎）"
            },
            ("外滩", "南京东路", "人民广场"): {
                "area": "南京东路/外滩周边",
                "food": "海派风味（本帮面点、老字号餐厅）"
            },
            ("武康路", "衡山路", "安福路", "梧桐区", "徐汇"): {
                "area": "武康路/衡山路街区",
                "food": "梧桐区文艺小馆（咖啡、西餐、Brunch）"
            },
            ("新天地", "淮海路", "田子坊"): {
                "area": "新天地/淮海路商圈",
                "food": "时尚餐饮（创意菜、日料、轻食）"
            },
            ("陆家嘴", "浦东"): {
                "area": "陆家嘴/浦东中心",
                "food": "商务简餐（商场美食广场、高性价比套餐）"
            },
            # 成都
            ("宽窄巷子", "锦里", "武侯祠", "成都老城"): {
                "area": "宽窄巷子/锦里周边",
                "food": "川味小吃（担担面、钟水饺、串串香）"
            },
            ("春熙路", "太古里", "IFS"): {
                "area": "春熙路/太古里商圈",
                "food": "成都时尚餐饮（火锅、冒菜、川菜）"
            },
            ("熊猫基地", "动物园"): {
                "area": "熊猫基地周边",
                "food": "景区周边简餐（农家乐、川菜家常馆）"
            },
            # 重庆
            ("解放碑", "洪崖洞", "朝天门"): {
                "area": "解放碑/洪崖洞周边",
                "food": "渝派美食（重庆小面、酸辣粉、江湖菜）"
            },
            ("磁器口", "沙坪坝"): {
                "area": "磁器口古镇周边",
                "food": "古镇特色（毛血旺、鸡杂、糍粑）"
            },
            ("南山", "一棵树"): {
                "area": "南山一棵树周边",
                "food": "南山美食（泉水鸡、豆花饭）"
            },
            # 西安
            ("回民街", "钟楼", "鼓楼", "西安老城"): {
                "area": "回民街/钟楼附近",
                "food": "陕味清真小吃（羊肉泡馍、肉夹馍、凉皮）"
            },
            ("大雁塔", "大唐不夜城", "曲江"): {
                "area": "大雁塔/曲江周边",
                "food": "大唐文化区餐饮（陕菜、饺子宴）"
            },
            ("城墙", "永宁门"): {
                "area": "城墙/南门周边",
                "food": "城中古韵餐饮（biangbiang面、臊子面）"
            },
            # 泉州
            ("西街", "开元寺", "中山路", "泉州老城"): {
                "area": "西街/开元寺周边",
                "food": "闽南小吃（面线糊、姜母鸭、烧肉粽）"
            },
            ("关岳庙", "清净寺", "涂门街"): {
                "area": "关岳庙/清净寺周边",
                "food": "泉州宗教区小吃（元宵丸、四果汤）"
            },
            # 洛阳
            ("龙门石窟", "洛阳南郊"): {
                "area": "龙门石窟周边",
                "food": "景区周边简餐（洛阳水席、不翻汤）"
            },
            ("洛邑古城", "丽景门", "老城"): {
                "area": "洛邑古城/老城片区",
                "food": "洛阳老城风味（浆面条、糊涂面）"
            },
            # 南京
            ("夫子庙", "秦淮河", "老门东", "南京老城"): {
                "area": "夫子庙/秦淮河周边",
                "food": "金陵风味（鸭血粉丝汤、盐水鸭、秦淮小吃）"
            },
            ("中山陵", "明孝陵", "钟山"): {
                "area": "中山陵/钟山风景区",
                "food": "景区周边简餐（农家菜、山下小镇餐饮）"
            },
            # 苏州
            ("平江路", "观前街", "苏州老城"): {
                "area": "平江路/观前街一带",
                "food": "苏帮风味（苏式汤面、糕团、松鼠桂鱼）"
            },
            ("山塘街", "虎丘"): {
                "area": "山塘街/虎丘周边",
                "food": "姑苏水乡风味（苏帮菜、船菜）"
            },
            # 厦门
            ("鼓浪屿", "中山路", "厦门老城"): {
                "area": "鼓浪屿/中山路周边",
                "food": "闽南特色（沙茶面、海蛎煎、土笋冻）"
            },
            ("曾厝垵", "环岛路"): {
                "area": "曾厝垵/环岛路一带",
                "food": "文艺渔村小吃（海鲜、烧仙草、花生汤）"
            },
            # 青岛
            ("栈桥", "中山路", "青岛老城"): {
                "area": "栈桥/中山路周边",
                "food": "青岛海鲜特色（啤酒海鲜、海肠捞饭）"
            },
            ("五四广场", "奥帆中心"): {
                "area": "五四广场/奥帆中心周边",
                "food": "海景商圈餐饮（海鲜、鲁菜）"
            },
            # 通用老城/古城
            ("老城", "古城", "古镇", "旧城"): {
                "area": f"{region or destination or '老城'}片区",
                "food": "当地特色小吃（走街串巷发掘市井美味）"
            },
            # 通用商圈/步行街
            ("商圈", "步行街", "CBD", "中心区", "繁华区"): {
                "area": "商圈美食区",
                "food": "多元餐饮（各地料理、商务套餐）"
            },
            # 通用景区/公园
            ("景区", "公园", "博物馆", "展览馆"): {
                "area": "景区周边餐饮区",
                "food": "景区配套简餐（快餐、当地家常菜）"
            },
        }

        # 【修复】匹配查找（多关键词组合）
        for keywords, info in mapping.items():
            if any(kw in region or kw in destination for kw in keywords if kw):
                return f"{info['area']}{info['food']}"

        # 【修复】基于城市名进一步细化
        city_mappings = {
            "北京": ("老城胡同片区", "京味特色（炸酱面、卤煮、豆汁）"),
            "上海": ("海派街区", "本帮风味（本帮菜、生煎、小笼）"),
            "杭州": ("西湖周边", "杭帮特色（片儿川、龙井虾仁）"),
            "成都": ("老城街区", "川味小吃（担担面、钟水饺）"),
            "重庆": ("主城核心区", "渝派美食（火锅、小面、江湖菜）"),
            "西安": ("老城片区", "陕味特色（肉夹馍、凉皮、泡馍）"),
            "泉州": ("老城核心", "闽南小吃（面线糊、姜母鸭）"),
            "洛阳": ("老城片区", "洛阳风味（浆面条、水席）"),
            "南京": ("老城街区", "金陵风味（鸭血粉丝、盐水鸭）"),
            "苏州": ("姑苏老街", "苏帮风味（苏式汤面、糕团）"),
            "厦门": ("鹭岛老街", "闽南特色（沙茶面、海蛎煎）"),
            "青岛": ("老城海滨", "青岛海鲜特色（啤酒海鲜）"),
        }
        for city, (area, food) in city_mappings.items():
            if city in destination or city in region:
                return f"{area}{food}"

        # 【修复】默认：区域名 + 通用美食类别
        if region and region not in ["未知", "未注明区域"]:
            return f"{region}及周边当地特色餐饮"
        return "当地特色美食（午餐灵活安排）"

    def _render_lunch_slot(
        self,
        lunch_spot: Optional[Dict[str, Any]],
        region: str,
        budget_data: Dict[str, Any],
        destination: str = "",
    ) -> str:
        food_cost = self._coerce_float(budget_data.get("food_cost"))
        per_day = self._coerce_float(budget_data.get("per_day_budget"))
        day_count = max(self._safe_int(budget_data.get("day_count"), default=1), 1)
        num_travelers = max(self._safe_int(budget_data.get("num_travelers"), default=1), 1)
        lunch_budget_text = "按当天餐饮预算灵活安排"

        def _format_lunch_range(low: int, high: int, scene_label: str) -> str:
            return f"人均约 ¥{low}-{high}（{scene_label}，估算）"

        # 【修复】使用更保守的午餐估算基准，避免所有城市都套同一档
        base_lunch_ranges = {
            # 一线城市（高消费）
            "北京": (50, 80),
            "上海": (55, 85),
            "广州": (45, 75),
            "深圳": (50, 80),
            # 新一线/强二线（中等偏高）
            "杭州": (40, 70),
            "南京": (40, 65),
            "成都": (35, 60),
            "重庆": (35, 60),
            "西安": (30, 55),
            "厦门": (40, 65),
            "天津": (35, 60),
            # 普通旅游城市（较实惠）
            "泉州": (25, 45),
            "洛阳": (25, 45),
            "昆明": (30, 50),
            "贵阳": (25, 45),
            "哈尔滨": (30, 55),
            "长沙": (30, 55),
            "武汉": (35, 60),
            "济南": (30, 55),
            # 默认
            "默认": (35, 65),
        }

        # 【修复】根据目的地匹配估算区间
        matched_range = None
        for city, range_vals in base_lunch_ranges.items():
            if city != "默认" and city in destination:
                matched_range = range_vals
                break
        if matched_range is None:
            matched_range = base_lunch_ranges["默认"]

        # 【修复】根据 lunch_spot 类型调整区间
        if lunch_spot:
            spot_name = str(lunch_spot.get("name") or "").strip()
            spot_text = " ".join(
                str(value).strip()
                for value in [
                    spot_name,
                    lunch_spot.get("category"),
                    lunch_spot.get("region"),
                    " ".join(
                        str(tag).strip()
                        for tag in (lunch_spot.get("tags") or [])
                        if str(tag).strip()
                    ) if isinstance(lunch_spot.get("tags"), list) else "",
                ]
                if str(value).strip()
            )
            if any(keyword in spot_text for keyword in ["夜市", "老街", "小吃", "美食街", "市集"]):
                scene_label = "当地小吃/简餐"
                matched_range = (matched_range[0] - 10, matched_range[1] - 15)
            elif any(keyword in spot_text for keyword in ["景区", "景点", "古城", "博物馆", "公园", "步行街"]):
                scene_label = "景区周边简餐"
                matched_range = (matched_range[0], matched_range[1] - 5)
            elif any(keyword in spot_text for keyword in ["商圈", "商场", "广场", "中心", "CBD", "综合体"]):
                scene_label = "商圈普通正餐"
                matched_range = (matched_range[0] + 10, matched_range[1] + 15)
            else:
                scene_label = "当地特色餐饮"
        else:
            if any(keyword in region for keyword in ["老城", "古城", "文化片区", "景区"]):
                scene_label = "老城/景区周边小吃"
                matched_range = (matched_range[0] - 10, matched_range[1] - 15)
            elif any(keyword in region for keyword in ["夜市", "夜游"]):
                scene_label = "当地小吃/夜市简餐"
                matched_range = (matched_range[0] - 15, matched_range[1] - 20)
            elif any(keyword in region for keyword in ["商圈", "步行街"]):
                scene_label = "商圈正餐"
                matched_range = (matched_range[0] + 5, matched_range[1] + 10)
            else:
                scene_label = "当地特色餐饮"

        # 【修复】确保区间合理
        low, high = matched_range
        low = max(low, 20)
        high = max(high, low + 15)
        lunch_budget_text = _format_lunch_range(low, high, scene_label)

        # 【修复】生成更本地化的午餐名称和推荐理由
        localized_lunch = self._build_localized_lunch_name(region, destination)
        if lunch_spot:
            name = str(lunch_spot.get("name") or localized_lunch).strip()
            reason = self._build_lunch_reason(lunch_spot, region)
        else:
            name = localized_lunch
            reason = "建议把午餐安排在当前活动区域附近，节省通勤时间并留出休息缓冲。"

        return "\n".join(
            [
                "#### 🍽️ 午餐推荐",
                "- ⏰ **建议时段**：12:00-13:30",
                f"- 📍 **推荐地点**：{name}",
                f"- 💵 **预算参考**：{lunch_budget_text}",
                f"- 🍜 **推荐理由**：{reason}",
            ]
        )

    def _build_lunch_reason(self, lunch_spot: Dict[str, Any], region: str) -> str:
        """根据午餐点的特点生成推荐理由。"""
        name = str(lunch_spot.get("name") or "").strip()
        category = str(lunch_spot.get("category") or "").strip()
        tags = lunch_spot.get("tags") or []
        tags_str = " ".join(str(t) for t in tags if str(t).strip()) if isinstance(tags, list) else ""
        combined = f"{name} {category} {tags_str}".lower()

        if any(kw in combined for kw in ["夜市", "老街", "小吃", "美食街", "市集"]):
            return "这里更适合体验当地小吃和城市烟火气，也方便顺势衔接下午或晚间安排。"
        elif any(kw in combined for kw in ["景区", "景点", "古城", "博物馆", "公园", "步行街"]):
            return "适合放在当前景点周边顺路解决，减少通勤并保留更多游玩时间。"
        elif any(kw in combined for kw in ["商圈", "商场", "CBD"]):
            return "商圈餐饮选择丰富，适合商务休闲兼顾，休息与用餐体验更舒适。"
        elif any(kw in combined for kw in ["湖", "河", "江", "海滨", "水边"]):
            return "滨水区域氛围独特，用餐同时可观景，适合慢节奏休憩。"
        elif any(kw in combined for kw in ["古镇", "古城", "老城", "胡同"]):
            return "老城/古镇区餐饮更具在地特色，建议边吃边感受当地生活气息。"
        else:
            return "适合把用餐和短暂休整放在景点串联之间，减少来回折返。"

    def _render_day_tips(
        self,
        region: str,
        items: List[Dict[str, Any]],
        weather_data: Dict[str, Any],
    ) -> str:
        tips = [f"优先把 {region} 内的点位串联游玩，减少来回换乘。"]
        if len(items) >= 3:
            tips.append("当天点位较多，建议把拍照和排队时间也一并算进节奏。")
        risk_tags = weather_data.get("risk_tags") if isinstance(weather_data.get("risk_tags"), list) else []
        if "rain" in risk_tags:
            tips.append("如遇降雨，优先把室内点位放在前后做机动替换。")
        if "heat" in risk_tags:
            tips.append("午后注意补水和防晒，重体力步行尽量放在上午或傍晚。")
        if "temperature_gap" in risk_tags:
            tips.append("早晚温差较明显，随身带一件轻薄外套会更稳妥。")
        tip_lines = [f"- {item}" for item in self._dedupe_preserve_order(tips)[:3]]
        return "\n".join(["#### 📌 今日小贴士", *tip_lines])

    def _build_budget_saving_tips(self, budget: Dict[str, Any], budget_text: str) -> List[str]:
        suggestions: List[str] = []
        pending_ticket_count = self._safe_int(budget.get("pending_ticket_count"), default=0)
        confirmed_ticket_cost = self._coerce_float(budget.get("confirmed_ticket_cost"))
        has_pending_ticket_cost = bool(budget.get("has_pending_ticket_cost")) or pending_ticket_count > 0
        pending_ticket_tip_added = False
        raw_suggestions = budget.get("optimization_suggestions")
        if isinstance(raw_suggestions, list):
            for item in raw_suggestions:
                if not isinstance(item, dict):
                    continue
                category = str(item.get("category") or "").strip()
                saving = self._coerce_float(item.get("potential_savings"))
                suggestion = self._clean_inline_text(item.get("suggestion"))
                is_ticket_related = self._is_ticket_related_text(category) or self._is_ticket_related_text(suggestion)
                if has_pending_ticket_cost and is_ticket_related:
                    pending_ticket_tip_added = True
                    if (confirmed_ticket_cost or 0.0) <= 0:
                        suggestions.append("部分景点票价待确认，建议出发前核实门票政策和预约要求；若景点存在临时收费或季节性收费，最好提前在线确认。")
                    else:
                        suggestions.append("部分景点票价待确认，建议先核实门票价格与预约规则，再决定是否购买联票或取舍收费景点。")
                    continue
                pieces = [part for part in [category, suggestion] if part]
                if not pieces:
                    continue
                line = "：".join(pieces[:2]) if len(pieces) > 1 else pieces[0]
                if saving is not None:
                    line += f"（可节省约 {self._format_money(saving)}）"
                suggestions.append(line)

        extracted_items = self._extract_section_items(budget_text, ["省钱技巧", "优化建议", "预算总结与优化建议"])
        if has_pending_ticket_cost:
            extracted_items = [item for item in extracted_items if not self._is_ticket_related_text(item)]
        suggestions.extend(extracted_items)
        if has_pending_ticket_cost and not pending_ticket_tip_added:
            if (confirmed_ticket_cost or 0.0) <= 0:
                suggestions.append("部分景点票价待确认，建议出发前核实门票政策和预约要求；若景点存在临时收费或季节性收费，最好提前在线确认。")
            else:
                suggestions.append("部分景点票价待确认，建议优先核实票价与预约规则，再决定是否购买联票或取舍收费景点。")
        if not suggestions:
            suggestions = [
                "把同一区域景点放在同一天，通常比频繁跨区更省交通费。",
                "住宿尽量优先选在核心行程区附近，能同时压缩打车和通勤时间。",
                "热门景区周边用餐建议错开正餐高峰，价格和排队体验通常更友好。",
            ]
            if has_pending_ticket_cost:
                suggestions.append("部分景点票价待确认，建议出发前核实门票政策和预约要求。")
        return self._dedupe_structured_items(suggestions)[:5]

    def _build_weather_overview_points(
        self,
        current: Dict[str, Any],
        forecasts: List[Dict[str, Any]],
        warnings: List[str],
    ) -> List[str]:
        points: List[str] = []
        temp_range: Dict[str, Any] = {}
        risk_tags: List[str] = []
        current_point = self._format_current_observation(current)
        if current_point:
            points.append(current_point)
        else:
            points.append("当前实况暂未获取到可靠数据。")
        if forecasts:
            min_temp = min(
                (item.get("min_temp") for item in forecasts if item.get("min_temp") is not None),
                default=None,
            )
            max_temp = max(
                (item.get("max_temp") for item in forecasts if item.get("max_temp") is not None),
                default=None,
            )
            if min_temp is not None and max_temp is not None:
                points.append(f"未来{len(forecasts)}天温度大致在 {min_temp}℃ 到 {max_temp}℃ 之间。")
            weather_labels = self._dedupe_preserve_order(
                [str(item.get("day_weather") or item.get("weather") or "").strip() for item in forecasts if str(item.get("day_weather") or item.get("weather") or "").strip()]
            )
            if weather_labels:
                points.append(f"未来{len(forecasts)}天以 {'、'.join(weather_labels[:2])} 为主。")
            fact_notice = self._build_forecast_fact_notice(forecasts)
            if fact_notice:
                points.append(fact_notice)
        else:
            points.append("未来几天预报暂未获取到可靠数据，请以临近出发时的实时预报为准。")
        points.extend(self._clean_inline_text(item) for item in warnings if self._clean_inline_text(item))
        return self._dedupe_preserve_order(points)[:4]
        if temp_range.get("min") is not None and temp_range.get("max") is not None:
            points.append(f"温度大致在 {temp_range.get('min')}℃ 到 {temp_range.get('max')}℃ 之间。")
        if forecasts:
            weather_labels = self._dedupe_preserve_order(
                [str(item.get("day_weather") or item.get("weather") or "").strip() for item in forecasts if str(item.get("day_weather") or item.get("weather") or "").strip()]
            )
            if weather_labels:
                points.append(f"这几天以 {'、'.join(weather_labels[:2])} 为主。")
        points.extend(self._naturalize_weather_risks(risk_tags))
        points.extend(self._clean_inline_text(item) for item in warnings if self._clean_inline_text(item))
        if not points:
            points.append("暂未获取到可靠天气预报，请以临近出发时的实时预报为准。")
        return self._dedupe_preserve_order(points)[:4]

    def _build_weather_day_advice(self, item: Dict[str, Any]) -> str:
        tips: List[str] = []
        risk_tags = item.get("risk_tags") if isinstance(item.get("risk_tags"), list) else []
        weather_text = self._format_daily_weather_text(item)
        rain_prob = self._safe_int(item.get("precipitation"), default=0)
        max_temp = self._safe_int(item.get("max_temp"), default=-99)
        min_temp = self._safe_int(item.get("min_temp"), default=99)
        wind_speed = self._coerce_float(item.get("wind_speed"))
        if self._looks_rainy_weather(weather_text) or rain_prob > 0:
            tips.append("有雨，建议带雨具")
        if max_temp >= 33:
            tips.append("白天偏热，注意防晒补水")
        if max_temp != -99 and min_temp != 99 and max_temp - min_temp >= 8:
            tips.append("早晚温差大，带一件薄外套")
        if wind_speed is not None and wind_speed >= 25:
            tips.append("风力偏大，户外停留别太久")
        if not tips:
            tips.append("适合按常规节奏出行")
        return "；".join(self._dedupe_preserve_order(tips))
        risk_tags = item.get("risk_tags") if isinstance(item.get("risk_tags"), list) else []
        rain_prob = self._safe_int(item.get("precipitation"), default=0)
        max_temp = self._safe_int(item.get("max_temp"), default=-99)
        wind_speed = self._coerce_float(item.get("wind_speed"))
        if "rain" in risk_tags or rain_prob >= 50:
            tips.append("备好雨具")
        if "heat" in risk_tags or max_temp >= 33:
            tips.append("注意防晒补水")
        if "temperature_gap" in risk_tags:
            tips.append("早晚加一件薄外套")
        if "wind" in risk_tags or (wind_speed is not None and wind_speed >= 25):
            tips.append("户外停留别太久")
        if not tips:
            tips.append("适合按常规节奏出行")
        return "，".join(self._dedupe_preserve_order(tips))

    def _build_outfit_suggestions(self, forecasts: List[Dict[str, Any]], *, weather_available: bool) -> List[str]:
        suggestions: List[str] = []
        packing_list: List[str] = []
        risk_tags: List[str] = []
        if not weather_available or not forecasts:
            return ["天气数据暂不可用，出发前请查看实时天气预报自行准备穿搭。"]
        min_temp = min((item.get("min_temp") for item in forecasts if item.get("min_temp") is not None), default=None)
        max_temp = max((item.get("max_temp") for item in forecasts if item.get("max_temp") is not None), default=None)
        weather_labels = " ".join(
            str(item.get("day_weather") or item.get("weather") or "").strip()
            for item in forecasts
        )
        if max_temp is not None and max_temp >= 33:
            suggestions.append("白天偏热，建议以轻薄透气穿搭为主，并准备防晒用品。")
        if min_temp is not None and min_temp <= 12:
            suggestions.append("早晚偏凉，建议带一件薄外套或保暖层。")
        if min_temp is not None and max_temp is not None and max_temp - min_temp >= 8:
            suggestions.append("温差较明显，分层穿搭会更稳妥。")
        if self._looks_rainy_weather(weather_labels):
            suggestions.append("有雨信号时，鞋子尽量选防滑、耐走的款式，并备好雨具。")
        if not suggestions:
            suggestions.append("天气整体平稳，按舒适步行穿搭准备即可。")
        return self._dedupe_preserve_order(suggestions)[:4]
        items = [str(item).strip() for item in packing_list if str(item).strip()]
        if items:
            suggestions.append(f"建议以轻便舒适为主，优先准备 {'、'.join(self._dedupe_preserve_order(items)[:4])}。")
        if "temperature_gap" in risk_tags:
            suggestions.append("早晚温差偏大时，薄外套会比单层穿着更稳妥。")
        if "rain" in risk_tags:
            suggestions.append("有降雨信号时，鞋子尽量选择防滑、耐走的款式。")
        if "heat" in risk_tags:
            suggestions.append("白天气温偏高时，建议准备透气衣物和防晒用品。")
        if not suggestions:
            suggestions.append("天气整体平稳，按舒适步行穿搭准备即可。")
        return self._dedupe_preserve_order(suggestions)[:4]

    def _has_current_weather(self, current: Dict[str, Any]) -> bool:
        if not isinstance(current, dict):
            return False
        return current.get("temperature") is not None or bool(str(current.get("weather") or "").strip())

    def _format_current_observation(self, current: Dict[str, Any]) -> str:
        if not self._has_current_weather(current):
            return ""
        temp = current.get("temperature")
        weather_text = str(current.get("weather") or "天气未知").strip() or "天气未知"
        report_time = str(current.get("report_time") or "").strip()
        if temp is None:
            temp_text = weather_text
        else:
            temp_text = f"{temp}℃，{weather_text}"
        if report_time:
            return f"当前实况 {temp_text}（{report_time} 观测）。"
        return f"当前实况 {temp_text}。"

    def _build_forecast_fact_notice(self, forecasts: List[Dict[str, Any]]) -> str:
        if not forecasts:
            return ""
        if any(self._looks_rainy_weather(self._format_daily_weather_text(item)) or self._safe_int(item.get("precipitation"), default=0) > 0 for item in forecasts):
            return "未来几天有降水信号，行程里最好预留可切换的室内备选。"
        if any(
            item.get("min_temp") is not None
            and item.get("max_temp") is not None
            and (item.get("max_temp") - item.get("min_temp")) >= 8
            for item in forecasts
        ):
            return "未来几天早晚温差较明显，随身带一件薄外套会更稳妥。"
        if any((item.get("max_temp") or -99) >= 33 for item in forecasts):
            return "未来几天白天偏热，户外活动尽量避开最晒的时段。"
        return ""

    def _format_daily_weather_text(self, item: Dict[str, Any]) -> str:
        day_weather = str(item.get("day_weather") or item.get("weather") or "").strip()
        night_weather = str(item.get("night_weather") or "").strip()
        if day_weather and night_weather and night_weather != day_weather:
            return f"{day_weather}转{night_weather}"
        return day_weather or night_weather or "待确认"

    def _looks_rainy_weather(self, weather_text: str) -> bool:
        text = str(weather_text or "").strip()
        return any(keyword in text for keyword in ("雨", "雪", "雷", "雾"))

    def _build_day_theme(self, destination: str, items: List[Dict[str, Any]]) -> str:
        names = self._dedupe_preserve_order(
            [str(item.get("name") or "").strip() for item in items if str(item.get("name") or "").strip()]
        )
        if names:
            return f"{'、'.join(names[:2])} 串联游"
        return f"{destination} 深度游"

    def _extract_food_pois(self, pois: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for poi in pois:
            if not isinstance(poi, dict):
                continue
            category = str(poi.get("category") or "").strip()
            tags = " ".join(str(tag).strip() for tag in (poi.get("tags") or []) if str(tag).strip())
            name = str(poi.get("name") or "").strip()
            if any(keyword in " ".join([category, tags, name]) for keyword in ["美食", "小吃", "夜市", "老街", "餐厅"]):
                result.append(poi)
        return result

    def _build_food_items_from_pois(self, pois: List[Dict[str, Any]]) -> List[str]:
        items: List[str] = []
        for poi in self._extract_food_pois(pois)[:4]:
            name = str(poi.get("name") or "").strip()
            tags = self._dedupe_preserve_order([str(tag).strip() for tag in (poi.get("tags") or []) if str(tag).strip()])
            if not name:
                continue
            if tags:
                items.append(f"{name}：适合安排 {'、'.join(tags[:2])} 相关的在地体验。")
            else:
                items.append(f"{name}：适合补充在地美食体验。")
        return items

    def _pick_food_spot(
        self,
        region: str,
        food_pois: List[Dict[str, Any]],
        used_food_names: List[str],
    ) -> Optional[Dict[str, Any]]:
        for poi in food_pois:
            name = str(poi.get("name") or "").strip()
            poi_region = str(poi.get("region") or poi.get("area") or "").strip()
            if not name or name in used_food_names:
                continue
            if region and poi_region and region in poi_region:
                return poi
        for poi in food_pois:
            name = str(poi.get("name") or "").strip()
            if name and name not in used_food_names:
                return poi
        return None

    def _dedupe_day_items(self, items: List[Dict[str, Any]], slot: str) -> List[Dict[str, Any]]:
        seen: List[str] = []
        result: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("time_slot") or "").strip() != slot:
                continue
            name = str(item.get("name") or "").strip()
            key = self._normalize_dedupe_key(name)
            if not key or key in seen:
                continue
            seen.append(key)
            result.append(item)
        return result

    def _extract_labeled_value(self, text: str, labels: List[str]) -> str:
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            line = self._clean_inline_text(raw_line)
            if not line:
                continue
            if any(label in line for label in labels):
                parts = re.split(r"[:：]\s*", line, maxsplit=1)
                if len(parts) == 2 and parts[1].strip():
                    return parts[1].strip()
        return ""

    def _extract_section_items(self, text: str, headings: List[str]) -> List[str]:
        block = self._extract_heading_block(text, headings)
        items: List[str] = []
        for line in block:
            clean = self._clean_inline_text(line)
            if not clean:
                continue
            if clean.endswith("：") and len(clean) <= 12:
                continue
            items.append(clean)
        return self._dedupe_preserve_order(items)

    def _extract_heading_block(self, text: str, headings: List[str]) -> List[str]:
        if not text:
            return []
        lines = [line.rstrip() for line in text.splitlines()]
        collected: List[str] = []
        capturing = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if capturing and collected:
                    continue
                continue
            clean = self._clean_inline_text(stripped)
            if any(heading in clean for heading in headings):
                capturing = True
                continue
            if capturing and (stripped.startswith("#") or stripped.startswith("---")):
                break
            if capturing:
                collected.append(stripped)
        return collected

    def _clean_inline_text(self, value: Any) -> str:
        text = self._strip_internal_display_fields(str(value or ""))
        text = re.sub(r"^[\-\*\u2022]+\s*", "", text.strip())
        text = re.sub(r"^\d+[.)、]\s*", "", text)
        text = text.replace("**", "").replace("__", "").replace("`", "")
        text = re.sub(r"\s+", " ", text)
        return text.strip(" -")

    def _is_ticket_related_text(self, value: Any) -> bool:
        text = self._clean_inline_text(value)
        if not text:
            return False
        keywords = ["门票", "票价", "联票", "套票", "景点票", "ticket"]
        lowered = text.lower()
        return any(keyword.lower() in lowered for keyword in keywords)

    def _dedupe_preserve_order(self, items: List[str]) -> List[str]:
        seen: List[str] = []
        result: List[str] = []
        for item in items:
            clean = str(item or "").strip()
            if not clean:
                continue
            key = self._normalize_dedupe_key(clean)
            if not key or key in seen:
                continue
            seen.append(key)
            result.append(clean)
        return result

    def _dedupe_structured_items(self, items: List[str]) -> List[str]:
        seen: List[str] = []
        result: List[str] = []
        for item in items:
            clean = str(item or "").strip()
            if not clean:
                continue
            key = self._normalize_structured_key(clean)
            if not key or key in seen:
                continue
            seen.append(key)
            result.append(clean)
        return result

    def _filter_distinct_items(self, items: List[str], references: List[str]) -> List[str]:
        reference_keys = [
            self._normalize_structured_key(item)
            for item in references
            if self._normalize_structured_key(item)
        ]
        result: List[str] = []
        for item in items:
            clean = str(item or "").strip()
            if not clean:
                continue
            key = self._normalize_structured_key(clean)
            if not key or key in reference_keys:
                continue
            result.append(clean)
        return result

    def _normalize_structured_key(self, value: str) -> str:
        key = self._clean_inline_text(value)
        key = re.sub(r"^[\u4e00-\u9fffA-Za-z]{1,8}[：:]\s*", "", key)
        key = re.sub(r"[（(]可节省约[^）)]*[）)]", "", key)
        key = re.sub(r"^[\u4e00-\u9fffA-Za-z]{1,8}\s*[|｜/]\s*", "", key)
        return self._normalize_dedupe_key(key)

    def _normalize_dedupe_key(self, value: str) -> str:
        key = str(value or "").strip().lower()
        key = re.sub(r"^\d+[.)、]\s*", "", key)
        key = re.sub(r"^[\-\*\u2022]+\s*", "", key)
        key = key.replace("**", "").replace("__", "").replace("`", "")
        key = re.sub(r"\s+", "", key)
        return key.strip("：:;；，,。.")

    def _dedupe_consecutive_lines(self, text: str) -> str:
        lines: List[str] = []
        previous_key = ""
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if not line:
                if lines and lines[-1] == "":
                    continue
                lines.append("")
                previous_key = ""
                continue
            if line.lstrip().startswith("|"):
                lines.append(line)
                previous_key = ""
                continue
            key = self._normalize_dedupe_key(line)
            if key and key == previous_key:
                continue
            lines.append(line)
            previous_key = key
        return "\n".join(lines).strip()

    def _normalize_spacing(self, text: str) -> str:
        cleaned = re.sub(r"\n{3,}", "\n\n", str(text or "").strip())
        return cleaned.strip()

    def _strip_internal_display_fields(self, text: str) -> str:
        result_lines: List[str] = []
        for raw_line in str(text or "").splitlines():
            line = raw_line.rstrip()
            if any(re.match(pattern, line, flags=re.IGNORECASE) for pattern in self.WEATHER_SOURCE_PATTERNS):
                continue
            result_lines.append(line)
        return "\n".join(result_lines)

    def _naturalize_weather_risks(self, risk_tags: List[str]) -> List[str]:
        tips: List[str] = []
        if "rain" in risk_tags:
            tips.append("有降雨信号，建议准备雨具并预留室内备选。")
        if "heat" in risk_tags:
            tips.append("白天气温偏高，户外活动尽量安排在上午或傍晚。")
        if "temperature_gap" in risk_tags:
            tips.append("早晚温差较明显，随身带一件轻薄外套更稳妥。")
        if "wind" in risk_tags:
            tips.append("风力偏大时，长时间户外停留和高处观景要更谨慎。")
        if "storm" in risk_tags:
            tips.append("如遇强对流或突发恶劣天气，优先切换为室内方案。")
        if not tips and risk_tags == []:
            tips.append("天气整体较平稳，适合按常规节奏出行。")
        return self._dedupe_preserve_order(tips)

    def _naturalize_conflict_message(self, message: str) -> str:
        clean = self._clean_inline_text(message)
        clean = clean.replace("warning", "").replace("info", "").strip("：: ")
        return clean

    def _format_pending_ticket_pois(self, names: List[Any], count: int, limit: int = 3) -> str:
        clean_names = self._dedupe_preserve_order(
            [str(name).strip() for name in names if str(name).strip()]
        )
        if not count:
            return ""
        if not clean_names:
            return f"{count} 个景点待确认"
        shown = clean_names[:limit]
        if len(clean_names) > limit or count > len(shown):
            return f"{'、'.join(shown)} 等 {count} 个景点"
        return "、".join(shown)

    def _first_non_empty_region(self, items: List[Dict[str, Any]]) -> str:
        for item in items:
            region = str(item.get("region") or item.get("city") or "").strip()
            if region:
                return region
        return ""

    def _format_money(self, amount: Optional[float]) -> str:
        if amount is None:
            return "待确认"
        rounded = round(amount, 2)
        if abs(rounded - int(rounded)) < 0.01:
            return f"¥{int(rounded)}"
        return f"¥{rounded:.2f}"

    def _format_temp_band(self, min_temp: Any, max_temp: Any) -> str:
        if min_temp is None and max_temp is None:
            return "暂未获取"
        if min_temp is None:
            return f"≤ {max_temp}℃"
        if max_temp is None:
            return f"≥ {min_temp}℃"
        return f"{min_temp}℃ - {max_temp}℃"

    def _safe_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _coerce_float(self, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _build_planner_result_data(self, planner_context: Dict[str, Any]) -> Dict[str, Any]:
        structured_summary = planner_context["structured_summary"]
        return {
            "decision_summary": planner_context["decision_summary"],
            "planning_rationale": planner_context["planning_rationale"],
            "conflicts": planner_context["conflicts"],
            "structured_summary": structured_summary,
            "poi_list": structured_summary.get("attraction", {}).get("pois"),
            "daily_plans": structured_summary.get("itinerary", {}).get("data", {}).get("daily_plans"),
            "budget_summary": {
                "total_budget": structured_summary.get("budget", {}).get("total_budget"),
                "confirmed_total_cost": structured_summary.get("budget", {}).get("confirmed_total_cost"),
                "per_day_budget": structured_summary.get("budget", {}).get("per_day_budget"),
                "is_over_budget": structured_summary.get("budget", {}).get("is_over_budget"),
                "transport_cost": structured_summary.get("budget", {}).get("transport_cost"),
                "hotel_cost": structured_summary.get("budget", {}).get("hotel_cost"),
                "food_cost": structured_summary.get("budget", {}).get("food_cost"),
                "ticket_cost": structured_summary.get("budget", {}).get("ticket_cost"),
                "confirmed_ticket_cost": structured_summary.get("budget", {}).get("confirmed_ticket_cost"),
                "pending_ticket_count": structured_summary.get("budget", {}).get("pending_ticket_count"),
                "pending_ticket_pois": structured_summary.get("budget", {}).get("pending_ticket_pois"),
                "estimated_by": structured_summary.get("budget", {}).get("estimated_by"),
            },
        }

    def _iter_content_chunks(self, content: str, chunk_size: int = 200):
        if not content:
            return
        for index in range(0, len(content), chunk_size):
            yield content[index:index + chunk_size]

    def _build_other_results_text(self, agent_results: Dict[str, Dict[str, Any]]) -> str:
        parts: List[str] = []
        label_map = {
            "attraction": "景点信息",
            "itinerary": "行程信息",
            "budget": "预算信息",
            "weather": "天气信息",
        }
        for agent_name in ["attraction", "itinerary", "budget", "weather"]:
            result = agent_results.get(agent_name)
            if not result:
                continue
            content = result.get("content", "").strip()
            if not content:
                continue
            parts.append(f"{label_map.get(agent_name, agent_name)}：\n{content}")
        return "\n\n".join(parts) if parts else "暂无其他 Agent 文本结果"

    def _build_structured_summary(
        self,
        session: SessionContext,
        context: ExecutionContext,
        agent_results: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        attraction_data = agent_results.get("attraction", {}).get("data", {})
        itinerary_data = agent_results.get("itinerary", {}).get("data", {})
        budget_data = agent_results.get("budget", {}).get("data", {})
        weather_data = agent_results.get("weather", {}).get("data", {})

        attraction_content = agent_results.get("attraction", {}).get("content", "")
        itinerary_content = agent_results.get("itinerary", {}).get("content", "")
        budget_content = agent_results.get("budget", {}).get("content", "")
        weather_content = agent_results.get("weather", {}).get("content", "")
        weather_risk_tags = weather_data.get("risk_tags")
        if not isinstance(weather_risk_tags, list):
            weather_risk_tags = self._extract_weather_risks(weather_content)

        pois = attraction_data.get("pois")
        if not isinstance(pois, list):
            pois = []

        traveler_profile = self._build_traveler_profile(session, context)
        itinerary_days = self._extract_day_count(itinerary_content, context.extracted_info.get("duration", 3))
        daily_poi_count = self._estimate_daily_poi_count(itinerary_content, itinerary_days, len(pois))
        rest_detected = any(keyword in itinerary_content for keyword in ["??", "??", "????"])
        cross_region_detected = self._count_cross_region_signals(pois)
        outdoor_ratio = self._estimate_outdoor_ratio(pois, attraction_content, itinerary_content)

        return {
            "attraction": {
                "pois": pois,
                "poi_count": len(pois),
                "regions": self._extract_regions(pois),
                "outdoor_ratio": outdoor_ratio,
            },
            "itinerary": {
                "data": itinerary_data,
                "content": itinerary_content,
                "days": itinerary_days,
                "daily_poi_count": daily_poi_count,
                "rest_detected": rest_detected,
                "cross_region_detected": cross_region_detected,
                "feasibility_notes": self._extract_feasibility_notes(itinerary_content),
            },
            "budget": {
                "data": budget_data,
                "content": budget_content,
                "total_budget": budget_data.get("total_budget"),
                "confirmed_total_cost": budget_data.get("confirmed_total_cost"),
                "daily_budget": budget_data.get("daily_budget"),
                "per_person_budget": budget_data.get("per_person_budget"),
                "per_day_budget": budget_data.get("per_day_budget"),
                "transport_cost": budget_data.get("transport_cost"),
                "hotel_cost": budget_data.get("hotel_cost"),
                "food_cost": budget_data.get("food_cost"),
                "ticket_cost": budget_data.get("ticket_cost"),
                "confirmed_ticket_cost": budget_data.get("confirmed_ticket_cost"),
                "other_cost": budget_data.get("other_cost"),
                "buffer_cost": budget_data.get("buffer_cost"),
                "is_over_budget": budget_data.get("is_over_budget"),
                "budget_limit": budget_data.get("budget_limit"),
                "estimated_by": budget_data.get("estimated_by"),
                "budget_breakdown": budget_data.get("budget_breakdown"),
                "optimization_suggestions": budget_data.get("optimization_suggestions"),
                "pending_ticket_count": budget_data.get("pending_ticket_count"),
                "pending_ticket_pois": budget_data.get("pending_ticket_pois"),
                "has_pending_ticket_cost": budget_data.get("has_pending_ticket_cost"),
                "free_ticket_count": budget_data.get("free_ticket_count"),
                "known_ticket_count": budget_data.get("known_ticket_count"),
                "ticket_cost_summary": budget_data.get("ticket_cost_summary"),
            },
            "weather": {
                "data": weather_data,
                "content": weather_content,
                "risk_tags": weather_risk_tags,
            },
            "profile": traveler_profile,
        }

    def _build_section_presence_summary(
        self,
        agent_results: Dict[str, Dict[str, Any]],
        structured_summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        summary: Dict[str, Any] = {}
        for agent_name in ["attraction", "itinerary", "budget", "weather"]:
            result = agent_results.get(agent_name, {})
            data = result.get("data") if isinstance(result, dict) else {}
            if not isinstance(data, dict):
                data = {}
            section = structured_summary.get(agent_name, {}) if isinstance(structured_summary, dict) else {}
            summary[agent_name] = {
                "content_len": len(str(result.get("content") or "")) if isinstance(result, dict) else 0,
                "data_keys": sorted(data.keys()),
                "pois_len": len(data.get("pois")) if isinstance(data.get("pois"), list) else 0,
                "poi_list_len": len(data.get("poi_list")) if isinstance(data.get("poi_list"), list) else 0,
                "daily_plans_len": len(data.get("daily_plans")) if isinstance(data.get("daily_plans"), list) else 0,
                "budget_breakdown_keys": sorted((data.get("budget_breakdown") or {}).keys()) if isinstance(data.get("budget_breakdown"), dict) else [],
                "section_has_content": bool(section),
            }
        return summary

    def _build_traveler_profile(self, session: SessionContext, context: ExecutionContext) -> Dict[str, Any]:
        tourist_type = context.extracted_info.get("tourist_type") or session.preferences.tourist_type or "general"
        travel_styles = context.extracted_info.get("travel_styles") or session.preferences.travel_style or []
        traveler_ages = session.trip_context.traveler_ages if session and session.trip_context else []
        recent_text = " ".join(turn.user_message for turn in session.get_recent_messages(3)) if session else ""

        is_family = tourist_type == "family" or "亲子" in travel_styles or any(k in recent_text for k in ["亲子", "带娃", "孩子", "小孩", "家庭"])
        is_senior = tourist_type == "senior" or any(age >= 60 for age in traveler_ages) or any(k in recent_text for k in ["老人", "长辈", "爸妈"])
        relaxed = is_family or is_senior or "休闲" in travel_styles

        return {
            "tourist_type": tourist_type,
            "travel_styles": travel_styles,
            "is_family": is_family,
            "is_senior": is_senior,
            "relaxed_mode": relaxed,
        }

    def _extract_regions(self, pois: List[Dict[str, Any]]) -> List[str]:
        regions: List[str] = []
        for poi in pois:
            region = str(poi.get("region") or poi.get("district") or poi.get("area") or "").strip()
            if region and region not in regions:
                regions.append(region)
        return regions

    def _estimate_outdoor_ratio(self, pois: List[Dict[str, Any]], attraction_content: str, itinerary_content: str) -> float:
        if pois:
            outdoor_keywords = ["公园", "山", "湖", "徒步", "夜游", "海边", "景区", "古镇"]
            outdoor_count = 0
            for poi in pois:
                text = " ".join(str(value) for value in [poi.get("name", ""), *(poi.get("tags", []) or [])])
                if any(keyword in text for keyword in outdoor_keywords):
                    outdoor_count += 1
            return outdoor_count / max(len(pois), 1)
        combined = f"{attraction_content}\n{itinerary_content}"
        if any(keyword in combined for keyword in ["徒步", "公园", "湖", "山", "夜景"]):
            return 0.7
        return 0.4

    def _extract_day_count(self, itinerary_content: str, fallback_duration: Any) -> int:
        matches = re.findall(r"Day\s*\d+|第\s*\d+\s*天", itinerary_content, flags=re.IGNORECASE)
        if matches:
            return len(matches)
        try:
            return int(fallback_duration or 3)
        except (TypeError, ValueError):
            return 3

    def _estimate_daily_poi_count(self, itinerary_content: str, days: int, poi_count: int) -> float:
        poi_markers = len(re.findall(r"景点|景区|公园|博物馆|古镇|乐园", itinerary_content))
        if poi_markers > 0 and days > 0:
            return round(poi_markers / days, 1)
        if poi_count > 0 and days > 0:
            return round(poi_count / days, 1)
        return 0.0

    def _count_cross_region_signals(self, pois: List[Dict[str, Any]]) -> int:
        regions = self._extract_regions(pois)
        if len(regions) <= 1:
            return 0
        return len(regions) - 1

    def _extract_feasibility_notes(self, itinerary_content: str) -> List[str]:
        notes: List[str] = []
        for line in itinerary_content.splitlines():
            if "约束摘要" in line or "备注" in line or "校验" in line or "通勤" in line:
                clean_line = line.strip("- ").strip()
                if clean_line:
                    notes.append(clean_line)
        return notes[:6]

    def _extract_weather_risks(self, weather_content: str) -> List[str]:
        risk_map = {
            "rain": ["下雨", "小雨", "中雨", "大雨", "暴雨", "降雨", "雨具"],
            "heat": ["高温", "炎热", "暴晒", "紫外线"],
            "cold": ["降温", "低温", "寒冷", "温差"],
            "wind": ["大风", "风力", "阵风"],
        }
        risks: List[str] = []
        for risk_name, keywords in risk_map.items():
            if any(keyword in weather_content for keyword in keywords):
                risks.append(risk_name)
        return risks

    def _check_conflicts(
        self,
        session: SessionContext,
        context: ExecutionContext,
        structured_summary: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        conflicts: List[Dict[str, str]] = []
        conflicts.extend(self._check_weather_conflicts(structured_summary))
        conflicts.extend(self._check_budget_conflicts(context, structured_summary))
        conflicts.extend(self._check_intensity_conflicts(session, context, structured_summary))
        conflicts.extend(self._check_feasibility_conflicts(structured_summary))
        return conflicts

    def _check_weather_conflicts(self, structured_summary: Dict[str, Any]) -> List[Dict[str, str]]:
        risks = structured_summary["weather"]["risk_tags"]
        outdoor_ratio = structured_summary["attraction"]["outdoor_ratio"]
        conflicts: List[Dict[str, str]] = []
        if "rain" in risks and outdoor_ratio >= 0.5:
            conflicts.append({
                "type": "weather",
                "level": "warning",
                "message": "天气包含降雨信号，但当前景点组合偏户外，建议准备雨具或保留室内备选。",
            })
        if "heat" in risks and outdoor_ratio >= 0.5:
            conflicts.append({
                "type": "weather",
                "level": "warning",
                "message": "天气存在高温风险，需控制午间户外暴晒并增加休息补水提示。",
            })
        return conflicts

    def _check_budget_conflicts(self, context: ExecutionContext, structured_summary: Dict[str, Any]) -> List[Dict[str, str]]:
        budget_info = structured_summary["budget"]
        budget_total = self._coerce_float(budget_info.get("confirmed_total_cost") or budget_info.get("total_budget"))
        confirmed_ticket_total = self._coerce_float(budget_info.get("confirmed_ticket_cost"))
        if confirmed_ticket_total is None:
            confirmed_ticket_total = self._coerce_float(budget_info.get("ticket_cost")) or 0.0
        pending_ticket_count = self._safe_int(budget_info.get("pending_ticket_count"), default=0)
        daily_budget = self._coerce_float(budget_info.get("daily_budget"))

        conflicts: List[Dict[str, str]] = []
        if pending_ticket_count > 0:
            if budget_total and confirmed_ticket_total > budget_total * 0.35 and confirmed_ticket_total > 0:
                conflicts.append({
                    "type": "budget",
                    "level": "warning",
                    "message": f"当前已确认门票约 {int(confirmed_ticket_total)} 元，另有 {pending_ticket_count} 个景点门票待确认，票务支出可能继续上浮，建议关注取舍与联票。",
                })
            else:
                conflicts.append({
                    "type": "budget",
                    "level": "info",
                    "message": f"当前有 {pending_ticket_count} 个景点门票待确认，最终票务支出可能上浮，建议出发前再核实票价和预约要求。",
                })
            return conflicts

        if budget_total and confirmed_ticket_total > budget_total * 0.35:
            conflicts.append({
                "type": "budget",
                "level": "warning",
                "message": f"按当前已确认景点门票估算约 {int(confirmed_ticket_total)} 元，票务占总预算偏高，建议关注取舍与联票。",
            })
        if daily_budget and confirmed_ticket_total > daily_budget:
            conflicts.append({
                "type": "budget",
                "level": "info",
                "message": "当前已确认景点门票成本可能接近日均预算上限，餐饮与交通安排需更保守。",
            })
        return conflicts

    def _check_intensity_conflicts(
        self,
        session: SessionContext,
        context: ExecutionContext,
        structured_summary: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        profile = structured_summary["profile"]
        itinerary = structured_summary["itinerary"]
        conflicts: List[Dict[str, str]] = []

        if profile["relaxed_mode"] and itinerary["daily_poi_count"] > 3:
            conflicts.append({
                "type": "intensity",
                "level": "warning",
                "message": "当前用户画像偏低强度，但行程中单日景点数量偏多，建议控制节奏。",
            })
        if profile["relaxed_mode"] and not itinerary["rest_detected"]:
            conflicts.append({
                "type": "intensity",
                "level": "warning",
                "message": "当前用户画像偏低强度，但行程文本中休息/午餐安排不明显，需重点提醒。",
            })
        if profile["relaxed_mode"] and itinerary["cross_region_detected"] > itinerary["days"]:
            conflicts.append({
                "type": "intensity",
                "level": "info",
                "message": "景点涉及区域较多，老人/亲子场景下应减少跨区奔波。",
            })
        return conflicts

    def _check_feasibility_conflicts(self, structured_summary: Dict[str, Any]) -> List[Dict[str, str]]:
        notes = structured_summary["itinerary"]["feasibility_notes"]
        conflicts: List[Dict[str, str]] = []
        for note in notes:
            if "需关注" in note or "超出" in note:
                conflicts.append({
                    "type": "feasibility",
                    "level": "warning",
                    "message": f"行程可行性提示：{note}",
                })
        return conflicts

    def _build_planning_rationale(
        self,
        structured_summary: Dict[str, Any],
        conflicts: List[Dict[str, str]],
    ) -> List[str]:
        rationale: List[str] = []
        regions = structured_summary["attraction"]["regions"]
        if regions:
            rationale.append(f"优先按区域整合景点，当前主要涉及：{'、'.join(regions[:4])}。")
        if structured_summary["itinerary"]["rest_detected"]:
            rationale.append("行程中保留了午餐或休息时段，避免连续高强度移动。")
        if structured_summary["budget"]["total_budget"]:
            rationale.append("已将预算结果纳入总控，优先避免门票与日预算明显冲突。")
        if structured_summary["weather"]["risk_tags"]:
            rationale.append("已检查天气风险，并将雨天/高温等提醒并入最终建议。")
        if structured_summary["profile"]["relaxed_mode"]:
            rationale.append("考虑到用户画像偏低强度，优先控制单日节奏与跨区域奔波。")
        if structured_summary["itinerary"]["feasibility_notes"]:
            rationale.append("已吸收行程侧的通勤、约束和可行性提示，避免让模型自由打乱安排。")
        if conflicts:
            rationale.append("最终方案会明确保留已识别风险和调整建议，而不是隐藏冲突。")
        return rationale

    def _build_decision_summary(
        self,
        structured_summary: Dict[str, Any],
        conflicts: List[Dict[str, str]],
        planning_rationale: List[str],
    ) -> str:
        lines = [
            f"结构化整合：景点 {structured_summary['attraction']['poi_count']} 个，行程 {structured_summary['itinerary']['days']} 天。",
            f"预算参考：{structured_summary['budget']['total_budget'] or '未提供'}，天气风险：{', '.join(structured_summary['weather']['risk_tags']) if structured_summary['weather']['risk_tags'] else '未识别明显风险'}。",
            f"用户画像：{structured_summary['profile']['tourist_type']}，低强度模式：{'是' if structured_summary['profile']['relaxed_mode'] else '否'}。",
        ]
        if conflicts:
            lines.append("冲突检查结果：" + "；".join(conflict["message"] for conflict in conflicts[:4]))
        if planning_rationale:
            lines.append("安排依据：" + "；".join(planning_rationale[:5]))
        return "\n".join(lines)

    def _build_planner_prompt(
        self,
        destination: Any,
        duration: Any,
        num_travelers: Any,
        budget: Any,
        travel_styles: List[str],
        planner_context: Dict[str, Any],
    ) -> str:
        final_content = str(planner_context.get("final_content") or "").strip()
        return (
            "你是旅游规划助手的最终文案渲染器。\n"
            "请逐字输出下面这份已经校验完成的最终旅游规划，不要改写标题、emoji、Day 层级、表格列名或段落结构。\n\n"
            f"{self.STREAM_CANONICAL_PLAN_MARKER}\n"
            f"{final_content}"
        )

    def _parse_price(self, price_text: str) -> float:
        if not price_text or "免费" in price_text:
            return 0.0
        numbers = [float(match) for match in re.findall(r"\d+(?:\.\d+)?", price_text)]
        return min(numbers) if numbers else 0.0
