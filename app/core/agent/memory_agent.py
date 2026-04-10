"""
Memory Agent - 记忆管理 Agent
负责提取、存储、检索和遗忘信息
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from app.core.agent.base import BaseAgent
from app.core.agent.protocol import AgentProtocol, AgentResult, AgentTask, AgentType
from app.core.agent.registry import AgentRegistry
from app.core.agent.message_bus import MessageBus
from app.core.logger import get_logger

logger = get_logger(__name__)


class MemoryType(str, Enum):
    """记忆类型"""
    EPISODIC = "episodic"      # 情景记忆（具体事件）
    SEMANTIC = "semantic"       # 语义记忆（事实知识）
    PROCEDURAL = "procedural"   # 程序记忆（技能/习惯）
    WORKING = "working"         # 工作记忆（短期）


@dataclass
class MemoryEntry:
    """记忆条目"""
    id: str
    content: str
    memory_type: MemoryType
    agent_name: str
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    importance: float = 0.5  # 0-1 重要性评分
    tags: List[str] = field(default_factory=list)
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    @property
    def is_expired(self) -> bool:
        # 工作记忆 5 分钟过期，其他 30 天
        if self.memory_type == MemoryType.WORKING:
            return self.age_seconds > 300
        return self.age_seconds > 30 * 24 * 3600

    def touch(self) -> None:
        """更新访问时间"""
        self.last_accessed = time.time()
        self.access_count += 1


class MemoryStore:
    """
    记忆存储
    支持向量检索和关键词检索
    """

    def __init__(
        self,
        max_entries: int = 10000,
        default_ttl: int = 3600,
    ):
        self.max_entries = max_entries
        self.default_ttl = default_ttl
        self._memories: Dict[str, MemoryEntry] = {}
        self._by_type: Dict[MemoryType, List[str]] = {m: [] for m in MemoryType}
        self._by_agent: Dict[str, List[str]] = {}

    def add(
        self,
        content: str,
        memory_type: MemoryType,
        agent_name: str,
        importance: float = 0.5,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryEntry:
        """添加记忆"""
        import uuid
        entry_id = str(uuid.uuid4())

        entry = MemoryEntry(
            id=entry_id,
            content=content,
            memory_type=memory_type,
            agent_name=agent_name,
            importance=importance,
            tags=tags or [],
            metadata=metadata or {},
        )

        # 存储
        self._memories[entry_id] = entry
        self._by_type[memory_type].append(entry_id)

        if agent_name not in self._by_agent:
            self._by_agent[agent_name] = []
        self._by_agent[agent_name].append(entry_id)

        # 清理过期记忆
        if len(self._memories) > self.max_entries:
            self._cleanup()

        logger.debug(f"Added memory: {entry_id} ({memory_type.value})")
        return entry

    def get(self, entry_id: str) -> Optional[MemoryEntry]:
        """获取记忆"""
        entry = self._memories.get(entry_id)
        if entry:
            entry.touch()
        return entry

    def search(
        self,
        query: str,
        memory_type: Optional[MemoryType] = None,
        agent_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[MemoryEntry]:
        """搜索记忆"""
        candidates = self._memories.values()

        # 按类型过滤
        if memory_type:
            candidates = [e for e in candidates if e.memory_type == memory_type]

        # 按 agent 过滤
        if agent_name:
            candidates = [e for e in candidates if e.agent_name == agent_name]

        # 过滤过期
        candidates = [e for e in candidates if not e.is_expired]

        # 简单关键词匹配
        results = []
        query_lower = query.lower()
        for entry in candidates:
            if query_lower in entry.content.lower():
                entry.touch()
                results.append(entry)

        # 按重要性排序
        results.sort(key=lambda e: (e.importance, e.access_count), reverse=True)

        return results[:limit]

    def get_recent(self, limit: int = 10) -> List[MemoryEntry]:
        """获取最近的记忆"""
        sorted_entries = sorted(
            self._memories.values(),
            key=lambda e: e.last_accessed,
            reverse=True
        )
        return sorted_entries[:limit]

    def forget(self, entry_id: str) -> bool:
        """遗忘记忆"""
        if entry_id not in self._memories:
            return False

        entry = self._memories[entry_id]

        # 从索引中移除
        if entry_id in self._by_type[entry.memory_type]:
            self._by_type[entry.memory_type].remove(entry_id)

        if entry_id in self._by_agent.get(entry.agent_name, []):
            self._by_agent[entry.agent_name].remove(entry_id)

        # 删除
        del self._memories[entry_id]
        logger.debug(f"Forgot memory: {entry_id}")
        return True

    def clear(self, agent_name: Optional[str] = None) -> int:
        """清除记忆"""
        if agent_name:
            entry_ids = self._by_agent.get(agent_name, [])
            for entry_id in entry_ids:
                self.forget(entry_id)
            return len(entry_ids)
        else:
            count = len(self._memories)
            self._memories.clear()
            for mem_list in self._by_type.values():
                mem_list.clear()
            self._by_agent.clear()
            return count

    def _cleanup(self) -> None:
        """清理低重要性记忆"""
        # 按重要性排序，删除最低的 10%
        sorted_entries = sorted(
            self._memories.values(),
            key=lambda e: e.importance
        )
        to_delete = sorted_entries[:len(sorted_entries) // 10]

        for entry in to_delete:
            self.forget(entry.id)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计"""
        return {
            "total_memories": len(self._memories),
            "by_type": {
                mtype.value: len(ids) for mtype, ids in self._by_type.items()
            },
            "by_agent": {
                name: len(ids) for name, ids in self._by_agent.items()
            },
        }


