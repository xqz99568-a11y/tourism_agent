"""Day 7 formal test-draft dataset generation and quota gate.

This module is deliberately offline-only.  It creates the 100-case formal test
draft required before spending API budget and audits whether the draft matches
the paper protocol: 100 statistical cases, 130 actual turns, 30 two-turn
scenarios, eight task categories, and balanced coverage over the five frozen
tourism cities.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

from app.core.benchmark_dataset_validator import build_benchmark_dataset_quality_report
from app.core.fixed_data import (
    FIXED_CITY_IDS,
    canonical_json_sha256,
    get_fixed_tourism_data,
    validate_fixed_data_snapshot,
)


DAY7_TEST_DRAFT_DATASET_SCHEMA_VERSION = "ctp-benchmark-v1"
DAY7_TEST_DRAFT_GATE_SCHEMA_VERSION = "ctp-day7-test-draft-gate-v1"
DAY7_TEST_DRAFT_FEASIBILITY_SCHEMA_VERSION = "ctp-day7-test-draft-feasibility-v1"

DEFAULT_TEST_DRAFT_DATASET_ID = "ctp120_test_draft"
DEFAULT_TEST_DRAFT_DATASET_VERSION = "2026-08-01-draft-v1"
DEFAULT_EXPECTED_CASE_COUNT = 100
DEFAULT_EXPECTED_TURN_COUNT = 130
DEFAULT_EXPECTED_SCENARIO_CASE_COUNT = 30
DEFAULT_EXPECTED_CITY_CASE_COUNT = 16
MIN_TOURISM_TEMPLATE_FAMILY_COUNT = 35
MAX_TOURISM_TEMPLATE_FAMILY_SIZE = 6

TEST_DRAFT_CASE_TASK_QUOTAS: Dict[str, int] = {
    "trip_planning": 20,
    "attraction_recommendation": 10,
    "weather_query": 10,
    "budget_query": 10,
    "partial_replan": 20,
    "weather_adjustment": 10,
    "clarification": 10,
    "general_chat": 10,
}

TOURISM_CASE_TASK_TYPES = {
    "trip_planning",
    "attraction_recommendation",
    "weather_query",
    "budget_query",
    "partial_replan",
    "weather_adjustment",
}

CITY_NAMES = {
    "beijing": "北京",
    "hangzhou": "杭州",
    "xian": "西安",
    "shenzhen": "深圳",
    "guilin": "桂林",
}

CITY_ORDER = ("beijing", "hangzhou", "xian", "shenzhen", "guilin")
ALL_TOOLS = ["poi_search", "weather_query", "budget_calculator"]

_TRIP_STYLES = (
    "城市文化观察",
    "轻松打卡",
    "周末深度游",
    "亲友同行",
    "慢节奏体验",
    "第一次到访",
    "公共交通优先",
    "避开拥挤路线",
    "上午出发节奏",
    "傍晚返程安排",
)

_ATTRACTION_THEMES: Sequence[tuple[str, list[str]]] = (
    ("历史文化", ["history_culture"]),
    ("自然风景", ["nature"]),
    ("室内博物馆", ["indoor", "history_culture"]),
    ("亲子友好", ["family"]),
    ("公园休闲", ["nature"]),
    ("城市地标", []),
    ("少走路备选", []),
    ("雨天室内", ["indoor"]),
    ("摄影打卡", []),
    ("文化展馆", ["history_culture"]),
)

_CONTEXTS = (
    "希望最后答案按日期分段，方便人工核对约束",
    "同行者不熟悉当地交通，请把建议说得直接一些",
    "我会把结果用于实验标注，希望城市边界保持清楚",
    "请优先使用固定离线资料中能支撑的景点和天气信息",
    "如果预算紧张，请在结论里明确说明是否超支",
    "我更关心工具调用是否完整，所以需要保留依据",
    "答案可以简洁，但关键日期、人数和预算都要出现",
    "请把天气风险和行程调整理由分开表达",
    "我只需要可执行方案，营销式夸张描述不是重点",
    "请把闲聊内容和真实旅行规划区分清楚",
    "请把景点数量控制在标注要求内，减少点位堆叠",
    "需要保持上一轮条件时，请维持原城市和日期",
    "请优先说明是否需要补充信息，再决定是否规划",
    "我希望看到多 Agent 协作中工具选择的差异",
    "请把用户当前话语中的变化条件放在最高优先级",
)


def build_ctp120_test_draft_document(
    *,
    dataset_id: str = DEFAULT_TEST_DRAFT_DATASET_ID,
    dataset_version: str = DEFAULT_TEST_DRAFT_DATASET_VERSION,
) -> Dict[str, Any]:
    """Return the deterministic 100-case formal test draft document."""
    cases: list[dict[str, Any]] = []
    cases.extend(_trip_planning_cases(start_index=1, count=20))
    cases.extend(_attraction_cases(start_index=21, count=10))
    cases.extend(_weather_query_cases(start_index=31, count=10))
    cases.extend(_budget_query_cases(start_index=41, count=10))
    cases.extend(_partial_replan_cases(start_index=51, count=20))
    cases.extend(_weather_adjustment_cases(start_index=71, count=10))
    cases.extend(_clarification_cases(start_index=81, count=10))
    cases.extend(_general_chat_cases(start_index=91, count=10))
    _finalize_test_draft_cases(cases)
    return {
        "schema_version": DAY7_TEST_DRAFT_DATASET_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "split": "test_draft",
        "language": "zh-CN",
        "target_formal_case_count": DEFAULT_EXPECTED_CASE_COUNT,
        "target_formal_turn_count": DEFAULT_EXPECTED_TURN_COUNT,
        "description": (
            "100个中文正式测试集草稿案例；用于冻结正式测试集前的配额、中文、重复、"
            "近似重复和离线可行性审计。该草稿不得直接与开发集结果混用。"
        ),
        "comparison_files": ["ctp120_dev.json", "benchmark_test.json"],
        "annotation_policy": {
            "visible_language": "zh-CN",
            "gold_visible_to_generation": False,
            "slot_gold_consistency_required": True,
            "changed_slot_current_utterance_required": True,
            "preserved_slot_previous_state_required": True,
            "fixed_offline_city_only": True,
            "statistical_unit": "case_id",
            "actual_turn_unit": "single case or scenario turn",
        },
        "quota_policy": {
            "case_task_quotas": dict(TEST_DRAFT_CASE_TASK_QUOTAS),
            "city_related_case_quota_per_city": DEFAULT_EXPECTED_CITY_CASE_COUNT,
            "scenario_case_count": DEFAULT_EXPECTED_SCENARIO_CASE_COUNT,
            "scenario_turn_count": 2,
        },
        "cases": cases,
    }


def build_day7_test_draft_gate(
    *,
    document: Mapping[str, Any],
    cases: Iterable[Mapping[str, Any]],
    expected_case_count: int = DEFAULT_EXPECTED_CASE_COUNT,
    expected_turn_count: int = DEFAULT_EXPECTED_TURN_COUNT,
    expected_scenario_case_count: int = DEFAULT_EXPECTED_SCENARIO_CASE_COUNT,
    expected_city_case_count: int = DEFAULT_EXPECTED_CITY_CASE_COUNT,
    expected_case_task_quotas: Mapping[str, int] | None = None,
    comparison_splits: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    quality_report: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a machine-readable gate for the formal test draft."""
    raw_cases = [case for case in cases if isinstance(case, Mapping)]
    quotas = dict(expected_case_task_quotas or TEST_DRAFT_CASE_TASK_QUOTAS)
    if quality_report is None:
        quality_report = build_benchmark_dataset_quality_report(
            document=document,
            cases=raw_cases,
            expected_case_count=expected_case_count,
            strict_formal=True,
            comparison_splits=comparison_splits,
        )
    case_task_distribution = _case_task_distribution(raw_cases)
    unit_task_distribution = _unit_task_distribution(raw_cases)
    city_distribution = _city_case_distribution(raw_cases)
    structure = _dataset_structure(raw_cases)
    duplicate_counts = _quality_duplicate_counts(quality_report)
    visible_artifacts = _visible_artifact_report(raw_cases)
    semantic_duplicates = _semantic_template_duplicate_groups(raw_cases)
    template_family_report = _semantic_template_family_report(raw_cases)
    tool_label_completeness = _tool_label_completeness(raw_cases)
    feasibility_summary = build_day7_test_draft_feasibility_report(
        quality_report=quality_report,
    )
    expected_city_distribution = {
        city_id: expected_city_case_count for city_id in FIXED_CITY_IDS
    }
    checks = {
        "quality_gate_passed": quality_report.get("status") == "passed",
        "case_count_matches": structure["case_count"] == expected_case_count,
        "turn_count_matches": structure["total_turn_count"] == expected_turn_count,
        "scenario_case_count_matches": (
            structure["scenario_case_count"] == expected_scenario_case_count
        ),
        "all_scenarios_are_double_turn": structure["non_double_turn_scenario_count"] == 0,
        "case_task_quotas_match": dict(sorted(case_task_distribution.items()))
        == dict(sorted(quotas.items())),
        "city_case_quotas_match": dict(sorted(city_distribution.items()))
        == dict(sorted(expected_city_distribution.items())),
        "city_related_case_count_matches": sum(city_distribution.values())
        == expected_city_case_count * len(FIXED_CITY_IDS),
        "language_all_zh_cn": _nested(quality_report, "language", "non_chinese_unit_count") == 0,
        "no_internal_duplicate_inputs": duplicate_counts["internal_duplicate_count"] == 0,
        "no_cross_split_duplicate_inputs": duplicate_counts["cross_split_duplicate_count"] == 0,
        "no_near_duplicate_inputs": duplicate_counts["near_duplicate_count"] == 0,
        "no_semantic_template_duplicate_inputs": not semantic_duplicates,
        "tourism_template_family_diversity_sufficient": (
            template_family_report["tourism_template_family_count"]
            >= MIN_TOURISM_TEMPLATE_FAMILY_COUNT
        ),
        "tourism_template_family_size_below_limit": (
            template_family_report["max_tourism_template_family_size"]
            <= MAX_TOURISM_TEMPLATE_FAMILY_SIZE
        ),
        "no_visible_experiment_artifacts": visible_artifacts["leaking_unit_count"] == 0,
        "required_tools_explicit_for_all_units": tool_label_completeness[
            "missing_required_tools_count"
        ]
        == 0,
        "forbidden_tools_explicit_for_all_units": tool_label_completeness[
            "missing_forbidden_tools_count"
        ]
        == 0,
        "offline_feasibility_passed": feasibility_summary["status"] == "passed",
        "comparison_splits_checked": _nested(
            quality_report,
            "policy",
            "cross_split_duplicate_check",
        )
        is True,
    }
    failed_checks = [name for name, value in checks.items() if not value]
    return {
        "schema_version": DAY7_TEST_DRAFT_GATE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not failed_checks else "failed",
        "paper_claims_allowed": False,
        "dataset_id": document.get("dataset_id"),
        "dataset_version": document.get("dataset_version"),
        "split": document.get("split"),
        "dataset_sha256": canonical_json_sha256(document),
        "expected": {
            "case_count": expected_case_count,
            "turn_count": expected_turn_count,
            "scenario_case_count": expected_scenario_case_count,
            "double_turn_scenario_count": expected_scenario_case_count,
            "case_task_quotas": quotas,
            "city_case_distribution": expected_city_distribution,
        },
        "actual": {
            **structure,
            "case_task_distribution": dict(sorted(case_task_distribution.items())),
            "unit_task_distribution": dict(sorted(unit_task_distribution.items())),
            "city_case_distribution": dict(sorted(city_distribution.items())),
            "city_related_case_count": sum(city_distribution.values()),
            "language": quality_report.get("language"),
            "duplicate_counts": {
                **duplicate_counts,
                "semantic_template_duplicate_count": len(semantic_duplicates),
                "tourism_template_family_count": template_family_report[
                    "tourism_template_family_count"
                ],
                "max_tourism_template_family_size": template_family_report[
                    "max_tourism_template_family_size"
                ],
            },
            "semantic_template_duplicate_groups": semantic_duplicates[:20],
            "semantic_template_family_report": template_family_report,
            "visible_artifacts": visible_artifacts,
            "tool_label_completeness": tool_label_completeness,
        },
        "quality_gate": {
            "schema_version": quality_report.get("schema_version"),
            "status": quality_report.get("status"),
            "error_count": len(quality_report.get("errors") or []),
            "warning_count": len(quality_report.get("warnings") or []),
            "errors": list(quality_report.get("errors") or [])[:20],
            "warnings": list(quality_report.get("warnings") or [])[:20],
        },
        "offline_feasibility": feasibility_summary,
        "checks": checks,
        "failed_checks": failed_checks,
        "paper_use_policy": {
            "summary": (
                "This is a held-out formal test draft.  It can be used for "
                "preflight and manual annotation review, but final paper claims "
                "still require a real, frozen formal run."
            ),
            "allowed_uses": [
                "formal test-set preflight",
                "quota and feasibility evidence",
                "manual review before final freeze",
            ],
            "forbidden_uses": [
                "final result claims without running the four-method experiment",
                "mixing with ctp120_dev development results",
            ],
        },
    }


