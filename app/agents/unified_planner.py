"""
统一旅行规划 Agent。
单 Agent / 单轮规划 baseline 实现，用于与多 Agent 主流程做实验对比。
默认主链路仍然是多 Agent 协同方案，`unified_planner` 不作为默认执行链路。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.base import AgentCapability, AgentConfig, AgentResponse, AgentStatus, BaseAgent
from app.core.context import ExecutionContext, SessionContext
from app.core.logger import get_logger

logger = get_logger(__name__)


UNIFIED_AGENT_CONFIG = AgentConfig(
    name="unified_planner",
    description="统一规划 Agent，单次调用完成所有任务的 baseline 实现",
    instructions="""你是一位热情专业的旅游规划助手，可以在单次 LLM 调用中完成景点推荐、行程规划、预算分析等任务。
注意：该实现用于单 Agent / 单轮规划 baseline 对比，不替代多 Agent 主流程。
请输出完整、可读、结构清晰的旅游规划结果。
""",
    capabilities=[
        AgentCapability.PLANNING,
        AgentCapability.REASONING,
        AgentCapability.EXECUTION,
    ],
    max_retries=3,
    timeout_seconds=90,
)


class UnifiedPlannerAgent(BaseAgent):
    """
    统一规划 Agent。
    保留为单 Agent / 单轮规划 baseline，用于与多 Agent 协同流程做实验对比。
    默认不作为系统主链路。
    """

    def __init__(self, llm=None, **kwargs):
        super().__init__(UNIFIED_AGENT_CONFIG, llm)

    async def plan(
        self,
        session: SessionContext,
        context: ExecutionContext,
    ) -> List[str]:
        return ["unified_execute"]

    async def execute(
        self,
        session: SessionContext,
        context: ExecutionContext,
    ) -> AgentResponse:
        params = self._resolve_params(session, context)

        system_prompt = f"""你是一位热情专业的旅游规划助手，正在为用户规划一次完整的 {params['destination']} 旅行。
规划参数：
- 目的地：{params['destination']}
- 行程天数：{params['duration']} 天
- 出行人数：{params['num_travelers']} 人
- 预算：{params['budget']}
- 旅行风格：{params['styles_str']}

请一次性输出完整旅游规划（Markdown 格式），包括：
1. 目的地概览
2. 每日行程
3. 预算估算
4. 实用贴士

多用 emoji，内容清晰、完整、可读。
"""

        messages = self.build_messages(session, system_prompt)

        try:
            self._record_tool_usage(
                context or self._build_fallback_context(session),
                step_name="统一规划",
                tool_name="llm_chat",
                arguments={"model": "default", "messages_count": len(messages)},
            )

            response = await self.chat(messages)

            return AgentResponse(
                agent_name=self.name,
                status=AgentStatus.COMPLETED,
                content=response.content,
                tokens_used=response.usage.get("total_tokens", 0),
                metadata={
                    "destination": params["destination"],
                    "duration": params["duration"],
                    "num_travelers": params["num_travelers"],
                    "llm_calls_saved": 4,
                    "mode": "single_agent_baseline",
                    "baseline": True,
                },
            )
        except Exception as e:
            logger.exception(f"Unified planner failed: {e}")
            return AgentResponse(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                content="",
                error=str(e),
            )

    async def execute_stream(
        self,
        session: SessionContext,
        context: ExecutionContext,
    ):
        """流式执行统一规划，仅作为单 Agent baseline 流式入口，不作为系统默认主链路。"""
        params = self._resolve_params(session, context)

        system_prompt = f"""你是一位热情专业的旅游规划助手，正在为用户规划一次完整的 {params['destination']} 旅行。
规划参数：目的地={params['destination']}，{params['duration']}天，{params['num_travelers']}人，预算={params['budget']}，风格={params['styles_str']}

请输出完整的旅游规划，包括：
1. 目的地概览
2. 每日行程
3. 预算估算
4. 实用贴士

使用 Markdown 格式，多用 emoji。
"""

        messages = self.build_messages(session, system_prompt)

        buffer = ""
        # Keep the complete stream for the final AgentResponse content.
        full_content = ""
        tokens_count = 0

        try:
            async for token in self.chat_stream(messages):
                buffer += token
                full_content += token
                tokens_count += 1
                if len(buffer) >= 5 or token.endswith("\n"):
                    yield buffer
                    buffer = ""

            if buffer:
                yield buffer

            yield AgentResponse(
                agent_name=self.name,
                status=AgentStatus.COMPLETED,
                content=full_content,
                tokens_used=tokens_count,
                metadata={
                    "destination": params["destination"],
                    "duration": params["duration"],
                    "mode": "single_agent_baseline",
                    "baseline": True,
                },
            )
        except Exception as e:
            logger.exception(f"Unified stream failed: {e}")
            yield AgentResponse(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                content="",
                error=str(e),
            )

    def _resolve_params(self, session: SessionContext, context: Optional[ExecutionContext]) -> Dict[str, Any]:
        extracted = context.extracted_info if context else {}
        destination = extracted.get("destination") or session.trip_context.destination or "未知"
        duration = extracted.get("duration") or session.trip_context.duration_days or 3
        num_travelers = extracted.get("num_travelers") or session.trip_context.num_travelers or 2
        budget = extracted.get("budget") or extracted.get("budget_level") or session.preferences.budget_level or "中等"
        travel_styles = extracted.get("travel_styles") or session.preferences.travel_style or ["休闲"]
        styles_str = ", ".join(travel_styles) if isinstance(travel_styles, list) else str(travel_styles)

        return {
            "destination": destination,
            "duration": duration,
            "num_travelers": num_travelers,
            "budget": budget,
            "travel_styles": travel_styles,
            "styles_str": styles_str,
        }

    def _build_fallback_context(self, session: SessionContext) -> ExecutionContext:
        return ExecutionContext(request_id="unified-baseline", session_id=session.session_id)
