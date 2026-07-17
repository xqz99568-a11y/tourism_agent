"""
实验指标采集模块
用于采集和输出论文所需的实验结构化指标
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class CollaborationMode(str, Enum):
    """协作模式枚举"""
    BASELINE_PLAIN = "baseline_plain"
    STRUCTURED_COLLABORATION = "structured_collaboration"


class ReviewModeExperiment(str, Enum):
    """Review 实验模式枚举"""
    NO_REVIEW = "no_review"
    REVIEW_ONLY = "review_only"
    REVIEW_AND_FIX = "review_and_fix"


@dataclass
class ExperimentContext:
    """实验上下文"""
    experiment_case_id: str = ""
    experiment_group: str = ""
    collaboration_mode: str = CollaborationMode.BASELINE_PLAIN.value
    review_mode: str = ReviewModeExperiment.NO_REVIEW.value
    structured_modules_enabled: Dict[str, bool] = field(default_factory=dict)
    timestamp: str = ""


@dataclass
class ExperimentMetrics:
    """实验指标"""
    # 案例标识
    experiment_case_id: str = ""
    experiment_group: str = ""
    
    # 模式标识
    collaboration_mode: str = ""
    review_mode: str = ""
    
    # 结构完整性指标
    has_poi_list: bool = False
    poi_count: int = 0
    has_daily_plans: bool = False
    day_count: int = 0
    has_structured_budget: bool = False
    has_structured_review: bool = False
    
    # Review 评分指标
    overall_review_score: float = 0.0
    completeness_score: float = 0.0
    consistency_score: float = 0.0
    feasibility_score: float = 0.0
    personalization_score: float = 0.0
    constraint_satisfaction_score: float = 0.0
    issue_count: int = 0
    warning_count: int = 0

    # 独立硬约束检查指标
    hard_constraint_applicable_count: int = 0
    hard_constraint_passed_count: int = 0
    hard_constraint_failed_count: int = 0
    hard_constraints_all_satisfied: Optional[bool] = None
    hcsr: Optional[float] = None
    
    # 预算可解释性指标
    is_over_budget: Optional[bool] = None
    total_budget: Optional[float] = None
    budget_limit: Optional[float] = None
    has_budget_breakdown: bool = False
    
    # 行程可行性指标
    unscheduled_poi_count: int = 0
    has_empty_days: bool = False
    has_overloaded_days: bool = False
    
    # Review 修正指标
    has_fix_applied: bool = False
    fix_rule_count: int = 0
    score_improvement: Optional[float] = None
    
    # 实验时间戳
    timestamp: str = ""


def build_experiment_metrics(
    attraction_result: Optional[Any] = None,
    itinerary_result: Optional[Any] = None,
    budget_result: Optional[Any] = None,
    review_result: Optional[Any] = None,
    experiment_ctx: Optional[ExperimentContext] = None,
) -> ExperimentMetrics:
    """
    从各 Agent 结果构建实验指标
    
    Args:
        attraction_result: Attraction Agent 结果
        itinerary_result: Itinerary Agent 结果
        budget_result: Budget Agent 结果
        review_result: Review Agent 结果
        experiment_ctx: 实验上下文
    
    Returns:
        ExperimentMetrics: 实验指标对象
    """
    metrics = ExperimentMetrics()
    
    # 设置时间戳
    metrics.timestamp = datetime.utcnow().isoformat()
    
    # 设置实验上下文
    if experiment_ctx:
        metrics.experiment_case_id = experiment_ctx.experiment_case_id
        metrics.experiment_group = experiment_ctx.experiment_group
        metrics.collaboration_mode = experiment_ctx.collaboration_mode
        metrics.review_mode = experiment_ctx.review_mode
    
    # 采集 POI 指标
    _collect_poi_metrics(metrics, attraction_result)
    
    # 采集行程指标
    _collect_itinerary_metrics(metrics, itinerary_result)
    
    # 采集预算指标
    _collect_budget_metrics(metrics, budget_result)
    
    # 采集 Review 指标
    _collect_review_metrics(metrics, review_result)
    
    return metrics


def constraint_metrics_from_report(constraint_report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build objective hard-constraint metrics from the independent checker."""
    data = constraint_report or {}
    if isinstance(data.get("data"), dict):
        data = data["data"]
    applicable = _safe_int(data.get("applicable_count"))
    passed = _safe_int(data.get("passed_count"))
    failed = _safe_int(data.get("failed_count"))
    all_passed = data.get("all_passed")
    return {
        "constraint_report": constraint_report or {},
        "hard_constraint_applicable_count": applicable,
        "hard_constraint_passed_count": passed,
        "hard_constraint_failed_count": failed,
        "hard_constraints_all_satisfied": None if applicable == 0 else bool(all_passed),
        "hcsr": None if applicable == 0 else round(passed / applicable, 4),
    }


