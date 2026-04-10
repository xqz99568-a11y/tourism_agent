"""
缓存监控和统计模块
提供缓存状态查询和性能指标
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.agent_cache import get_agent_cache, CacheMetrics
from app.core.llm.manager import get_llm_manager, LLMCallMetrics
from app.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class OptimizationStats:
    """优化统计"""
    total_llm_calls_saved: int = 0
    total_tokens_saved: int = 0
    cache_hit_rate: float = 0.0
    avg_response_time_ms: float = 0.0
    requests_served: int = 0


@dataclass
class CacheSnapshot:
    """缓存快照"""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    agent_cache: Dict[str, Any] = field(default_factory=dict)
    llm_cache: Dict[str, Any] = field(default_factory=dict)
    optimization_stats: OptimizationStats = field(default_factory=OptimizationStats)


class CacheMonitor:
    """
    缓存监控器
    收集和报告缓存性能指标
    """

    def __init__(self):
        self._agent_cache = get_agent_cache()
        self._llm_manager = get_llm_manager()
        self._start_time = time.time()
        self._total_requests = 0
        self._total_llm_calls = 0
        self._total_llm_calls_saved = 0

    def record_request(self, cache_hit: bool = False, llm_call: bool = True) -> None:
        """记录请求"""
        self._total_requests += 1
        if llm_call:
            self._total_llm_calls += 1
        if cache_hit:
            self._total_llm_calls_saved += 1

    def get_snapshot(self) -> CacheSnapshot:
        """获取缓存快照"""
        agent_stats = self._agent_cache.get_stats()
        llm_stats = self._llm_manager.metrics.to_dict() if hasattr(self._llm_manager, 'metrics') else {}

        # 计算优化统计
        optimization = OptimizationStats(
            total_llm_calls_saved=self._total_llm_calls_saved,
            total_tokens_saved=agent_stats.get("metrics", {}).get("tokens_saved", 0),
            cache_hit_rate=agent_stats.get("metrics", {}).get("hit_rate", 0),
            requests_served=self._total_requests,
        )

        return CacheSnapshot(
            agent_cache=agent_stats,
            llm_cache=llm_stats,
            optimization_stats=optimization,
        )

    def get_summary(self) -> Dict[str, Any]:
        """获取摘要报告"""
        snapshot = self.get_snapshot()
        uptime_seconds = time.time() - self._start_time

        # 计算节省比例
        total_calls = snapshot.llm_cache.get("total_calls", 0)
        cached_calls = snapshot.llm_cache.get("cached_calls", 0)
        llm_savings = cached_calls / total_calls if total_calls > 0 else 0

        return {
            "uptime_seconds": uptime_seconds,
            "total_requests": self._total_requests,
            "total_llm_calls": self._total_llm_calls,
            "llm_calls_saved": self._total_llm_calls_saved,
            "llm_savings_rate": f"{llm_savings:.1%}",
            "cache_hit_rate": snapshot.optimization_stats.cache_hit_rate,
            "tokens_saved": snapshot.optimization_stats.total_tokens_saved,
            "agent_cache_size": snapshot.agent_cache.get("size", 0),
            "llm_cache_stats": snapshot.llm_cache,
        }

    def get_recommendations(self) -> List[str]:
        """获取优化建议"""
        recommendations = []
        snapshot = self.get_snapshot()

        # 检查缓存命中率
        hit_rate = snapshot.optimization_stats.cache_hit_rate
        if hit_rate < 0.3:
            recommendations.append(
                "缓存命中率较低(<30%)，建议增加缓存 TTL 或优化缓存键"
            )
        elif hit_rate > 0.7:
            recommendations.append(
                "缓存命中率良好(>70%)，当前缓存策略运行良好"
            )

        # 检查 LLM 调用
        llm_stats = snapshot.llm_cache
        total_calls = llm_stats.get("total_calls", 0)
        if total_calls > 0:
            failed_calls = llm_stats.get("failed_calls", 0)
            failure_rate = failed_calls / total_calls
            if failure_rate > 0.1:
                recommendations.append(
                    f"LLM 失败率较高({failure_rate:.1%})，建议检查 LLM 配置"
                )

        # 检查缓存大小
        cache_size = snapshot.agent_cache.get("size", 0)
        max_size = snapshot.agent_cache.get("max_size", 500)
        if cache_size > max_size * 0.9:
            recommendations.append(
                "缓存接近满载，建议增加缓存大小或缩短 TTL"
            )

        return recommendations


# 全局监控器
_monitor: Optional[CacheMonitor] = None


def get_cache_monitor() -> CacheMonitor:
    """获取缓存监控器"""
    global _monitor
    if _monitor is None:
        _monitor = CacheMonitor()
    return _monitor


def init_cache_monitor() -> CacheMonitor:
    """初始化缓存监控器"""
    global _monitor
    _monitor = CacheMonitor()
    return _monitor
