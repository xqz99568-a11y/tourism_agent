from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from app.agents.orchestrator import AgentOrchestrator
    from app.core.context import SessionContext
    from app.core.llm.client import LLMManager


class TourismSystemApp:
    """
    旅游规划系统主应用
    管理会话状态和 Agent 协调
    """

    def __init__(
        self,
        verify_opening_hours_online: bool = False,
        auto_repair: bool = False,
        max_revision_rounds: int = 0,
    ):
        self.verify_opening_hours_online = verify_opening_hours_online
        self.auto_repair = auto_repair
        self.max_revision_rounds = max_revision_rounds

        # CLI 启动时先保持轻量，首次真正处理请求时再初始化重对象
        self.llm: Optional["LLMManager"] = None
        self.orchestrator: Optional["AgentOrchestrator"] = None

        # 会话管理
        self._sessions: Dict[str, "SessionContext"] = {}

    def ensure_runtime_initialized(self) -> None:
        """延迟初始化 LLM、orchestrator 和 agents，避免 CLI 启动前阻塞。"""
        if self.llm is not None and self.orchestrator is not None:
            return

        from app.agents.attraction import AttractionAgent
        from app.agents.budget import BudgetAgent
        from app.agents.itinerary import ItineraryAgent
        from app.agents.orchestrator import AgentOrchestrator
        from app.agents.planner import PlannerAgent
        from app.agents.review import ReviewAgent
        from app.agents.weather import WeatherAgent
        from app.core.llm.client import LLMManager

        llm = LLMManager()
        orchestrator = AgentOrchestrator(llm)

        orchestrator.register_agent(PlannerAgent(llm))
        orchestrator.register_agent(AttractionAgent(llm))
        orchestrator.register_agent(ItineraryAgent(llm))
        orchestrator.register_agent(BudgetAgent(llm))
        orchestrator.register_agent(WeatherAgent(llm))
        orchestrator.register_agent(ReviewAgent(llm))

        self.llm = llm
        self.orchestrator = orchestrator

    def get_or_create_session(self, session_id: str) -> SessionContext:
        """获取或创建会话"""
        from app.core.context import SessionContext

        if session_id not in self._sessions:
            self._sessions[session_id] = SessionContext(session_id=session_id)
        return self._sessions[session_id]

    def reset_session(self, session_id: str) -> None:
        """重置会话"""
        if session_id in self._sessions:
            del self._sessions[session_id]

    def handle_query(self, text: str, session_id: str = "default") -> Dict[str, Any]:
        """
        同步处理查询（用于 CLI）
        """
        self.ensure_runtime_initialized()
        session = self.get_or_create_session(session_id)

        # 同步运行异步处理
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(self._process_async(text, session, session_id))
        return result

    async def _process_async(
        self,
        text: str,
        session: SessionContext,
        session_id: str,
    ) -> Dict[str, Any]:
        """异步处理查询"""
        self.ensure_runtime_initialized()
        responses = []
        final_content = ""
        thinking_steps = []
        last_step_count = 0
        requires_clarification = False
        clarification_message = ""
        questions = []
        missing_fields = []

        try:
            async for event in self.orchestrator.process(session, text, session_id):
                # 追踪追问信息
                if event.get("requires_clarification"):
                    requires_clarification = True
                    clarification_message = event.get("clarification_message", "")
                    questions = event.get("questions") or []
                    missing_fields = event.get("missing_fields") or []
                # 收集思考步骤
                if "thinking_steps" in event:
                    new_steps = event["thinking_steps"]
                    # 只打印新增的步骤
                    if len(new_steps) > last_step_count:
                        new_items = new_steps[last_step_count:]
                        if new_items:
                            self._print_thinking_steps(new_items)
                        last_step_count = len(new_steps)
                    thinking_steps = new_steps

                if event.get("status") == "completed" and "content" in event:
                    final_content = event["content"]

                if "results" in event:
                    responses = event["results"]

                # 记录 AI 响应
                if event.get("status") in ("completed", "failed"):
                    session.add_turn(
                        user_message=text,
                        ai_message=final_content,
                    )

        except Exception as e:
            return {
                "系统答复": f"处理请求时出错: {str(e)}",
                "会话ID": session_id,
                "轮次": session.turn_count,
                "思考步骤": thinking_steps,
            }

        # 构建结果
        result = {
            "系统答复": final_content or "抱歉，暂时无法处理您的请求。",
            "会话ID": session_id,
            "轮次": session.turn_count,
            "思考步骤": thinking_steps,
        }
        
        # 传递追问信息
        if requires_clarification:
            result["requires_clarification"] = True
            result["展示"] = {
                "mode": "need_info",
                "ask_question": clarification_message or "请补充关键信息。",
            }
            result["追问状态"] = {
                "缺失核心字段": missing_fields or [],
                "questions": questions or [],
            }
            # 追问时不显示系统答复
            result["系统答复"] = ""
        
        return result

    def _print_thinking_steps(self, steps: list) -> None:
        """打印思考步骤到控制台"""
        if not steps:
            return

        # 统一 Agent 名称大小写
        def format_agent(name: str) -> str:
            name_map = {
                "系统": "系统",
                "编排器": "编排器",
                "planner": "Planner",
                "attraction": "Attraction",
                "itinerary": "Itinerary",
                "budget": "Budget",
                "weather": "Weather",
                "review": "Review",
            }
            return name_map.get(name.lower(), name.capitalize())

        print("\n" + "-" * 60)
        print("Agent 协作过程")
        print("-" * 60)

        for step in steps:
            agent = format_agent(step.get("agent", "未知"))
            step_name = step.get("step", "")
            detail = step.get("detail", "")
            status = step.get("status", "")

            status_label = {
                "running": "RUNNING",
                "completed": "DONE",
                "failed": "FAILED",
            }.get(status, "INFO")
            print(f"{status_label} [{agent}] {step_name}: {detail}")

        print("-" * 60)