def _collect_poi_metrics(metrics: ExperimentMetrics, attraction_result: Optional[Any]) -> None:
    """采集 POI 相关指标"""
    if not attraction_result:
        return
    
    data = getattr(attraction_result, "data", None) or {}
    
    poi_list = data.get("poi_list") or data.get("pois") or []
    if isinstance(poi_list, list):
        metrics.has_poi_list = len(poi_list) > 0
        metrics.poi_count = len(poi_list)


def _collect_itinerary_metrics(metrics: ExperimentMetrics, itinerary_result: Optional[Any]) -> None:
    """采集行程相关指标"""
    if not itinerary_result:
        return
    
    data = getattr(itinerary_result, "data", None) or {}
    
    daily_plans = data.get("daily_plans") or []
    if isinstance(daily_plans, list):
        metrics.has_daily_plans = len(daily_plans) > 0
        metrics.day_count = len(daily_plans)
    
    unscheduled = data.get("unscheduled_pois") or []
    if isinstance(unscheduled, list):
        metrics.unscheduled_poi_count = len(unscheduled)
    
    # 检查是否有空天数
    if metrics.has_daily_plans:
        empty_days = sum(1 for plan in daily_plans if not _has_pois_in_day(plan))
        metrics.has_empty_days = empty_days > 0
        
        overloaded_days = sum(1 for plan in daily_plans if _is_day_overloaded(plan))
        metrics.has_overloaded_days = overloaded_days > 0


def _has_pois_in_day(plan: Any) -> bool:
    """检查某天是否有景点"""
    if not isinstance(plan, dict):
        return False
    items = plan.get("items") or []
    return any(
        item.get("name") not in ["午餐 / 休息", "晚餐 / 休息", "备选景点（未排入）"]
        for item in items
        if isinstance(item, dict)
    )


def _is_day_overloaded(plan: Any) -> bool:
    """检查某天是否超载"""
    if not isinstance(plan, dict):
        return False
    items = plan.get("items") or []
    poi_count = sum(
        1 for item in items
        if isinstance(item, dict)
        and item.get("name") not in ["午餐 / 休息", "晚餐 / 休息"]
    )
    return poi_count > 4


def _collect_budget_metrics(metrics: ExperimentMetrics, budget_result: Optional[Any]) -> None:
    """采集预算相关指标"""
    if not budget_result:
        return
    
    data = getattr(budget_result, "data", None) or {}
    
    metrics.has_structured_budget = bool(data.get("total_budget"))
    
    if data.get("total_budget"):
        try:
            metrics.total_budget = float(data.get("total_budget"))
        except (TypeError, ValueError):
            pass
    
    if data.get("budget_limit"):
        try:
            metrics.budget_limit = float(data.get("budget_limit"))
        except (TypeError, ValueError):
            pass
    
    metrics.is_over_budget = data.get("is_over_budget")
    
    breakdown = data.get("budget_breakdown")
    metrics.has_budget_breakdown = isinstance(breakdown, dict) and bool(breakdown)


