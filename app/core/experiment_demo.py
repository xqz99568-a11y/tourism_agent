"""
实验演示脚本
演示如何运行实验、收集指标和导出论文数据
"""
from app.core.experiment_runner import get_experiment_runner
from app.core.experiment_metrics import (
    CollaborationMode,
    ReviewModeExperiment,
    ExperimentMetrics,
    metrics_to_dict,
)


def demo_experiment_metrics():
    """演示实验指标采集"""
    print("=" * 60)
    print("实验指标采集演示")
    print("=" * 60)
    
    # 创建实验运行器
    runner = get_experiment_runner()
    
    # 演示：创建实验上下文
    print("\n1. 创建实验上下文")
    
    # 实验组1：结构化协作对比
    print("\n  [实验组1: 结构化协作对比]")
    
    # baseline_plain 模式
    ctx1 = runner.create_experiment_context(
        experiment_case_id="case_001",
        collaboration_mode=CollaborationMode.BASELINE_PLAIN.value,
        review_mode=ReviewModeExperiment.NO_REVIEW.value,
        experiment_group="group_structured_comparison",
    )
    print(f"    - baseline_plain: {ctx1.collaboration_mode}, structured_modules={ctx1.structured_modules_enabled}")
    
    # structured_collaboration 模式
    ctx2 = runner.create_experiment_context(
        experiment_case_id="case_002",
        collaboration_mode=CollaborationMode.STRUCTURED_COLLABORATION.value,
        review_mode=ReviewModeExperiment.REVIEW_ONLY.value,
        experiment_group="group_structured_comparison",
    )
    print(f"    - structured_collaboration: {ctx2.collaboration_mode}, structured_modules={ctx2.structured_modules_enabled}")
    
    # 实验组2：Review 对比
    print("\n  [实验组2: Review对比]")
    
    for review_mode in ReviewModeExperiment:
        ctx = runner.create_experiment_context(
            experiment_case_id=f"case_review_{review_mode.value}",
            collaboration_mode=CollaborationMode.STRUCTURED_COLLABORATION.value,
            review_mode=review_mode.value,
            experiment_group="group_review_comparison",
        )
        print(f"    - {review_mode.value}: review_enabled={ctx.structured_modules_enabled.get('structured_review')}")
    
    # 演示：创建模拟指标
    print("\n2. 创建模拟实验指标")
    
    metrics = ExperimentMetrics()
    metrics.experiment_case_id = "case_001"
    metrics.experiment_group = "group_structured_comparison"
    metrics.collaboration_mode = CollaborationMode.STRUCTURED_COLLABORATION.value
    metrics.review_mode = ReviewModeExperiment.REVIEW_ONLY.value
    
    # 结构完整性
    metrics.has_poi_list = True
    metrics.poi_count = 6
    metrics.has_daily_plans = True
    metrics.day_count = 3
    metrics.has_structured_budget = True
    metrics.has_structured_review = True
    
    # Review 评分
    metrics.overall_review_score = 7.8
    metrics.completeness_score = 8.0
    metrics.consistency_score = 7.5
    metrics.feasibility_score = 8.0
    metrics.personalization_score = 7.5
    metrics.constraint_satisfaction_score = 8.0
    metrics.issue_count = 2
    metrics.warning_count = 1
    
    # 预算
    metrics.is_over_budget = False
    metrics.total_budget = 5000.0
    metrics.budget_limit = 5000.0
    metrics.has_budget_breakdown = True
    
    # 行程
    metrics.unscheduled_poi_count = 0
    metrics.has_empty_days = False
    metrics.has_overloaded_days = False
    
    # 修正
    metrics.has_fix_applied = False
    metrics.fix_rule_count = 0
    
    # 转换为字典
    metrics_dict = metrics_to_dict(metrics)
    
    print("\n实验指标输出:")
    print("-" * 40)
    for key, value in metrics_dict.items():
        if key == "metrics":
            print(f"  {key}:")
            for m_key, m_value in value.items():
                print(f"    - {m_key}: {m_value}")
        else:
            print(f"  {key}: {value}")
    
    return metrics_dict


