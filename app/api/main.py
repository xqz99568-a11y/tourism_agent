"""
FastAPI 主应用入口
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
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
        user_message = request.message

        # 获取或创建会话
        if session_id not in _sessions:
            _sessions[session_id] = SessionContext(session_id=session_id)
        session = _sessions[session_id]

        # 处理请求
        results = []
        final_content = ""

        async for event in orchestrator.process(session, user_message, session_id):
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
        user_message = request.message

        # 【本轮修复】获取或创建会话
        if session_id not in _sessions:
            _sessions[session_id] = SessionContext(session_id=session_id)
        session = _sessions[session_id]

        # 【本轮修复】创建 abort_event 用于中止 orchestrator
        abort_event = asyncio.Event()

        async def generate():
            sent_streaming_chunks = False
            # 【本轮修复】注册 abort 回调：当 fetch abort 时设置 event
            def on_fetch_done():
                if not abort_event.is_set():
                    abort_event.set()

            try:
                # 【本轮修复】传递 abort_event 给 orchestrator
                async for event in orchestrator.process(session, user_message, session_id, abort_event=abort_event):
                    # 如果 abort_event 被设置，提前退出
                    if abort_event.is_set():
                        logger.info(f"Request {session_id} aborted by client")
                        break

                    if event.get("is_streaming") and isinstance(event.get("content"), str) and event.get("content"):
                        sent_streaming_chunks = True

                    is_terminal = (
                        event.get("phase") == "response_synthesis"
                        and event.get("status") == "completed"
                        and "content" in event
                    )
                    if is_terminal and sent_streaming_chunks and event.get("final_content_already_streamed"):
                        event_no_content = dict(event)
                        if isinstance(event_no_content.get("content"), str):
                            event_no_content["final_content_len"] = len(event_no_content["content"])
                        event_no_content["content"] = ""
                        yield f"data: {json.dumps(event_no_content, ensure_ascii=False)}\n\n"

                        final_marker = {
                            "type": "final",
                            "content": "",
                            "final_content_already_streamed": True,
                            "execution_time_ms": event.get("execution_time_ms", 0),
                            "emotion": event.get("emotion", "neutral"),
                            "suggestions": event.get("suggestions", []),
                        }
                        yield "event: final\n"
                        yield f"data: {json.dumps(final_marker, ensure_ascii=False)}\n\n"
                    else:
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    # 主动让出事件循环，尽快把当前 chunk 刷给客户端
                    await asyncio.sleep(0)

                yield "data: [DONE]\n\n"
            except asyncio.CancelledError:
                # 【本轮修复】捕获取消异常，确保 abort_event 被设置
                if not abort_event.is_set():
                    abort_event.set()
                logger.info(f"Request {session_id} cancelled")
                raise

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
