"""
Context 模块
管理对话上下文和会话状态
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Callable, Awaitable, Union

from app.core.logger import get_logger

if TYPE_CHECKING:
    from app.schemas.messages import UserMessage, AIMessage, SystemMessage


logger = get_logger(__name__)


class ThinkingStatus(str, Enum):
    """思考状态"""
    PENDING = "pending"      # 等待中
    RUNNING = "running"      # 执行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"       # 失败


@dataclass
class ReasoningNode:
    """推理节点 - 构成推理链的基本单元"""
    content: str  # 推理内容
    reasoning_type: str = "analysis"  # analysis/inference/decision/fact
    confidence: float = 1.0  # 置信度 0-1
    children: List["ReasoningNode"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "reasoning_type": self.reasoning_type,
            "confidence": self.confidence,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class ToolCall:
    """工具调用记录"""
    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    result: Optional[str] = None
    status: str = "pending"  # pending/running/completed/failed
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    error: Optional[str] = None

    @property
    def duration_ms(self) -> float:
        """执行时长（毫秒）"""
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000

    def complete(self, result: str = None, error: str = None) -> None:
        """完成调用"""
        self.end_time = time.time()
        self.status = "failed" if error else "completed"
        self.result = result
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "result": self.result,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class APICall:
    """外部 API 调用记录"""
    service: str  # 服务名称，如 "高德地图API"
    endpoint: str  # API 端点
    params: Dict[str, Any] = field(default_factory=dict)  # 请求参数
    response: Optional[Dict[str, Any]] = None  # 响应数据（脱敏后）
    status: str = "pending"  # pending/running/completed/failed
    http_status: Optional[int] = None  # HTTP 状态码
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    error: Optional[str] = None
    cost_ms: Optional[float] = None  # 实际耗时

    @property
    def duration_ms(self) -> float:
        """执行时长（毫秒）"""
        if self.cost_ms is not None:
            return self.cost_ms
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000

    def complete(
        self,
        response: Dict[str, Any] = None,
        http_status: int = 200,
        error: str = None,
        cost_ms: float = None,
    ) -> None:
        """完成调用"""
        self.end_time = time.time()
        self.cost_ms = cost_ms
        if error:
            self.status = "failed"
            self.error = error
            self.http_status = http_status or 500
        else:
            self.status = "completed"
            self.http_status = http_status or 200
            # 存储响应（可选择脱敏）
            if response:
                self.response = self._sanitize_response(response)

    def _sanitize_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """脱敏响应数据，移除敏感信息"""
        sanitized = {}
        # 保留关键字段
        for key in ["count", "pois", "lives", "forecasts", "status", "info", "count"]:
            if key in response:
                sanitized[key] = response[key]
        # 限制数量
        if "pois" in sanitized and isinstance(sanitized["pois"], list):
            sanitized["pois"] = sanitized["pois"][:5]  # 只保留前5条
        return sanitized

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service": self.service,
            "endpoint": self.endpoint,
            "params": self.params,
            "response": self.response,
            "status": self.status,
            "http_status": self.http_status,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class RAGQuery:
    """RAG 检索查询记录"""
    query: str  # 检索查询
    retrieved_docs: List[str] = field(default_factory=list)  # 检索到的文档摘要
    relevance_scores: List[float] = field(default_factory=list)  # 相关性得分
    selected_doc: Optional[str] = None  # 最终选择的文档
    status: str = "running"  # running/completed/failed
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    error: Optional[str] = None

    @property
    def duration_ms(self) -> float:
        """检索耗时（毫秒）"""
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000

    def complete(self, selected_doc: str = None, error: str = None) -> None:
        """完成检索"""
        self.end_time = time.time()
        if error:
            self.status = "failed"
            self.error = error
        else:
            self.status = "completed"
            self.selected_doc = selected_doc

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "retrieved_docs": self.retrieved_docs,
            "relevance_scores": self.relevance_scores,
            "selected_doc": self.selected_doc,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class LearningStep:
    """用户画像学习步骤"""
    user_action: str  # 用户行为描述
    system_learned: str  # 系统学习到的内容
    confidence: float = 0.0  # 置信度
    category: str = "preference"  # preference/behavior/budget/timing
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_action": self.user_action,
            "system_learned": self.system_learned,
            "confidence": self.confidence,
            "category": self.category,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class AgentMetrics:
    """Agent 执行指标"""
    agent_name: str
    execution_time_ms: float = 0
    tokens_used: int = 0
    tool_calls_count: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    status: str = "pending"

    def complete(self, tokens_used: int = 0) -> None:
        """完成指标记录"""
        self.end_time = time.time()
        self.execution_time_ms = (self.end_time - self.start_time) * 1000
        self.tokens_used = tokens_used
        self.status = "completed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "execution_time_ms": self.execution_time_ms,
            "tokens_used": self.tokens_used,
            "tool_calls_count": self.tool_calls_count,
            "status": self.status,
        }


@dataclass
class AgentThinkingStep:
    """Agent 思考步骤 - 增强版"""
    agent_name: str
    step: str
    detail: str = ""
    status: str = "running"  # pending/running/completed/failed

    # 增强字段
    reasoning_chain: List[ReasoningNode] = field(default_factory=list)  # 推理链
    tool_calls: List[ToolCall] = field(default_factory=list)  # 工具调用
    api_calls: List[APICall] = field(default_factory=list)  # 外部API调用
    rag_queries: List[RAGQuery] = field(default_factory=list)  # RAG检索
    learning_steps: List[LearningStep] = field(default_factory=list)  # 用户学习
    context: Dict[str, Any] = field(default_factory=dict)  # 上下文信息
    confidence: float = 0.0  # 置信度
    sub_steps: List["AgentThinkingStep"] = field(default_factory=list)  # 子步骤
    waiting_for: Optional[List[str]] = None  # 等待的依赖

    timestamp: datetime = field(default_factory=datetime.utcnow)

    def add_reasoning(
        self,
        content: str,
        reasoning_type: str = "analysis",
        confidence: float = 1.0,
    ) -> ReasoningNode:
        """添加推理节点"""
        node = ReasoningNode(
            content=content,
            reasoning_type=reasoning_type,
            confidence=confidence,
        )
        self.reasoning_chain.append(node)
        return node

    def add_tool_call(self, tool_name: str, arguments: Dict[str, Any] = None) -> ToolCall:
        """添加工具调用"""
        call = ToolCall(
            tool_name=tool_name,
            arguments=arguments or {},
        )
        self.tool_calls.append(call)
        return call

    def add_api_call(
        self,
        service: str,
        endpoint: str,
        params: Dict[str, Any] = None,
    ) -> APICall:
        """添加外部API调用"""
        call = APICall(
            service=service,
            endpoint=endpoint,
            params=params or {},
        )
        self.api_calls.append(call)
        return call

    def add_rag_query(
        self,
        query: str,
        retrieved_docs: List[str] = None,
        relevance_scores: List[float] = None,
    ) -> RAGQuery:
        """添加RAG检索查询"""
        rag = RAGQuery(
            query=query,
            retrieved_docs=retrieved_docs or [],
            relevance_scores=relevance_scores or [],
        )
        self.rag_queries.append(rag)
        return rag

    def add_learning_step(
        self,
        user_action: str,
        system_learned: str,
        confidence: float = 0.0,
        category: str = "preference",
    ) -> LearningStep:
        """添加用户学习步骤"""
        step = LearningStep(
            user_action=user_action,
            system_learned=system_learned,
            confidence=confidence,
            category=category,
        )
        self.learning_steps.append(step)
        return step

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent_name,
            "step": self.step,
            "detail": self.detail,
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
            "reasoning_chain": [r.to_dict() for r in self.reasoning_chain],
            "tool_calls": [t.to_dict() for t in self.tool_calls],
            "api_calls": [a.to_dict() for a in self.api_calls],
            "rag_queries": [r.to_dict() for r in self.rag_queries],
            "learning_steps": [l.to_dict() for l in self.learning_steps],
            "context": self.context,
            "confidence": self.confidence,
            "sub_steps": [s.to_dict() for s in self.sub_steps],
            "waiting_for": self.waiting_for,
        }

    @property
    def reasoning_text(self) -> str:
        """获取推理链文本"""
        lines = []
        for node in self.reasoning_chain:
            icon = {
                "analysis": "🔍",
                "inference": "🤔",
                "decision": "✅",
                "fact": "📌",
            }.get(node.reasoning_type, "💡")
            lines.append(f"{icon} {node.content}")
        return "\n".join(lines) if lines else self.detail


@dataclass
class ConversationTurn:
    """对话轮次"""
    turn_id: int
    user_message: str
    ai_message: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    agent_name: Optional[str] = None
    tools_used: List[str] = field(default_factory=list)
    execution_time_ms: Optional[float] = None


@dataclass
class UserPreferences:
    """用户偏好"""
    travel_style: List[str] = field(default_factory=list)  # 轻松/冒险/文化/美食
    budget_level: str = "medium"  # economy/medium/luxury
    tourist_type: str = "general"  # backpacker/family/luxury/couple/senior
    preferred_seasons: List[str] = field(default_factory=list)
    dietary_restrictions: List[str] = field(default_factory=list)
    mobility_requirements: List[str] = field(default_factory=list)
    interests: List[str] = field(default_factory=list)
    special_needs: List[str] = field(default_factory=list)

    # 学习到的偏好
    liked_attractions: List[str] = field(default_factory=list)
    disliked_attractions: List[str] = field(default_factory=list)
    preferred_destinations: List[str] = field(default_factory=list)
    average_trip_duration: Optional[int] = None  # 天数

    # 新增：扩展偏好
    age_group: Optional[str] = None  # 儿童/青年/中年/老年
    group_type: Optional[str] = None  # solo/couple/family/friends
    pace_preference: str = "moderate"  # tight/moderate/relaxed
    favorite_time_of_day: List[str] = field(default_factory=list)  # 上午/下午/晚上
    accessibility_needs: bool = False  # 无障碍需求

    # 情感偏好
    preferred_response_style: str = "friendly"  # friendly/formal/casual
    patience_level: str = "normal"  # low/normal/high

    @property
    def special_requirements(self) -> List[str]:
        """兼容 intent schema 中的 special_requirements 命名"""
        return self.special_needs

    @special_requirements.setter
    def special_requirements(self, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, list):
            self.special_needs = value
        elif isinstance(value, str):
            self.special_needs = [value] if value else []
        else:
            self.special_needs = list(value)


@dataclass
class TripContext:
    """旅行上下文"""
    destination: Optional[str] = None
    departure_place: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    duration_days: Optional[int] = None
    budget_amount: Optional[float] = None
    num_travelers: int = 1
    traveler_ages: List[int] = field(default_factory=list)  # 儿童/成人/老人
    is_domestic: bool = True  # 国内/境外

    # 已规划的行程
    planned_days: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def origin(self) -> Optional[str]:
        """兼容 intent schema 中的 origin 命名"""
        return self.departure_place

    @origin.setter
    def origin(self, value: Optional[str]) -> None:
        if value is not None:
            self.departure_place = value

    def to_snapshot(self) -> Dict[str, Any]:
        """转换为可序列化的快照"""
        return {
            "destination": self.destination,
            "departure_place": self.departure_place,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "duration_days": self.duration_days,
            "budget_amount": self.budget_amount,
            "num_travelers": self.num_travelers,
            "traveler_ages": self.traveler_ages,
            "is_domestic": self.is_domestic,
            "planned_days": self.planned_days,
        }

    @classmethod
    def from_snapshot(cls, data: Dict[str, Any]) -> "TripContext":
        """从快照恢复"""
        return cls(
            destination=data.get("destination"),
            departure_place=data.get("departure_place"),
            start_date=datetime.fromisoformat(data["start_date"]) if data.get("start_date") else None,
            end_date=datetime.fromisoformat(data["end_date"]) if data.get("end_date") else None,
            duration_days=data.get("duration_days"),
            budget_amount=data.get("budget_amount"),
            num_travelers=data.get("num_travelers", 1),
            traveler_ages=data.get("traveler_ages", []),
            is_domestic=data.get("is_domestic", True),
            planned_days=data.get("planned_days", []),
        )


@dataclass
class CommittedTripSnapshot:
    """
    【本轮新增】已提交的旅行快照
    - durable，跨 turn 继承
    - 用于 follow-up 的基础
    - 只在成功完成规划或成功完成 follow-up 后更新
    """
    # 核心字段
    destination: Optional[str] = None
    duration_days: Optional[int] = None
    budget_amount: Optional[float] = None
    travel_dates: Optional[str] = None  # 字符串格式便于序列化
    people_count: int = 1
    
    # 偏好
    preferences: List[str] = field(default_factory=list)  # 美食/拍照/轻松/室内优先等
    
    # 已生成计划的结构化摘要
    plan_summary: Optional[Dict[str, Any]] = None
    
    # 元数据
    last_committed_turn_id: Optional[str] = None
    committed_at: datetime = field(default_factory=datetime.utcnow)
    
    def is_complete(self) -> bool:
        """检查快照是否完整（足以支持 follow-up）"""
        return all([
            self.destination,
            self.duration_days,
        ])
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "destination": self.destination,
            "duration_days": self.duration_days,
            "budget_amount": self.budget_amount,
            "travel_dates": self.travel_dates,
            "people_count": self.people_count,
            "preferences": self.preferences,
            "plan_summary": self.plan_summary,
            "last_committed_turn_id": self.last_committed_turn_id,
            "committed_at": self.committed_at.isoformat(),
        }


@dataclass 
class PendingClarificationLatch:
    """
    【本轮新增】待处理追问锁存器
    - transient session-scoped，低优先级，可被抢占
    - 用于识别像"3天""预算2000"这样的直接回答
    - 完整新规划和一般追问可以抢占它
    """
    # 缺失的槽位（使用统一 canonical slot names）
    missing_slots: List[str] = field(default_factory=list)
    
    # 来源信息
    origin_turn_id: Optional[str] = None
    origin_request_id: Optional[str] = None
    origin_intent: str = "unknown"
    
    # 已提取的部分信息
    partial_extracted: Dict[str, Any] = field(default_factory=dict)
    
    # 时间戳
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    # 是否已消费
    consumed: bool = False
    
    # 是否已过期（超过一定时间未响应）
    expired: bool = False
    
    def is_active(self) -> bool:
        """检查 latch 是否仍然有效"""
        return not self.consumed and not self.expired
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "missing_slots": self.missing_slots,
            "origin_turn_id": self.origin_turn_id,
            "origin_request_id": self.origin_request_id,
            "origin_intent": self.origin_intent,
            "partial_extracted": self.partial_extracted,
            "created_at": self.created_at.isoformat(),
            "consumed": self.consumed,
            "expired": self.expired,
        }


@dataclass
class ExecutionContext:
    """执行上下文 - 用于 Agent 间共享"""
    request_id: str
    session_id: str
    user_id: Optional[str] = None

    # 当前状态
    current_phase: str = "init"
    active_agents: List[str] = field(default_factory=list)
    completed_agents: List[str] = field(default_factory=list)

    # 中间结果
    extracted_info: Dict[str, Any] = field(default_factory=dict)
    agent_results: Dict[str, Any] = field(default_factory=dict)

    # 错误处理
    errors: List[Dict[str, Any]] = field(default_factory=dict)
    retry_count: int = 0

    # 思考步骤日志
    thinking_steps: List[AgentThinkingStep] = field(default_factory=list)

    # Agent 执行指标
    agent_metrics: Dict[str, AgentMetrics] = field(default_factory=dict)

    # 流式回调（用于实时输出思考步骤）
    thinking_callback: Optional[Callable[[AgentThinkingStep], Awaitable[None]]] = None
    # 指标回调
    metrics_callback: Optional[Callable[[AgentMetrics], Awaitable[None]]] = None

    # 流式事件队列（用于批处理）
    _pending_events: List[Dict[str, Any]] = field(default_factory=list)
    _stream_enabled: bool = True

    def enable_streaming(self) -> None:
        """启用流式输出"""
        self._stream_enabled = True

    def disable_streaming(self) -> None:
        """禁用流式输出（用于批量处理）"""
        self._stream_enabled = False

    def add_result(self, agent_name: str, result: Any) -> None:
        """添加 Agent 结果"""
        self.agent_results[agent_name] = result
        if agent_name not in self.completed_agents:
            self.completed_agents.append(agent_name)

    def get_result(self, agent_name: str) -> Optional[Any]:
        """获取 Agent 结果"""
        return self.agent_results.get(agent_name)

    def has_result(self, agent_name: str) -> bool:
        """检查是否有结果"""
        return agent_name in self.agent_results

    def add_error(self, agent_name: str, error: Union[Exception, str]) -> None:
        """添加错误"""
        error_str = str(error) if isinstance(error, Exception) else error
        self.errors[agent_name] = {
            "agent": agent_name,
            "error": error_str,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.retry_count += 1

    def start_agent_metrics(self, agent_name: str) -> AgentMetrics:
        """开始记录 Agent 执行指标"""
        metrics = AgentMetrics(agent_name=agent_name)
        self.agent_metrics[agent_name] = metrics
        return metrics

    def complete_agent_metrics(self, agent_name: str, tokens_used: int = 0) -> Optional[AgentMetrics]:
        """完成 Agent 指标记录"""
        metrics = self.agent_metrics.get(agent_name)
        if metrics:
            metrics.complete(tokens_used)
            # 触发指标回调
            if self.metrics_callback and self._stream_enabled:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(self.metrics_callback(metrics))
                    else:
                        asyncio.run(self.metrics_callback(metrics))
                except Exception:
                    pass
        return metrics

    def add_thinking_step(
        self,
        agent_name: str,
        step: str,
        detail: str = "",
        status: str = "running",
        reasoning_chain: Optional[List[Dict[str, Any]]] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        api_calls: Optional[List[Dict[str, Any]]] = None,
        rag_queries: Optional[List[Dict[str, Any]]] = None,
        learning_steps: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        confidence: float = 0.0,
        waiting_for: Optional[List[str]] = None,
    ) -> AgentThinkingStep:
        """添加思考步骤 - 增强版"""
        thinking_step = AgentThinkingStep(
            agent_name=agent_name,
            step=step,
            detail=detail,
            status=status,
            confidence=confidence,
            waiting_for=waiting_for,
        )

        # 添加推理链
        if reasoning_chain:
            for r in reasoning_chain:
                thinking_step.add_reasoning(
                    content=r.get("content", ""),
                    reasoning_type=r.get("reasoning_type", "analysis"),
                    confidence=r.get("confidence", 1.0),
                )

        # 添加工具调用
        if tool_calls:
            for tc in tool_calls:
                call = thinking_step.add_tool_call(
                    tool_name=tc.get("tool_name", ""),
                    arguments=tc.get("arguments", {}),
                )
                if tc.get("status") == "completed":
                    call.complete(result=tc.get("result"))

        # 添加外部API调用
        if api_calls:
            for ac in api_calls:
                call = thinking_step.add_api_call(
                    service=ac.get("service", ""),
                    endpoint=ac.get("endpoint", ""),
                    params=ac.get("params", {}),
                )
                if ac.get("status") == "completed":
                    call.complete(
                        response=ac.get("response"),
                        http_status=ac.get("http_status", 200),
                    )

        # 添加RAG检索
        if rag_queries:
            for rq in rag_queries:
                rag = thinking_step.add_rag_query(
                    query=rq.get("query", ""),
                    retrieved_docs=rq.get("retrieved_docs", []),
                    relevance_scores=rq.get("relevance_scores", []),
                )
                if rq.get("status") == "completed":
                    rag.complete(selected_doc=rq.get("selected_doc"))

        # 添加学习步骤
        if learning_steps:
            for ls in learning_steps:
                thinking_step.add_learning_step(
                    user_action=ls.get("user_action", ""),
                    system_learned=ls.get("system_learned", ""),
                    confidence=ls.get("confidence", 0.0),
                    category=ls.get("category", "preference"),
                )

        # 添加上下文
        if context:
            thinking_step.context = context

        self.thinking_steps.append(thinking_step)

        # 流式回调
        if self.thinking_callback and self._stream_enabled:
            self._emit_thinking_event(thinking_step)

        return thinking_step

    def _emit_thinking_event(self, step: AgentThinkingStep) -> None:
        """触发思考步骤事件"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._safe_callback(step))
            else:
                asyncio.run(self._safe_callback(step))
        except Exception:
            pass

    async def _safe_callback(self, step: AgentThinkingStep) -> None:
        """安全的回调执行"""
        try:
            if self.thinking_callback:
                await self.thinking_callback(step)
        except Exception:
            pass

    def update_thinking_step(
        self,
        agent_name: str,
        step: str,
        detail: str = "",
        status: str = "completed",
        reasoning_chain: Optional[List[Dict[str, Any]]] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        api_calls: Optional[List[Dict[str, Any]]] = None,
        context: Optional[Dict[str, Any]] = None,
        confidence: float = 0.0,
    ) -> None:
        """更新思考步骤状态"""
        # 查找最近的未完成的同类型步骤
        for ts in reversed(self.thinking_steps):
            if ts.agent_name == agent_name and ts.step == step:
                # 更新基本信息
                if detail:
                    ts.detail = detail
                ts.status = status
                if confidence > 0:
                    ts.confidence = confidence

                # 更新推理链
                if reasoning_chain:
                    for r in reasoning_chain:
                        ts.add_reasoning(
                            content=r.get("content", ""),
                            reasoning_type=r.get("reasoning_type", "analysis"),
                            confidence=r.get("confidence", 1.0),
                        )

                # 更新工具调用
                if tool_calls:
                    for tc in tool_calls:
                        call = ts.add_tool_call(
                            tool_name=tc.get("tool_name", ""),
                            arguments=tc.get("arguments", {}),
                        )
                        if tc.get("status") == "completed":
                            call.complete(result=tc.get("result"))

                # 更新外部API调用
                if api_calls:
                    for ac in api_calls:
                        call = ts.add_api_call(
                            service=ac.get("service", ""),
                            endpoint=ac.get("endpoint", ""),
                            params=ac.get("params", {}),
                        )
                        if ac.get("status") == "completed":
                            call.complete(
                                response=ac.get("response"),
                                http_status=ac.get("http_status", 200),
                            )

                # 更新上下文
                if context:
                    ts.context.update(context)

                # 触发回调
                if self.thinking_callback and self._stream_enabled:
                    self._emit_thinking_event(ts)
                break

    def add_sub_thinking_step(
        self,
        parent_agent: str,
        parent_step: str,
        sub_agent: str,
        sub_step: str,
        sub_detail: str = "",
    ) -> AgentThinkingStep:
        """添加子思考步骤"""
        # 查找父步骤
        parent = None
        for ts in reversed(self.thinking_steps):
            if ts.agent_name == parent_agent and ts.step == parent_step:
                parent = ts
                break

        if parent:
            sub = AgentThinkingStep(
                agent_name=sub_agent,
                step=sub_step,
                detail=sub_detail,
                status="running",
            )
            parent.sub_steps.append(sub)
            return sub
        else:
            # 如果没找到父步骤，直接添加
            return self.add_thinking_step(
                agent_name=sub_agent,
                step=sub_step,
                detail=sub_detail,
            )

    def add_reasoning_to_latest(
        self,
        agent_name: str,
        content: str,
        reasoning_type: str = "analysis",
        confidence: float = 1.0,
    ) -> Optional[ReasoningNode]:
        """向最新的思考步骤添加推理节点"""
        for ts in reversed(self.thinking_steps):
            if ts.agent_name == agent_name:
                node = ts.add_reasoning(content, reasoning_type, confidence)
                # 更新 detail 为推理链文本
                ts.detail = ts.reasoning_text
                return node
        return None

    def add_rag_query_to_latest(
        self,
        agent_name: str,
        query: str,
        retrieved_docs: List[str] = None,
        relevance_scores: List[float] = None,
        selected_doc: str = None,
        status: str = "completed",
    ) -> Optional[RAGQuery]:
        """向最新的思考步骤添加RAG检索记录"""
        for ts in reversed(self.thinking_steps):
            if ts.agent_name == agent_name:
                rag = ts.add_rag_query(
                    query=query,
                    retrieved_docs=retrieved_docs or [],
                    relevance_scores=relevance_scores or [],
                )
                if status == "completed":
                    rag.complete(selected_doc=selected_doc)
                return rag
        return None

    def add_learning_step_to_latest(
        self,
        agent_name: str,
        user_action: str,
        system_learned: str,
        confidence: float = 0.0,
        category: str = "preference",
    ) -> Optional[LearningStep]:
        """向最新的思考步骤添加用户学习记录"""
        for ts in reversed(self.thinking_steps):
            if ts.agent_name == agent_name:
                return ts.add_learning_step(
                    user_action=user_action,
                    system_learned=system_learned,
                    confidence=confidence,
                    category=category,
                )
        return None

    def add_api_call_to_latest(
        self,
        agent_name: str,
        service: str,
        endpoint: str,
        params: Dict[str, Any] = None,
        status: str = "completed",
        response: Dict[str, Any] = None,
        http_status: int = 200,
        error: str = None,
        cost_ms: float = None,
    ) -> Optional[APICall]:
        """向最新的思考步骤添加外部API调用"""
        for ts in reversed(self.thinking_steps):
            if ts.agent_name == agent_name:
                call = ts.add_api_call(
                    service=service,
                    endpoint=endpoint,
                    params=params,
                )
                if status == "completed":
                    call.complete(response=response, http_status=http_status, cost_ms=cost_ms)
                elif status == "failed":
                    call.complete(error=error, http_status=http_status or 500)
                return call
        return None

    def get_agent_thinking_steps(self, agent_name: str) -> List[AgentThinkingStep]:
        """获取指定 Agent 的思考步骤"""
        return [ts for ts in self.thinking_steps if ts.agent_name == agent_name]

    def get_latest_step(self, agent_name: str) -> Optional[AgentThinkingStep]:
        """获取指定 Agent 最新的思考步骤"""
        steps = self.get_agent_thinking_steps(agent_name)
        return steps[-1] if steps else None

    def get_thinking_summary(self) -> Dict[str, Any]:
        """获取思考过程摘要"""
        return {
            "total_steps": len(self.thinking_steps),
            "completed_steps": len([ts for ts in self.thinking_steps if ts.status == "completed"]),
            "running_steps": len([ts for ts in self.thinking_steps if ts.status == "running"]),
            "agents_involved": list(set(ts.agent_name for ts in self.thinking_steps)),
            "metrics": {name: m.to_dict() for name, m in self.agent_metrics.items()},
        }