class ChatSession:
    """Chat Session 兼容类"""
    pass


def _configure_cli_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(errors="backslashreplace")


@lru_cache(maxsize=1)
def _get_request_models():
    from pydantic import BaseModel

    class ChatRequest(BaseModel):
        req: Optional[str] = None
        query: Optional[str] = None
        message: Optional[str] = None
        session_id: Optional[str] = None
        sessionId: Optional[str] = None

        def get_text(self) -> str:
            return str(self.message or self.query or self.req or "")

        def get_session_id(self) -> str:
            return str(self.session_id or self.sessionId or "web-default")

    class ResetRequest(BaseModel):
        session_id: Optional[str] = None
        sessionId: Optional[str] = None

        def get_session_id(self) -> str:
            return str(self.session_id or self.sessionId or "web-default")

    class FeedbackRequest(BaseModel):
        session_id: Optional[str] = None
        sessionId: Optional[str] = None
        rating: str | int  # 'positive' or 'negative'
        comment: Optional[str] = None

        def get_session_id(self) -> str:
            return str(self.session_id or self.sessionId or "web-default")

        def get_rating(self) -> str:
            if isinstance(self.rating, str):
                normalized = self.rating.strip().lower()
                if normalized in {"positive", "negative"}:
                    return normalized
                return "positive"

            return "positive" if int(self.rating) > 0 else "negative"

    ChatRequest.model_rebuild()
    ResetRequest.model_rebuild()
    FeedbackRequest.model_rebuild()

    return ChatRequest, ResetRequest, FeedbackRequest


def _save_feedback(session_id: str, rating: str, comment: Optional[str]) -> None:
    import os

    feedback_data = {
        "session_id": session_id,
        "rating": rating,
        "comment": comment,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    feedback_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "feedback")
    os.makedirs(feedback_dir, exist_ok=True)

    feedback_file = os.path.join(
        feedback_dir,
        f"feedback_{datetime.now().strftime('%Y%m%d')}.jsonl",
    )
    with open(feedback_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(feedback_data, ensure_ascii=False) + "\n")


