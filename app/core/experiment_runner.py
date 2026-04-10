"""
实验运行器模块
用于执行实验对比、收集结果和导出论文数据
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.experiment_metrics import (
    CollaborationMode,
    ExperimentContext,
    ExperimentMetrics,
    ReviewModeExperiment,
    build_experiment_metrics,
    build_experiment_record,
    metrics_to_dict,
)


class ExperimentRunner:
    """
    实验运行器
    负责执行实验对比、收集结果和导出论文数据
    """
    
    # 预定义的测试案例
    TEST_CASES = [
        {
            "id": "case_001",
            "input": {
                "destination": "杭州",
                "duration": 3,
                "num_travelers": 2,
                "budget_level": "medium",
            },
        },
        {
            "id": "case_002",
            "input": {
                "destination": "成都",
                "duration": 4,
                "num_travelers": 2,
                "budget_level": "medium",
            },
        },
        {
            "id": "case_003",
            "input": {
                "destination": "北京",
                "duration": 5,
                "num_travelers": 3,
                "budget_level": "luxury",
            },
        },
    ]
    
    def __init__(self):
        self.experiment_records: List[Dict[str, Any]] = []
        self.current_context: Optional[ExperimentContext] = None
    
    def create_experiment_context(
        self,
        experiment_case_id: str,
        collaboration_mode: str,
        review_mode: str,
        experiment_group: str = "",
    ) -> ExperimentContext:
        """
        创建实验上下文
        
        Args:
            experiment_case_id: 实验案例 ID
            collaboration_mode: 协作模式
            review_mode: Review 模式
            experiment_group: 实验组标识
        
        Returns:
            ExperimentContext: 实验上下文
        """
        ctx = ExperimentContext(
            experiment_case_id=experiment_case_id,
            experiment_group=experiment_group,
            collaboration_mode=collaboration_mode,
            review_mode=review_mode,
            timestamp=datetime.utcnow().isoformat(),
        )
        
        # 设置结构化模块启用状态
        ctx.structured_modules_enabled = {
            "poi_list": collaboration_mode == CollaborationMode.STRUCTURED_COLLABORATION.value,
            "daily_plans": collaboration_mode == CollaborationMode.STRUCTURED_COLLABORATION.value,
            "structured_budget": collaboration_mode == CollaborationMode.STRUCTURED_COLLABORATION.value,
            "structured_review": review_mode != ReviewModeExperiment.NO_REVIEW.value,
        }
        
        self.current_context = ctx
        return ctx
    
    def collect_experiment_metrics(
        self,
        attraction_result: Optional[Any] = None,
        itinerary_result: Optional[Any] = None,
        budget_result: Optional[Any] = None,
        review_result: Optional[Any] = None,
    ) -> ExperimentMetrics:
        """
        收集实验指标
        
        Args:
            attraction_result: Attraction Agent 结果
            itinerary_result: Itinerary Agent 结果
            budget_result: Budget Agent 结果
            review_result: Review Agent 结果
        
        Returns:
            ExperimentMetrics: 实验指标
        """
        return build_experiment_metrics(
            attraction_result=attraction_result,
            itinerary_result=itinerary_result,
            budget_result=budget_result,
            review_result=review_result,
            experiment_ctx=self.current_context,
        )
    
    def record_experiment(
        self,
        input_case: Dict[str, Any],
        result_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        记录单次实验结果
        
        Args:
            input_case: 输入案例
            result_snapshot: 结果快照
        
        Returns:
            Dict: 实验记录
        """
        if not self.current_context:
            return {}
        
        metrics = self.collect_experiment_metrics()
        
        record = build_experiment_record(
            experiment_case_id=self.current_context.experiment_case_id,
            collaboration_mode=self.current_context.collaboration_mode,
            review_mode=self.current_context.review_mode,
            input_case=input_case,
            metrics=metrics,
            result_snapshot=result_snapshot,
            experiment_group=self.current_context.experiment_group,
        )
        
        self.experiment_records.append(record)
        return record
    
    def generate_experiment_id(self, prefix: str = "exp") -> str:
        """生成唯一实验 ID"""
        return f"{prefix}_{uuid.uuid4().hex[:8]}"
    
    def export_results(self, output_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        导出实验结果
        
        Args:
            output_path: 输出文件路径（可选）
        
        Returns:
            List[Dict]: 实验结果列表
        """
        results = self.experiment_records
        
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
        
        return results
    
    def generate_comparison_table(
        self,
        records: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        生成对比表（可用于论文）
        
        Args:
            records: 实验记录列表（可选，默认使用已有记录）
        
        Returns:
            str: Markdown 格式的对比表
        """
        if records is None:
            records = self.experiment_records
        
        if not records:
            return "暂无实验数据"
        
        # 构建 Markdown 表格
        lines = [
            "| 案例ID | 协作模式 | Review模式 | POI数量 | 天数 | 预算超限 | Overall评分 | 问题数 | 警告数 | 修正 |",
            "|--------|----------|------------|---------|------|----------|-------------|--------|--------|------|",
        ]
        
        for record in records:
            metrics = record.get("metrics", {})
            lines.append(
                f"| {record.get('experiment_case_id', '')} "
                f"| {record.get('collaboration_mode', '')} "
                f"| {record.get('review_mode', '')} "
                f"| {metrics.get('poi_count', 0)} "
                f"| {metrics.get('day_count', 0)} "
                f"| {'是' if metrics.get('is_over_budget') else '否'} "
                f"| {metrics.get('overall_review_score', 0):.1f} "
                f"| {metrics.get('issue_count', 0)} "
                f"| {metrics.get('warning_count', 0)} "
                f"| {'是' if metrics.get('has_fix_applied') else '否'} |"
            )
        
        return "\n".join(lines)
    
    def generate_statistics_summary(self) -> Dict[str, Any]:
        """
        生成统计摘要
        
        Returns:
            Dict: 统计摘要
        """
        if not self.experiment_records:
            return {
                "total_experiments": 0,
                "message": "暂无实验数据",
            }
        
        records = self.experiment_records
        
        # 按协作模式分组统计
        collab_stats: Dict[str, Dict[str, Any]] = {}
        for mode in CollaborationMode:
            mode_records = [r for r in records if r.get("collaboration_mode") == mode.value]
            if mode_records:
                scores = [r.get("metrics", {}).get("overall_review_score", 0) for r in mode_records]
                issue_counts = [r.get("metrics", {}).get("issue_count", 0) for r in mode_records]
                collab_stats[mode.value] = {
                    "count": len(mode_records),
                    "avg_score": sum(scores) / len(scores) if scores else 0,
                    "avg_issues": sum(issue_counts) / len(issue_counts) if issue_counts else 0,
                }
        
        # 按 Review 模式分组统计
        review_stats: Dict[str, Dict[str, Any]] = {}
        for mode in ReviewModeExperiment:
            mode_records = [r for r in records if r.get("review_mode") == mode.value]
            if mode_records:
                scores = [r.get("metrics", {}).get("overall_review_score", 0) for r in mode_records]
                issue_counts = [r.get("metrics", {}).get("issue_count", 0) for r in mode_records]
                review_stats[mode.value] = {
                    "count": len(mode_records),
                    "avg_score": sum(scores) / len(scores) if scores else 0,
                    "avg_issues": sum(issue_counts) / len(issue_counts) if issue_counts else 0,
                }
        
        # 计算结构字段完备率
        has_poi_rate = sum(1 for r in records if r.get("metrics", {}).get("has_poi_list")) / len(records)
        has_daily_rate = sum(1 for r in records if r.get("metrics", {}).get("has_daily_plans")) / len(records)
        has_budget_rate = sum(1 for r in records if r.get("metrics", {}).get("has_structured_budget")) / len(records)
        
        # 计算超预算率
        over_budget_count = sum(1 for r in records if r.get("metrics", {}).get("is_over_budget") is True)
        over_budget_rate = over_budget_count / len(records) if records else 0
        
        return {
            "total_experiments": len(records),
            "collaboration_mode_stats": collab_stats,
            "review_mode_stats": review_stats,
            "structure_completeness": {
                "poi_list_rate": round(has_poi_rate, 2),
                "daily_plans_rate": round(has_daily_rate, 2),
                "structured_budget_rate": round(has_budget_rate, 2),
            },
            "over_budget_rate": round(over_budget_rate, 2),
            "generated_at": datetime.utcnow().isoformat(),
        }


# 全局单例实例
_experiment_runner: Optional[ExperimentRunner] = None


def get_experiment_runner() -> ExperimentRunner:
    """获取实验运行器单例"""
    global _experiment_runner
    if _experiment_runner is None:
        _experiment_runner = ExperimentRunner()
    return _experiment_runner