def _collect_review_metrics(metrics: ExperimentMetrics, review_result: Optional[Any]) -> None:
    """采集 Review 相关指标"""
    if not review_result:
        return
    
    data = getattr(review_result, "data", None) or {}
    
    metrics.has_structured_review = True
    
    scores = data.get("review_scores") or {}
    if scores:
        metrics.overall_review_score = _safe_float(scores.get("overall", 0))
        metrics.completeness_score = _safe_float(scores.get("completeness", 0))
        metrics.consistency_score = _safe_float(scores.get("consistency", 0))
        metrics.feasibility_score = _safe_float(scores.get("feasibility", 0))
        metrics.personalization_score = _safe_float(scores.get("personalization", 0))
        metrics.constraint_satisfaction_score = _safe_float(scores.get("constraint_satisfaction", 0))
    
    issues = data.get("review_issues") or []
    if isinstance(issues, list):
        metrics.issue_count = len(issues)
    
    warnings = data.get("review_warnings") or []
    if isinstance(warnings, list):
        metrics.warning_count = len(warnings)
    
    metrics.has_fix_applied = data.get("has_been_fixed", False)
    
    fix_rules = data.get("fix_applied_rules") or []
    if isinstance(fix_rules, list):
        metrics.fix_rule_count = len(fix_rules)


def _safe_float(value: Any) -> float:
    """安全转换为浮点数"""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def metrics_to_dict(metrics: ExperimentMetrics) -> Dict[str, Any]:
    """将实验指标转换为字典"""
    return {
        "experiment_case_id": metrics.experiment_case_id,
        "experiment_group": metrics.experiment_group,
        "collaboration_mode": metrics.collaboration_mode,
        "review_mode": metrics.review_mode,
        "metrics": {
            "has_poi_list": metrics.has_poi_list,
            "poi_count": metrics.poi_count,
            "has_daily_plans": metrics.has_daily_plans,
            "day_count": metrics.day_count,
            "has_structured_budget": metrics.has_structured_budget,
            "has_structured_review": metrics.has_structured_review,
            "overall_review_score": metrics.overall_review_score,
            "completeness_score": metrics.completeness_score,
            "consistency_score": metrics.consistency_score,
            "feasibility_score": metrics.feasibility_score,
            "personalization_score": metrics.personalization_score,
            "constraint_satisfaction_score": metrics.constraint_satisfaction_score,
            "issue_count": metrics.issue_count,
            "warning_count": metrics.warning_count,
            "hard_constraint_applicable_count": metrics.hard_constraint_applicable_count,
            "hard_constraint_passed_count": metrics.hard_constraint_passed_count,
            "hard_constraint_failed_count": metrics.hard_constraint_failed_count,
            "hard_constraints_all_satisfied": metrics.hard_constraints_all_satisfied,
            "hcsr": metrics.hcsr,
            "is_over_budget": metrics.is_over_budget,
            "total_budget": metrics.total_budget,
            "budget_limit": metrics.budget_limit,
            "has_budget_breakdown": metrics.has_budget_breakdown,
            "unscheduled_poi_count": metrics.unscheduled_poi_count,
            "has_empty_days": metrics.has_empty_days,
            "has_overloaded_days": metrics.has_overloaded_days,
            "has_fix_applied": metrics.has_fix_applied,
            "fix_rule_count": metrics.fix_rule_count,
            "score_improvement": metrics.score_improvement,
        },
        "timestamp": metrics.timestamp,
    }


def build_experiment_record(
    experiment_case_id: str,
    collaboration_mode: str,
    review_mode: str,
    input_case: Dict[str, Any],
    metrics: ExperimentMetrics,
    result_snapshot: Optional[Dict[str, Any]] = None,
    experiment_group: str = "",
) -> Dict[str, Any]:
    """
    构建完整的实验记录
    
    Args:
        experiment_case_id: 实验案例 ID
        collaboration_mode: 协作模式
        review_mode: Review 模式
        input_case: 输入案例
        metrics: 实验指标
        result_snapshot: 结果快照
        experiment_group: 实验组标识
    
    Returns:
        Dict: 完整的实验记录
    """
    record = {
        "experiment_case_id": experiment_case_id,
        "experiment_group": experiment_group,
        "collaboration_mode": collaboration_mode,
        "review_mode": review_mode,
        "input_case": {
            "destination": input_case.get("destination"),
            "duration": input_case.get("duration"),
            "num_travelers": input_case.get("num_travelers"),
            "budget_level": input_case.get("budget_level"),
        },
        "metrics": metrics_to_dict(metrics)["metrics"],
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    if result_snapshot:
        record["result_snapshot"] = result_snapshot
    
    return record


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