@dataclass
class SessionContext:
    """
    会话上下文
    管理整个会话的生命周期
    """
    session_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    # 对话历史
    conversation_history: List[ConversationTurn] = field(default_factory=list)
    current_turn: int = 0

    # 用户信息
    user_id: Optional[str] = None
    preferences: UserPreferences = field(default_factory=UserPreferences)

    # 旅行上下文
    trip_context: TripContext = field(default_factory=TripContext)

    # 【本轮新增】已提交的旅行快照（durable，跨 turn 继承）
    committed_trip_snapshot: Optional[CommittedTripSnapshot] = None

    # 【本轮新增】待处理追问锁存器（transient，可被抢占）
    pending_clarification_latch: Optional[PendingClarificationLatch] = None

    # 对话模式上下文
    dialog_mode: str = "planning"  # qa/planning/chat
    mode_confidence: float = 0.8
    previous_mode: Optional[str] = None

    # 情感上下文
    detected_emotion: Optional[str] = None  # happy/neutral/frustrated/confused/excited/worried
    emotion_confidence: float = 0.0
    emotion_history: List[Dict[str, Any]] = field(default_factory=list)  # 情感历史记录

    # 图片分析上下文
    pending_image_analysis: Optional[Dict[str, Any]] = None  # 待处理的图片

    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_turn(
        self,
        user_message: str,
        ai_message: Optional[str] = None,
        agent_name: Optional[str] = None,
        tools_used: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ConversationTurn:
        """添加对话轮次"""
        turn = ConversationTurn(
            turn_id=self.current_turn,
            user_message=user_message,
            ai_message=ai_message,
            agent_name=agent_name,
            tools_used=tools_used or [],
            metadata=metadata or {},
        )
        self.conversation_history.append(turn)
        self.current_turn += 1
        self.updated_at = datetime.utcnow()
        return turn

    def get_recent_messages(self, n: int = 10) -> List[ConversationTurn]:
        """获取最近的 n 条消息"""
        return self.conversation_history[-n:]

    def get_formatted_history(self) -> List[Dict[str, str]]:
        """获取格式化的对话历史"""
        result = []
        for turn in self.conversation_history:
            result.append({
                "role": "user",
                "content": turn.user_message,
            })
            if turn.ai_message:
                result.append({
                    "role": "assistant",
                    "content": turn.ai_message,
                })
        return result

    @property
    def turn_count(self) -> int:
        """对话轮次计数"""
        return len([t for t in self.conversation_history if t.ai_message])

    @property
    def is_empty(self) -> bool:
        """是否为空会话"""
        return len(self.conversation_history) == 0

    # ========== 【本轮新增】多轮状态管理方法 ==========

    @staticmethod
    def _merge_string_values(*groups: Any) -> List[str]:
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

    def commit_trip_snapshot(
        self,
        destination: str,
        duration_days: int,
        budget_amount: Optional[float] = None,
        travel_dates: Optional[str] = None,
        people_count: int = 1,
        preferences: Optional[List[str]] = None,
        plan_summary: Optional[Dict[str, Any]] = None,
        last_committed_turn_id: Optional[str] = None,
    ) -> CommittedTripSnapshot:
        """
        【本轮新增】提交旅行快照
        - 成功完成规划或 follow-up 后调用
        - 更新 committed_trip_snapshot
        """
        self.committed_trip_snapshot = CommittedTripSnapshot(
            destination=destination,
            duration_days=duration_days,
            budget_amount=budget_amount,
            travel_dates=travel_dates,
            people_count=people_count,
            preferences=self._merge_string_values(preferences or []),
            plan_summary=plan_summary,
            last_committed_turn_id=last_committed_turn_id,
            committed_at=datetime.utcnow(),
        )
        # 同时更新 trip_context（保持一致性）
        self.trip_context.destination = destination
        self.trip_context.duration_days = duration_days
        self.trip_context.budget_amount = budget_amount
        self.trip_context.num_travelers = people_count
        
        logger.info(
            f"[MULTITURN_TRACE] Trip snapshot committed: "
            f"destination={destination} duration={duration_days} budget={budget_amount}"
        )
        return self.committed_trip_snapshot

    def update_trip_snapshot_preferences(
        self,
        preferences: List[str],
        plan_summary: Optional[Dict[str, Any]] = None,
    ) -> None:
        """【本轮新增】更新快照偏好（用于 follow-up）"""
        if self.committed_trip_snapshot:
            self.committed_trip_snapshot.preferences = self._merge_string_values(
                self.committed_trip_snapshot.preferences,
                preferences,
            )
            if plan_summary:
                self.committed_trip_snapshot.plan_summary = plan_summary
            self.committed_trip_snapshot.committed_at = datetime.utcnow()

    def set_pending_clarification(
        self,
        missing_slots: List[str],
        origin_turn_id: Optional[str] = None,
        origin_request_id: Optional[str] = None,
        origin_intent: str = "unknown",
        partial_extracted: Optional[Dict[str, Any]] = None,
    ) -> PendingClarificationLatch:
        """【本轮新增】设置待处理追问锁存器"""
        self.pending_clarification_latch = PendingClarificationLatch(
            missing_slots=missing_slots,
            origin_turn_id=origin_turn_id,
            origin_request_id=origin_request_id,
            origin_intent=origin_intent,
            partial_extracted=partial_extracted or {},
            created_at=datetime.utcnow(),
        )
        logger.info(
            f"[MULTITURN_TRACE] Clarification latch set: "
            f"missing_slots={missing_slots}"
        )
        return self.pending_clarification_latch

    def consume_clarification_latch(self) -> None:
        """【本轮新增】消费（标记为已消费）追问锁存器"""
        if self.pending_clarification_latch:
            self.pending_clarification_latch.consumed = True
            logger.info("[MULTITURN_TRACE] Clarification latch consumed")

    def clear_clarification_latch(self) -> None:
        """【本轮新增】清除追问锁存器"""
        self.pending_clarification_latch = None
        logger.info("[MULTITURN_TRACE] Clarification latch cleared")

    def preempt_clarification_latch(self) -> None:
        """【本轮新增】抢占并清除追问锁存器（用于完整新规划）"""
        was_active = self.pending_clarification_latch and self.pending_clarification_latch.is_active()
        self.clear_clarification_latch()
        if was_active:
            logger.info("[MULTITURN_TRACE] Clarification latch preempted by new plan")

    def has_committed_trip(self) -> bool:
        """【本轮新增】检查是否有已提交的旅行快照"""
        return self.committed_trip_snapshot is not None and self.committed_trip_snapshot.is_complete()

    def is_follow_up_message(self, user_message: str) -> bool:
        """
        【本轮新增】检测消息是否是 follow-up
        follow-up = 对当前行程的修改/增强/偏好补充
        """
        if not self.has_committed_trip():
            return False

        text = str(user_message or "").strip()
        if not text:
            return False
        
        # 明确不是 follow-up 的模式（完整新规划关键词）
        full_new_keywords = ("帮我做一个", "帮我规划一个", "我想去旅游", "重新规划")
        for kw in full_new_keywords:
            if kw in text:
                return False
        
        # 可能是 follow-up 的模式（偏好增强、调整类）
        follow_up_keywords = (
            "想多", "想少", "改成", "改一下", "调整", "增加", "减少", "优化一下", "微调",
            "美食", "当地美食", "拍照", "出片", "摄影", "夜景",
            "室内多一点", "室外多一点", "预算改成", "预算调到", "预算调整到",
            "多走路", "少走路", "少换乘", "节奏轻松", "轻松点", "慢一点", "更集中", "顺路一点", "别太折腾", "别太赶", "别太累", "调松", "松一点",
        )
        looks_like_follow_up = any(kw in text for kw in follow_up_keywords)

        # 侧问默认走轻量问答；但若用户表达了“想优化/想调整”的意图，则优先视为 follow-up。
        if self.is_side_question(text) and not looks_like_follow_up:
            return False

        return looks_like_follow_up

    def is_side_question(self, user_message: str) -> bool:
        """
        【本轮新增】检测消息是否是侧问/闲聊
        """
        side_question_keywords = (
            "谢谢", "交通方便", "方便吗", "贵不贵", "值不值", "下雨",
            "室内还是室外", "住哪个区域", "住哪", "哪个区域更方便",
            "需要带什么", "穿什么", "衣服", "天气", "推荐住哪",
            "会不会太赶", "太赶", "赶不赶", "累不累", "会不会累", "走路多吗",
            "适合老人", "带老人", "长辈", "爸妈",
            "门票贵", "票价贵", "票价", "预算够", "预算够不够", "预算够用",
        )
        return any(kw in user_message for kw in side_question_keywords)