class MemoryAgent(BaseAgent):
    """
    记忆管理 Agent
    支持记忆的提取、检索和遗忘
    """

    def __init__(
        self,
        name: str = "memory",
        agent_type: AgentType = AgentType.MEMORY,
        description: str = "记忆管理 Agent",
        message_bus: Optional[MessageBus] = None,
        registry: Optional[AgentRegistry] = None,
        max_memories: int = 10000,
        **kwargs,
    ):
        super().__init__(
            name=name,
            agent_type=agent_type,
            description=description,
            message_bus=message_bus,
            registry=registry,
            **kwargs,
        )

        self.store = MemoryStore(max_entries=max_memories)

        logger.info(f"MemoryAgent initialized with max={max_memories}")

    async def _execute(
        self,
        task: AgentTask,
        context: Dict[str, Any],
    ) -> AgentResult:
        """执行记忆操作"""
        action = task.input_data.get("action", "retrieve")
        query = task.input_data.get("query", "")
        content = task.input_data.get("content", "")
        memory_type_str = task.input_data.get("memory_type", "episodic")

        try:
            memory_type = MemoryType(memory_type_str)
        except ValueError:
            memory_type = MemoryType.EPISODIC

        if action == "store":
            return await self._store_memory(
                content=content,
                memory_type=memory_type,
                importance=task.input_data.get("importance", 0.5),
                tags=task.input_data.get("tags", []),
                metadata=task.input_data.get("metadata", {}),
            )

        elif action == "retrieve":
            return await self._retrieve_memories(
                query=query,
                memory_type=memory_type,
                limit=task.input_data.get("limit", 10),
            )

        elif action == "forget":
            return await self._forget_memory(
                memory_id=task.input_data.get("memory_id", ""),
            )

        elif action == "clear":
            return await self._clear_memories(
                agent_name=task.input_data.get("agent_name"),
            )

        elif action == "stats":
            return await self._get_stats()

        else:
            return AgentResult(
                task_id=task.id,
                agent_name=self.name,
                success=False,
                error=f"Unknown action: {action}",
            )

    async def _store_memory(
        self,
        content: str,
        memory_type: MemoryType,
        importance: float,
        tags: List[str],
        metadata: Dict[str, Any],
    ) -> AgentResult:
        """存储记忆"""
        entry = self.store.add(
            content=content,
            memory_type=memory_type,
            agent_name=self.name,
            importance=importance,
            tags=tags,
            metadata=metadata,
        )

        return AgentResult(
            task_id="store",
            agent_name=self.name,
            success=True,
            data={
                "action": "store",
                "memory_id": entry.id,
                "memory_type": entry.memory_type.value,
            },
            content=f"记忆已存储 (ID: {entry.id})",
        )

    async def _retrieve_memories(
        self,
        query: str,
        memory_type: Optional[MemoryType],
        limit: int,
    ) -> AgentResult:
        """检索记忆"""
        memories = self.store.search(
            query=query,
            memory_type=memory_type,
            limit=limit,
        )

        if not memories:
            return AgentResult(
                task_id="retrieve",
                agent_name=self.name,
                success=True,
                data={
                    "action": "retrieve",
                    "count": 0,
                    "memories": [],
                },
                content="没有找到相关记忆",
            )

        # 格式化输出
        memory_list = []
        content_lines = ["找到以下相关记忆：\n"]

        for i, mem in enumerate(memories, 1):
            memory_list.append({
                "id": mem.id,
                "content": mem.content,
                "type": mem.memory_type.value,
                "importance": mem.importance,
                "age": f"{mem.age_seconds / 3600:.1f}小时前",
                "access_count": mem.access_count,
            })

            content_lines.append(f"{i}. [{mem.memory_type.value}] {mem.content[:100]}...")

        return AgentResult(
            task_id="retrieve",
            agent_name=self.name,
            success=True,
            data={
                "action": "retrieve",
                "count": len(memories),
                "memories": memory_list,
            },
            content="\n".join(content_lines),
        )

    async def _forget_memory(self, memory_id: str) -> AgentResult:
        """遗忘记忆"""
        success = self.store.forget(memory_id)

        return AgentResult(
            task_id="forget",
            agent_name=self.name,
            success=success,
            data={
                "action": "forget",
                "memory_id": memory_id,
                "forgotten": success,
            },
            content="记忆已遗忘" if success else "记忆不存在",
        )

    async def _clear_memories(self, agent_name: Optional[str]) -> AgentResult:
        """清除记忆"""
        count = self.store.clear(agent_name=agent_name)

        return AgentResult(
            task_id="clear",
            agent_name=self.name,
            success=True,
            data={
                "action": "clear",
                "cleared_count": count,
            },
            content=f"已清除 {count} 条记忆",
        )

    async def _get_stats(self) -> AgentResult:
        """获取统计"""
        stats = self.store.get_stats()

        return AgentResult(
            task_id="stats",
            agent_name=self.name,
            success=True,
            data={
                "action": "stats",
                **stats,
            },
            content=f"记忆统计: {stats['total_memories']} 条记忆",
        )
