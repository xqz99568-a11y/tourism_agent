"""
Message Bus - Agent 间事件驱动的消息通信
支持发布/订阅模式，实现 Agent 间的解耦通信
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Awaitable,
    TypeVar,
)

from app.core.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class MessageType(str, Enum):
    """消息类型"""
    # 任务消息
    TASK_REQUEST = "task_request"
    TASK_RESPONSE = "task_response"
    TASK_PROGRESS = "task_progress"
    TASK_CANCEL = "task_cancel"

    # 事件消息
    EVENT_START = "event_start"
    EVENT_COMPLETE = "event_complete"
    EVENT_ERROR = "event_error"
    EVENT_WARNING = "event_warning"

    # 状态消息
    STATE_UPDATE = "state_update"
    STATE_QUERY = "state_query"

    # 协作消息
    QUERY = "query"
    NOTIFICATION = "notification"
    BROADCAST = "broadcast"


class MessagePriority(str, Enum):
    """消息优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Message:
    """消息"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    msg_type: MessageType = MessageType.NOTIFICATION
    sender: str = ""
    recipients: Set[str] = field(default_factory=set)  # 空表示广播
    topic: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: MessagePriority = MessagePriority.NORMAL
    correlation_id: Optional[str] = None  # 用于关联请求-响应
    timestamp: datetime = field(default_factory=datetime.utcnow)
    ttl_seconds: float = 300.0  # 消息生存时间
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_broadcast(self) -> bool:
        return len(self.recipients) == 0

    @property
    def age_seconds(self) -> float:
        return (datetime.utcnow() - self.timestamp).total_seconds()

    @property
    def is_expired(self) -> bool:
        return self.age_seconds > self.ttl_seconds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.msg_type.value,
            "sender": self.sender,
            "recipients": list(self.recipients),
            "topic": self.topic,
            "payload": self.payload,
            "priority": self.priority.value,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class Subscription:
    """订阅"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str = ""
    topic: str = ""
    callback: Optional[Callable[[Message], Awaitable[None]]] = None
    filter_func: Optional[Callable[[Message], bool]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def match(self, message: Message) -> bool:
        """检查消息是否匹配此订阅"""
        if message.topic != self.topic:
            return False

        if message.recipients and self.agent_name not in message.recipients:
            return False

        if self.filter_func:
            return self.filter_func(message)

        return True


class MessageBus:
    """
    Message Bus - Agent 间消息通信总线
    支持发布/订阅、请求/响应、广播等模式
    """

    def __init__(self, max_queue_size: int = 1000):
        self.max_queue_size = max_queue_size
        self._subscriptions: Dict[str, List[Subscription]] = {}  # topic -> subscriptions
        self._agent_subscriptions: Dict[str, List[str]] = {}  # agent_name -> subscription_ids
        self._message_queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=max_queue_size)
        self._pending_responses: Dict[str, asyncio.Future[Message]] = {}  # correlation_id -> future
        self._running = False
        self._processor_task: Optional[asyncio.Task] = None
        self._stats = {
            "messages_sent": 0,
            "messages_received": 0,
            "messages_processed": 0,
            "broadcasts": 0,
            "direct_messages": 0,
        }

        logger.info("MessageBus initialized")

    async def start(self) -> None:
        """启动消息总线"""
        if self._running:
            return

        self._running = True
        self._processor_task = asyncio.create_task(self._process_messages())
        logger.info("MessageBus started")

    async def stop(self) -> None:
        """停止消息总线"""
        self._running = False

        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass

        # 清理所有挂起的响应
        for future in self._pending_responses.values():
            if not future.done():
                future.cancel()

        self._pending_responses.clear()
        logger.info("MessageBus stopped")

    # ========== 订阅管理 ==========

    def subscribe(
        self,
        agent_name: str,
        topic: str,
        callback: Optional[Callable[[Message], Awaitable[None]]] = None,
        filter_func: Optional[Callable[[Message], bool]] = None,
    ) -> str:
        """
        订阅主题

        Args:
            agent_name: 订阅者名称
            topic: 主题
            callback: 回调函数
            filter_func: 过滤函数

        Returns:
            订阅ID
        """
        subscription = Subscription(
            agent_name=agent_name,
            topic=topic,
            callback=callback,
            filter_func=filter_func,
        )

        if topic not in self._subscriptions:
            self._subscriptions[topic] = []

        self._subscriptions[topic].append(subscription)

        if agent_name not in self._agent_subscriptions:
            self._agent_subscriptions[agent_name] = []

        self._agent_subscriptions[agent_name].append(subscription.id)

        logger.debug(f"Agent '{agent_name}' subscribed to topic '{topic}'")
        return subscription.id

    def unsubscribe(self, agent_name: str, topic: Optional[str] = None) -> int:
        """
        取消订阅

        Args:
            agent_name: 订阅者名称
            topic: 主题（None 表示取消所有订阅）

        Returns:
            取消的订阅数量
        """
        count = 0

        if topic:
            # 取消特定主题的订阅
            if topic in self._subscriptions:
                subs = self._subscriptions[topic]
                self._subscriptions[topic] = [
                    s for s in subs if s.agent_name != agent_name
                ]
                count = len(subs) - len(self._subscriptions[topic])
        else:
            # 取消所有订阅
            for topic_subs in self._subscriptions.values():
                before = len(topic_subs)
                topic_subs[:] = [s for s in topic_subs if s.agent_name != agent_name]
                count += before - len(topic_subs)

        if agent_name in self._agent_subscriptions:
            del self._agent_subscriptions[agent_name]

        logger.debug(f"Agent '{agent_name}' unsubscribed from {count} subscriptions")
        return count

    def get_subscriptions(self, topic: str) -> List[Subscription]:
        """获取主题的所有订阅"""
        return self._subscriptions.get(topic, [])

    # ========== 消息发送 ==========

    async def publish(
        self,
        topic: str,
        sender: str,
        payload: Dict[str, Any] = None,
        priority: MessagePriority = MessagePriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        发布消息（广播）

        Args:
            topic: 主题
            sender: 发送者
            payload: 消息内容
            priority: 优先级
            metadata: 元数据
        """
        message = Message(
            msg_type=MessageType.BROADCAST,
            sender=sender,
            topic=topic,
            payload=payload or {},
            priority=priority,
            metadata=metadata or {},
        )

        await self._enqueue_message(message)
        self._stats["broadcasts"] += 1
        self._stats["messages_sent"] += 1

        logger.debug(f"Broadcast: {sender} -> {topic}")

    async def send(
        self,
        recipient: str,
        sender: str,
        topic: str,
        payload: Dict[str, Any] = None,
        priority: MessagePriority = MessagePriority.NORMAL,
        correlation_id: Optional[str] = None,
    ) -> None:
        """
        发送直接消息

        Args:
            recipient: 接收者
            sender: 发送者
            topic: 主题
            payload: 消息内容
            priority: 优先级
            correlation_id: 关联ID（用于请求-响应）
        """
        message = Message(
            msg_type=MessageType.NOTIFICATION,
            sender=sender,
            recipients={recipient},
            topic=topic,
            payload=payload or {},
            priority=priority,
            correlation_id=correlation_id,
        )

        await self._enqueue_message(message)
        self._stats["direct_messages"] += 1
        self._stats["messages_sent"] += 1

        logger.debug(f"Direct: {sender} -> {recipient} ({topic})")

    async def request(
        self,
        recipient: str,
        sender: str,
        topic: str,
        payload: Dict[str, Any] = None,
        timeout: float = 30.0,
    ) -> Message:
        """
        发送请求并等待响应（请求-响应模式）

        Args:
            recipient: 接收者
            sender: 发送者
            topic: 主题
            payload: 请求内容
            timeout: 超时时间

        Returns:
            响应消息

        Raises:
            asyncio.TimeoutError: 超时
        """
        correlation_id = str(uuid.uuid4())

        message = Message(
            msg_type=MessageType.QUERY,
            sender=sender,
            recipients={recipient},
            topic=topic,
            payload=payload or {},
            correlation_id=correlation_id,
        )

        # 创建 Future 等待响应
        future: asyncio.Future[Message] = asyncio.get_event_loop().create_future()
        self._pending_responses[correlation_id] = future

        try:
            await self._enqueue_message(message)
            self._stats["messages_sent"] += 1

            # 等待响应
            response = await asyncio.wait_for(future, timeout=timeout)
            return response

        except asyncio.TimeoutError:
            del self._pending_responses[correlation_id]
            raise asyncio.TimeoutError(f"Request to {recipient} timed out after {timeout}s")

        finally:
            self._pending_responses.pop(correlation_id, None)

    async def broadcast(
        self,
        sender: str,
        topic: str,
        payload: Dict[str, Any] = None,
        exclude: Optional[List[str]] = None,
    ) -> None:
        """
        广播到所有订阅者

        Args:
            sender: 发送者
            topic: 主题
            payload: 消息内容
            exclude: 排除的接收者列表
        """
        recipients = set()
        for sub in self._subscriptions.get(topic, []):
            if sub.agent_name != sender and (not exclude or sub.agent_name not in exclude):
                recipients.add(sub.agent_name)

        if not recipients:
            return

        message = Message(
            msg_type=MessageType.BROADCAST,
            sender=sender,
            recipients=recipients,
            topic=topic,
            payload=payload or {},
        )

        await self._enqueue_message(message)
        self._stats["broadcasts"] += 1
        self._stats["messages_sent"] += 1

        logger.debug(f"Broadcast: {sender} -> {len(recipients)} recipients ({topic})")

    # ========== 内部处理 ==========

    async def _enqueue_message(self, message: Message) -> None:
        """将消息加入队列"""
        try:
            self._message_queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning(f"Message queue full, dropping message {message.id}")

    async def _process_messages(self) -> None:
        """消息处理循环"""
        while self._running:
            try:
                message = await asyncio.wait_for(
                    self._message_queue.get(),
                    timeout=1.0
                )

                self._stats["messages_received"] += 1
                await self._dispatch_message(message)
                self._stats["messages_processed"] += 1

            except asyncio.TimeoutError:
                continue

            except Exception as e:
                logger.exception(f"Error processing message: {e}")

    async def _dispatch_message(self, message: Message) -> None:
        """分发消息到订阅者"""
        if message.is_expired:
            logger.debug(f"Message {message.id} expired, dropping")
            return

        # 检查是否有挂起的响应（请求-响应模式）
        if message.correlation_id and message.correlation_id in self._pending_responses:
            future = self._pending_responses[message.correlation_id]
            if not future.done():
                future.set_result(message)
            return

        # 分发给所有匹配的订阅者
        subscriptions = self._subscriptions.get(message.topic, [])

        for sub in subscriptions:
            if sub.match(message):
                try:
                    if sub.callback:
                        await sub.callback(message)
                except Exception as e:
                    logger.error(f"Error in subscription callback: {e}")

    # ========== 工具方法 ==========

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total_subs = sum(len(subs) for subs in self._subscriptions.values())
        return {
            **self._stats,
            "subscriptions": total_subs,
            "topics": len(self._subscriptions),
            "agents": len(self._agent_subscriptions),
            "pending_responses": len(self._pending_responses),
            "queue_size": self._message_queue.qsize(),
        }

    def get_topics(self) -> List[str]:
        """获取所有主题"""
        return list(self._subscriptions.keys())

    def get_agent_topics(self, agent_name: str) -> List[str]:
        """获取 Agent 订阅的主题"""
        sub_ids = self._agent_subscriptions.get(agent_name, [])
        topics = []
        for topic, subs in self._subscriptions.items():
            for sub in subs:
                if sub.id in sub_ids:
                    topics.append(topic)
        return topics


# ========== 全局消息总线实例 ==========

_message_bus: Optional[MessageBus] = None


def get_message_bus() -> MessageBus:
    """获取全局消息总线实例"""
    global _message_bus
    if _message_bus is None:
        _message_bus = MessageBus()
    return _message_bus


async def init_message_bus() -> MessageBus:
    """初始化并启动消息总线"""
    bus = get_message_bus()
    await bus.start()
    return bus


async def shutdown_message_bus() -> None:
    """关闭消息总线"""
    global _message_bus
    if _message_bus:
        await _message_bus.stop()
        _message_bus = None