def build_day7_test_draft_feasibility_report(
    *,
    quality_report: Mapping[str, Any],
) -> Dict[str, Any]:
    """Summarize offline feasibility checks from the dataset quality report."""
    units = [unit for unit in quality_report.get("units") or [] if isinstance(unit, Mapping)]
    checked_units = [
        unit
        for unit in units
        if _nested(unit, "offline_feasibility", "checked") is True
    ]
    failed_units = [
        unit
        for unit in checked_units
        if _nested(unit, "offline_feasibility", "status") != "passed"
    ]
    city_counts: Counter[str] = Counter()
    task_counts: Counter[str] = Counter()
    for unit in checked_units:
        city_id = str(unit.get("city_id") or "")
        task_type = str(unit.get("task_type") or "")
        if city_id:
            city_counts[city_id] += 1
        if task_type:
            task_counts[task_type] += 1
    fixed_snapshot = _fixed_data_snapshot()
    return {
        "schema_version": DAY7_TEST_DRAFT_FEASIBILITY_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not failed_units and quality_report.get("status") == "passed" else "failed",
        "quality_status": quality_report.get("status"),
        "unit_count": len(units),
        "checked_tourism_unit_count": len(checked_units),
        "passed_tourism_unit_count": len(checked_units) - len(failed_units),
        "failed_tourism_unit_count": len(failed_units),
        "city_unit_distribution": dict(sorted(city_counts.items())),
        "task_unit_distribution": dict(sorted(task_counts.items())),
        "fixed_data_snapshot": fixed_snapshot,
        "failed_units": [
            {
                "label": unit.get("label"),
                "task_type": unit.get("task_type"),
                "city_id": unit.get("city_id"),
                "errors": _nested(unit, "offline_feasibility", "errors") or [],
            }
            for unit in failed_units[:20]
        ],
        "policy": {
            "fixed_city_ids": list(FIXED_CITY_IDS),
            "max_trip_days_checked_against_fixed_weather": True,
            "min_attractions_checked_against_fixed_poi_count": True,
            "weather_change_checked_against_fixed_scenarios": True,
        },
    }