def create_web_app(app: TourismSystemApp):
    try:
        from fastapi import Body, FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
    except Exception as exc:
        raise RuntimeError("Web 模式需要安装 fastapi uvicorn pydantic") from exc

    ChatRequest, ResetRequest, FeedbackRequest = _get_request_models()

    web = FastAPI(title="旅游规划 Agent 系统", version="1.0.0")

    web.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @web.get("/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "service": "旅游规划 Agent 系统",
            "time": datetime.now().isoformat(timespec="seconds"),
        }

    @web.post("/chat")
    def chat(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        text = str(payload.get("message") or payload.get("query") or payload.get("req") or "")
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "web-default").strip() or "web-default"

        try:
            app.ensure_runtime_initialized()
            return app.handle_query(text, session_id=session_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @web.post("/session/reset")
    def reset(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "web-default").strip() or "web-default"
        app.reset_session(session_id)
        return {"status": "ok", "session_id": session_id}

    @web.post("/feedback")
    def submit_feedback(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        try:
            session_id = str(payload.get("session_id") or payload.get("sessionId") or "web-default").strip() or "web-default"
            rating_input = payload.get("rating", "positive")
            if isinstance(rating_input, str):
                rating = "negative" if rating_input.strip().lower() == "negative" else "positive"
            else:
                rating = "positive" if int(rating_input) > 0 else "negative"
            comment = payload.get("comment")
            _save_feedback(session_id, rating, comment if isinstance(comment, str) else None)
            print(f"Received feedback: session_id={session_id}, rating={rating}, comment={comment}")
            return {"status": "ok", "message": "反馈提交成功"}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return web


def create_sse_app(app: TourismSystemApp):
    """创建支持SSE流式输出的Web应用"""
    try:
        from fastapi import Body, FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
        from sse_starlette import EventSourceResponse
    except Exception as exc:
        raise RuntimeError("Web 模式需要安装 fastapi uvicorn pydantic sse-starlette") from exc

    ChatRequest, ResetRequest, FeedbackRequest = _get_request_models()

    web = FastAPI(title="旅游规划 Agent 系统 (流式版)", version="1.1.0")

    web.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @web.get("/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "service": "旅游规划 Agent 系统",
            "time": datetime.now().isoformat(timespec="seconds"),
        }

    @web.post("/chat")
    def chat(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        text = str(payload.get("message") or payload.get("query") or payload.get("req") or "")
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "web-default").strip() or "web-default"

        try:
            app.ensure_runtime_initialized()
            return app.handle_query(text, session_id=session_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @web.post("/chat/stream")
    async def chat_stream(payload: Dict[str, Any] = Body(...)):
        """
        流式输出接口，使用 Server-Sent Events (SSE) 协议。
        实时返回 Agent 思考步骤和最终结果。
        """
        text = str(payload.get("message") or payload.get("query") or payload.get("req") or "")
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "web-default").strip() or "web-default"

        async def event_generator():
            from app.core.context import SessionContext

            app.ensure_runtime_initialized()

            # 获取或创建会话
            session = app.get_or_create_session(session_id)
            
            # 发送初始连接消息
            yield {
                "event": "connected",
                "data": json.dumps({
                    "type": "connected",
                    "session_id": session_id,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "message": "已连接，正在处理您的请求...",
                }, ensure_ascii=False)
            }
            
            last_thinking_count = 0
            sent_streaming_chunks = False
            streaming_content = ""
            
            try:
                # 使用真实的 orchestrator 流式输出
                async for event in app.orchestrator.process(session, text, session_id):
                    # 发送思考步骤更新
                    if "thinking_steps" in event and event["thinking_steps"]:
                        new_steps = event["thinking_steps"]
                        if len(new_steps) > last_thinking_count:
                            # 只发送新增的步骤
                            latest_step = new_steps[-1]
                            yield {
                                "event": "thinking_step",
                                "data": json.dumps({
                                    "type": "thinking_step",
                                    "step": latest_step,
                                    "all_steps": new_steps,
                                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                                }, ensure_ascii=False)
                            }
                            last_thinking_count = len(new_steps)
                    
                    # 发送阶段更新
                    if "phase" in event and "status" in event:
                        yield {
                            "event": "phase_update",
                            "data": json.dumps({
                                "type": "phase_update",
                                "phase": event.get("phase"),
                                "status": event.get("status"),
                                "message": event.get("message", ""),
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                            }, ensure_ascii=False)
                        }
                    
                    # orchestrator 主动发的 final event（SSE 标准格式）
                    if event.get("event") == "final" and event.get("data"):
                        yield event

                    # 发送正文增量（planner 的 streaming chunk）
                    if event.get("is_streaming") and isinstance(event.get("content"), str) and event.get("content"):
                        sent_streaming_chunks = True
                        streaming_content += event.get("content", "")
                        yield {
                            "event": "streaming",
                            "data": json.dumps({
                                "type": "streaming",
                                "content": event.get("content", ""),
                                "phase": event.get("phase"),
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                            }, ensure_ascii=False)
                        }
                    
                    # 发送最终结果（orchestrator 返回的 content 事件）
                    if event.get("status") == "completed" and "content" in event:
                        final_text = event.get("content", "") or ""
                        if sent_streaming_chunks and event.get("final_content_already_streamed"):
                            # 已经通过 streaming 事件增量发完正文，这里 final 只做结束标记，避免整段覆盖
                            final_text = ""
                        final_event = {
                            "event": "final",
                            "data": json.dumps({
                                "type": "final",
                                "content": final_text,
                                "thinking_steps": event.get("thinking_steps", []),
                                "execution_time_ms": event.get("execution_time_ms", 0),
                                "emotion": event.get("emotion", "neutral"),
                                "suggestions": event.get("suggestions", []),
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                            }, ensure_ascii=False)
                        }
                        # 缺信息追问：补充 structured 字段供前端兜底展示
                        if event.get("requires_clarification"):
                            parsed_data = json.loads(final_event["data"])
                            parsed_data["missing_fields"] = event.get("missing_fields", [])
                            parsed_data["clarification_questions"] = event.get("questions", [])
                            final_event["data"] = json.dumps(parsed_data, ensure_ascii=False)
                        yield final_event
                        
                        # 记录到会话
                        session.add_turn(
                            user_message=text,
                            ai_message=(streaming_content or event.get("content", "")),
                        )

            except Exception as exc:
                yield {
                    "event": "error",
                    "data": json.dumps({
                        "type": "error",
                        "message": str(exc),
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    }, ensure_ascii=False)
                }
            
            # 发送完成消息
            yield {
                "event": "done",
                "data": json.dumps({
                    "type": "done",
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                }, ensure_ascii=False)
            }
        
        return EventSourceResponse(event_generator())

    @web.post("/session/reset")
    def reset(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "web-default").strip() or "web-default"
        app.reset_session(session_id)
        return {"status": "ok", "session_id": session_id}

    @web.post("/feedback")
    def submit_feedback(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        try:
            session_id = str(payload.get("session_id") or payload.get("sessionId") or "web-default").strip() or "web-default"
            rating_input = payload.get("rating", "positive")
            if isinstance(rating_input, str):
                rating = "negative" if rating_input.strip().lower() == "negative" else "positive"
            else:
                rating = "positive" if int(rating_input) > 0 else "negative"
            comment = payload.get("comment")
            _save_feedback(session_id, rating, comment if isinstance(comment, str) else None)
            print(f"Received feedback: session_id={session_id}, rating={rating}, comment={comment}")
            return {"status": "ok", "message": "反馈提交成功"}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return web


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="旅游规划 Agent 启动入口")
    parser.add_argument("--mode", choices=["cli", "once", "web"], default="cli", help="运行模式")
    parser.add_argument("--query", type=str, default="", help="once 模式下的单次输入")
    parser.add_argument("--session-id", type=str, default="cli-default", help="会话 ID")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--verify-opening-hours-online", action="store_true", help="在线校验开放时间")
    parser.add_argument("--auto-repair", action="store_true", help="启用自动修复")
    parser.add_argument("--disable-auto-repair", action="store_true", help="禁用自动修复")
    parser.add_argument("--max-revision-rounds", type=int, default=0, help="最大修复轮数")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="web 监听地址")
    parser.add_argument("--port", type=int, default=8000, help="web 监听端口")
    return parser


def _build_app(args: argparse.Namespace) -> TourismSystemApp:
    auto_repair = bool(args.auto_repair) and not bool(args.disable_auto_repair)
    return TourismSystemApp(
        verify_opening_hours_online=bool(args.verify_opening_hours_online),
        auto_repair=auto_repair,
        max_revision_rounds=max(0, int(args.max_revision_rounds)),
    )


def _run_once(app: TourismSystemApp, args: argparse.Namespace) -> None:
    if not (args.query or "").strip():
        raise SystemExit("once 模式必须提供 --query")
    out = app.handle_query(args.query, session_id=args.session_id)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    # 处理非 JSON 输出
    reply = out.get("系统答复") or ""
    if reply:
        print(reply)
    else:
        print("抱歉，暂时无法处理您的请求。")


def _run_web(app: TourismSystemApp, args: argparse.Namespace) -> None:
    # 使用支持SSE的版本
    web = create_sse_app(app)
    try:
        import uvicorn  # type: ignore
    except Exception as exc:
        raise SystemExit("web 模式需要安装 uvicorn") from exc
    uvicorn.run(web, host=args.host, port=int(args.port))


def main() -> None:
    args = _build_parser().parse_args()
    app = _build_app(args)

    if args.mode == "once":
        _run_once(app, args)
        return
    if args.mode == "web":
        _run_web(app, args)
        return
    _configure_cli_stdio()
    from app.cli_runner import run_cli

    run_cli(app, session_id=args.session_id, show_json=bool(args.json))


__all__ = ["ChatSession", "TourismSystemApp", "create_web_app", "main"]


if __name__ == "__main__":
    main()
