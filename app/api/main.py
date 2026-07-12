"""
FastAPI 主应用入口
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import json
from pydantic import BaseModel

from app.core.config import settings
from app.core.context import SessionContext
from app.core.llm.client import LLMManager
from app.core.logger import get_logger, setup_logging
from app.agents.orchestrator import AgentOrchestrator
from app.agents.planner import PlannerAgent
from app.agents.attraction import AttractionAgent
from app.agents.itinerary import ItineraryAgent
from app.agents.budget import BudgetAgent
from app.agents.weather import WeatherAgent
from app.agents.review import ReviewAgent
from app.core.tracing import mark_trace_status

logger = get_logger(__name__)


class ChatRequestSchema(BaseModel):
    """聊天请求"""
    session_id: Optional[str] = None
    sessionId: Optional[str] = None  # 前端兼容
    message: str

    def get_session_id(self) -> str:
        """获取会话 ID，兼容两种命名"""
        return self.session_id or self.sessionId or str(uuid.uuid4())


class ChatResponseSchema(BaseModel):
    """聊天响应"""
    session_id: str
    message_id: str
    content: str


llm_manager: Optional[LLMManager] = None
orchestrator: Optional[AgentOrchestrator] = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理"""
    global llm_manager, orchestrator

    logger.info("Starting Tourism Agent API...")

    setup_logging()

    # 初始化 LLM
    llm_manager = LLMManager()

    # 初始化编排器
    orchestrator = AgentOrchestrator(llm_manager)

    # 注册 Agent
    orchestrator.register_agent(PlannerAgent(llm_manager))
    orchestrator.register_agent(AttractionAgent(llm_manager))
    orchestrator.register_agent(ItineraryAgent(llm_manager))
    orchestrator.register_agent(BudgetAgent(llm_manager))
    orchestrator.register_agent(WeatherAgent(llm_manager))
    orchestrator.register_agent(ReviewAgent(llm_manager))

    logger.info("Tourism Agent API started successfully")

    yield

    logger.info("Tourism Agent API shutdown complete")


