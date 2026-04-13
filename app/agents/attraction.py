"""
Attraction Agent
"""
# ruff: noqa: UP006, UP035, UP045
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agents.base import AgentCapability, AgentConfig, AgentResponse, AgentStatus, BaseAgent
from app.core.context import ExecutionContext, SessionContext
from app.core.logger import get_logger
from app.tools.poi_search import POIDetailTool, POISearchTool

logger = get_logger(__name__)

POI = Dict[str, Any]
TOP_N = 6
MAX_SEARCH_QUERIES = 4
SEARCH_LIMIT = 8
ATTRACTION_IO_CONCURRENCY = 4
LOCAL_POI_DIR = Path(__file__).resolve().parents[2] / "data" / "pois"

CATEGORY_STANDARD_VALUES = {
    "nature", "history", "museum", "landmark", "shopping", "food",
    "leisure", "nightlife", "cultural", "other"
}

BEST_TIME_VALUES = {"morning", "afternoon", "evening", "flexible"}
PRIORITY_VALUES = {"high", "medium", "low"}
INDOOR_OUTDOOR_VALUES = {"indoor", "outdoor", "mixed"}


ATTRACTION_CONFIG = AgentConfig(
    name="attraction",
    description="景点推荐 Agent，负责搜索和推荐旅游景点",
    instructions="你是一位资深旅游顾问，请优先基于真实 POI 检索结果给出推荐。",
    capabilities=[AgentCapability.SEARCH, AgentCapability.REASONING],
    max_retries=3,
    timeout_seconds=45,
    tools=["poi_search", "poi_detail"],
)