def demo_experiment_records():
    """演示实验记录构建"""
    print("\n" + "=" * 60)
    print("实验记录构建演示")
    print("=" * 60)
    
    runner = get_experiment_runner()
    
    # 创建实验上下文
    runner.create_experiment_context(
        experiment_case_id="demo_001",
        collaboration_mode=CollaborationMode.STRUCTURED_COLLABORATION.value,
        review_mode=ReviewModeExperiment.REVIEW_AND_FIX.value,
        experiment_group="demo_group",
    )
    
    # 输入案例
    input_case = {
        "destination": "杭州",
        "duration": 3,
        "num_travelers": 2,
        "budget_level": "medium",
    }
    
    # 模拟结果快照
    result_snapshot = {
        "attraction": {
            "poi_count": 6,
            "top_pois": ["西湖", "灵隐寺", "宋城"],
        },
        "itinerary": {
            "day_count": 3,
            "daily_plans_complete": True,
        },
        "budget": {
            "total_budget": 5000,
            "is_over_budget": False,
        },
        "review": {
            "overall_score": 7.8,
            "issue_count": 2,
            "has_fix": True,
        },
    }
    
    # 记录实验
    record = runner.record_experiment(
        input_case=input_case,
        result_snapshot=result_snapshot,
    )
    
    print("\n实验记录:")
    print("-" * 40)
    for key, value in record.items():
        if key == "metrics":
            print(f"  {key}:")
            for m_key, m_value in value.items():
                print(f"    - {m_key}: {m_value}")
        else:
            print(f"  {key}: {value}")
    
    return record


def demo_comparison_table():
    """演示对比表生成"""
    print("\n" + "=" * 60)
    print("对比表生成演示（Markdown格式）")
    print("=" * 60)
    
    runner = get_experiment_runner()
    
    # 添加更多实验记录
    runner.create_experiment_context(
        experiment_case_id="case_baseline",
        collaboration_mode=CollaborationMode.BASELINE_PLAIN.value,
        review_mode=ReviewModeExperiment.NO_REVIEW.value,
        experiment_group="group_1",
    )
    runner.record_experiment(
        input_case={"destination": "成都", "duration": 4, "num_travelers": 2, "budget_level": "medium"},
        result_snapshot={"attraction": {"poi_count": 5}},
    )
    
    runner.create_experiment_context(
        experiment_case_id="case_structured",
        collaboration_mode=CollaborationMode.STRUCTURED_COLLABORATION.value,
        review_mode=ReviewModeExperiment.REVIEW_ONLY.value,
        experiment_group="group_1",
    )
    runner.record_experiment(
        input_case={"destination": "成都", "duration": 4, "num_travelers": 2, "budget_level": "medium"},
        result_snapshot={"attraction": {"poi_count": 6}},
    )
    
    runner.create_experiment_context(
        experiment_case_id="case_review_fix",
        collaboration_mode=CollaborationMode.STRUCTURED_COLLABORATION.value,
        review_mode=ReviewModeExperiment.REVIEW_AND_FIX.value,
        experiment_group="group_2",
    )
    runner.record_experiment(
        input_case={"destination": "成都", "duration": 4, "num_travelers": 2, "budget_level": "medium"},
        result_snapshot={"attraction": {"poi_count": 6}},
    )
    
    # 生成对比表
    print("\n" + runner.generate_comparison_table())


def demo_statistics_summary():
    """演示统计摘要生成"""
    print("\n" + "=" * 60)
    print("统计摘要生成演示")
    print("=" * 60)
    
    runner = get_experiment_runner()
    
    summary = runner.generate_statistics_summary()
    
    import json
    print("\n" + json.dumps(summary, indent=2, ensure_ascii=False))


def demo_export():
    """演示结果导出"""
    print("\n" + "=" * 60)
    print("结果导出演示")
    print("=" * 60)
    
    runner = get_experiment_runner()
    
    # 导出到控制台
    results = runner.export_results()
    print(f"\n已导出 {len(results)} 条实验记录")
    
    # 生成对比表
    if results:
        print("\n" + runner.generate_comparison_table())


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Tourism Agent 实验系统演示")
    print("=" * 60)
    
    # 演示各项功能
    demo_experiment_metrics()
    demo_experiment_records()
    demo_comparison_table()
    demo_statistics_summary()
    demo_export()
    
    print("\n" + "=" * 60)
    print("演示完成！")
    print("=" * 60)