def render_day7_test_draft_report(gate: Mapping[str, Any]) -> str:
    """Render a concise Chinese Markdown report for the formal test draft."""
    expected = _dict(gate.get("expected"))
    actual = _dict(gate.get("actual"))
    feasibility = _dict(gate.get("offline_feasibility"))
    lines = [
        "# Day 7 正式测试集草稿验收报告",
        "",
        "## 结论",
        "",
        f"- gate_status: `{gate.get('status')}`",
        f"- paper_claims_allowed: `{gate.get('paper_claims_allowed')}`",
        f"- dataset: `{gate.get('dataset_id')}` / `{gate.get('dataset_version')}`",
        f"- case_count: `{actual.get('case_count')}` / `{expected.get('case_count')}`",
        f"- total_turn_count: `{actual.get('total_turn_count')}` / `{expected.get('turn_count')}`",
        f"- scenario_case_count: `{actual.get('scenario_case_count')}` / `{expected.get('scenario_case_count')}`",
        f"- offline_feasibility: `{feasibility.get('status')}`",
        f"- failed_checks: `{gate.get('failed_checks') or []}`",
        "",
        "说明：这是正式测试集草稿的离线验收，不调用大模型；它证明数据结构、配额和固定数据可行性可以进入正式实验前检查。",
        "",
        "## 重建与预检查命令",
        "",
        "```powershell",
        "python experiments\\build_day7_test_draft.py --strict",
        "python experiments\\validate_benchmark_dataset.py --benchmark experiments\\benchmark.json --expected-cases 100",
        "python experiments\\run_formal_experiment.py --benchmark experiments\\benchmark.json --expected-cases 100 --preflight-only --skip-llm-config-check",
        "```",
        "",
        "## 八类任务配额（按统计案例 case_id 计）",
        "",
        "| Task type | Expected | Actual |",
        "|---|---:|---:|",
    ]
    actual_case_tasks = _dict(actual.get("case_task_distribution"))
    for task_type, expected_count in _dict(expected.get("case_task_quotas")).items():
        lines.append(f"| {task_type} | {expected_count} | {actual_case_tasks.get(task_type, 0)} |")
    lines.extend(
        [
            "",
            "## 实际轮次任务分布（展开多轮后）",
            "",
            "| Task type | Unit count |",
            "|---|---:|",
        ]
    )
    for task_type, count in _dict(actual.get("unit_task_distribution")).items():
        lines.append(f"| {task_type} | {count} |")
    lines.extend(
        [
            "",
            "## 五城覆盖（按城市相关统计案例计）",
            "",
            "| City | Expected | Actual |",
            "|---|---:|---:|",
        ]
    )
    actual_cities = _dict(actual.get("city_case_distribution"))
    for city_id, expected_count in _dict(expected.get("city_case_distribution")).items():
        lines.append(f"| {city_id} | {expected_count} | {actual_cities.get(city_id, 0)} |")
    duplicate_counts = _dict(actual.get("duplicate_counts"))
    template_family = _dict(actual.get("semantic_template_family_report"))
    lines.extend(
        [
            "",
            "## 重复、中文与可行性",
            "",
            f"- non_chinese_unit_count: `{_nested(actual, 'language', 'non_chinese_unit_count')}`",
            f"- internal_duplicate_count: `{duplicate_counts.get('internal_duplicate_count')}`",
            f"- cross_split_duplicate_count: `{duplicate_counts.get('cross_split_duplicate_count')}`",
            f"- near_duplicate_count: `{duplicate_counts.get('near_duplicate_count')}`",
            f"- tourism_template_family_count: `{template_family.get('tourism_template_family_count')}`",
            f"- max_tourism_template_family_size: `{template_family.get('max_tourism_template_family_size')}`",
            f"- checked_tourism_unit_count: `{feasibility.get('checked_tourism_unit_count')}`",
            f"- failed_tourism_unit_count: `{feasibility.get('failed_tourism_unit_count')}`",
            "",
            "## 检查项",
            "",
            "| Check | Passed |",
            "|---|---:|",
        ]
    )
    for key, value in _dict(gate.get("checks")).items():
        lines.append(f"| {key} | `{value}` |")
    return "\n".join(lines) + "\n"


