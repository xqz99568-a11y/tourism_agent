"""
统一旅行规划 API 端点
使用统一规划器减少 LLM 调用
"""
from __future__ import annotations

from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from app.core.agent_cache import get_agent_cache, init_agent_cache
from app.core.optimized_orchestrator import OptimizedAgentOrchestrator, UnifiedAgentExecutor
from app.core.cache_monitor import get_cache_monitor, init_cache_monitor
from app.core.context import SessionContext
from app.core.llm.manager import get_llm_manager
from app.core.logger import get_logger
from app.core.tracing import (
    finish_agent_run,
    is_experiment_cache_disabled,
    record_tool_call,
    request_trace,
    start_agent_run,
)
from app.schemas import IntentType

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["优化规划"])


class UnifiedPlanRequest(BaseModel):
    """统一规划请求"""
    destination: str = Field(..., description="目的地")
    duration: int = Field(default=3, ge=1, le=30, description="行程天数")
    num_travelers: int = Field(default=2, ge=1, le=20, description="出行人数")
    budget_level: str = Field(default="medium", description="预算级别: economy/medium/luxury")
    travel_styles: List[str] = Field(default_factory=lambda: ["休闲"], description="旅行风格")
    use_cache: bool = Field(default=True, description="是否使用缓存")
    use_unified_agent: bool = Field(default=True, description="是否使用统一规划Agent（减少LLM调用）")


class UnifiedPlanResponse(BaseModel):
    """统一规划响应"""
    success: bool
    content: str
    intent: str
    cache_hit: bool = False
    llm_calls_saved: int = 0
    tokens_used: int = 0
    execution_time_ms: float
    cache_stats: Optional[Dict[str, Any]] = None


class CacheStatsResponse(BaseModel):
    """缓存统计响应"""
    agent_cache: Dict[str, Any]
    llm_cache: Dict[str, Any]
    optimization_stats: Dict[str, Any]


@router.post("/plan/unified", response_model=UnifiedPlanResponse)
async def unified_plan(request: UnifiedPlanRequest) -> UnifiedPlanResponse:
    """
    统一旅行规划接口
    通过单次 LLM 调用完成所有规划任务，减少调用次数
    """
    from app.core.di import get_container
    from app.agents.unified_planner import UnifiedPlannerAgent
    import time
    import uuid

    start_time = time.time()
    request_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    with request_trace(request_id, session_id):
        # 初始化组件
        llm = get_llm_manager()
        cache = get_agent_cache()

        # 检查缓存
        cache_hit = False
        extracted_info = {
            "destination": request.destination,
            "duration": request.duration,
            "num_travelers": request.num_travelers,
            "budget_level": request.budget_level,
            "travel_styles": request.travel_styles,
        }

        cache_allowed = request.use_cache and not is_experiment_cache_disabled()
        if cache_allowed:
            cached = cache.get(
                agent_name="unified_planner",
                intent_type="trip_planning",
                extracted_info=extracted_info,
            )
            if cached:
                cache_hit = True
                elapsed = (time.time() - start_time) * 1000
                record_tool_call(
                    "agent_cache",
                    params={"agent_name": "unified_planner", "intent_type": "trip_planning"},
                    duration_ms=elapsed,
                    status="completed",
                    success=True,
                    component="unified_plan_api",
                    cache_hit=True,
                    fallback_used=False,
                )
                return UnifiedPlanResponse(
                    success=True,
                    content=cached.content,
                    intent="trip_planning",
                    cache_hit=True,
                    llm_calls_saved=1,
                    execution_time_ms=elapsed,
                )

        # 创建会话
        session = SessionContext(
            session_id=session_id,
        )
        session.trip_context.destination = request.destination
        session.trip_context.num_travelers = request.num_travelers
        session.trip_context.duration_days = request.duration
        session.preferences.budget_level = request.budget_level
        session.preferences.travel_style = request.travel_styles

        # 执行统一规划
        unified_agent = UnifiedPlannerAgent(llm=llm)
        streaming_content = ""
        agent_run = start_agent_run("unified_planner")
        tokens_used = 0

        try:
            async for result in unified_agent.execute_stream(session, None):
                if isinstance(result, str):
                    streaming_content += result
                elif hasattr(result, 'content'):
                    streaming_content = result.content
                    tokens_used = int(getattr(result, "tokens_used", 0) or 0)

            finish_agent_run(
                agent_run,
                agent_name="unified_planner",
                status="completed",
                tokens=tokens_used,
                tool_count=0,
            )

            # 缓存结果
            if cache_allowed and streaming_content:
                cache.set(
                    agent_name="unified_planner",
                    intent_type="trip_planning",
                    extracted_info=extracted_info,
                    content=streaming_content,
                )

            elapsed = (time.time() - start_time) * 1000

            return UnifiedPlanResponse(
                success=True,
                content=streaming_content,
                intent="trip_planning",
                cache_hit=cache_hit,
                llm_calls_saved=0,
                execution_time_ms=elapsed,
            )

        except Exception as e:
            finish_agent_run(
                agent_run,
                agent_name="unified_planner",
                status="failed",
                tokens=tokens_used,
                tool_count=0,
                error=e,
            )
            logger.exception(f"Unified plan failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/cache/stats", response_model=CacheStatsResponse)
async def get_optimization_stats() -> CacheStatsResponse:
    """
    获取缓存和优化统计
    """
    monitor = get_cache_monitor()
    snapshot = monitor.get_snapshot()

    return CacheStatsResponse(
        agent_cache=snapshot.agent_cache,
        llm_cache=snapshot.llm_cache,
        optimization_stats={
            "total_llm_calls_saved": snapshot.optimization_stats.total_llm_calls_saved,
            "total_tokens_saved": snapshot.optimization_stats.total_tokens_saved,
            "cache_hit_rate": snapshot.optimization_stats.cache_hit_rate,
            "requests_served": snapshot.optimization_stats.requests_served,
        },
    )


@router.post("/cache/clear")
async def clear_cache(
    agent_name: Optional[str] = None,
    destination: Optional[str] = None,
) -> Dict[str, Any]:
    """
    清除缓存
    """
    cache = get_agent_cache()
    count = cache.invalidate(agent_name=agent_name, destination=destination)

    return {
        "success": True,
        "entries_cleared": count,
    }


@router.get("/cache/recommendations")
async def get_cache_recommendations() -> Dict[str, Any]:
    """
    获取优化建议
    """
    monitor = get_cache_monitor()

    return {
        "recommendations": monitor.get_recommendations(),
        "current_stats": monitor.get_summary(),
    }