def create_app() -> FastAPI:
    allowed_origins = sorted({
        settings.frontend_url.rstrip("/"),
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    })
    """创建 FastAPI 应用"""
    app = FastAPI(
        title="Tourism Agent API",
        description="基于 Multi-Agent 的智能旅游规划系统",
        version=settings.version,
        lifespan=lifespan,
    )

    # 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 会话存储
    _sessions: Dict[str, SessionContext] = {}

    # 异常处理
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail},
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(f"Unhandled exception: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error"},
        )

    # 路由
    @app.get("/health")
    async def health_check() -> Dict[str, Any]:
        """健康检查"""
        return {
            "status": "healthy",
            "version": settings.version,
        }

    @app.post("/chat", response_model=ChatResponseSchema)
    async def chat(request: ChatRequestSchema) -> ChatResponseSchema:
        """对话接口"""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Service not initialized")

        session_id = request.get_session_id()
        request_id = str(uuid.uuid4())
        user_message = request.message

        # 获取或创建会话
        if session_id not in _sessions:
            _sessions[session_id] = SessionContext(session_id=session_id)
        session = _sessions[session_id]

        # 处理请求
        results = []
        final_content = ""

        async for event in orchestrator.process(session, user_message, request_id):
            if event.get("status") == "completed" and "content" in event:
                final_content = event["content"]
            if "results" in event:
                results = event["results"]

        return ChatResponseSchema(
            session_id=session_id,
            message_id=str(uuid.uuid4()),
            content=final_content,
        )

    @app.post("/chat/stream")
    async def chat_stream(request: ChatRequestSchema):
        """流式对话接口"""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Service not initialized")

        session_id = request.get_session_id()
        request_id = str(uuid.uuid4())
        user_message = request.message

        # 【本轮修复】获取或创建会话
        if session_id not in _sessions:
            _sessions[session_id] = SessionContext(session_id=session_id)
        session = _sessions[session_id]

        # 【本轮修复】创建 abort_event 用于中止 orchestrator
        abort_event = asyncio.Event()

        def build_sse_payload(
            event_type: str,
            *,
            content: str = "",
            content_kind: str = "none",
            phase: str = "",
            status: str = "",
            base: Optional[Dict[str, Any]] = None,
            **extra: Any,
        ) -> Dict[str, Any]:
            payload: Dict[str, Any] = {}
            if base:
                payload.update(
                    {
                        key: value
                        for key, value in base.items()
                        if key not in {"event", "data", "type", "content", "content_kind", "is_streaming"}
                    }
                )
            payload.update(
                {
                    "type": event_type,
                    "content": content,
                    "content_kind": content_kind,
                    "phase": phase,
                    "status": status,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                }
            )
            for key, value in extra.items():
                if value is not None:
                    payload[key] = value
            return payload

        def format_sse(event_name: str, payload_data: Dict[str, Any]) -> str:
            return f"event: {event_name}\n" + f"data: {json.dumps(payload_data, ensure_ascii=False)}\n\n"

        async def generate():
            last_thinking_count = 0
            streaming_content = ""
            yield format_sse(
                "connected",
                build_sse_payload(
                    "connected",
                    content_kind="none",
                    phase="connection",
                    status="connected",
                    session_id=session_id,
                    message="已连接，正在处理您的请求...",
                ),
            )
            # 【本轮修复】注册 abort 回调：当 fetch abort 时设置 event
            def on_fetch_done():
                if not abort_event.is_set():
                    abort_event.set()

            try:
                # 【本轮修复】传递 abort_event 给 orchestrator
                async for event in orchestrator.process(session, user_message, request_id, abort_event=abort_event):
                    # 如果 abort_event 被设置，提前退出
                    if abort_event.is_set():
                        mark_trace_status("aborted", error="client abort_event set")
                        logger.info(f"Request {request_id} aborted by client")
                        break

                    raw_content = event.get("content")
                    is_streaming_chunk = (
                        bool(event.get("is_streaming"))
                        and isinstance(raw_content, str)
                        and bool(raw_content)
                    )
                    is_terminal = event.get("status") == "completed" and isinstance(raw_content, str)

                    if "thinking_steps" in event and event["thinking_steps"]:
                        new_steps = event["thinking_steps"]
                        if len(new_steps) > last_thinking_count:
                            latest_step = new_steps[-1]
                            yield format_sse(
                                "thinking_step",
                                build_sse_payload(
                                    "thinking_step",
                                    content_kind="none",
                                    phase="agent_step",
                                    status="running",
                                    step=latest_step,
                                    all_steps=new_steps,
                                    thinking_steps=new_steps,
                                ),
                            )
                            last_thinking_count = len(new_steps)

                    if event.get("event") == "final" and event.get("data"):
                        raw_final_data = event.get("data")
                        if isinstance(raw_final_data, str):
                            try:
                                parsed_final = json.loads(raw_final_data)
                            except json.JSONDecodeError:
                                parsed_final = {"content": raw_final_data}
                        elif isinstance(raw_final_data, dict):
                            parsed_final = raw_final_data
                        else:
                            parsed_final = {}
                        yield format_sse(
                            "final",
                            build_sse_payload(
                                "final",
                                content=str(parsed_final.get("content") or ""),
                                content_kind="final_full",
                                phase=str(parsed_final.get("phase") or event.get("phase") or "response_synthesis"),
                                status=str(parsed_final.get("status") or event.get("status") or "completed"),
                                base=parsed_final if isinstance(parsed_final, dict) else None,
                            ),
                        )
                        continue

                    if is_streaming_chunk:
                        streaming_content += raw_content
                        yield format_sse(
                            "streaming",
                            build_sse_payload(
                                "streaming",
                                content=raw_content,
                                content_kind="delta",
                                phase=str(event.get("phase") or "response_synthesis"),
                                status=str(event.get("status") or "running"),
                                base=event,
                            ),
                        )
                        await asyncio.sleep(0)
                        continue

                    if is_terminal:
                        final_text = raw_content or ""
                        yield format_sse(
                            "final",
                            build_sse_payload(
                                "final",
                                content=final_text,
                                content_kind="final_full",
                                phase=str(event.get("phase") or "response_synthesis"),
                                status=str(event.get("status") or "completed"),
                                base=event,
                            ),
                        )
                        await asyncio.sleep(0)
                        continue
                    if (
                        "phase" in event
                        and "status" in event
                        and not event.get("is_streaming")
                        and not (event.get("status") == "completed" and "content" in event)
                    ):
                        yield format_sse(
                            "phase_update",
                            build_sse_payload(
                                "phase_update",
                                content_kind="none",
                                phase=str(event.get("phase") or ""),
                                status=str(event.get("status") or ""),
                                base=event,
                            ),
                        )
                        await asyncio.sleep(0)
                    # 主动让出事件循环，尽快把当前 chunk 刷给客户端
                    await asyncio.sleep(0)

                yield format_sse(
                    "done",
                    build_sse_payload(
                        "done",
                        content_kind="none",
                        phase="connection",
                        status="completed",
                    ),
                )
            except asyncio.CancelledError:
                # 【本轮修复】捕获取消异常，确保 abort_event 被设置
                if not abort_event.is_set():
                    abort_event.set()
                mark_trace_status("cancelled", error="client cancelled SSE stream")
                logger.info(f"Request {request_id} cancelled")
                raise
            except Exception as exc:
                yield format_sse(
                    "error",
                    build_sse_payload(
                        "error",
                        content_kind="none",
                        phase="error",
                        status="failed",
                        message=str(exc),
                    ),
                )

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/session/reset")
    async def reset_session(session_id: str) -> Dict[str, str]:
        """重置会话"""
        if session_id in _sessions:
            del _sessions[session_id]
        return {"status": "success", "message": f"Session {session_id} reset"}

    return app


# 应用实例
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.api.main:app",
        host=settings.server.host,
        port=settings.server.port,
        reload=settings.server.reload,
    )