def write_json(path: str | Path, payload: Any) -> Path:
    """Write JSON with the repository's experiment formatting."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def write_text(path: str | Path, payload: str) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload, encoding="utf-8")
    return output


def _with_context(text: str, case_no: int) -> str:
    return f"{text.rstrip('。')}。补充背景：{_context(case_no)}。"


def _trip_plan_user_input(
    *,
    city: str,
    day: int,
    duration: int,
    style: str,
    people: int,
    budget: int,
    case_no: int,
    offset: int,
) -> str:
    variants = (
        f"我想去{city}玩{duration}天，2026年9月{day}日出发，{people}个人，预算{budget}元；请按{style}的感觉安排景点、天气提醒、每日路线和费用估算。",
        f"帮我把{city}{duration}天旅行捋清楚：2026年9月{day}日走，{people}个人，费用控制在{budget}元左右，景点、天气、每天安排和预算都要有。",
        f"准备2026年9月{day}日到{city}旅行{duration}天，同行{people}个人，总预算{budget}元；希望方案偏{style}，同时给出天气风险和花费判断。",
        f"{people}个人计划在2026年9月{day}日出发去{city}，玩{duration}天，预算上限{budget}元；请把景点选择、天气、行程节奏和费用放在一份方案里。",
        f"请为{city}做一个{duration}天{style}行程，出发日是2026年9月{day}日，{people}个人，预算{budget}元；我需要能直接执行的路线、天气提示和费用估算。",
    )
    return _with_context(variants[offset % len(variants)], case_no)


def _attraction_user_input(
    *,
    city: str,
    attraction_count: int,
    theme: str,
    case_no: int,
    offset: int,
) -> str:
    variants = (
        f"只帮我挑{city}{attraction_count}个{theme}类景点，按推荐理由列出即可；不要天气、路线和预算，也不要生成完整行程。",
        f"我现在只想看{city}的{theme}景点，请选{attraction_count}个并说明为什么值得去；先别安排日程、天气或费用。",
        f"请从{city}里筛{attraction_count}个偏{theme}的点位，给出简短理由就好，不需要路线、天气预报和预算估算。",
        f"帮我做一个{city}{theme}景点小清单，数量控制在{attraction_count}个；这次只要景点推荐，不要扩展成完整旅行方案。",
        f"如果只看{theme}方向，{city}有哪些{attraction_count}个点比较合适？请按理由排序，不用查天气和算钱。",
    )
    return _with_context(variants[offset % len(variants)], case_no)


def _weather_query_user_input(
    *,
    city: str,
    day: int,
    duration: int,
    case_no: int,
    offset: int,
) -> str:
    variants = (
        f"请只查询{city}2026年9月{day}日开始{duration}天的天气预报，顺便说明穿衣和出行风险；不要推荐景点、不要安排路线、不要估算预算。",
        f"我只需要{city}天气：从2026年9月{day}日算起看{duration}天，请告诉我风险和穿衣建议，先不要做景点或行程。",
        f"帮我看一下{city}2026年9月{day}日出发后{duration}天的天气情况；回答聚焦天气，不要夹带路线和预算。",
        f"{city}在2026年9月{day}日开始的{duration}天适不适合出门？请只给天气判断、风险提醒和简单准备建议。",
        f"查一下{city}{duration}天天气，起始日期是2026年9月{day}日；我不需要景点清单，也不需要费用测算。",
    )
    return _with_context(variants[offset % len(variants)], case_no)


def _budget_query_user_input(
    *,
    city: str,
    day: int,
    duration: int,
    people: int,
    budget: int,
    case_no: int,
    offset: int,
) -> str:
    variants = (
        f"只帮我估算{city}2026年9月{day}日出发、{duration}天、{people}个人旅行，预算{budget}元是否够用；请给出总费用判断，不要生成景点清单或天气报告。",
        f"{people}个人去{city}玩{duration}天，2026年9月{day}日出发，预算是{budget}元；我只想知道钱够不够，不要展开景点和路线。",
        f"请评估一下{city}{duration}天旅行费用：2026年9月{day}日走，{people}个人，预算上限{budget}元；回答重点放在费用是否可行。",
        f"如果我们{people}个人在2026年9月{day}日去{city}旅行{duration}天，{budget}元预算大概能不能覆盖？先别给天气和景点推荐。",
        f"帮我算{city}旅行预算是否紧张：出发日期2026年9月{day}日，天数{duration}天，人数{people}个人，总预算{budget}元。",
    )
    return _with_context(variants[offset % len(variants)], case_no)


def _scenario_plan_user_input(
    *,
    city: str,
    day: int,
    duration: int,
    people: int,
    budget: int,
    case_no: int,
    offset: int,
    month: int,
) -> str:
    variants = (
        f"先为{city}规划2026年{month}月{day}日出发的{duration}天旅行，{people}个人，预算{budget}元，包含景点、天气、行程和预算。",
        f"我们准备2026年{month}月{day}日去{city}玩{duration}天，{people}个人，预算{budget}元；请先给完整旅行方案。",
        f"请把{city}{duration}天行程先搭起来：2026年{month}月{day}日出发，{people}个人，预算{budget}元，景点、天气、路线和花费都要覆盖。",
        f"{people}个人在2026年{month}月{day}日出发去{city}旅行{duration}天，预算{budget}元；先做一版完整安排，后面我可能再改条件。",
        f"帮我做{city}旅行初版计划，时间是2026年{month}月{day}日开始{duration}天，{people}个人，预算{budget}元。",
    )
    return _with_context(variants[offset % len(variants)], case_no)


def _weather_change_user_input(
    *,
    city: str,
    day: int,
    duration: int,
    people: int,
    budget: int,
    visible_weather: str,
    affected_day: int,
    case_no: int,
    offset: int,
) -> str:
    variants = (
        f"{city}第{affected_day}天出现{visible_weather}，只调整受影响的第{affected_day}天；2026年11月{day}日出发、{duration}天、{people}个人和{budget}元预算都保持不变。",
        f"刚才的{city}方案里，第{affected_day}天遇到{visible_weather}。原计划仍是2026年11月{day}日出发、{duration}天、{people}个人、预算{budget}元，请只改这一天。",
        f"需要改一下{city}行程：第{affected_day}天有{visible_weather}风险，出发日2026年11月{day}日、行程{duration}天、人数{people}个人、预算{budget}元不变。",
        f"{city}旅行第{affected_day}天改按{visible_weather}处理；2026年11月{day}日出发，整体{duration}天，{people}个人，{budget}元预算，请保留其他条件。",
        f"如果{city}第{affected_day}天变成{visible_weather}，请局部调整当天安排。原条件是2026年11月{day}日出发、{duration}天、{people}个人、预算{budget}元。",
    )
    return _with_context(variants[offset % len(variants)], case_no)


def _trip_planning_cases(*, start_index: int, count: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for offset in range(count):
        case_no = start_index + offset
        city_id = _city_for(offset)
        day = 2 + offset
        duration = 2 + (offset % 3)
        people = 2 + (offset % 4)
        budget = 4800 + offset * 180
        city = CITY_NAMES[city_id]
        style = _TRIP_STYLES[offset % len(_TRIP_STYLES)]
        cases.append(
            {
                "case_id": f"ctp_test_{case_no:03d}_{city_id}_full_plan",
                "user_input": _trip_plan_user_input(
                    city=city,
                    day=day,
                    duration=duration,
                    style=style,
                    people=people,
                    budget=budget,
                    case_no=case_no,
                    offset=offset,
                ),
                "expected": _trip_expected(
                    city_id=city_id,
                    start_date=f"2026-09-{day:02d}",
                    duration=duration,
                    people=people,
                    budget=budget,
                ),
            }
        )
    return cases


def _attraction_cases(*, start_index: int, count: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for offset in range(count):
        case_no = start_index + offset
        city_id = _city_for(offset)
        city = CITY_NAMES[city_id]
        theme, preferences = _ATTRACTION_THEMES[offset % len(_ATTRACTION_THEMES)]
        attraction_count = 2 + (offset % 2)
        expected: dict[str, Any] = {
            "task_type": "attraction_recommendation",
            "destination": city_id,
            "min_attractions": attraction_count,
            "max_attractions": attraction_count,
            "required_tools": ["poi_search"],
            "accepted_agent_sets": [["attraction"]],
            "accepted_tool_sets": [["poi_search"]],
        }
        if preferences:
            expected["preferences"] = preferences
        cases.append(
            {
                "case_id": f"ctp_test_{case_no:03d}_{city_id}_attractions",
                "user_input": _attraction_user_input(
                    city=city,
                    attraction_count=attraction_count,
                    theme=theme,
                    case_no=case_no,
                    offset=offset,
                ),
                "expected": expected,
            }
        )
    return cases


def _weather_query_cases(*, start_index: int, count: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for offset in range(count):
        case_no = start_index + offset
        city_id = _city_for(offset)
        city = CITY_NAMES[city_id]
        day = 4 + offset
        duration = 2 + (offset % 3)
        cases.append(
            {
                "case_id": f"ctp_test_{case_no:03d}_{city_id}_weather_only",
                "user_input": _weather_query_user_input(
                    city=city,
                    day=day,
                    duration=duration,
                    case_no=case_no,
                    offset=offset,
                ),
                "expected": {
                    "task_type": "weather_query",
                    "destination": city_id,
                    "start_date": f"2026-09-{day:02d}",
                    "duration_days": duration,
                    "required_tools": ["weather_query"],
                    "accepted_agent_sets": [["weather"]],
                    "accepted_tool_sets": [["weather_query"]],
                },
            }
        )
    return cases


def _budget_query_cases(*, start_index: int, count: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for offset in range(count):
        case_no = start_index + offset
        city_id = _city_for(offset)
        city = CITY_NAMES[city_id]
        day = 6 + offset
        duration = 2 + (offset % 3)
        people = 2 + (offset % 4)
        budget = 3600 + offset * 220
        cases.append(
            {
                "case_id": f"ctp_test_{case_no:03d}_{city_id}_budget_only",
                "user_input": _budget_query_user_input(
                    city=city,
                    day=day,
                    duration=duration,
                    people=people,
                    budget=budget,
                    case_no=case_no,
                    offset=offset,
                ),
                "expected": {
                    "task_type": "budget_query",
                    "destination": city_id,
                    "start_date": f"2026-09-{day:02d}",
                    "duration_days": duration,
                    "people_count": people,
                    "budget_limit": budget,
                    "required_tools": ["budget_calculator"],
                    "accepted_agent_sets": [["budget"]],
                    "accepted_tool_sets": [["budget_calculator"]],
                },
            }
        )
    return cases


def _partial_replan_cases(*, start_index: int, count: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for offset in range(count):
        case_no = start_index + offset
        city_id = _city_for(offset)
        city = CITY_NAMES[city_id]
        day = 8 + (offset % 18)
        duration = 2 + (offset % 2)
        people = 2 + (offset % 3)
        budget = 5200 + offset * 160
        change_kind = offset % 4
        t1_expected = _trip_expected(
            city_id=city_id,
            start_date=f"2026-10-{day:02d}",
            duration=duration,
            people=people,
            budget=budget,
        )
        t2_user, t2_expected = _partial_turn(
            city_id=city_id,
            city=city,
            day=day,
            old_duration=duration,
            people=people,
            budget=budget,
            change_kind=change_kind,
            case_no=case_no,
        )
        cases.append(
            {
                "case_id": f"ctp_test_{case_no:03d}_{city_id}_partial_replan",
                "case_type": "multi_turn",
                "description": f"{city}完整规划后的局部条件修改场景。",
                "turns": [
                    {
                        "turn_id": "t1_full_plan",
                        "target_turn": False,
                        "user_input": _scenario_plan_user_input(
                            city=city,
                            day=day,
                            duration=duration,
                            people=people,
                            budget=budget,
                            case_no=case_no,
                            offset=offset,
                            month=10,
                        ),
                        "expected": t1_expected,
                    },
                    {
                        "turn_id": "t2_partial_change",
                        "target_turn": True,
                        "user_input": t2_user,
                        "expected": t2_expected,
                    },
                ],
            }
        )
    return cases


def _weather_adjustment_cases(*, start_index: int, count: int) -> list[dict[str, Any]]:
    scenarios = (
        ("rain", "下雨", 1),
        ("high_temperature", "高温", 2),
        ("low_temperature", "明显降温", 1),
        ("rain", "雨天", 2),
        ("high_temperature", "炎热高温", 1),
    )
    cases: list[dict[str, Any]] = []
    for offset in range(count):
        case_no = start_index + offset
        city_id = _city_for(offset)
        city = CITY_NAMES[city_id]
        day = 3 + offset
        duration = 2 + (offset % 2)
        people = 2 + (offset % 3)
        budget = 5600 + offset * 170
        scenario_type, visible_weather, affected_day = scenarios[offset % len(scenarios)]
        affected_day = min(affected_day, duration)
        t1_expected = _trip_expected(
            city_id=city_id,
            start_date=f"2026-11-{day:02d}",
            duration=duration,
            people=people,
            budget=budget,
        )
        cases.append(
            {
                "case_id": f"ctp_test_{case_no:03d}_{city_id}_weather_adjustment",
                "case_type": "multi_turn",
                "description": f"{city}完整规划后的天气突发调整场景。",
                "turns": [
                    {
                        "turn_id": "t1_full_plan",
                        "target_turn": False,
                        "user_input": _scenario_plan_user_input(
                            city=city,
                            day=day,
                            duration=duration,
                            people=people,
                            budget=budget,
                            case_no=case_no,
                            offset=offset,
                            month=11,
                        ),
                        "expected": t1_expected,
                    },
                    {
                        "turn_id": "t2_weather_change",
                        "target_turn": True,
                        "user_input": _weather_change_user_input(
                            city=city,
                            day=day,
                            duration=duration,
                            people=people,
                            budget=budget,
                            visible_weather=visible_weather,
                            affected_day=affected_day,
                            case_no=case_no + 200,
                            offset=offset,
                        ),
                        "current_slots": {"weather_scenario": scenario_type},
                        "weather_change": {
                            "scenario_type": scenario_type,
                            "affected_days": [affected_day],
                        },
                        "expected": {
                            "task_type": "weather_adjustment",
                            "changed_slots": ["weather_scenario"],
                            "preserved_slots": [
                                "destination",
                                "start_date",
                                "duration_days",
                                "people_count",
                                "budget_amount",
                            ],
                            "required_tools": ["weather_query"],
                            "accepted_agent_sets": [["weather", "itinerary"]],
                            "accepted_tool_sets": [["weather_query"]],
                            "weather_change": {
                                "scenario_type": scenario_type,
                                "affected_days": [affected_day],
                            },
                            "hard_constraints": {
                                "destination": city_id,
                                "start_date": f"2026-11-{day:02d}",
                                "duration_days": duration,
                                "people_count": people,
                                "budget_limit": budget,
                                "weather_adjustment_required": True,
                            },
                        },
                    },
                ],
            }
        )
    return cases


def _clarification_cases(*, start_index: int, count: int) -> list[dict[str, Any]]:
    prompts = (
        "我想下个月出去玩，但城市、出发日期、天数和预算都没定，请先问我需要补充哪些信息。",
        "我们一家人想做一次短途旅行，还没决定目的地和出发时间，也不知道预算，请帮我澄清。",
        "我只说想休假几天，但没有给城市、日期、同行人数和花费上限，请不要直接规划，先提问。",
        "朋友让我帮忙查旅游方案，可我现在缺少目的地、天数、日期和预算，请先列出追问项。",
        "我想要一个旅行建议，不过关键信息还空着：去哪、什么时候走、玩几天、多少钱都没想好。",
        "请先别调用景点或天气工具，我还没有确定城市和出发日期，也没有预算范围。",
        "我准备带父母出去走走，但目的地、旅行天数和预算都没定，请先帮我确认必要信息。",
        "如果我只说想旅游但没有城市、日期、人数和预算，你应该先问什么？请用旅游助手口吻回答。",
        "我有出游想法但信息很零散，目的地、开始日期、天数、预算都缺，请先做澄清。",
        "先不要给方案，我还没决定去哪、几号出发、几个人和花多少钱，请帮我整理要补充的问题。",
    )
    cases = []
    for offset in range(count):
        case_no = start_index + offset
        cases.append(
            {
                "case_id": f"ctp_test_{case_no:03d}_clarification",
                "user_input": f"{prompts[offset]}补充背景：{_context(case_no)}。",
                "expected": {
                    "task_type": "clarification",
                    "missing_slots": [
                        "destination",
                        "start_date",
                        "duration_days",
                        "budget_amount",
                    ],
                    "accepted_agent_sets": [[]],
                    "accepted_tool_sets": [[]],
                    "forbidden_tools": ALL_TOOLS,
                },
            }
        )
    return cases


def _general_chat_cases(*, start_index: int, count: int) -> list[dict[str, Any]]:
    prompts = (
        "你好，我只是想了解这个旅游助手能做什么，暂时不需要景点、天气、路线或预算。",
        "先打个招呼：如果以后我要规划旅行，你通常会怎样帮我？现在不要生成具体方案。",
        "今天不做旅游计划，我只想测试一下对话是否正常，请不要调用任何旅行工具。",
        "请用一句话介绍你作为智慧旅游助手的能力，不要推荐城市和景点。",
        "我现在只是闲聊，想知道你能不能记住用户约束；不要查询天气或预算。",
        "晚上好，今天没有出行需求，只想确认系统在线，不需要旅行规划。",
        "请简单说说你能帮旅行者处理哪些事情，但不要展开成真实行程。",
        "如果用户之后再给目的地，你可以继续帮助规划；这条消息本身只是普通对话。",
        "我想听听你能处理哪些旅游问题，别把这句话当成正式旅行请求。",
        "谢谢，先不用做任何景点、天气、预算或路线任务，我们只是检查聊天功能。",
    )
    cases = []
    for offset in range(count):
        case_no = start_index + offset
        cases.append(
            {
                "case_id": f"ctp_test_{case_no:03d}_general_chat",
                "user_input": f"{prompts[offset]}补充背景：{_context(case_no)}。",
                "expected": {
                    "task_type": "general_chat",
                    "accepted_agent_sets": [[]],
                    "accepted_tool_sets": [[]],
                    "forbidden_tools": ALL_TOOLS,
                },
            }
        )
    return cases


def _partial_turn(
    *,
    city_id: str,
    city: str,
    day: int,
    old_duration: int,
    people: int,
    budget: int,
    change_kind: int,
    case_no: int,
) -> tuple[str, dict[str, Any]]:
    if change_kind == 0:
        new_duration = old_duration + 1
        variants = (
            f"现在把{city}行程改成{new_duration}天，其余条件保持不变：2026年10月{day}日出发、{people}个人、预算{budget}元；请只重排受影响的行程并更新天气与预算。",
            f"{city}这趟想多玩一天，改为{new_duration}天；出发日还是2026年10月{day}日，{people}个人和{budget}元预算不变，请局部调整。",
            f"请把刚才的{city}方案天数改到{new_duration}天，2026年10月{day}日出发、{people}个人、预算{budget}元都沿用上一轮。",
            f"我想把{city}旅行延长到{new_duration}天，其他条件不要动：2026年10月{day}日走，{people}个人，预算{budget}元。",
            f"{city}计划的日期和人数预算都不变，仍是2026年10月{day}日出发、{people}个人、{budget}元；只把行程改成{new_duration}天。",
        )
        return (
            _with_context(variants[case_no % len(variants)], case_no + 100),
            _partial_expected(
                city_id=city_id,
                day=day,
                duration=new_duration,
                people=people,
                budget=budget,
                changed_slots=["duration_days"],
                agents=["weather", "itinerary", "budget"],
                tools=["weather_query", "budget_calculator"],
            ),
        )
    if change_kind == 1:
        new_people = people + 1
        variants = (
            f"把{city}这趟旅行的人数改成{new_people}个人，2026年10月{day}日出发、{old_duration}天和{budget}元预算不变；请同步调整行程容量和费用。",
            f"{city}方案人数要加到{new_people}个人，日期仍是2026年10月{day}日，天数{old_duration}天，预算{budget}元，请重新算相关安排。",
            f"同行人数变为{new_people}个人；刚才{city}行程的2026年10月{day}日出发、{old_duration}天、{budget}元预算都保留。",
            f"请只更新人数：{city}旅行改为{new_people}个人，原来的2026年10月{day}日出发、{old_duration}天和{budget}元预算不要改。",
            f"{city}这次多一位同行者，人数改成{new_people}个人；出发日期2026年10月{day}日、天数{old_duration}天、预算{budget}元沿用上一轮。",
        )
        return (
            _with_context(variants[case_no % len(variants)], case_no + 100),
            _partial_expected(
                city_id=city_id,
                day=day,
                duration=old_duration,
                people=new_people,
                budget=budget,
                changed_slots=["people_count"],
                agents=["itinerary", "budget"],
                tools=["budget_calculator"],
            ),
        )
    if change_kind == 2:
        new_budget = budget + 700
        variants = (
            f"{city}方案的预算上限改成{new_budget}元，2026年10月{day}日出发、{old_duration}天、{people}个人都不变；请据此局部更新住宿餐饮和总费用。",
            f"预算可以放宽到{new_budget}元；{city}旅行仍按2026年10月{day}日出发、{old_duration}天、{people}个人处理，请只重算费用相关部分。",
            f"把刚才{city}行程的花费上限调到{new_budget}元，日期、天数和人数保持为2026年10月{day}日、{old_duration}天、{people}个人。",
            f"请更新预算：{city}这趟现在按{new_budget}元上限算，2026年10月{day}日出发、{old_duration}天、{people}个人不变。",
            f"{city}旅行其他条件沿用上一轮，只把总预算从{budget}元改为{new_budget}元，请重新判断费用是否合理。",
        )
        return (
            _with_context(variants[case_no % len(variants)], case_no + 100),
            _partial_expected(
                city_id=city_id,
                day=day,
                duration=old_duration,
                people=people,
                budget=new_budget,
                changed_slots=["budget_amount"],
                agents=["itinerary", "budget"],
                tools=["budget_calculator"],
            ),
        )
    variants = (
        f"请把{city}方案改成亲子、少走路的低强度版本，2026年10月{day}日出发、{old_duration}天、{people}个人和{budget}元预算都沿用上一轮；需要重新筛选适合家庭的点位。",
        f"{city}这次同行里有孩子，希望改成亲子友好、少走路的版本；日期2026年10月{day}日、{old_duration}天、{people}个人、预算{budget}元都保持不变。",
        f"保留{city}原来的时间和预算：2026年10月{day}日出发、{old_duration}天、{people}个人、{budget}元；请把景点和路线改成少走路、适合家庭的版本。",
        f"刚才的{city}方案强度有点高，请改成低强度亲子版，其他条件仍是2026年10月{day}日、{old_duration}天、{people}个人、{budget}元预算。",
        f"请局部改偏好：{city}行程要亲子、轻松、少步行；出发日期2026年10月{day}日，天数{old_duration}天，人数{people}个人，预算{budget}元不变。",
    )
    return (
        _with_context(variants[case_no % len(variants)], case_no + 100),
        _partial_expected(
            city_id=city_id,
            day=day,
            duration=old_duration,
            people=people,
            budget=budget,
            changed_slots=["traveler_group", "preferences", "special_requirements"],
            agents=["attraction", "itinerary", "budget"],
            tools=["poi_search", "budget_calculator"],
            extra_constraints={
                "traveler_group": "family",
                "preferences": ["family"],
                "special_requirements": ["low_intensity"],
            },
        ),
    )


def _trip_expected(
    *,
    city_id: str,
    start_date: str,
    duration: int,
    people: int,
    budget: int,
) -> dict[str, Any]:
    return {
        "task_type": "trip_planning",
        "required_tools": ALL_TOOLS,
        "accepted_agent_sets": [["attraction", "weather", "itinerary", "budget"]],
        "accepted_tool_sets": [ALL_TOOLS],
        "hard_constraints": {
            "destination": city_id,
            "start_date": start_date,
            "duration_days": duration,
            "people_count": people,
            "min_attractions": 3,
            "max_attractions": min(6, duration * 2),
            "max_pois_per_day": 2,
            "budget_limit": budget,
        },
    }


def _partial_expected(
    *,
    city_id: str,
    day: int,
    duration: int,
    people: int,
    budget: int,
    changed_slots: list[str],
    agents: list[str],
    tools: list[str],
    extra_constraints: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    constraints = {
        "destination": city_id,
        "start_date": f"2026-10-{day:02d}",
        "duration_days": duration,
        "people_count": people,
        "min_attractions": 3,
        "max_pois_per_day": 2,
        "budget_limit": budget,
    }
    constraints.update(extra_constraints or {})
    return {
        "task_type": "partial_replan",
        "changed_slots": changed_slots,
        "preserved_slots": [
            slot
            for slot in (
                "destination",
                "start_date",
                "duration_days",
                "people_count",
                "budget_amount",
            )
            if slot not in set(changed_slots)
        ],
        "required_tools": tools,
        "accepted_agent_sets": [agents],
        "accepted_tool_sets": [tools],
        "hard_constraints": constraints,
    }


def _case_task_distribution(cases: Sequence[Mapping[str, Any]]) -> Counter[str]:
    return Counter(_case_task_type(case) for case in cases)


def _unit_task_distribution(cases: Sequence[Mapping[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for case in cases:
        turns = case.get("turns")
        if isinstance(turns, list) and turns:
            for turn in turns:
                if isinstance(turn, Mapping):
                    counts[_task_type(turn)] += 1
        else:
            counts[_task_type(case)] += 1
    return counts


def _city_case_distribution(cases: Sequence[Mapping[str, Any]]) -> Counter[str]:
    data = get_fixed_tourism_data()
    counts: Counter[str] = Counter()
    for case in cases:
        task_type = _case_task_type(case)
        if task_type not in TOURISM_CASE_TASK_TYPES:
            continue
        target = _case_target_unit(case)
        city_id = data.resolve_city_id(_expected_city(target))
        if city_id:
            counts[city_id] += 1
    return counts


def _dataset_structure(cases: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    scenario_lengths = [
        len(case.get("turns") or [])
        for case in cases
        if isinstance(case.get("turns"), list) and case.get("turns")
    ]
    return {
        "case_count": len(cases),
        "single_turn_case_count": len(cases) - len(scenario_lengths),
        "scenario_case_count": len(scenario_lengths),
        "double_turn_scenario_count": sum(1 for length in scenario_lengths if length == 2),
        "non_double_turn_scenario_count": sum(1 for length in scenario_lengths if length != 2),
        "total_turn_count": sum(scenario_lengths) + len(cases) - len(scenario_lengths),
    }


def _case_task_type(case: Mapping[str, Any]) -> str:
    target = _case_target_unit(case)
    return _task_type(target)


def _case_target_unit(case: Mapping[str, Any]) -> Mapping[str, Any]:
    turns = case.get("turns")
    if isinstance(turns, list) and turns:
        for turn in turns:
            if isinstance(turn, Mapping) and turn.get("target_turn") is True:
                return turn
        for turn in reversed(turns):
            if isinstance(turn, Mapping):
                return turn
    return case


def _task_type(unit: Mapping[str, Any]) -> str:
    expected = unit.get("expected")
    if isinstance(expected, Mapping) and expected.get("task_type"):
        return str(expected["task_type"])
    return str(unit.get("task_type") or "unknown")


def _expected_city(unit: Mapping[str, Any]) -> Any:
    expected = unit.get("expected")
    if not isinstance(expected, Mapping):
        return None
    hard = expected.get("hard_constraints")
    if isinstance(hard, Mapping) and hard.get("destination"):
        return hard.get("destination")
    return expected.get("destination")


def _quality_duplicate_counts(quality_report: Mapping[str, Any]) -> dict[str, int]:
    coverage = _dict(quality_report.get("coverage"))
    return {
        "internal_duplicate_count": len(coverage.get("duplicate_visible_input_groups") or []),
        "cross_split_duplicate_count": len(
            coverage.get("cross_split_duplicate_visible_input_groups") or []
        ),
        "near_duplicate_count": len(coverage.get("near_duplicate_visible_input_pairs") or []),
    }


def _fixed_data_snapshot() -> dict[str, Any]:
    try:
        snapshot = validate_fixed_data_snapshot()
    except Exception as exc:
        return {"valid": False, "error": str(exc)}
    return {
        "valid": True,
        "schema_version": snapshot.get("schema_version"),
        "hash_strategy": snapshot.get("hash_strategy"),
        "file_count": snapshot.get("file_count"),
        "combined_sha256": snapshot.get("combined_sha256"),
        "city_ids": snapshot.get("city_ids"),
    }


def _city_for(index: int) -> str:
    return CITY_ORDER[index % len(CITY_ORDER)]


def _context(case_no: int) -> str:
    return _natural_context(case_no).rstrip("。")


_VISIBLE_EXPERIMENT_ARTIFACT_TERMS = (
    "样本编号",
    "实验标注",
    "固定离线资料",
    "工具调用",
    "多 Agent",
    "多Agent",
    "多角色旅游系统",
    "系统架构",
    "补充背景",
)


def _finalize_test_draft_cases(cases: list[dict[str, Any]]) -> None:
    """Apply formal-test visibility and label rules to generated cases."""
    sequence = 1
    for unit in _iter_case_units(cases):
        task_type = _task_type(unit)
        if "user_input" in unit:
            unit["user_input"] = _clean_visible_user_input(
                str(unit.get("user_input") or ""),
                sequence=sequence,
                task_type=task_type,
            )
            sequence += 1
        expected = unit.get("expected")
        if isinstance(expected, dict):
            _complete_tool_labels(expected)


def _complete_tool_labels(expected: dict[str, Any]) -> None:
    task_type = str(expected.get("task_type") or "")
    accepted_tool_sets = _as_tool_sets(expected.get("accepted_tool_sets"))
    if "required_tools" in expected:
        required_tools = _ordered_tools(expected.get("required_tools"))
    elif accepted_tool_sets:
        required_tools = _ordered_tools(accepted_tool_sets[0])
    else:
        required_tools = []
    if task_type in {"clarification", "general_chat"}:
        required_tools = []
    expected["required_tools"] = required_tools
    expected["forbidden_tools"] = _ordered_tools(
        expected.get("forbidden_tools")
        if "forbidden_tools" in expected
        else [tool for tool in ALL_TOOLS if tool not in set(required_tools)]
    )


def _clean_visible_user_input(text: str, *, sequence: int, task_type: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"补充背景：[^。！？!?]*(?:[。！？!?]|$)", "", cleaned)
    cleaned = re.sub(r"样本编号\s*[0-9０-９一二三四五六七八九十百零]+", "", cleaned)
    replacements = {
        "实验标注": "个人整理",
        "固定离线资料": "可靠资料",
        "工具调用": "信息依据",
        "多 Agent": "多角色",
        "多Agent": "多角色",
        " Agent ": " 助手 ",
        "旅游工具": "旅游查询功能",
        "调用任何": "启动任何",
        "调用景点": "查询景点",
        "调用天气": "查询天气",
        "测试一下": "试一下",
        "测试一个": "试一个",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip("。；;，, ")
    context = _natural_context(sequence, task_type=task_type)
    if context and context not in cleaned:
        cleaned = f"{cleaned}。{context}"
    return cleaned.strip()


def _natural_context(sequence: int, *, task_type: str = "") -> str:
    if task_type in {"clarification", "general_chat"}:
        openers = (
            "我现在只是想先把需求边界弄清楚",
            "我还没准备好让你直接做具体安排",
            "这条消息主要是想确认下一步该怎么说",
            "我希望你先用普通对话的方式回应",
            "我暂时不需要展开成正式旅行方案",
        )
        styles = (
            "请回答得简短一点。",
            "请先帮我理清需要补充的信息。",
            "请不要主动扩展成行程安排。",
            "请用容易转述给家人的话说明。",
            "请把重点放在我下一步该提供什么。",
        )
    else:
        openers = (
            "我比较在意少绕路",
            "同行者希望节奏稳一点",
            "我想减少临时变动",
            "这次更看重省心",
            "我希望选择理由清楚",
            "同行者不想走太多回头路",
            "我更喜欢稳妥可执行的建议",
            "请兼顾休息时间",
            "我希望建议别太赶",
            "请注意步行强度",
            "我想把安排转发给同行者",
            "请尽量避免信息堆得太满",
            "我更关心当天能不能顺利执行",
            "请把重要风险说在前面",
            "我希望保留一点机动时间",
        )
        styles = (
            "请先给结论再补充理由。",
            "请用分点方式说清楚。",
            "请把取舍原因讲明白。",
            "请少用夸张宣传语。",
            "请给出容易执行的说法。",
            "请提醒我哪些地方需要提前确认。",
            "请把不确定之处单独说明。",
            "请尽量用普通游客能看懂的话。",
            "请避免安排得过满。",
            "请把重点控制在真正有用的信息上。",
        )
    opener = openers[sequence % len(openers)]
    style = styles[(sequence // len(openers)) % len(styles)]
    return f"{opener}，{style}"


def _iter_case_units(cases: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for case in cases:
        turns = case.get("turns")
        if isinstance(turns, list) and turns:
            units.extend(turn for turn in turns if isinstance(turn, dict))
        else:
            units.append(case)
    return units


def _tool_label_completeness(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    missing_required: list[str] = []
    missing_forbidden: list[str] = []
    total = 0
    for unit in _iter_mapping_units(cases):
        total += 1
        expected = unit.get("expected")
        label = _unit_identity(unit)
        if not isinstance(expected, Mapping) or "required_tools" not in expected:
            missing_required.append(label)
        if not isinstance(expected, Mapping) or "forbidden_tools" not in expected:
            missing_forbidden.append(label)
    return {
        "unit_count": total,
        "required_tools_labeled_count": total - len(missing_required),
        "forbidden_tools_labeled_count": total - len(missing_forbidden),
        "missing_required_tools_count": len(missing_required),
        "missing_forbidden_tools_count": len(missing_forbidden),
        "missing_required_tools_units": missing_required[:20],
        "missing_forbidden_tools_units": missing_forbidden[:20],
    }


def _visible_artifact_report(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    leaking: list[dict[str, Any]] = []
    for unit in _iter_mapping_units(cases):
        text = str(unit.get("user_input") or "")
        terms = [
            term
            for term in _VISIBLE_EXPERIMENT_ARTIFACT_TERMS
            if term.lower() in text.lower()
        ]
        if terms:
            leaking.append({"label": _unit_identity(unit), "terms": terms})
    return {
        "policy": "formal visible user_input must not expose dataset IDs, sample IDs, annotation hints, tool labels, or multi-agent design",
        "forbidden_terms": list(_VISIBLE_EXPERIMENT_ARTIFACT_TERMS),
        "leaking_unit_count": len(leaking),
        "leaking_units": leaking[:20],
    }


def _semantic_template_duplicate_groups(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = {}
    for unit in _iter_mapping_units(cases):
        normalized = _semantic_template_text(str(unit.get("user_input") or ""))
        if not normalized:
            continue
        groups.setdefault(normalized, []).append(_unit_identity(unit))
    return [
        {
            "normalized_template": normalized,
            "count": len(labels),
            "example_labels": labels[:10],
        }
        for normalized, labels in sorted(groups.items())
        if len(labels) > 1
    ]


def _semantic_template_family_report(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[str]] = {}
    tourism_unit_count = 0
    for unit in _iter_mapping_units(cases):
        task_type = _task_type(unit)
        if task_type not in TOURISM_CASE_TASK_TYPES:
            continue
        tourism_unit_count += 1
        normalized = _semantic_template_family_text(str(unit.get("user_input") or ""))
        if not normalized:
            continue
        groups.setdefault(normalized, []).append(_unit_identity(unit))

    sorted_groups = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    family_count = len(groups)
    max_family_size = max((len(labels) for labels in groups.values()), default=0)
    return {
        "policy": (
            "Count tourism-task wording families after removing city/date/number "
            "values and generated review-context suffixes."
        ),
        "tourism_unit_count": tourism_unit_count,
        "min_tourism_template_family_count": MIN_TOURISM_TEMPLATE_FAMILY_COUNT,
        "max_allowed_tourism_template_family_size": MAX_TOURISM_TEMPLATE_FAMILY_SIZE,
        "tourism_template_family_count": family_count,
        "max_tourism_template_family_size": max_family_size,
        "diversity_sufficient": family_count >= MIN_TOURISM_TEMPLATE_FAMILY_COUNT,
        "family_size_below_limit": max_family_size <= MAX_TOURISM_TEMPLATE_FAMILY_SIZE,
        "largest_families": [
            {
                "normalized_template": normalized,
                "count": len(labels),
                "example_labels": labels[:10],
            }
            for normalized, labels in sorted_groups[:20]
        ],
    }


def _semantic_template_text(text: str) -> str:
    normalized = str(text or "").casefold()
    for city in CITY_NAMES.values():
        normalized = normalized.replace(city, "<city>")
    for city_id in CITY_ORDER:
        normalized = normalized.replace(city_id, "<city>")
    normalized = re.sub(r"20[0-9]{2}年[0-9]{1,2}月[0-9]{1,2}日", "<date>", normalized)
    normalized = re.sub(r"[0-9０-９]+(?:\.[0-9０-９]+)?", "<num>", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"[，。！？、；：,.!?;:\"'（）()《》【】\[\]{}<>]+", "", normalized)
    return normalized


def _semantic_template_family_text(text: str) -> str:
    normalized = _strip_generated_review_context(str(text or "")).casefold()
    for city in CITY_NAMES.values():
        normalized = normalized.replace(city, "<city>")
    for city_id in CITY_ORDER:
        normalized = normalized.replace(city_id, "<city>")
    normalized = re.sub(r"20[0-9]{2}年[0-9]{1,2}月[0-9]{1,2}日", "<date>", normalized)
    normalized = re.sub(r"[0-9０-９]+(?:\.[0-9０-９]+)?", "<num>", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"[，。！？、；：,.!?;:\"'（）()《》【】\[\]{}<>]+", "", normalized)
    return normalized


def _strip_generated_review_context(text: str) -> str:
    stripped = str(text or "").strip()
    generated_context_starts = (
        "我现在只是想先把需求边界弄清楚",
        "我还没准备好让你直接做具体安排",
        "这条消息主要是想确认下一步该怎么说",
        "我希望你先用普通对话的方式回应",
        "我暂时不需要展开成正式旅行方案",
        "我比较在意少绕路",
        "同行者希望节奏稳一点",
        "我想减少临时变动",
        "这次更看重省心",
        "我希望选择理由清楚",
        "同行者不想走太多回头路",
        "我更喜欢稳妥可执行的建议",
        "请兼顾休息时间",
        "我希望建议别太赶",
        "请注意步行强度",
        "我想把安排转发给同行者",
        "请尽量避免信息堆得太满",
        "我更关心当天能不能顺利执行",
        "请把重要风险说在前面",
        "我希望保留一点机动时间",
    )
    for marker in generated_context_starts:
        marker_index = stripped.find(marker)
        if marker_index > 0:
            return stripped[:marker_index].rstrip("。；;，, ")
    return stripped


def _iter_mapping_units(cases: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    units: list[Mapping[str, Any]] = []
    for case in cases:
        turns = case.get("turns")
        if isinstance(turns, list) and turns:
            for turn in turns:
                if isinstance(turn, Mapping):
                    unit = dict(turn)
                    unit.setdefault("case_id", case.get("case_id"))
                    units.append(unit)
        else:
            units.append(case)
    return units


def _unit_identity(unit: Mapping[str, Any]) -> str:
    case_id = str(unit.get("case_id") or "")
    turn_id = str(unit.get("turn_id") or "")
    if case_id and turn_id:
        return f"{case_id}/{turn_id}"
    return case_id or turn_id or "unit"


def _as_tool_sets(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    if not value:
        return []
    if all(not isinstance(item, list) for item in value):
        return [_ordered_tools(value)]
    return [_ordered_tools(item) for item in value if isinstance(item, list)]


def _ordered_tools(value: Any) -> list[str]:
    values = {str(item) for item in _as_list(value) if str(item)}
    return [tool for tool in ALL_TOOLS if tool in values]


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current
