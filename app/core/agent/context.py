"""
Agent 上下文 - 跨 Agent 状态共享
用于在 Agent 间传递和共享状态
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from app.core.agent.protocol import AgentResult


@dataclass
class StateEntry:
    """状态条目"""
    key: str
    value: Any
    agent_name: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    version: int = 1
    access_count: int = 0
    tags: Set[str] = field(default_factory=set)

    def update(self, value: Any, agent_name: str) -> None:
        """更新值"""
        self.value = value
        self.agent_name = agent_name
        self.updated_at = datetime.utcnow()
        self.version += 1


@dataclass
class SharedContext:
    """
    共享上下文
    Agent 间状态共享的容器
    """
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    entries: Dict[str, StateEntry] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def set(self, key: str, value: Any, agent_name: str, tags: Optional[Set[str]] = None) -> None:
        """设置状态值"""
        if key in self.entries:
            self.entries[key].update(value, agent_name)
            if tags:
                self.entries[key].tags.update(tags)
        else:
            self.entries[key] = StateEntry(
                key=key,
                value=value,
                agent_name=agent_name,
                tags=tags or set(),
            )
        self.updated_at = datetime.utcnow()

    def get(self, key: str, default: Any = None) -> Any:
        """获取状态值"""
        entry = self.entries.get(key)
        if entry:
            entry.access_count += 1
            return entry.value
        return default

    def get_entries_by_tag(self, tag: str) -> List[StateEntry]:
        """获取带有特定标签的所有条目"""
        return [e for e in self.entries.values() if tag in e.tags]

    def get_by_agent(self, agent_name: str) -> Dict[str, Any]:
        """获取指定 Agent 设置的所有值"""
        return {
            key: entry.value
            for key, entry in self.entries.items()
            if entry.agent_name == agent_name
        }

    def get_recent(self, limit: int = 10) -> List[StateEntry]:
        """获取最近更新的条目"""
        sorted_entries = sorted(
            self.entries.values(),
            key=lambda e: e.updated_at,
            reverse=True
        )
        return sorted_entries[:limit]

    def delete(self, key: str) -> bool:
        """删除状态值"""
        if key in self.entries:
            del self.entries[key]
            self.updated_at = datetime.utcnow()
            return True
        return False

    def clear(self, agent_name: Optional[str] = None) -> int:
        """
        清除状态

        Args:
            agent_name: 如果指定，只清除该 Agent 的状态

        Returns:
            清除的条目数
        """
        if agent_name:
            keys_to_delete = [
                key for key, entry in self.entries.items()
                if entry.agent_name == agent_name
            ]
            for key in keys_to_delete:
                del self.entries[key]
            count = len(keys_to_delete)
        else:
            count = len(self.entries)
            self.entries.clear()

        self.updated_at = datetime.utcnow()
        return count

    def merge_results(self, results: Dict[str, AgentResult]) -> None:
        """合并 Agent 结果到上下文"""
        for task_id, result in results.items():
            if result.success:
                self.set(f"result:{task_id}", result, agent_name=result.agent_name, tags={"result"})
                if result.artifacts:
                    for key, value in result.artifacts.items():
                        self.set(f"artifact:{key}", value, agent_name=result.agent_name, tags={"artifact"})

    def snapshot(self) -> Dict[str, Any]:
        """创建快照"""
        return {
            "session_id": self.session_id,
            "entries": {
                key: {
                    "value": entry.value,
                    "agent_name": entry.agent_name,
                    "version": entry.version,
                    "tags": list(entry.tags),
                }
                for key, entry in self.entries.items()
            },
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def restore(self, snapshot: Dict[str, Any]) -> None:
        """从快照恢复"""
        self.session_id = snapshot.get("session_id", self.session_id)

        entries_data = snapshot.get("entries", {})
        for key, data in entries_data.items():
            self.entries[key] = StateEntry(
                key=key,
                value=data["value"],
                agent_name=data["agent_name"],
                version=data.get("version", 1),
                tags=set(data.get("tags", [])),
            )

    def __contains__(self, key: str) -> bool:
        return key in self.entries

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value, agent_name="unknown")

    def __len__(self) -> int:
        return len(self.entries)


class ExecutionContext:
    """
    执行上下文
    管理单个请求的执行状态
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.shared_context = SharedContext(session_id=self.session_id)
        self.results: Dict[str, AgentResult] = {}
        self.active_agents: List[str] = []
        self.completed_agents: List[str] = []
        self.failed_agents: List[str] = []
        self.retry_count: int = 0
        self.max_retries: int = 3
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.metadata: Dict[str, Any] = {}

    def add_result(self, agent_name: str, result: AgentResult) -> None:
        """添加 Agent 结果"""
        self.results[agent_name] = result
        self.completed_agents.append(agent_name)
        if agent_name in self.active_agents:
            self.active_agents.remove(agent_name)

        # 合并到共享上下文
        self.shared_context.set(
            f"result:{agent_name}",
            result,
            agent_name=agent_name,
            tags={"result", agent_name}
        )

    def add_error(self, agent_name: str, error: Exception) -> None:
        """记录错误"""
        self.failed_agents.append(agent_name)
        if agent_name in self.active_agents:
            self.active_agents.remove(agent_name)

        self.shared_context.set(
            f"error:{agent_name}",
            str(error),
            agent_name=agent_name,
            tags={"error"}
        )

    def is_complete(self) -> bool:
        """检查是否所有 Agent 都已完成"""
        return len(self.active_agents) == 0

    def get_result(self, agent_name: str) -> Optional[AgentResult]:
        """获取指定 Agent 的结果"""
        return self.results.get(agent_name)

    def get_all_results(self) -> Dict[str, AgentResult]:
        """获取所有结果"""
        return copy.copy(self.results)

    def get_duration_ms(self) -> float:
        """获取执行时长（毫秒）"""
        if self.started_at:
            end = self.completed_at or datetime.utcnow()
            return (end - self.started_at).total_seconds() * 1000
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "active_agents": self.active_agents,
            "completed_agents": self.completed_agents,
            "failed_agents": self.failed_agents,
            "results_count": len(self.results),
            "duration_ms": self.get_duration_ms(),
            "metadata": self.metadata,
        }