class AttractionAgent(BaseAgent):
    """负责景点搜索和推荐。"""

    def __init__(self, llm=None, **kwargs):
        super().__init__(ATTRACTION_CONFIG, llm)
        self.poi_search_tool = POISearchTool()
        self.poi_detail_tool = POIDetailTool()
        self._local_poi_cache: Dict[str, List[POI]] = {}

    async def plan(self, session: SessionContext, context: ExecutionContext) -> List[str]:
        return ["search_pois_by_destination", "enrich_top_pois", "summarize_recommendations"]

    async def execute(self, session: SessionContext, context: ExecutionContext) -> AgentResponse:
        inputs = self._normalize_attraction_inputs(session, context)
        destination = inputs.get("destination") or ""
        travel_styles = inputs.get("travel_style") or []
        interests = inputs.get("interests") or []
        special_requirements = inputs.get("special_requirements") or []
        tourist_type = str(inputs.get("group_type") or (session.preferences.tourist_type if session and session.preferences else "general")).strip()
        request_cache: Dict[str, Dict[Any, Any]] = {"poi_search": {}, "poi_detail": {}}

        if not destination:
            return AgentResponse(
                agent_name=self.name,
                status=AgentStatus.COMPLETED,
                content="请先告诉我你想去哪里旅行，我再基于真实景点检索为你推荐。",
            )

        execute_start = time.perf_counter()
        self._set_context_info("destination", destination)
        self._set_context_info("travel_styles", travel_styles)
        self._set_context_info("interests", interests)
        self._set_context_info("special_requirements", special_requirements)
        self._set_context_info("tourist_type", tourist_type)

        self._record_thinking_reasoning(
            context,
            step_name="分析需求",
            reasoning_content=(
                f"目的地：{destination}\n旅行风格：{'、'.join(travel_styles) if travel_styles else '综合'}\n"
                f"兴趣偏好：{'、'.join(interests) if interests else '未指定'}\n"
                f"特殊需求：{'、'.join(special_requirements) if special_requirements else '无'}\n游客类型：{tourist_type}"
            ),
            reasoning_type="analysis",
        )

        search_keywords = self._build_search_keywords(destination, travel_styles, interests, special_requirements, tourist_type)
        self._record_thinking_reasoning(
            context,
            step_name="检索策略",
            reasoning_content=f"将按以下关键词真实检索 POI：{', '.join(search_keywords)}",
            reasoning_type="decision",
        )

        try:
            candidates = await self._search_candidates_concurrent(context, destination, search_keywords, request_cache)
            if not candidates:
                content = (
                    f"我已经尝试通过真实 POI 检索为你查找 {destination} 的景点，但当前没有拿到足够可靠的候选结果。"
                    "建议补充更具体的兴趣词，比如博物馆、亲子、夜景、老街等，我再继续帮你筛。"
                )
                fallback_data = self._build_attraction_result(inputs, [], content, 0, search_keywords, [], 0)
                response = AgentResponse(
                    agent_name=self.name,
                    status=AgentStatus.COMPLETED,
                    content=content,
                    data=fallback_data,
                    tool_calls=self._serialize_tool_calls(),
                    metadata={"selected_poi_count": 0, "detail_poi_count": 0, "knowledge_hits": 0},
                )
                self._record_stage_timing(
                    context,
                    "attraction",
                    (time.perf_counter() - execute_start) * 1000,
                    poi_count=0,
                )
                return response

            local_knowledge = self._load_local_pois(destination)
            top_candidates = self._select_top_candidates(destination, candidates, travel_styles, interests, special_requirements, tourist_type, local_knowledge)
            self._record_thinking_reasoning(
                context,
                step_name="筛选候选",
                reasoning_content=self._build_selection_summary(top_candidates),
                reasoning_type="decision",
            )

            detailed_candidates = await self._fetch_details_concurrent(context, top_candidates, request_cache)
            structured_pois = self._build_structured_pois(detailed_candidates)
            knowledge_hits = sum(1 for poi in structured_pois if poi.get("knowledge_source"))

            self._record_thinking_reasoning(
                context,
                step_name="知识补充",
                reasoning_content=(
                    f"已对 Top-{len(top_candidates)} 候选补充真实详情，"
                    f"其中 {knowledge_hits} 个景点命中本地 POI 知识数据，用于补全开放时间、门票、时长和适配标签。"
                ),
                reasoning_type="fact",
            )

            llm_summary_start = time.perf_counter()
            content, tokens_used = await self._generate_recommendation_content(
                session, destination, travel_styles, interests, special_requirements, tourist_type, structured_pois
            )
            self._record_stage_timing(
                context,
                "attraction.llm_summary",
                (time.perf_counter() - llm_summary_start) * 1000,
                poi_count=len(structured_pois),
            )
            self._record_thinking_reasoning(
                context,
                step_name="生成推荐",
                reasoning_content=f"景点推荐完成，共返回 {len(structured_pois)} 个结构化 POI。",
                reasoning_type="decision",
            )

            result_data = self._build_attraction_result(
                inputs,
                structured_pois,
                content,
                tokens_used,
                search_keywords,
                top_candidates,
                knowledge_hits,
            )

            response = AgentResponse(
                agent_name=self.name,
                status=AgentStatus.COMPLETED,
                content=content,
                tokens_used=tokens_used,
                data=result_data,
                tool_calls=self._serialize_tool_calls(),
                metadata={
                    "selected_poi_count": len(top_candidates),
                    "detail_poi_count": len(structured_pois),
                    "knowledge_hits": knowledge_hits,
                    "poi_list_count": len(result_data.get("poi_list", [])),
                },
            )
            self._record_stage_timing(
                context,
                "attraction",
                (time.perf_counter() - execute_start) * 1000,
                poi_count=len(structured_pois),
            )
            return response
        except Exception as e:
            logger.exception(f"Attraction agent failed: {e}")
            self._record_thinking_complete(context, step_name="搜索失败", result_summary=f"景点推荐失败: {str(e)}")
            self._record_stage_timing(
                context,
                "attraction",
                (time.perf_counter() - execute_start) * 1000,
                status="failed",
            )
            return AgentResponse(agent_name=self.name, status=AgentStatus.FAILED, content="", error=str(e))

    async def _search_candidates(self, context: ExecutionContext, destination: str, search_keywords: List[str]) -> List[POI]:
        merged: Dict[str, POI] = {}
        for keyword in search_keywords[:MAX_SEARCH_QUERIES]:
            arguments = {"keywords": keyword, "city": destination, "limit": SEARCH_LIMIT}
            step_name = f"POI搜索[{keyword}]"
            call = self._start_tool_call("poi_search", arguments)
            result = await self.poi_search_tool.execute(**arguments)
            if result.success and isinstance(result.data, list):
                self._complete_tool_call("poi_search", result=f"{keyword}: {len(result.data)} hits")
                context.add_thinking_step(
                    agent_name=self.name.capitalize(),
                    step=step_name,
                    detail=f"poi_search 返回 {len(result.data)} 条候选结果。",
                    status="completed",
                    tool_calls=[{"tool_name": "poi_search", "arguments": arguments, "status": "completed", "result": f"{len(result.data)} hits", "duration_ms": call.duration_ms}],
                    api_calls=result.api_calls or [],
                )
                for rank, item in enumerate(result.data, start=1):
                    candidate = dict(item)
                    candidate["_search_keyword"] = keyword
                    candidate["_search_rank"] = rank
                    candidate["_search_query_count"] = 1
                    key = self._candidate_key(candidate)
                    merged[key] = self._merge_candidate(merged[key], candidate) if key in merged else candidate
            else:
                error_text = result.error or "poi_search 未返回可用结果"
                self._complete_tool_call("poi_search", error=error_text)
                context.add_thinking_step(
                    agent_name=self.name.capitalize(),
                    step=step_name,
                    detail=f"poi_search 失败：{error_text}",
                    status="failed",
                    tool_calls=[{"tool_name": "poi_search", "arguments": arguments, "status": "failed", "error": error_text, "duration_ms": call.duration_ms}],
                    api_calls=result.api_calls or [],
                )
        return list(merged.values())

    async def _fetch_details(self, context: ExecutionContext, candidates: List[POI]) -> List[POI]:
        detailed: List[POI] = []
        for candidate in candidates:
            enriched = dict(candidate)
            poi_id = str(candidate.get("id") or "").strip()
            if not poi_id:
                detailed.append(enriched)
                continue
            arguments = {"poi_id": poi_id}
            step_name = f"POI详情[{candidate.get('name', poi_id)}]"
            call = self._start_tool_call("poi_detail", arguments)
            result = await self.poi_detail_tool.execute(**arguments)
            api_log = {
                "service": self.poi_detail_tool.external_service or "poi_detail",
                "endpoint": "/v3/place/detail",
                "params": {"id": poi_id},
                "status": "completed" if result.success else "failed",
                "response": {"name": result.data.get("name"), "type": result.data.get("type")} if result.success and isinstance(result.data, dict) else None,
                "error": result.error,
                "http_status": 200 if result.success else 500,
                "cost_ms": call.duration_ms,
            }
            if result.success and isinstance(result.data, dict):
                self._complete_tool_call("poi_detail", result=f"{result.data.get('name') or candidate.get('name')}: detail loaded")
                enriched["_detail"] = result.data
                context.add_thinking_step(
                    agent_name=self.name.capitalize(),
                    step=step_name,
                    detail="poi_detail 已补充详情信息。",
                    status="completed",
                    tool_calls=[{"tool_name": "poi_detail", "arguments": arguments, "status": "completed", "result": "detail loaded", "duration_ms": call.duration_ms}],
                    api_calls=[api_log],
                )
            else:
                error_text = result.error or "poi_detail 未返回可用结果"
                self._complete_tool_call("poi_detail", error=error_text)
                context.add_thinking_step(
                    agent_name=self.name.capitalize(),
                    step=step_name,
                    detail=f"poi_detail 失败：{error_text}",
                    status="failed",
                    tool_calls=[{"tool_name": "poi_detail", "arguments": arguments, "status": "failed", "error": error_text, "duration_ms": call.duration_ms}],
                    api_calls=[api_log],
                )
            detailed.append(enriched)
        return detailed

    async def _search_candidates_concurrent(
        self,
        context: ExecutionContext,
        destination: str,
        search_keywords: List[str],
        request_cache: Dict[str, Dict[Any, Any]],
    ) -> List[POI]:
        stage_start = time.perf_counter()
        merged: Dict[str, POI] = {}
        semaphore = asyncio.Semaphore(ATTRACTION_IO_CONCURRENCY)
        inflight_searches: Dict[Any, asyncio.Task[Dict[str, Any]]] = {}

        async def run_search(index: int, keyword: str, arguments: Dict[str, Any], cache_key: Any) -> Dict[str, Any]:
            async with semaphore:
                call = self._start_tool_call("poi_search", arguments)
                try:
                    result = await self.poi_search_tool.execute(**arguments)
                except Exception as exc:
                    error_text = str(exc)
                    call.complete(error=error_text)
                    logger.warning(f"poi_search failed for {destination}/{keyword}: {error_text}")
                    return {
                        "index": index,
                        "keyword": keyword,
                        "success": False,
                        "error": error_text,
                        "api_calls": [],
                        "duration_ms": call.duration_ms,
                        "cached": False,
                    }

                if result.success and isinstance(result.data, list):
                    call.complete(result=f"{keyword}: {len(result.data)} hits")
                    request_cache["poi_search"][cache_key] = [dict(item) for item in result.data]
                    return {
                        "index": index,
                        "keyword": keyword,
                        "success": True,
                        "data": [dict(item) for item in result.data],
                        "api_calls": result.api_calls or [],
                        "duration_ms": call.duration_ms,
                        "cached": False,
                    }

                error_text = result.error or "poi_search no usable result"
                call.complete(error=error_text)
                return {
                    "index": index,
                    "keyword": keyword,
                    "success": False,
                    "error": error_text,
                    "api_calls": result.api_calls or [],
                    "duration_ms": call.duration_ms,
                    "cached": False,
                }

        async def search_one(index: int, keyword: str) -> Dict[str, Any]:
            arguments = {"keywords": keyword, "city": destination, "limit": SEARCH_LIMIT}
            cache_key = (destination, keyword, SEARCH_LIMIT)
            cached = request_cache["poi_search"].get(cache_key)
            if cached is not None:
                return {
                    "index": index,
                    "keyword": keyword,
                    "success": True,
                    "data": [dict(item) for item in cached],
                    "api_calls": [],
                    "duration_ms": 0.0,
                    "cached": True,
                }

            task = inflight_searches.get(cache_key)
            if task is None:
                task = asyncio.create_task(run_search(index, keyword, arguments, cache_key))
                inflight_searches[cache_key] = task

            outcome = await task
            if inflight_searches.get(cache_key) is task and task.done():
                inflight_searches.pop(cache_key, None)

            normalized_outcome = dict(outcome)
            normalized_outcome["index"] = index
            normalized_outcome["keyword"] = keyword
            return normalized_outcome

        outcomes = await asyncio.gather(
            *(search_one(index, keyword) for index, keyword in enumerate(search_keywords[:MAX_SEARCH_QUERIES])),
            return_exceptions=False,
        )

        for outcome in sorted(outcomes, key=lambda item: item["index"]):
            keyword = outcome["keyword"]
            arguments = {"keywords": keyword, "city": destination, "limit": SEARCH_LIMIT}
            step_name = f"POI搜索[{keyword}]"

            if outcome["success"]:
                items = outcome["data"]
                result_text = f"{len(items)} hits" if not outcome["cached"] else f"cache hit: {len(items)} hits"
                detail_text = (
                    f"poi_search cache hit, returned {len(items)} candidates."
                    if outcome["cached"]
                    else f"poi_search returned {len(items)} candidates."
                )
                context.add_thinking_step(
                    agent_name=self.name.capitalize(),
                    step=step_name,
                    detail=detail_text,
                    status="completed",
                    tool_calls=[{
                        "tool_name": "poi_search",
                        "arguments": arguments,
                        "status": "completed",
                        "result": result_text,
                        "duration_ms": outcome["duration_ms"],
                    }],
                    api_calls=outcome["api_calls"],
                )
                for rank, item in enumerate(items, start=1):
                    candidate = dict(item)
                    candidate["_search_keyword"] = keyword
                    candidate["_search_rank"] = rank
                    candidate["_search_query_count"] = 1
                    key = self._candidate_key(candidate)
                    merged[key] = self._merge_candidate(merged[key], candidate) if key in merged else candidate
            else:
                error_text = outcome["error"]
                context.add_thinking_step(
                    agent_name=self.name.capitalize(),
                    step=step_name,
                    detail=f"poi_search failed: {error_text}",
                    status="failed",
                    tool_calls=[{
                        "tool_name": "poi_search",
                        "arguments": arguments,
                        "status": "failed",
                        "error": error_text,
                        "duration_ms": outcome["duration_ms"],
                    }],
                    api_calls=outcome["api_calls"],
                )

        self._record_stage_timing(
            context,
            "attraction._search_candidates",
            (time.perf_counter() - stage_start) * 1000,
            query_count=min(len(search_keywords), MAX_SEARCH_QUERIES),
            merged_count=len(merged),
        )
        return list(merged.values())

    async def _fetch_details_concurrent(
        self,
        context: ExecutionContext,
        candidates: List[POI],
        request_cache: Dict[str, Dict[Any, Any]],
    ) -> List[POI]:
        stage_start = time.perf_counter()
        semaphore = asyncio.Semaphore(ATTRACTION_IO_CONCURRENCY)
        inflight_details: Dict[str, asyncio.Task[Dict[str, Any]]] = {}

        async def run_detail(index: int, enriched: POI, poi_id: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                call = self._start_tool_call("poi_detail", arguments)
                try:
                    result = await self.poi_detail_tool.execute(**arguments)
                except Exception as exc:
                    error_text = str(exc)
                    call.complete(error=error_text)
                    logger.warning(f"poi_detail failed for {poi_id}: {error_text}")
                    return {
                        "index": index,
                        "candidate": dict(enriched),
                        "poi_id": poi_id,
                        "arguments": arguments,
                        "success": False,
                        "error": error_text,
                        "duration_ms": call.duration_ms,
                        "api_log": {
                            "service": self.poi_detail_tool.external_service or "poi_detail",
                            "endpoint": "/v3/place/detail",
                            "params": {"id": poi_id},
                            "status": "failed",
                            "response": None,
                            "error": error_text,
                            "http_status": 500,
                            "cost_ms": call.duration_ms,
                        },
                        "cached": False,
                        "skipped": False,
                    }

                api_log = {
                    "service": self.poi_detail_tool.external_service or "poi_detail",
                    "endpoint": "/v3/place/detail",
                    "params": {"id": poi_id},
                    "status": "completed" if result.success else "failed",
                    "response": {"name": result.data.get("name"), "type": result.data.get("type")} if result.success and isinstance(result.data, dict) else None,
                    "error": result.error,
                    "http_status": 200 if result.success else 500,
                    "cost_ms": call.duration_ms,
                }
                if result.success and isinstance(result.data, dict):
                    call.complete(result=f"{result.data.get('name') or enriched.get('name')}: detail loaded")
                    detail_data = dict(result.data)
                    request_cache["poi_detail"][poi_id] = detail_data
                    enriched_with_detail = dict(enriched)
                    enriched_with_detail["_detail"] = dict(detail_data)
                    return {
                        "index": index,
                        "candidate": enriched_with_detail,
                        "poi_id": poi_id,
                        "arguments": arguments,
                        "success": True,
                        "cached": False,
                        "duration_ms": call.duration_ms,
                        "api_log": api_log,
                        "skipped": False,
                    }

                error_text = result.error or "poi_detail no usable result"
                call.complete(error=error_text)
                api_log["error"] = error_text
                api_log["status"] = "failed"
                api_log["http_status"] = 500
                return {
                    "index": index,
                    "candidate": dict(enriched),
                    "poi_id": poi_id,
                    "arguments": arguments,
                    "success": False,
                    "error": error_text,
                    "duration_ms": call.duration_ms,
                    "api_log": api_log,
                    "cached": False,
                    "skipped": False,
                }

        async def fetch_one(index: int, candidate: POI) -> Dict[str, Any]:
            enriched = dict(candidate)
            poi_id = str(candidate.get("id") or "").strip()
            if not poi_id:
                return {
                    "index": index,
                    "candidate": enriched,
                    "poi_id": "",
                    "cached": False,
                    "skipped": True,
                }

            arguments = {"poi_id": poi_id}
            cached_detail = request_cache["poi_detail"].get(poi_id)
            if cached_detail is not None:
                enriched["_detail"] = dict(cached_detail)
                return {
                    "index": index,
                    "candidate": enriched,
                    "poi_id": poi_id,
                    "arguments": arguments,
                    "success": True,
                    "cached": True,
                    "duration_ms": 0.0,
                    "api_log": None,
                    "skipped": False,
                }

            task = inflight_details.get(poi_id)
            if task is None:
                task = asyncio.create_task(run_detail(index, enriched, poi_id, arguments))
                inflight_details[poi_id] = task

            outcome = await task
            if inflight_details.get(poi_id) is task and task.done():
                inflight_details.pop(poi_id, None)

            normalized_outcome = dict(outcome)
            normalized_outcome["index"] = index
            normalized_outcome["candidate"] = dict(outcome["candidate"])
            normalized_outcome["poi_id"] = poi_id
            normalized_outcome["arguments"] = arguments
            return normalized_outcome

        outcomes = await asyncio.gather(
            *(fetch_one(index, candidate) for index, candidate in enumerate(candidates)),
            return_exceptions=False,
        )

        detailed: List[POI] = []
        for outcome in sorted(outcomes, key=lambda item: item["index"]):
            enriched = outcome["candidate"]
            detailed.append(enriched)

            if outcome.get("skipped"):
                continue

            poi_id = outcome["poi_id"]
            step_name = f"POI详情[{enriched.get('name', poi_id)}]"
            arguments = outcome["arguments"]

            if outcome["success"]:
                detail_text = "poi_detail cache hit, reused detail info." if outcome["cached"] else "poi_detail loaded detail info."
                result_text = "cache hit" if outcome["cached"] else "detail loaded"
                context.add_thinking_step(
                    agent_name=self.name.capitalize(),
                    step=step_name,
                    detail=detail_text,
                    status="completed",
                    tool_calls=[{
                        "tool_name": "poi_detail",
                        "arguments": arguments,
                        "status": "completed",
                        "result": result_text,
                        "duration_ms": outcome["duration_ms"],
                    }],
                    api_calls=[outcome["api_log"]] if outcome["api_log"] else [],
                )
            else:
                error_text = outcome["error"]
                context.add_thinking_step(
                    agent_name=self.name.capitalize(),
                    step=step_name,
                    detail=f"poi_detail failed: {error_text}",
                    status="failed",
                    tool_calls=[{
                        "tool_name": "poi_detail",
                        "arguments": arguments,
                        "status": "failed",
                        "error": error_text,
                        "duration_ms": outcome["duration_ms"],
                    }],
                    api_calls=[outcome["api_log"]] if outcome["api_log"] else [],
                )

        self._record_stage_timing(
            context,
            "attraction._fetch_details",
            (time.perf_counter() - stage_start) * 1000,
            candidate_count=len(candidates),
            detailed_count=len(detailed),
        )
        return detailed

    async def _generate_recommendation_content(
        self,
        session: SessionContext,
        destination: str,
        travel_styles: List[str],
        interests: List[str],
        special_requirements: List[str],
        tourist_type: str,
        pois: List[POI],
    ) -> tuple[str, int]:
        if not pois:
            return f"我已经尝试基于真实 POI 检索为你查找 {destination} 的景点，但当前结果不足，暂时不建议直接给出不可靠推荐。", 0
        if not self.llm:
            return self._build_fallback_content(destination, pois), 0
        system_prompt = (
            f"你是一位旅游顾问，现在要基于真实 POI 数据为用户总结 {destination} 的景点推荐。\n"
            "下面提供的数据已经来自真实的 poi_search / poi_detail 检索结果，并补充了仓库内真实 POI 知识数据。"
            "请严格只基于这些数据做排序、解释和推荐，不要新增未出现的景点，不要虚构地址、开放时间、门票或游玩时长。\n\n"
            f"用户画像：\n- 旅行风格：{'、'.join(travel_styles) if travel_styles else '综合'}\n"
            f"- 兴趣偏好：{'、'.join(interests) if interests else '未指定'}\n"
            f"- 特殊需求：{'、'.join(special_requirements) if special_requirements else '无'}\n- 游客类型：{tourist_type}\n\n"
            f"候选 POI 数据：\n{self._format_pois_for_prompt(pois)}\n\n"
            "输出要求：先给简短结论，再列 3-5 个重点推荐景点及理由，最后补一段怎么选的建议。未知字段请直接写“信息待确认”，不要编造新景点。"
        )
        response = await self.chat(self.build_messages(session, system_prompt))
        formatted_content = self._format_recommendation_content(destination, pois, response.content)
        return formatted_content, response.usage.get("total_tokens", 0)

    def _record_stage_timing(
        self,
        context: ExecutionContext,
        stage: str,
        duration_ms: float,
        **metadata: Any,
    ) -> None:
        stage_timings = getattr(context, "_stage_timings", None)
        if stage_timings is None:
            stage_timings = {}
            context._stage_timings = stage_timings
        stage_timings[stage] = round(duration_ms, 2)
        metadata_text = " ".join(
            f"{key}={value}"
            for key, value in metadata.items()
            if value is not None and value != ""
        )
        logger.info(
            f"Timing request_id={getattr(context, 'request_id', '')} stage={stage} "
            f"duration_ms={duration_ms:.2f} {metadata_text}".rstrip()
        )

    def _build_structured_pois(self, candidates: List[POI]) -> List[POI]:
        structured: List[POI] = []
        for candidate in candidates:
            detail = candidate.get("_detail") or {}
            knowledge = candidate.get("_knowledge_match") or {}
            name = str(detail.get("name") or candidate.get("name") or knowledge.get("name") or "").strip()
            if not name:
                continue
            area = self._first_non_empty(knowledge.get("area"), candidate.get("district"), candidate.get("city"))
            address = self._first_non_empty(detail.get("address"), candidate.get("address"), area)
            category = self._first_non_empty(knowledge.get("category"), detail.get("type"), candidate.get("type"))
            open_time = self._first_non_empty(knowledge.get("opening_hours"), detail.get("open_time"), candidate.get("opening_hours"))
            ticket_value = self._parse_ticket_price(knowledge.get("ticket_price"), detail.get("ticket_price"), candidate.get("ticket_price"))
            duration_hours = self._parse_duration_hours(
                knowledge.get("recommended_duration") or knowledge.get("visit_duration_hours") or knowledge.get("estimated_duration")
            )
            suitable_for = self._normalize_string_list(knowledge.get("suitable_for"))
            tags = self._dedupe_strings(
                self._normalize_string_list(knowledge.get("tags"))
                + self._split_tags(detail.get("tag"))
                + self._split_tags(candidate.get("type"))
                + self._normalize_string_list(candidate.get("_selection_reasons"))
            )
            structured.append(
                {
                    "name": name,
                    "address": address,
                    "area": area,
                    "region": area,
                    "category": category,
                    "open_time": open_time,
                    "opening_hours": open_time,
                    "ticket_price": self._format_ticket_price(ticket_value),
                    "ticket_price_value": ticket_value,
                    "rating": self._parse_float(candidate.get("rating")),
                    "suggested_duration": duration_hours,
                    "suggested_duration_hours": duration_hours,
                    "visit_duration_hours": duration_hours,
                    "family_friendly": self._infer_family_friendly(knowledge, suitable_for, tags),
                    "elder_friendly": self._infer_elder_friendly(knowledge, suitable_for, tags),
                    "tags": tags,
                    "suitable_for": suitable_for,
                    "indoor_outdoor": self._infer_indoor_outdoor(knowledge, category, tags),
                    "source": "poi_search+poi_detail",
                    "search_keyword": candidate.get("_search_keyword"),
                    "selection_score": candidate.get("_selection_score"),
                    "selection_reasons": candidate.get("_selection_reasons") or [],
                    "knowledge_source": knowledge.get("_knowledge_source"),
                }
            )
        return structured

    def _build_search_keywords(
        self,
        destination: str,
        travel_styles: List[str],
        interests: List[str],
        special_requirements: List[str],
        tourist_type: str,
    ) -> List[str]:
        keywords: List[str] = []
        keywords.extend(interests)
        style_keywords = {
            "休闲": ["公园", "老街"],
            "文化": ["博物馆", "古迹"],
            "亲子": ["动物园", "乐园"],
            "冒险": ["徒步", "山"],
            "蜜月": ["夜景", "浪漫"],
        }
        for style in travel_styles:
            keywords.extend(style_keywords.get(style, []))
        requirements_text = " ".join(special_requirements)
        if tourist_type == "family" or any(word in requirements_text for word in ["亲子", "孩子", "小孩", "家庭"]):
            keywords.append("亲子")
        if tourist_type == "senior" or any(word in requirements_text for word in ["老人", "长辈"]):
            keywords.extend(["公园", "博物馆"])
        if tourist_type == "couple" or any(word in requirements_text for word in ["情侣", "约会"]):
            keywords.append("夜景")
        keywords.append("景点")

        result: List[str] = []
        seen = set()
        for keyword in keywords:
            text = str(keyword or "").strip()
            if not text or text == destination or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result[:MAX_SEARCH_QUERIES]

    def _select_top_candidates(
        self,
        destination: str,
        candidates: List[POI],
        travel_styles: List[str],
        interests: List[str],
        special_requirements: List[str],
        tourist_type: str,
        local_knowledge: List[POI],
    ) -> List[POI]:
        scored: List[POI] = []
        for candidate in candidates:
            knowledge = self._match_local_poi(destination, candidate, local_knowledge)
            score, reasons = self._score_candidate(destination, candidate, knowledge, travel_styles, interests, special_requirements, tourist_type)
            item = dict(candidate)
            item["_selection_score"] = score
            item["_selection_reasons"] = reasons
            item["_knowledge_match"] = knowledge
            scored.append(item)
        scored.sort(
            key=lambda item: (
                item.get("_selection_score", 0),
                item.get("_search_query_count", 0),
                -int(item.get("_search_rank", SEARCH_LIMIT)),
            ),
            reverse=True,
        )
        return scored[:TOP_N]

    def _score_candidate(  # noqa: C901
        self,
        destination: str,
        candidate: POI,
        knowledge: Optional[POI],
        travel_styles: List[str],
        interests: List[str],
        special_requirements: List[str],
        tourist_type: str,
    ) -> tuple[float, List[str]]:
        score = 0.0
        reasons: List[str] = []
        rank = int(candidate.get("_search_rank") or SEARCH_LIMIT)
        score += max(0, SEARCH_LIMIT - rank + 1) * 2
        if rank <= 2:
            reasons.append("搜索结果靠前")
        if self._normalize_text(destination) in self._normalize_text(" ".join([str(candidate.get("address") or ""), str((knowledge or {}).get("area") or "")])):
            score += 6
            reasons.append("区域匹配度高")
        rating = self._parse_float(candidate.get("rating"))
        if rating is not None:
            score += rating * 2
            if rating >= 4.0:
                reasons.append("基础评分稳定")

        category_text = " ".join(
            self._normalize_string_list([candidate.get("type"), (knowledge or {}).get("category"), *((knowledge or {}).get("tags") or [])])
        )
        for interest in interests:
            if interest and interest in category_text:
                score += 5
                reasons.append(f"匹配兴趣：{interest}")
        for style in travel_styles:
            if style == "文化" and any(word in category_text for word in ["博物馆", "古迹", "文化"]):
                score += 4
                reasons.append("适合文化向行程")
            elif style == "休闲" and any(word in category_text for word in ["公园", "湖", "街", "古镇"]):
                score += 4
                reasons.append("适合休闲游")
            elif style == "亲子" and any(word in category_text for word in ["亲子", "动物园", "乐园"]):
                score += 5
                reasons.append("适合亲子")
            elif style == "蜜月" and any(word in category_text for word in ["夜景", "浪漫", "湖景", "海景"]):
                score += 4
                reasons.append("适合情侣/夜景")

        suitable_for = self._normalize_string_list((knowledge or {}).get("suitable_for"))
        tags = self._normalize_string_list((knowledge or {}).get("tags"))
        if tourist_type == "family" and any(word in suitable_for for word in ["家庭", "亲子"]):
            score += 5
            reasons.append("适配家庭出行")
        if tourist_type == "senior" and any(word in suitable_for for word in ["老人", "长者"]):
            score += 5
            reasons.append("适配老人出行")
        requirements_text = " ".join(special_requirements)
        if any(word in requirements_text for word in ["老人", "长辈"]) and self._infer_elder_friendly(knowledge or {}, suitable_for, tags):
            score += 3
            reasons.append("对老人更友好")
        if any(word in requirements_text for word in ["亲子", "孩子", "小孩"]) and self._infer_family_friendly(knowledge or {}, suitable_for, tags):
            score += 3
            reasons.append("对亲子更友好")

        duration_hours = self._parse_duration_hours((knowledge or {}).get("recommended_duration") or (knowledge or {}).get("estimated_duration"))
        if duration_hours <= 3.0:
            score += 2
            reasons.append("时长较好安排")
        elif tourist_type in {"family", "senior"} and duration_hours > 3.5:
            score -= 2
        ticket_value = self._parse_ticket_price((knowledge or {}).get("ticket_price"))
        if ticket_value == 0:
            score += 2
            reasons.append("门票成本友好")
        elif ticket_value is not None and ticket_value > 120:
            score -= 1
        if knowledge:
            score += 2
            reasons.append("信息完整度更高")
        return score, self._dedupe_strings(reasons)

    def _build_selection_summary(self, candidates: List[POI]) -> str:
        if not candidates:
            return "未筛出可进入详情补充的候选景点。"
        lines = []
        for index, candidate in enumerate(candidates, start=1):
            reasons = "、".join(candidate.get("_selection_reasons") or []) or "基础匹配"
            lines.append(f"{index}. {candidate.get('name', '未知景点')} | score={candidate.get('_selection_score', 0):.1f} | {reasons}")
        return "\n".join(lines)

    def _build_fallback_content(self, destination: str, pois: List[POI]) -> str:
        return self._format_recommendation_content(destination, pois, "")

    def _format_recommendation_content(self, destination: str, pois: List[POI], raw_content: str) -> str:
        conclusion = self._extract_recommendation_section(
            raw_content,
            ("结论：", "结论", "综上所述：", "综上所述"),
            ("重点推荐景点及理由", "推荐景点", "建议：", "建议"),
        )
        if not conclusion:
            conclusion = f"我基于真实 POI 检索，为你筛出了几处更适合在 {destination} 优先考虑的景点。"

        advice = self._extract_recommendation_section(
            raw_content,
            ("建议：", "建议", "怎么选：", "如何选择："),
            (),
        )
        if not advice:
            advice = f"如果你告诉我更偏向亲子互动、轻松散步、拍照打卡还是室内体验，我可以继续帮你把 {destination} 的候选景点再缩小一轮。"

        lines = [
            "✨ 结论",
            conclusion,
            "",
            "🎯 推荐景点",
        ]

        for index, poi in enumerate(pois[:4], start=1):
            name = str(poi.get("name") or "信息待确认").strip() or "信息待确认"
            reason = self._build_recommendation_reason(poi)
            area = str(poi.get("area") or poi.get("address") or "信息待确认").strip() or "信息待确认"
            ticket_price = str(poi.get("ticket_price") or "信息待确认").strip() or "信息待确认"
            duration_text = self._format_duration_text(poi.get("suggested_duration_hours"))

            lines.extend([
                f"{index}. 📍 {name}",
                f"   ✨ 推荐理由：{reason}",
                f"   🚇 区域/地址：{area}",
                f"   🎫 门票：{ticket_price}",
                f"   ⏰ 建议时长：{duration_text}",
            ])

        lines.extend([
            "",
            "💡 小建议",
            advice,
        ])
        return "\n".join(lines)

    def _extract_recommendation_section(
        self,
        raw_content: str,
        markers: tuple[str, ...],
        stop_markers: tuple[str, ...],
    ) -> str:
        text = str(raw_content or "").replace("\r\n", "\n").strip()
        if not text:
            return ""

        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if not lines:
            return ""

        start_index = None
        section_text = ""
        for idx, line in enumerate(lines):
            for marker in markers:
                if line.startswith(marker):
                    start_index = idx
                    section_text = line[len(marker):].lstrip("：: ").strip()
                    break
            if start_index is not None:
                break

        if start_index is None:
            if markers and markers[0].startswith("结论"):
                return lines[0]
            return ""

        collected = [section_text] if section_text else []
        for line in lines[start_index + 1:]:
            if any(line.startswith(stop_marker) for stop_marker in stop_markers):
                break
            if re.match(r"^\d+[.、]", line):
                break
            collected.append(line)

        return " ".join(part for part in collected if part).strip()

    def _build_recommendation_reason(self, poi: POI) -> str:
        area = str(poi.get("area") or poi.get("region") or "").strip()
        if not area:
            address = str(poi.get("address") or "").strip()
            if address and address != "信息待确认":
                area = address.split("，", 1)[0].split(",", 1)[0].strip()

        duration_value = poi.get("suggested_duration_hours")
        duration_hint = ""
        try:
            if duration_value is not None and float(duration_value) <= 4:
                duration_hint = "，半天到一天安排会更从容"
        except (TypeError, ValueError):
            duration_hint = ""

        if poi.get("family_friendly"):
            experience_hint = "，亲子互动会更自然"
        elif poi.get("elder_friendly"):
            experience_hint = "，整体节奏更容易放轻松"
        else:
            tags = self._normalize_string_list(poi.get("tags"))
            if any(tag in " ".join(tags) for tag in ["拍照", "摄影", "夜景", "街区", "散步"]):
                experience_hint = "，边走边逛边拍会更出片"
            elif tags:
                experience_hint = f"，也比较贴合这次想要的{tags[0]}体验"
            else:
                category = str(poi.get("category") or "").strip()
                experience_hint = f"，适合放进这次的{category}向推荐里" if category else ""

        if area and area != "信息待确认":
            return f"更适合放在{area}一带顺路安排{experience_hint}{duration_hint}。"

        return f"整体更适合做这次路线里的轻松候选点{experience_hint}{duration_hint}。"

    def _format_duration_text(self, duration_value: Any) -> str:
        try:
            if duration_value is None:
                return "信息待确认"
            duration = float(duration_value)
            if duration.is_integer():
                return f"{int(duration)}小时"
            return f"{duration:.1f}小时"
        except (TypeError, ValueError):
            return "信息待确认"

    def _format_pois_for_prompt(self, pois: List[POI]) -> str:
        return "\n".join(
            json.dumps(
                {
                    "rank": index,
                    "name": poi.get("name"),
                    "category": poi.get("category"),
                    "address": poi.get("address"),
                    "open_time": poi.get("open_time") or "信息待确认",
                    "ticket_price": poi.get("ticket_price") or "信息待确认",
                    "rating": poi.get("rating"),
                    "suggested_duration_hours": poi.get("suggested_duration_hours"),
                    "family_friendly": poi.get("family_friendly"),
                    "elder_friendly": poi.get("elder_friendly"),
                    "tags": poi.get("tags") or [],
                    "selection_reasons": poi.get("selection_reasons") or [],
                },
                ensure_ascii=False,
            )
            for index, poi in enumerate(pois, start=1)
        )

    def _load_local_pois(self, destination: str) -> List[POI]:
        cache_key = self._normalize_text(destination)
        if cache_key in self._local_poi_cache:
            return self._local_poi_cache[cache_key]
        local_pois: List[POI] = []
        if LOCAL_POI_DIR.exists():
            for path in LOCAL_POI_DIR.glob("*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if self._normalize_text(payload.get("city")) != cache_key:
                    continue
                for poi in payload.get("pois", []):
                    if isinstance(poi, dict):
                        item = dict(poi)
                        item["_knowledge_source"] = str(path.relative_to(LOCAL_POI_DIR.parent.parent))
                        local_pois.append(item)
        self._local_poi_cache[cache_key] = local_pois
        return local_pois

    def _match_local_poi(self, destination: str, candidate: POI, local_pois: List[POI]) -> Optional[POI]:
        target_name = self._normalize_text(candidate.get("name"))
        if not target_name:
            return None
        best_match: Optional[POI] = None
        best_score = 0
        for item in local_pois:
            item_name = self._normalize_text(item.get("name"))
            if not item_name:
                continue
            score = 0
            if target_name == item_name:
                score += 100
            elif target_name in item_name or item_name in target_name:
                score += 70
            keyword_text = self._normalize_text(candidate.get("_search_keyword"))
            if keyword_text and keyword_text in self._normalize_text(item.get("category")):
                score += 8
            if self._normalize_text(destination) == self._normalize_text(item.get("city")):
                score += 5
            if score > best_score:
                best_score = score
                best_match = item
        return best_match if best_score >= 70 else None

    def _candidate_key(self, candidate: POI) -> str:
        return str(candidate.get("id") or self._normalize_text(candidate.get("name")) or "").strip()

    def _merge_candidate(self, existing: POI, incoming: POI) -> POI:
        merged = dict(existing)
        for key in ["name", "address", "location", "tel", "type", "typecode", "biz_type", "rating"]:
            if not merged.get(key) and incoming.get(key):
                merged[key] = incoming[key]
        merged["_search_rank"] = min(int(existing.get("_search_rank") or SEARCH_LIMIT), int(incoming.get("_search_rank") or SEARCH_LIMIT))
        merged["_search_query_count"] = int(existing.get("_search_query_count") or 1) + 1
        return merged

    def _serialize_tool_calls(self) -> List[Dict[str, Any]]:
        return [{"tool_name": call.tool_name, "arguments": call.arguments, "status": call.status, "result": call.result, "error": call.error} for call in self._current_tool_calls]

    def _parse_ticket_price(self, *values: Any) -> Optional[float]:
        for value in values:
            if value is None or value == "":
                continue
            if isinstance(value, (int, float)):
                return max(float(value), 0.0)
            text = str(value).strip()
            if "免费" in text:
                return 0.0
            numbers = [float(match) for match in re.findall(r"\d+(?:\.\d+)?", text)]
            if numbers:
                return min(numbers)
        return None

    def _format_ticket_price(self, value: Optional[float]) -> str:
        if value is None:
            return ""
        if value == 0:
            return "免费"
        return f"{int(value)}元" if float(value).is_integer() else f"{value:.1f}元"

    def _parse_duration_hours(self, value: Any) -> float:
        if isinstance(value, (int, float)):
            numeric = float(value)
            return round(max(numeric / 60.0, 0.5), 1) if numeric > 12 else max(numeric, 0.5)
        text = str(value or "").strip()
        if not text:
            return 2.0
        range_match = re.search(r"(\d+(?:\.\d+)?)\s*[-~至到]\s*(\d+(?:\.\d+)?)\s*小时", text)
        if range_match:
            return round((float(range_match.group(1)) + float(range_match.group(2))) / 2, 1)
        hour_match = re.search(r"(\d+(?:\.\d+)?)\s*小时", text)
        if hour_match:
            return float(hour_match.group(1))
        minute_match = re.search(r"(\d+(?:\.\d+)?)\s*分钟", text)
        if minute_match:
            return round(max(float(minute_match.group(1)) / 60.0, 0.5), 1)
        if "半天" in text:
            return 4.0
        if "一天" in text or "1天" in text:
            return 8.0
        return 2.0

    def _parse_float(self, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).strip())
        except ValueError:
            return None

    def _split_tags(self, value: Any) -> List[str]:
        text = str(value or "").strip()
        if not text:
            return []
        return [item.strip() for item in re.split(r"[、,，;/｜|]+", text) if item and item.strip()]

    def _normalize_string_list(self, value: Any) -> List[str]:
        if value is None:
            return []
        items = value if isinstance(value, list) else [value]
        return self._dedupe_strings([str(item).strip() for item in items if str(item).strip()])

    def _dedupe_strings(self, values: List[str]) -> List[str]:
        result: List[str] = []
        seen = set()
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    def _infer_family_friendly(self, knowledge: POI, suitable_for: List[str], tags: List[str]) -> bool:
        combined = " ".join(suitable_for + tags + [str(knowledge.get("category") or "")])
        return any(word in combined for word in ["家庭", "亲子", "孩子", "乐园", "动物园"])

    def _infer_elder_friendly(self, knowledge: POI, suitable_for: List[str], tags: List[str]) -> bool:
        combined = " ".join(suitable_for + tags + [str(knowledge.get("walk_level") or "")])
        if any(word in combined for word in ["老人", "长者"]):
            return True
        walk_level = str(knowledge.get("walk_level") or "").lower()
        return walk_level in {"low", "medium"} and "徒步" not in combined and "高强度" not in combined

    def _infer_indoor_outdoor(self, knowledge: POI, category: str, tags: List[str]) -> str:
        if knowledge.get("indoor_outdoor"):
            return str(knowledge["indoor_outdoor"])
        if knowledge.get("indoor") is True:
            return "indoor"
        combined = " ".join([category, *tags])
        if any(word in combined for word in ["博物馆", "展馆", "室内", "艺术馆"]):
            return "indoor"
        if any(word in combined for word in ["公园", "山", "湖", "湿地", "海", "古镇", "夜景"]):
            return "outdoor"
        return "mixed"

    def _first_non_empty(self, *values: Any) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    def _normalize_text(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[（(].*?[）)]", "", text)
        text = re.sub(r"[市区县景区景点·\-\s]", "", text)
        return text

    def _normalize_attraction_inputs(self, session: SessionContext, context: ExecutionContext) -> Dict[str, Any]:
        """兼容读取上游输入字段。"""
        extracted = context.extracted_info or {}
        session_prefs = session.preferences if session else None
        result: Dict[str, Any] = {
            "destination": str(extracted.get("destination") or "").strip(),
            "city": str(extracted.get("city") or "").strip(),
            "region": str(extracted.get("region") or "").strip(),
            "district": str(extracted.get("district") or "").strip(),
            "area": str(extracted.get("area") or "").strip(),
            "location": str(extracted.get("location") or "").strip(),
            "preferences": self._normalize_string_list(extracted.get("preferences")),
            "interests": self._normalize_string_list(extracted.get("interests") or (session_prefs.interests if session_prefs else [])),
            "travel_style": self._normalize_string_list(extracted.get("travel_style") or (session_prefs.travel_style if session_prefs else [])),
            "group_type": str(extracted.get("group_type") or (session_prefs.group_type if session_prefs else "") or "").strip(),
            "special_requirements": self._normalize_string_list(
                extracted.get("special_requirements") or (session_prefs.special_needs if session_prefs else [])
            ),
            "must_visit": self._normalize_string_list(extracted.get("must_visit")),
            "avoid": self._normalize_string_list(extracted.get("avoid")),
            "days": extracted.get("days") or context.extracted_info.get("duration"),
            "duration": extracted.get("duration"),
            "daily_plans": extracted.get("daily_plans"),
            "schedule": extracted.get("schedule"),
            "budget": extracted.get("budget"),
            "budget_amount": self._parse_float(extracted.get("budget_amount")),
            "budget_limit": self._parse_float(extracted.get("budget_limit")),
            "total_budget": self._parse_float(extracted.get("total_budget")),
            "max_budget": self._parse_float(extracted.get("max_budget")),
            "weather": extracted.get("weather"),
            "weather_type": str(extracted.get("weather_type") or "").strip(),
            "forecast": extracted.get("forecast"),
            "daily_forecasts": extracted.get("daily_forecasts"),
            "warnings": extracted.get("warnings"),
            "risk_level": str(extracted.get("risk_level") or "").strip(),
        }
        if not result["destination"] and result["city"]:
            result["destination"] = result["city"]
        return result

    def _extract_destination(self, inputs: Dict[str, Any]) -> str:
        return inputs.get("destination") or inputs.get("city") or ""

    def _extract_preferences(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "interests": inputs.get("interests") or [],
            "travel_style": inputs.get("travel_style") or [],
            "group_type": inputs.get("group_type"),
            "special_requirements": inputs.get("special_requirements") or [],
            "must_visit": inputs.get("must_visit") or [],
            "avoid": inputs.get("avoid") or [],
        }

    def _select_candidate_pois(self, candidates: List[POI], inputs: Dict[str, Any]) -> List[POI]:
        """基于输入条件过滤候选 POI。"""
        must_visit = set(self._normalize_string_list(inputs.get("must_visit")))
        avoid = set(self._normalize_string_list(inputs.get("avoid")))
        filtered = []
        for poi in candidates:
            name = str(poi.get("name") or "").strip()
            if avoid and name and name in avoid:
                continue
            filtered.append(poi)
        return filtered

    def _infer_category(self, category: str, tags: List[str], name: str) -> Optional[str]:
        """推断标准化的 category 值。"""
        if category:
            cat_lower = category.lower()
            for std in CATEGORY_STANDARD_VALUES:
                if std in cat_lower or cat_lower in std:
                    return std
            combined = " ".join([category, *tags, name]).lower()
            if any(word in combined for word in ["博物馆", "展馆", "艺术"]):
                return "museum"
            if any(word in combined for word in ["公园", "山", "湖", "海", "湿地", "森林"]):
                return "nature"
            if any(word in combined for word in ["古镇", "老街", "历史", "古迹", "寺庙"]):
                return "history"
            if any(word in combined for word in ["购物", "商场", "商业街"]):
                return "shopping"
            if any(word in combined for word in ["美食", "餐厅", "小吃", "夜市"]):
                return "food"
            if any(word in combined for word in ["夜", "酒吧", "演出"]):
                return "nightlife"
            if any(word in combined for word in ["文化", "民俗", "非遗"]):
                return "cultural"
            if any(word in combined for word in ["乐园", "游乐", "动物园"]):
                return "leisure"
        return "other"

    def _infer_best_time_to_visit(self, knowledge: POI, tags: List[str], category: str) -> str:
        """推断最佳游览时段。"""
        if knowledge.get("best_time_to_visit"):
            val = str(knowledge["best_time_to_visit"]).lower()
            if val in BEST_TIME_VALUES:
                return val
        combined = " ".join([category, *tags])
        if any(word in combined for word in ["夜", "夜景", "灯光"]):
            return "evening"
        if any(word in combined for word in ["日出", "晨", "早起"]):
            return "morning"
        return "flexible"

    def _infer_indoor_outdoor(self, knowledge: POI, category: str, tags: List[str]) -> str:
        """推断室内/室外标识。"""
        if knowledge.get("indoor_outdoor"):
            val = str(knowledge["indoor_outdoor"]).strip().lower()
            if val in INDOOR_OUTDOOR_VALUES:
                return val
        combined = " ".join([category, *tags])
        if any(word in combined for word in ["博物馆", "展馆", "室内", "艺术馆"]):
            return "indoor"
        if any(word in combined for word in ["公园", "山", "湖", "湿地", "海", "古镇"]):
            return "outdoor"
        return "mixed"

    def _infer_priority(self, score: float, rating: Optional[float]) -> str:
        """根据评分和分数推断优先级。"""
        if score >= 30 or (rating is not None and rating >= 4.5):
            return "high"
        if score >= 15 or (rating is not None and rating >= 3.8):
            return "medium"
        return "low"

    def _infer_recommended_visit_duration(self, hours: float, group_type: str) -> float:
        """根据游客类型调整推荐游览时长。"""
        if not hours:
            return 2.0
        if group_type in {"family", "senior"} and hours > 4.0:
            return round(hours * 0.8, 1)
        return hours

    def _build_coordinates(self, raw: Any) -> Optional[Dict[str, Any]]:
        """从原始数据构建标准化坐标对象。"""
        if not raw:
            return None
        if isinstance(raw, dict):
            lat = self._parse_float(raw.get("lat") or raw.get("latitude"))
            lng = self._parse_float(raw.get("lng") or raw.get("longitude"))
            if lat is not None and lng is not None:
                return {"lat": lat, "lng": lng}
            return None
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            lng = self._parse_float(raw[0])
            lat = self._parse_float(raw[1])
            if lat is not None and lng is not None:
                return {"lat": lat, "lng": lng}
        return None

    def _build_estimated_cost(self, ticket_value: Optional[float], budget: Any, max_budget: Optional[float]) -> Optional[Dict[str, Any]]:
        """构建标准化的费用对象。"""
        amount = ticket_value
        if amount is not None:
            if amount == 0:
                cost_level = "free"
            elif amount < 50:
                cost_level = "low"
            elif amount < 150:
                cost_level = "medium"
            else:
                cost_level = "high"
            return {"amount": amount, "currency": "CNY", "cost_level": cost_level}
        return None

    def _ticket_price_status(self, value: Optional[float]) -> str:
        if value is None:
            return "unknown"
        if value == 0:
            return "free"
        return "known"

    def _normalize_poi_item(self, poi: POI, inputs: Dict[str, Any], index: int) -> Dict[str, Any]:
        """将单个 POI 规范化为标准结构。"""
        detail = poi.get("_detail") or {}
        knowledge = poi.get("_knowledge_match") or {}

        name = str(poi.get("name") or detail.get("name") or knowledge.get("name") or "").strip()
        city = inputs.get("city") or inputs.get("destination") or ""
        area = self._first_non_empty(knowledge.get("area"), poi.get("district"), poi.get("city"), city)
        category_raw = self._first_non_empty(knowledge.get("category"), detail.get("type"), poi.get("type"))
        tags = self._dedupe_strings(
            self._normalize_string_list(knowledge.get("tags"))
            + self._split_tags(detail.get("tag"))
            + self._split_tags(poi.get("type"))
        )
        category = self._infer_category(category_raw, tags, name)
        suitable_for = self._normalize_string_list(knowledge.get("suitable_for"))
        if not suitable_for:
            suitable_for = self._infer_suitable_for(tags, inputs.get("group_type"))

        duration_hours = self._parse_duration_hours(
            knowledge.get("recommended_duration") or knowledge.get("visit_duration_hours") or knowledge.get("estimated_duration")
        )
        duration_hours = self._infer_recommended_visit_duration(duration_hours, str(inputs.get("group_type") or ""))

        ticket_value = self._parse_ticket_price(knowledge.get("ticket_price"), detail.get("ticket_price"), poi.get("ticket_price"))
        budget = inputs.get("budget") or inputs.get("budget_amount") or inputs.get("max_budget")
        estimated_cost = self._build_estimated_cost(ticket_value, budget, inputs.get("max_budget"))

        raw_location = detail.get("location") or poi.get("location") or knowledge.get("location")
        coordinates = self._build_coordinates(raw_location)

        score = float(poi.get("_selection_score") or 0)
        rating = self._parse_float(poi.get("rating"))
        priority = self._infer_priority(score, rating)

        description_parts = []
        if knowledge.get("description"):
            desc = str(knowledge["description"])[:200]
            if desc:
                description_parts.append(desc)
        if poi.get("selection_reasons"):
            reasons = self._normalize_string_list(poi["selection_reasons"])
            if reasons:
                description_parts.append("推荐理由：" + "、".join(reasons[:3]))
        description = "。".join(description_parts) if description_parts else None

        best_time = self._infer_best_time_to_visit(knowledge, tags, category_raw)
        indoor_outdoor = self._infer_indoor_outdoor(knowledge, category_raw, tags)

        return {
            "name": name,
            "city": city or None,
            "category": category,
            "recommended_visit_duration_hours": duration_hours,
            "best_time_to_visit": best_time,
            "ticket_price": self._format_ticket_price(ticket_value) or None,
            "ticket_price_value": ticket_value,
            "ticket_price_status": self._ticket_price_status(ticket_value),
            "estimated_cost": estimated_cost,
            "description": description,
            "suitable_for": suitable_for,
            "source": str(poi.get("knowledge_source") or "poi_search+poi_detail"),
            "priority": priority,
            "indoor_outdoor": indoor_outdoor,
            "coordinates": coordinates,
            "opening_hours": self._first_non_empty(knowledge.get("opening_hours"), detail.get("open_time"), poi.get("opening_hours")) or None,
        }

    def _infer_suitable_for(self, tags: List[str], group_type: str) -> List[str]:
        """从标签和游客类型推断 suitable_for。"""
        result: List[str] = []
        combined = " ".join(tags).lower()
        if any(word in combined for word in ["家庭", "亲子", "孩子", "乐园", "动物园"]):
            result.append("family")
        if any(word in combined for word in ["情侣", "约会", "浪漫", "蜜月"]):
            result.append("couples")
        if any(word in combined for word in ["老人", "长者"]):
            result.append("seniors")
        if any(word in combined for word in ["历史", "古迹", "博物馆", "文化"]):
            result.append("history_lovers")
        if any(word in combined for word in ["朋友", "闺蜜", "兄弟"]):
            result.append("friends")
        if any(word in combined for word in ["摄影", "拍照"]):
            result.append("photography")
        if not result:
            if group_type == "family":
                result.append("family")
            elif group_type == "couple":
                result.append("couples")
            elif group_type == "senior":
                result.append("seniors")
        return result

    def _normalize_poi_list(self, pois: List[POI], inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
        """将 POI 列表规范化为标准结构列表。"""
        if not pois:
            return []
        result = []
        for i, poi in enumerate(pois):
            try:
                normalized = self._normalize_poi_item(poi, inputs, i)
                if normalized.get("name"):
                    result.append(normalized)
            except Exception:
                continue
        return result

    def _build_attraction_result(
        self,
        inputs: Dict[str, Any],
        structured_pois: List[POI],
        content: str,
        tokens_used: int,
        search_keywords: List[str],
        top_candidates: List[POI],
        knowledge_hits: int,
    ) -> Dict[str, Any]:
        """构建完整的 attraction 结果。"""
        poi_list = self._normalize_poi_list(structured_pois, inputs)
        city = inputs.get("city") or inputs.get("destination") or ""
        prefs = self._extract_preferences(inputs)

        result: Dict[str, Any] = {
            "destination": inputs.get("destination") or city,
            "styles": inputs.get("travel_style") or [],
            "interests": prefs.get("interests") or [],
            "special_requirements": prefs.get("special_requirements") or [],
            "pois": structured_pois,
            "poi_list": poi_list,
            "poi_count": len(poi_list),
            "search_queries": search_keywords,
            "retrieval_mode": "poi_search_then_detail",
        }

        # 【本轮修复】不再生成含"高优先级 0 / 室内 0 / 室外 0"的 attraction_summary，
        # 概览首句改由 planner 基于 poi 实际特征（description / tags）生成自然语言导语。
        # attraction_summary 字段不再设置，引导 planner 完全依赖结构化 poi 数据。

        result["selection_rules"] = {
            "top_n": TOP_N,
            "max_search_queries": MAX_SEARCH_QUERIES,
            "search_limit_per_query": SEARCH_LIMIT,
        }
        result["applied_preferences"] = prefs
        if city:
            result["applied_preferences"]["city"] = city

        return result
