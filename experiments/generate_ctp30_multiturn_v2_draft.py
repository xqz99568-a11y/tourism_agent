"""Generate the Route-B CTP30-v2 multi-turn sealed-validation draft.

This script creates review artifacts only.  The generated dataset is not wired
into the formal runner until the human review is complete and a later freeze
step renames/promotes it.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT_DIR = ROOT / "experiments" / "generated"
DATASET_PATH = OUT_DIR / "ctp30_multiturn_v2_draft.json"
REVIEW_PATH = OUT_DIR / "ctp30_multiturn_v2_human_review.md"
AUDIT_JSON_PATH = OUT_DIR / "ctp30_multiturn_v2_auto_audit.json"
AUDIT_MD_PATH = OUT_DIR / "ctp30_multiturn_v2_auto_audit.md"

REFERENCE_DATE = date(2026, 8, 6)
TOMORROW = REFERENCE_DATE + timedelta(days=1)
DAY_AFTER_TOMORROW = REFERENCE_DATE + timedelta(days=2)

NO_TOOLS = ["poi_search", "weather_query", "budget_calculator"]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    weather_manifest = _read_json(ROOT / "data" / "weather_snapshot" / "qweather_v1" / "snapshot_manifest.json")
    rail_manifest = _read_json(ROOT / "data" / "intercity_transport" / "snapshot_manifest.json")
    rail_table = _read_json(ROOT / "data" / "intercity_transport" / "rail_second_class_v1.json")
    fare_map = {
        (str(item["origin"]), str(item["destination"])): float(item["one_way_fare_per_person_cny"])
        for item in rail_table.get("routes", [])
    }
    cases = _build_cases(weather_manifest=weather_manifest, rail_manifest=rail_manifest, fare_map=fare_map)
    document = {
        "schema_version": "ctp-benchmark-v2",
        "dataset_id": "ctp30_multiturn_validation_v2_draft",
        "dataset_version": "2026-08-28-route-b-task1-expression-revision",
        "dataset_role": "sealed_multiturn_validation_draft_for_human_review",
        "split": "sealed_validation_candidate",
        "language": "zh-CN",
        "case_count": len(cases),
        "turn_count": sum(len(case["turns"]) for case in cases),
        "reference_date": REFERENCE_DATE.isoformat(),
        "description": (
            "Route-B draft CTP30-v2 set. Each case is a true two-turn scenario. "
            "Turn 1 creates the method-local context; turn 2 is the primary sealed "
            "multi-turn target. This draft must be manually reviewed before freeze."
        ),
        "weather_snapshot": _snapshot_summary(weather_manifest),
        "intercity_transport_snapshot": _intercity_summary(rail_manifest),
        "annotation_policy": {
            "visible_language": "zh-CN",
            "gold_visible_to_generation": False,
            "slot_gold_consistency_required": True,
            "changed_slot_current_utterance_required": True,
            "preserved_slot_previous_state_required": True,
            "fixed_offline_city_only": True,
            "recommended_formal_task_coverage_required": True,
            "single_annotator_with_auto_rule_audit": True,
            "human_review_required_before_freeze": True,
            "statistical_unit": "case_id",
            "actual_turn_unit": "scenario turn",
            "primary_evaluation_turn": "t2",
            "day8_weather_policy": (
                "Explicit relative dates are resolved against 2026-08-06 and must use "
                "the frozen QWeather snapshot. No-date trip plans must not invent "
                "weather and must remind users to check weather before departure."
            ),
            "intercity_budget_policy": (
                "Supported origin-destination routes use frozen adult second-class "
                "G/C/D-train round-trip fares. Missing or unsupported origin must not "
                "guess intercity cost."
            ),
        },
        "claim_policy": {
            "draft_only": True,
            "used_for_development_tuning": False,
            "allowed_methods_after_freeze": ["fixed_multi_agent", "adaptive_multi_agent"],
            "must_not_run_before_human_confirmation": True,
            "paper_wording_required": (
                "论文中应说明 CTP30-v2 由单人标注并经自动规则审计；不得声称多人一致性。"
            ),
        },
        "quota_policy": {
            "scenario_case_count": 30,
            "scenario_turn_count": 60,
            "total_turn_count": 60,
            "first_turn_role": "context_building",
            "target_turn_role": "primary_multi_turn_validation",
            "target_turn_task_quotas": _target_task_quotas(cases),
        },
        "cases": cases,
    }
    audit = _build_audit(document)
    _write_json(DATASET_PATH, document)
    _write_json(AUDIT_JSON_PATH, audit)
    REVIEW_PATH.write_text(_render_review(document, audit), encoding="utf-8")
    AUDIT_MD_PATH.write_text(_render_audit_md(audit), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": audit["status"],
                "dataset": DATASET_PATH.as_posix(),
                "human_review": REVIEW_PATH.as_posix(),
                "audit_json": AUDIT_JSON_PATH.as_posix(),
                "audit_md": AUDIT_MD_PATH.as_posix(),
                "case_count": document["case_count"],
                "turn_count": document["turn_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if audit["status"] == "passed" else 1


def _build_cases(
    *,
    weather_manifest: Mapping[str, Any],
    rail_manifest: Mapping[str, Any],
    fare_map: Mapping[tuple[str, str], float],
) -> list[dict[str, Any]]:
    ctx = {"weather_manifest": weather_manifest, "rail_manifest": rail_manifest, "fare_map": fare_map}
    return [
        _scenario(
            "ctp30_mt_v2_001",
            "预算变化｜杭州｜仅重算预算",
            _trip_turn(
                "我和朋友想去杭州玩3天，日期还没定，两个人总预算最多5500元，想轻松一点，先帮我安排一版。",
                destination="hangzhou",
                duration_days=3,
                people_count=2,
                budget_amount=5500,
                special_requirements=["low_intensity"],
                ctx=ctx,
            ),
            _partial_turn(
                "预算上限调整为4200元，目的地、行程天数和出行人数均保持不变，只需要重新判断费用是否够用。",
                changed_slots=["budget_amount"],
                preserved_slots=["destination", "duration_days", "people_count"],
                slots={"destination": "hangzhou", "duration_days": 3, "people_count": 2, "budget_amount": 4200},
                agents=["budget"],
                tools=["budget_calculator"],
                policy="budget_only",
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_002",
            "预算变化｜北京｜含城际交通",
            _trip_turn(
                "我从上海出发去北京玩2天，一个人，日期还没定，总预算最多6500元，想多看看历史文化景点。",
                origin="shanghai",
                destination="beijing",
                duration_days=2,
                people_count=1,
                budget_amount=6500,
                preferences=["history_culture"],
                ctx=ctx,
            ),
            _partial_turn(
                "总预算调整为5000元，出发地、目的地、行程天数和出行人数均保持不变，只重新计算预算。",
                changed_slots=["budget_amount"],
                preserved_slots=["origin", "destination", "duration_days", "people_count"],
                slots={"origin": "shanghai", "destination": "beijing", "duration_days": 2, "people_count": 1, "budget_amount": 5000, "preferences": ["history_culture"]},
                agents=["budget"],
                tools=["budget_calculator"],
                policy="budget_only",
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_003",
            "预算变化｜深圳｜保留天气证据",
            _trip_turn(
                "明天从广州去深圳玩2天，亲子两个人出行，总预算最多6200元，帮我安排得轻松一点。",
                origin="guangzhou",
                destination="shenzhen",
                start_date=TOMORROW.isoformat(),
                duration_days=2,
                people_count=2,
                budget_amount=6200,
                traveler_group="family",
                special_requirements=["low_intensity"],
                ctx=ctx,
            ),
            _partial_turn(
                "预算上限调整为5200元，出发时间、出发地、目的地、行程天数和出行人数均保持不变，只更新预算判断。",
                changed_slots=["budget_amount"],
                preserved_slots=["origin", "destination", "start_date", "duration_days", "people_count"],
                slots={"origin": "guangzhou", "destination": "shenzhen", "start_date": TOMORROW.isoformat(), "duration_days": 2, "people_count": 2, "budget_amount": 5200, "traveler_group": "family", "special_requirements": ["low_intensity"]},
                agents=["budget"],
                tools=["budget_calculator"],
                policy="budget_only_weather_preserved",
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_004",
            "人数变化｜桂林｜重排行程预算",
            _trip_turn(
                "我想和朋友去桂林玩3天，日期还没定，两个人，总预算最多5000元，希望山水风景多一点。",
                destination="guilin",
                duration_days=3,
                people_count=2,
                budget_amount=5000,
                preferences=["nature"],
                ctx=ctx,
            ),
            _partial_turn(
                "出行人数调整为3个人，目的地、行程天数和预算上限均保持不变，请重新安排路线和费用。",
                changed_slots=["people_count"],
                preserved_slots=["destination", "duration_days", "budget_amount"],
                slots={"destination": "guilin", "duration_days": 3, "people_count": 3, "budget_amount": 5000, "preferences": ["nature"]},
                agents=["itinerary", "budget"],
                tools=["budget_calculator"],
                policy="people_change_reuse_attractions",
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_005",
            "人数变化｜西安｜保留日期天气",
            _trip_turn(
                "后天我想带长辈去西安玩3天，一共3个人，总预算最多7600元，历史文化景点多一些，尽量少走路。",
                destination="xian",
                start_date=DAY_AFTER_TOMORROW.isoformat(),
                duration_days=3,
                people_count=3,
                budget_amount=7600,
                traveler_group="senior",
                preferences=["history_culture"],
                special_requirements=["low_intensity"],
                ctx=ctx,
            ),
            _partial_turn(
                "出行人数调整为4个人，仍然是带长辈并且希望少走路，出发时间、目的地、行程天数和预算上限均保持不变，请重新安排路线和预算。",
                changed_slots=["people_count"],
                preserved_slots=["destination", "start_date", "duration_days", "budget_amount"],
                slots={"destination": "xian", "start_date": DAY_AFTER_TOMORROW.isoformat(), "duration_days": 3, "people_count": 4, "budget_amount": 7600, "traveler_group": "senior", "preferences": ["history_culture"], "special_requirements": ["low_intensity"]},
                agents=["itinerary", "budget"],
                tools=["budget_calculator"],
                policy="people_change_reuse_attractions_weather",
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_006",
            "补充出发地｜杭州｜仅重算城际预算",
            _trip_turn(
                "我想去杭州玩2天，日期还没定，两个人，总预算最多3600元，先按没有出发地的情况做当地行程。",
                destination="hangzhou",
                duration_days=2,
                people_count=2,
                budget_amount=3600,
                ctx=ctx,
            ),
            _partial_turn(
                "我们从南京出发，目的地、行程天数、出行人数和预算上限均保持不变，路线不用重排，只把高铁大交通算进预算。",
                changed_slots=["origin"],
                preserved_slots=["destination", "duration_days", "people_count", "budget_amount"],
                slots={"origin": "nanjing", "destination": "hangzhou", "duration_days": 2, "people_count": 2, "budget_amount": 3600},
                agents=["budget"],
                tools=["budget_calculator"],
                policy="origin_changed_budget_only",
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_007",
            "补充出发地｜桂林｜重新安排行程",
            _trip_turn(
                "我想去桂林看山水，日期还没定，两个人玩3天，总预算最多5000元，请先按轻松少走路的节奏安排。",
                destination="guilin",
                duration_days=3,
                people_count=2,
                budget_amount=5000,
                special_requirements=["low_intensity"],
                ctx=ctx,
            ),
            _partial_turn(
                "我们从广州出发，目的地、行程天数、出行人数和预算上限均保持不变，想重新安排行程。",
                changed_slots=["origin"],
                preserved_slots=["destination", "duration_days", "people_count", "budget_amount"],
                slots={"origin": "guangzhou", "destination": "guilin", "duration_days": 3, "people_count": 2, "budget_amount": 5000, "special_requirements": ["low_intensity"]},
                agents=["itinerary", "budget"],
                tools=["budget_calculator"],
                policy="origin_replan_reuse_attractions",
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_008",
            "目的地变化｜深圳改桂林｜无日期",
            _trip_turn(
                "我想去深圳玩2天，日期还没定，两个人，总预算最多4800元，想安排得轻松一点。",
                destination="shenzhen",
                duration_days=2,
                people_count=2,
                budget_amount=4800,
                special_requirements=["low_intensity"],
                ctx=ctx,
            ),
            _partial_turn(
                "目的地调整为桂林，行程天数、出行人数和预算上限均保持不变，请重新推荐景点并安排完整路线。",
                changed_slots=["destination"],
                preserved_slots=["duration_days", "people_count", "budget_amount"],
                slots={"destination": "guilin", "duration_days": 2, "people_count": 2, "budget_amount": 4800, "special_requirements": ["low_intensity"]},
                agents=["attraction", "itinerary", "budget"],
                tools=["poi_search", "budget_calculator"],
                policy="destination_change_no_weather",
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_009",
            "目的地变化｜杭州改西安｜保留明天",
            _trip_turn(
                "我明天想去杭州玩2天，两个人，总预算最多4600元，帮我把景点、天气和预算都安排一下。",
                destination="hangzhou",
                start_date=TOMORROW.isoformat(),
                duration_days=2,
                people_count=2,
                budget_amount=4600,
                ctx=ctx,
            ),
            _partial_turn(
                "目的地调整为西安，出发时间、行程天数、出行人数和预算上限均保持不变，请重新做完整安排。",
                changed_slots=["destination"],
                preserved_slots=["start_date", "duration_days", "people_count", "budget_amount"],
                slots={"destination": "xian", "start_date": TOMORROW.isoformat(), "duration_days": 2, "people_count": 2, "budget_amount": 4600},
                agents=["attraction", "weather", "itinerary", "budget"],
                tools=["poi_search", "weather_query", "budget_calculator"],
                policy="destination_change_weather",
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_010",
            "天数变化｜北京｜无日期",
            _trip_turn(
                "我想去北京玩2天，日期还没定，两个人，总预算最多5200元，经典景点为主，节奏轻松少走路。",
                destination="beijing",
                duration_days=2,
                people_count=2,
                budget_amount=5200,
                special_requirements=["low_intensity"],
                ctx=ctx,
            ),
            _partial_turn(
                "行程天数调整为3天，目的地、出行人数和预算上限均保持不变，请重新安排每天路线和费用。",
                changed_slots=["duration_days"],
                preserved_slots=["destination", "people_count", "budget_amount"],
                slots={"destination": "beijing", "duration_days": 3, "people_count": 2, "budget_amount": 5200, "special_requirements": ["low_intensity"]},
                agents=["itinerary", "budget"],
                tools=["budget_calculator"],
                policy="duration_change_no_weather",
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_011",
            "天数变化｜深圳｜保留明天",
            _trip_turn(
                "明天想去深圳玩2天，两个人，总预算最多5600元，希望亲子友好一点。",
                destination="shenzhen",
                start_date=TOMORROW.isoformat(),
                duration_days=2,
                people_count=2,
                budget_amount=5600,
                traveler_group="family",
                ctx=ctx,
            ),
            _partial_turn(
                "行程天数调整为3天，出发时间、目的地、出行人数和预算上限均保持不变，请重新安排路线，并更新天气和预算。",
                changed_slots=["duration_days"],
                preserved_slots=["destination", "start_date", "people_count", "budget_amount"],
                slots={"destination": "shenzhen", "start_date": TOMORROW.isoformat(), "duration_days": 3, "people_count": 2, "budget_amount": 5600, "traveler_group": "family"},
                agents=["weather", "itinerary", "budget"],
                tools=["weather_query", "budget_calculator"],
                policy="duration_change_weather",
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_012",
            "日期变化｜西安｜新增天气",
            _trip_turn(
                "我想去西安玩3天，日期还没定，两个人，总预算最多5200元，希望历史文化景点多一点。",
                destination="xian",
                duration_days=3,
                people_count=2,
                budget_amount=5200,
                preferences=["history_culture"],
                ctx=ctx,
            ),
            _partial_turn(
                "出发时间调整为后天，目的地、行程天数、出行人数和预算上限均保持不变，请加入天气后重新安排。",
                changed_slots=["start_date"],
                preserved_slots=["destination", "duration_days", "people_count", "budget_amount"],
                slots={"destination": "xian", "start_date": DAY_AFTER_TOMORROW.isoformat(), "duration_days": 3, "people_count": 2, "budget_amount": 5200, "preferences": ["history_culture"]},
                agents=["weather", "itinerary", "budget"],
                tools=["weather_query", "budget_calculator"],
                policy="start_date_added_weather",
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_013",
            "偏好变化｜杭州｜改历史文化",
            _trip_turn(
                "我想去杭州玩3天，日期还没定，两个人，总预算最多5200元，先按自然风景和轻松节奏安排。",
                destination="hangzhou",
                duration_days=3,
                people_count=2,
                budget_amount=5200,
                preferences=["nature"],
                special_requirements=["low_intensity"],
                ctx=ctx,
            ),
            _partial_turn(
                "游玩偏好调整为历史文化和博物馆，目的地、行程天数、出行人数和预算上限均保持不变，请重新推荐景点并安排路线。",
                changed_slots=["preferences"],
                preserved_slots=["destination", "duration_days", "people_count", "budget_amount"],
                slots={"destination": "hangzhou", "duration_days": 3, "people_count": 2, "budget_amount": 5200, "preferences": ["history_culture"], "special_requirements": ["low_intensity"]},
                agents=["attraction", "itinerary", "budget"],
                tools=["poi_search", "budget_calculator"],
                policy="preference_change_no_weather",
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_014",
            "人群变化｜北京｜改带父母",
            _trip_turn(
                "我想去北京玩3天，日期还没定，两个人，总预算最多6000元，经典景点为主。",
                destination="beijing",
                duration_days=3,
                people_count=2,
                budget_amount=6000,
                ctx=ctx,
            ),
            _partial_turn(
                "出行人数调整为3个人，并且改为带老人出行，希望少走路；目的地、行程天数和预算上限均保持不变。",
                changed_slots=["people_count", "traveler_group", "special_requirements"],
                preserved_slots=["destination", "duration_days", "budget_amount"],
                slots={"destination": "beijing", "duration_days": 3, "people_count": 3, "budget_amount": 6000, "traveler_group": "senior", "special_requirements": ["low_intensity"]},
                agents=["attraction", "itinerary", "budget"],
                tools=["poi_search", "budget_calculator"],
                policy="traveler_group_change",
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_015",
            "无变化复用｜桂林｜重复上一轮",
            _trip_turn(
                "我想去桂林玩2天，日期还没定，两个人，总预算最多4200元，想看山水，但节奏希望轻松一点。",
                destination="guilin",
                duration_days=2,
                people_count=2,
                budget_amount=4200,
                preferences=["nature"],
                special_requirements=["low_intensity"],
                ctx=ctx,
            ),
            _partial_turn(
                "就按上一轮方案，目的地、行程天数、出行人数和预算上限均保持不变，请再帮我整理一遍。",
                changed_slots=[],
                preserved_slots=["destination", "duration_days", "people_count", "budget_amount"],
                slots={"destination": "guilin", "duration_days": 2, "people_count": 2, "budget_amount": 4200, "preferences": ["nature"], "special_requirements": ["low_intensity"]},
                agents=[],
                tools=[],
                policy="no_change_reuse",
                ctx=ctx,
                no_change_reuse=True,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_016",
            "天气调整｜深圳｜第一天下雨",
            _trip_turn(
                "明天想去深圳玩2天，亲子两个人出行，总预算最多5800元，想安排一个室内外结合的轻松行程。",
                destination="shenzhen",
                start_date=TOMORROW.isoformat(),
                duration_days=2,
                people_count=2,
                budget_amount=5800,
                traveler_group="family",
                special_requirements=["low_intensity", "indoor_preferred"],
                ctx=ctx,
            ),
            _weather_adjustment_turn(
                "如果明天下午下雨，出发时间、目的地、行程天数、出行人数和预算上限均保持不变，请把第一天户外项目往后挪，并顺便更新预算。",
                slots={"destination": "shenzhen", "start_date": TOMORROW.isoformat(), "duration_days": 2, "people_count": 2, "budget_amount": 5800, "traveler_group": "family", "special_requirements": ["low_intensity", "indoor_preferred"], "weather_scenario": "rain"},
                weather_change={"scenario_type": "rain", "affected_days": [1], "description": "明天下午下雨"},
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_017",
            "天气调整｜桂林｜第二天下雨",
            _trip_turn(
                "后天想去桂林玩3天，两个人，总预算最多5200元，想多看看山水风景。",
                destination="guilin",
                start_date=DAY_AFTER_TOMORROW.isoformat(),
                duration_days=3,
                people_count=2,
                budget_amount=5200,
                preferences=["nature"],
                ctx=ctx,
            ),
            _weather_adjustment_turn(
                "如果第2天下雨，出发时间、目的地、行程天数、出行人数和预算上限均保持不变，请把坐船和户外山水安排调整得保守一点，并重新计算费用。",
                slots={"destination": "guilin", "start_date": DAY_AFTER_TOMORROW.isoformat(), "duration_days": 3, "people_count": 2, "budget_amount": 5200, "preferences": ["nature"], "weather_scenario": "rain"},
                weather_change={"scenario_type": "rain", "affected_days": [2], "description": "第2天下雨"},
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_018",
            "天气调整｜杭州｜第二天高温",
            _trip_turn(
                "明天想去杭州玩2天，两个人，总预算最多5000元，想轻松看看自然风景和博物馆。",
                destination="hangzhou",
                start_date=TOMORROW.isoformat(),
                duration_days=2,
                people_count=2,
                budget_amount=5000,
                preferences=["history_culture", "nature"],
                special_requirements=["low_intensity"],
                ctx=ctx,
            ),
            _weather_adjustment_turn(
                "如果第二天高温，出发时间、目的地、行程天数、出行人数和预算上限均保持不变，请尽量减少室外暴晒项目，并重新计算预算。",
                slots={"destination": "hangzhou", "start_date": TOMORROW.isoformat(), "duration_days": 2, "people_count": 2, "budget_amount": 5000, "preferences": ["history_culture", "nature"], "special_requirements": ["low_intensity"], "weather_scenario": "high_temperature"},
                weather_change={"scenario_type": "high_temperature", "affected_days": [2], "description": "第二天高温"},
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_019",
            "天气调整｜北京｜第一天降温",
            _trip_turn(
                "后天想去北京玩2天，两个人，总预算最多5400元，经典文化景点为主。",
                destination="beijing",
                start_date=DAY_AFTER_TOMORROW.isoformat(),
                duration_days=2,
                people_count=2,
                budget_amount=5400,
                preferences=["history_culture"],
                ctx=ctx,
            ),
            _weather_adjustment_turn(
                "如果第一天降温比较明显，出发时间、目的地、行程天数、出行人数和预算上限均保持不变，请把露天排队时间压缩一下，并更新预算。",
                slots={"destination": "beijing", "start_date": DAY_AFTER_TOMORROW.isoformat(), "duration_days": 2, "people_count": 2, "budget_amount": 5400, "preferences": ["history_culture"], "weather_scenario": "low_temperature"},
                weather_change={"scenario_type": "low_temperature", "affected_days": [1], "description": "第一天降温"},
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_020",
            "天气调整｜西安｜旅途中有雨",
            _trip_turn(
                "明天想去西安玩3天，两个人，总预算最多5600元，历史文化和博物馆多一些。",
                destination="xian",
                start_date=TOMORROW.isoformat(),
                duration_days=3,
                people_count=2,
                budget_amount=5600,
                preferences=["history_culture"],
                ctx=ctx,
            ),
            _weather_adjustment_turn(
                "如果旅途中有雨，出发时间、目的地、行程天数、出行人数和预算上限均保持不变，请减少第2天和第3天的室外安排，并重新核算预算。",
                slots={"destination": "xian", "start_date": TOMORROW.isoformat(), "duration_days": 3, "people_count": 2, "budget_amount": 5600, "preferences": ["history_culture"], "weather_scenario": "rain"},
                weather_change={"scenario_type": "rain", "affected_days": [2, 3], "description": "第2天和第3天有雨"},
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_021",
            "天气调整｜深圳｜第二天高温",
            _trip_turn(
                "明天从广州去深圳玩3天，两个人，总预算最多6800元，想要轻松一点的亲子路线。",
                origin="guangzhou",
                destination="shenzhen",
                start_date=TOMORROW.isoformat(),
                duration_days=3,
                people_count=2,
                budget_amount=6800,
                traveler_group="family",
                special_requirements=["low_intensity"],
                ctx=ctx,
            ),
            _weather_adjustment_turn(
                "如果第二天高温暴晒，出发时间、出发地、目的地、行程天数、出行人数和预算上限均保持不变，请把室外活动调整到早晚。",
                slots={"origin": "guangzhou", "destination": "shenzhen", "start_date": TOMORROW.isoformat(), "duration_days": 3, "people_count": 2, "budget_amount": 6800, "traveler_group": "family", "special_requirements": ["low_intensity"], "weather_scenario": "high_temperature"},
                weather_change={"scenario_type": "high_temperature", "affected_days": [2], "description": "第二天高温暴晒"},
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_022",
            "预算追问｜桂林｜只问够不够",
            _trip_turn(
                "我想去桂林玩3天，两个人，日期还没定，总预算最多4600元，先给我安排一条轻松的山水路线。",
                destination="guilin",
                duration_days=3,
                people_count=2,
                budget_amount=4600,
                preferences=["nature"],
                special_requirements=["low_intensity"],
                ctx=ctx,
            ),
            _budget_query_turn(
                "行程先不改，目的地、行程天数、出行人数和预算上限均保持不变，只帮我重新说明预算够不够。",
                slots={"destination": "guilin", "duration_days": 3, "people_count": 2, "budget_amount": 4600, "preferences": ["nature"], "special_requirements": ["low_intensity"]},
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_023",
            "预算追问｜北京｜含广州出发",
            _trip_turn(
                "我从广州出发去北京玩4天，两个人，日期还没定，总预算最多12000元，经典景点为主。",
                origin="guangzhou",
                destination="beijing",
                duration_days=4,
                people_count=2,
                budget_amount=12000,
                ctx=ctx,
            ),
            _budget_query_turn(
                "路线先不改，出发地、目的地、行程天数、出行人数和预算上限均保持不变，只重新列出总费用和人均费用。",
                slots={"origin": "guangzhou", "destination": "beijing", "duration_days": 4, "people_count": 2, "budget_amount": 12000},
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_024",
            "预算追问｜杭州｜只算当地",
            _trip_turn(
                "我想去杭州玩3天，两个人，日期还没定，总预算最多4800元，先安排一版当地行程。",
                destination="hangzhou",
                duration_days=3,
                people_count=2,
                budget_amount=4800,
                ctx=ctx,
            ),
            _budget_query_turn(
                "如果只算目的地当地吃住行和门票，不含大交通，目的地、行程天数和出行人数均保持不变，大概需要多少钱？",
                slots={"destination": "hangzhou", "duration_days": 3, "people_count": 2, "budget_amount": 4800},
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_025",
            "预算追问｜西安｜分项费用",
            _trip_turn(
                "我想带老人去西安玩2天，一共3个人，日期还没定，总预算最多6000元，节奏希望轻松一点。",
                destination="xian",
                duration_days=2,
                people_count=3,
                budget_amount=6000,
                traveler_group="senior",
                special_requirements=["low_intensity"],
                ctx=ctx,
            ),
            _budget_query_turn(
                "行程不用重排，目的地、行程天数、出行人数和预算上限均保持不变，只把住宿、餐饮、门票和市内交通费用分项列清楚。",
                slots={"destination": "xian", "duration_days": 2, "people_count": 3, "budget_amount": 6000, "traveler_group": "senior", "special_requirements": ["low_intensity"]},
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_026",
            "天气追问｜杭州｜明后天",
            _trip_turn(
                "我想去杭州玩3天，两个人，日期还没定，总预算最多5200元，先安排一版轻松路线。",
                destination="hangzhou",
                duration_days=3,
                people_count=2,
                budget_amount=5200,
                special_requirements=["low_intensity"],
                ctx=ctx,
            ),
            _weather_query_turn(
                "那只帮我查一下杭州明天和后天的天气，路线先不用改。",
                slots={"destination": "hangzhou", "start_date": TOMORROW.isoformat(), "duration_days": 2, "people_count": 2, "budget_amount": 5200, "special_requirements": ["low_intensity"]},
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_027",
            "天气追问｜深圳｜后天起三天",
            _trip_turn(
                "我想去深圳玩3天，两个人，日期还没定，总预算最多6200元，亲子路线为主。",
                destination="shenzhen",
                duration_days=3,
                people_count=2,
                budget_amount=6200,
                traveler_group="family",
                ctx=ctx,
            ),
            _weather_query_turn(
                "只帮我查一下深圳后天开始未来3天的天气，看看适不适合安排户外活动。",
                slots={"destination": "shenzhen", "start_date": DAY_AFTER_TOMORROW.isoformat(), "duration_days": 3, "people_count": 2, "budget_amount": 6200, "traveler_group": "family"},
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_028",
            "天气追问｜北京｜一个月后超范围",
            _trip_turn(
                "我想去北京玩3天，两个人，日期还没确定，总预算最多6200元，历史文化景点为主。",
                destination="beijing",
                duration_days=3,
                people_count=2,
                budget_amount=6200,
                preferences=["history_culture"],
                ctx=ctx,
            ),
            _weather_query_turn(
                "如果一个月后去北京玩3天，现在能查到那几天的天气预报吗？这次只查天气。",
                slots={"destination": "beijing", "start_date": "2026-09-06", "duration_days": 3, "people_count": 2, "budget_amount": 6200, "preferences": ["history_culture"]},
                ctx=ctx,
            ),
        ),
        _scenario(
            "ctp30_mt_v2_029",
            "景点追问｜西安｜只要室内景点",
            _trip_turn(
                "我想去西安玩3天，两个人，日期还没定，总预算最多5600元，历史文化景点多一些。",
                destination="xian",
                duration_days=3,
                people_count=2,
                budget_amount=5600,
                preferences=["history_culture"],
                ctx=ctx,
            ),
            _attraction_turn(
                "行程先不用重排，只给我再推荐4个西安室内或博物馆类景点。",
                slots={"destination": "xian", "duration_days": 3, "people_count": 2, "budget_amount": 5600, "preferences": ["history_culture", "indoor"], "special_requirements": ["indoor_preferred"]},
            ),
        ),
        _scenario(
            "ctp30_mt_v2_030",
            "闲聊到澄清｜缺核心信息",
            _chat_turn("你好，我先随便看看，想了解一下你能不能帮我做旅游计划。"),
            _clarification_turn(
                "那我想做一份完整行程，但还没想好去哪，也没定玩几天、几个人去，你先问我需要补充什么。",
                missing_slots=["destination", "duration_days", "people_count"],
            ),
        ),
    ]


def _scenario(case_id: str, title: str, t1: Mapping[str, Any], t2: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "scenario_id": case_id,
        "title": title,
        "evaluation_scope": "target_turn_only_after_freeze",
        "primary_turn_id": "t2",
        "check": "第一轮真实运行建立该方法自己的状态；第二轮只允许读取同一方法上一轮状态，不注入金标状态。",
        "turns": [dict(t1, turn_id="t1"), dict(t2, turn_id="t2")],
    }


def _trip_turn(
    user_input: str,
    *,
    destination: str,
    duration_days: int,
    people_count: int,
    budget_amount: int,
    ctx: Mapping[str, Any],
    origin: str | None = None,
    start_date: str | None = None,
    traveler_group: str | None = None,
    preferences: list[str] | None = None,
    special_requirements: list[str] | None = None,
) -> dict[str, Any]:
    slots = _slots(
        origin=origin,
        destination=destination,
        start_date=start_date,
        duration_days=duration_days,
        people_count=people_count,
        budget_amount=budget_amount,
        traveler_group=traveler_group,
        preferences=preferences,
        special_requirements=special_requirements,
    )
    agents = ["attraction", "itinerary", "budget"]
    tools = ["poi_search", "budget_calculator"]
    forbidden: list[str] = ["weather_query"]
    expected = _common_expected("trip_planning", agents, tools, forbidden, slots, ctx)
    expected["hard_constraints"] = _hard_constraints(slots, min_attractions=max(3, min(5, duration_days + 1)))
    if start_date:
        agents = ["attraction", "weather", "itinerary", "budget"]
        tools = ["poi_search", "weather_query", "budget_calculator"]
        expected = _common_expected("trip_planning", agents, tools, [], slots, ctx)
        expected["hard_constraints"] = _hard_constraints(slots, min_attractions=max(3, min(5, duration_days + 1)))
        expected.update(_weather_fields(start_date, duration_days, ctx))
    else:
        expected.update(
            {
                "weather_required": False,
                "weather_date_policy": "no_date_no_specific_weather_for_trip_plan",
                "no_date_weather_reminder_required": True,
            }
        )
    return {
        "user_input": user_input,
        "task_type": "trip_planning",
        "current_slots": slots,
        "slots": slots,
        "expected": expected,
    }


def _partial_turn(
    user_input: str,
    *,
    changed_slots: list[str],
    preserved_slots: list[str],
    slots: Mapping[str, Any],
    agents: list[str],
    tools: list[str],
    policy: str,
    ctx: Mapping[str, Any],
    no_change_reuse: bool = False,
) -> dict[str, Any]:
    slots = dict(slots)
    expected = _common_expected("partial_replan", agents, tools, _forbidden(tools), slots, ctx)
    expected.update(
        {
            "hard_constraints": _hard_constraints(slots, min_attractions=max(3, min(5, int(slots.get("duration_days") or 2) + 1))),
            "changed_slots": changed_slots,
            "preserved_slots": preserved_slots,
            "partial_replan_policy": policy,
        }
    )
    if no_change_reuse:
        expected["replan_policy"] = "no_change_reuse"
        expected["hard_constraints"] = {
            "destination": slots.get("destination"),
            "duration_days": slots.get("duration_days"),
            "people_count": slots.get("people_count"),
            "budget_limit": slots.get("budget_amount"),
        }
    if slots.get("start_date") and ("weather_query" in tools or "start_date" in changed_slots or "duration_days" in changed_slots):
        expected.update(_weather_fields(str(slots["start_date"]), int(slots.get("duration_days") or 1), ctx))
    elif not slots.get("start_date"):
        expected.update(
            {
                "weather_required": False,
                "weather_date_policy": "no_date_no_specific_weather_for_trip_plan",
                "no_date_weather_reminder_required": True,
            }
        )
    return {
        "user_input": user_input,
        "task_type": "partial_replan",
        "current_slots": _changed_current_slots(slots, changed_slots),
        "slots": slots,
        "expected": expected,
    }


def _weather_adjustment_turn(
    user_input: str,
    *,
    slots: Mapping[str, Any],
    weather_change: Mapping[str, Any],
    ctx: Mapping[str, Any],
) -> dict[str, Any]:
    slots = dict(slots)
    expected = _common_expected(
        "weather_adjustment",
        ["itinerary", "budget"],
        ["budget_calculator"],
        ["poi_search", "weather_query"],
        slots,
        ctx,
    )
    expected.update(
        {
            "hard_constraints": _hard_constraints(slots, min_attractions=max(3, min(5, int(slots.get("duration_days") or 2) + 1))),
            "weather_change": dict(weather_change),
            "weather_adjustment_required": True,
            "weather_reuse_expected": True,
            "weather_query_must_not_rerun": True,
            "partial_replan_policy": "weather_adjustment_itinerary_budget",
            "previous_artifacts_expected": ["daily_itinerary", "attractions", "budget", "weather"],
        }
    )
    return {
        "user_input": user_input,
        "task_type": "weather_adjustment",
        "current_slots": {"weather_scenario": slots.get("weather_scenario")},
        "slots": slots,
        "weather_change": dict(weather_change),
        "expected": expected,
    }


def _budget_query_turn(user_input: str, *, slots: Mapping[str, Any], ctx: Mapping[str, Any]) -> dict[str, Any]:
    slots = dict(slots)
    expected = _common_expected("budget_query", ["budget"], ["budget_calculator"], ["poi_search", "weather_query"], slots, ctx)
    expected["hard_constraints"] = {
        "destination": slots.get("destination"),
        "duration_days": slots.get("duration_days"),
        "people_count": slots.get("people_count"),
        "budget_limit": slots.get("budget_amount"),
    }
    return {
        "user_input": user_input,
        "task_type": "budget_query",
        "current_slots": {},
        "slots": slots,
        "expected": expected,
    }


def _weather_query_turn(user_input: str, *, slots: Mapping[str, Any], ctx: Mapping[str, Any]) -> dict[str, Any]:
    slots = dict(slots)
    expected = _common_expected("weather_query", ["weather"], ["weather_query"], ["poi_search", "budget_calculator"], slots, ctx)
    expected["hard_constraints"] = {
        "destination": slots.get("destination"),
        "start_date": slots.get("start_date"),
        "duration_days": slots.get("duration_days"),
    }
    expected.update(_weather_fields(str(slots["start_date"]), int(slots["duration_days"]), ctx))
    return {
        "user_input": user_input,
        "task_type": "weather_query",
        "current_slots": {"start_date": slots.get("start_date"), "duration_days": slots.get("duration_days")},
        "slots": slots,
        "expected": expected,
    }


def _attraction_turn(user_input: str, *, slots: Mapping[str, Any]) -> dict[str, Any]:
    slots = dict(slots)
    expected = _common_expected(
        "attraction_recommendation",
        ["attraction"],
        ["poi_search"],
        ["weather_query", "budget_calculator"],
        slots,
        {},
    )
    expected.update(
        {
            "hard_constraints": {
                "destination": slots.get("destination"),
                "min_attractions": 4,
                "max_attractions": 6,
            },
            "min_attractions": 4,
            "max_attractions": 6,
        }
    )
    return {
        "user_input": user_input,
        "task_type": "attraction_recommendation",
        "current_slots": {"destination": slots.get("destination"), "preferences": slots.get("preferences"), "special_requirements": slots.get("special_requirements")},
        "slots": slots,
        "expected": expected,
    }


def _chat_turn(user_input: str) -> dict[str, Any]:
    return {
        "user_input": user_input,
        "task_type": "general_chat",
        "current_slots": {},
        "slots": {},
        "expected": {
            "task_type": "general_chat",
            "required_tools": [],
            "accepted_agent_sets": [[]],
            "accepted_tool_sets": [[]],
            "forbidden_tools": NO_TOOLS,
        },
    }


def _clarification_turn(user_input: str, *, missing_slots: list[str]) -> dict[str, Any]:
    return {
        "user_input": user_input,
        "task_type": "clarification",
        "current_slots": {},
        "slots": {},
        "expected": {
            "task_type": "clarification",
            "required_tools": [],
            "accepted_agent_sets": [[]],
            "accepted_tool_sets": [[]],
            "forbidden_tools": NO_TOOLS,
            "missing_slots": missing_slots,
        },
    }


def _common_expected(
    task_type: str,
    agents: list[str],
    tools: list[str],
    forbidden_tools: list[str],
    slots: Mapping[str, Any],
    ctx: Mapping[str, Any],
) -> dict[str, Any]:
    expected: dict[str, Any] = {
        "task_type": task_type,
        "required_tools": tools,
        "accepted_agent_sets": [agents],
        "accepted_tool_sets": [tools],
        "forbidden_tools": forbidden_tools,
    }
    expected.update(deepcopy(dict(slots)))
    expected.update(_budget_scope_fields(slots, ctx))
    return {key: value for key, value in expected.items() if value is not None}


def _budget_scope_fields(slots: Mapping[str, Any], ctx: Mapping[str, Any]) -> dict[str, Any]:
    destination = slots.get("destination")
    origin = slots.get("origin")
    people_count = int(slots.get("people_count") or 1)
    if not destination:
        return {}
    if not origin:
        return {
            "origin": None,
            "intercity_transport_included": False,
            "budget_scope": "destination_local_only",
            "mandatory_budget_disclaimer": True,
        }
    fare_map = ctx.get("fare_map") if isinstance(ctx.get("fare_map"), Mapping) else {}
    fare = fare_map.get((str(origin), str(destination)))
    if fare is None:
        return {
            "intercity_transport_included": False,
            "budget_scope": "local_only_route_uncovered",
            "mandatory_budget_disclaimer": True,
            "intercity_transport_mode": "high_speed_rail",
            "intercity_seat_class": "second_class",
        }
    return {
        "intercity_transport_mode": "high_speed_or_d_train",
        "intercity_seat_class": "second_class",
        "intercity_transport_included": True,
        "budget_scope": "local_plus_round_trip_intercity",
        "intercity_route_id": f"{origin}_{destination}_rail_second_class",
        "intercity_one_way_fare_per_person_cny": fare,
        "intercity_round_trip_cost_cny": fare * 2 * people_count,
    }


def _weather_fields(start_date: str, duration_days: int, ctx: Mapping[str, Any]) -> dict[str, Any]:
    manifest = ctx.get("weather_manifest") if isinstance(ctx.get("weather_manifest"), Mapping) else {}
    snapshot_start = date.fromisoformat(str(manifest.get("forecast_start_date") or "2026-08-07"))
    snapshot_end = date.fromisoformat(str(manifest.get("forecast_end_date") or "2026-09-05"))
    start = date.fromisoformat(start_date)
    requested = [start + timedelta(days=offset) for offset in range(duration_days)]
    covered = [item.isoformat() for item in requested if snapshot_start <= item <= snapshot_end]
    missing = [item.isoformat() for item in requested if item.isoformat() not in set(covered)]
    if len(covered) == len(requested):
        coverage = "full"
    elif covered:
        coverage = "partial"
    else:
        coverage = "out_of_range"
    return {
        "weather_required": True,
        "weather_date_policy": "explicit_date_use_qweather_snapshot",
        "expected_weather_coverage_status": coverage,
        "expected_weather_covered_dates": covered,
        "expected_weather_missing_dates": missing,
        "weather_snapshot_id": manifest.get("snapshot_id"),
    }


def _hard_constraints(slots: Mapping[str, Any], *, min_attractions: int | None = None) -> dict[str, Any]:
    constraints: dict[str, Any] = {}
    for source, target in (
        ("origin", "origin"),
        ("destination", "destination"),
        ("start_date", "start_date"),
        ("duration_days", "duration_days"),
        ("people_count", "people_count"),
        ("budget_amount", "budget_limit"),
        ("traveler_group", "traveler_group"),
    ):
        if slots.get(source) is not None:
            constraints[target] = slots[source]
    if min_attractions is not None:
        constraints["min_attractions"] = min_attractions
        constraints["max_pois_per_day"] = 2 if int(slots.get("duration_days") or 1) >= 2 else 3
    return constraints


def _slots(
    *,
    destination: str | None = None,
    origin: str | None = None,
    start_date: str | None = None,
    duration_days: int | None = None,
    people_count: int | None = None,
    budget_amount: int | None = None,
    traveler_group: str | None = None,
    preferences: list[str] | None = None,
    special_requirements: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "origin": origin,
        "destination": destination,
        "start_date": start_date,
        "duration_days": duration_days,
        "people_count": people_count,
        "budget_amount": budget_amount,
        "traveler_group": traveler_group,
        "preferences": preferences,
        "special_requirements": special_requirements,
    }
    return {key: value for key, value in payload.items() if value not in (None, [], {})}


def _changed_current_slots(slots: Mapping[str, Any], changed_slots: list[str]) -> dict[str, Any]:
    return {slot: slots[slot] for slot in changed_slots if slot in slots}


def _forbidden(required_tools: list[str]) -> list[str]:
    return [tool for tool in NO_TOOLS if tool not in set(required_tools)]


def _target_task_quotas(cases: list[Mapping[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for case in cases:
        turns = case.get("turns") if isinstance(case.get("turns"), list) else []
        if len(turns) >= 2:
            counter[str(turns[1].get("task_type"))] += 1
    return dict(sorted(counter.items()))


def _snapshot_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "provider": manifest.get("provider"),
        "snapshot_id": manifest.get("snapshot_id"),
        "forecast_start_date": manifest.get("forecast_start_date"),
        "forecast_end_date": manifest.get("forecast_end_date"),
        "forecast_horizon_days": manifest.get("forecast_horizon_days"),
        "combined_sha256": manifest.get("combined_sha256"),
    }


def _intercity_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "provider": manifest.get("provider"),
        "snapshot_id": manifest.get("snapshot_id"),
        "fare_snapshot_date": manifest.get("fare_snapshot_date"),
        "combined_sha256": manifest.get("combined_sha256"),
        "runtime_online_refresh_allowed": manifest.get("runtime_online_refresh_allowed"),
        "fare_scope": manifest.get("fare_scope"),
        "round_trip_multiplier": manifest.get("round_trip_multiplier"),
    }


def _build_audit(document: Mapping[str, Any]) -> dict[str, Any]:
    from app.core.benchmark_dataset_validator import build_benchmark_dataset_quality_report
    from app.core.fixed_data import canonical_json_sha256
    from app.core.formal_experiment_preflight import load_benchmark_document

    ctp100_doc, ctp100_cases = load_benchmark_document(ROOT / "experiments" / "ctp100_formal_v2.json")
    quality = build_benchmark_dataset_quality_report(
        document=document,
        cases=document["cases"],
        expected_case_count=30,
        strict_formal=True,
    )
    comparison_quality = build_benchmark_dataset_quality_report(
        document=document,
        cases=document["cases"],
        expected_case_count=30,
        strict_formal=False,
        comparison_splits={"ctp100_formal_v2": ctp100_cases},
    )
    turn_counter = Counter()
    target_counter = Counter()
    city_counter = Counter()
    for case in document["cases"]:
        for index, turn in enumerate(case["turns"], start=1):
            turn_counter[turn["task_type"]] += 1
            destination = (turn.get("slots") or {}).get("destination")
            if destination:
                city_counter[str(destination)] += 1
            if index == 2:
                target_counter[turn["task_type"]] += 1
    errors = list(quality.get("errors") or [])
    return {
        "schema_version": "ctp30-multiturn-v2-draft-audit-v1",
        "status": "passed" if not errors else "failed",
        "dataset_path": DATASET_PATH.as_posix(),
        "dataset_id": document.get("dataset_id"),
        "dataset_sha256": canonical_json_sha256(document),
        "case_count": document.get("case_count"),
        "turn_count": document.get("turn_count"),
        "scenario_case_count": sum(1 for case in document["cases"] if isinstance(case.get("turns"), list)),
        "target_turn_id": "t2",
        "turn_task_distribution": dict(sorted(turn_counter.items())),
        "target_turn_task_distribution": dict(sorted(target_counter.items())),
        "city_distribution": dict(sorted(city_counter.items())),
        "quality_status": quality.get("status"),
        "quality_errors": errors,
        "quality_warnings": quality.get("warnings") or [],
        "cross_split_duplicate_visible_input_groups": (
            comparison_quality.get("coverage", {}).get("cross_split_duplicate_visible_input_groups") or []
        ),
        "cross_split_near_duplicate_visible_input_pairs": (
            comparison_quality.get("coverage", {}).get("near_duplicate_visible_input_pairs") or []
        ),
        "human_review_required": True,
        "manual_review_status": "pending",
        "paper_disclosure": (
            "CTP30-v2 uses single-person case design and labeling followed by automatic "
            "schema, slot, weather, budget, city-coverage, and duplicate audits."
        ),
    }


def _render_review(document: Mapping[str, Any], audit: Mapping[str, Any]) -> str:
    lines = [
        "# CTP30-v2 多轮封闭验证集草案人工审阅表",
        "",
        "> 本文件由 `experiments/generate_ctp30_multiturn_v2_draft.py` 生成。当前只是草案，不是正式冻结集。",
        "",
        "## 审阅规则",
        "",
        "- 每个案例必须是两轮：第一轮建立上下文，第二轮是正式考察目标。",
        "- 第二轮的 `changed_slots` 必须能从第二轮用户话语直接读出来。",
        "- 第二轮的 `preserved_slots` 必须能从第一轮用户话语读出来。",
        "- 有明确日期时只能使用冻结 QWeather 快照；超出 2026-09-05 必须标为未覆盖。",
        "- 有出发地且路线支持时，预算必须包含冻结二等座往返城际交通；无出发地时必须说明不含城际交通。",
        "- 你逐题只需要判断：题目是否真实、金标是否符合你的论文设定、是否需要改写表达。",
        "",
        "## 自动审计摘要",
        "",
        f"- audit_status: `{audit.get('status')}`",
        f"- case_count / turn_count: `{audit.get('case_count')}` / `{audit.get('turn_count')}`",
        f"- target_turn_task_distribution: `{audit.get('target_turn_task_distribution')}`",
        f"- quality_errors: `{len(audit.get('quality_errors') or [])}`",
        f"- cross_split_near_duplicate_pairs: `{len(audit.get('cross_split_near_duplicate_visible_input_pairs') or [])}`",
        "",
        "## 逐题审阅",
        "",
        "| # | case_id | 第二轮任务 | 标题 | 第一轮用户话语 | 第二轮用户话语 | changed_slots | preserved_slots | 期望Agent | 期望工具 | 天气覆盖 | 城际预算 | 人工结论 | 修改意见 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, case in enumerate(document["cases"], start=1):
        t1, t2 = case["turns"]
        expected = t2.get("expected") or {}
        lines.append(
            "| {index} | `{case_id}` | `{task}` | {title} | {t1_input} | {t2_input} | `{changed}` | `{preserved}` | `{agents}` | `{tools}` | `{weather}` | `{budget}` | 待确认 |  |".format(
                index=index,
                case_id=case["case_id"],
                task=t2["task_type"],
                title=_escape_md(str(case["title"])),
                t1_input=_escape_md(str(t1["user_input"])),
                t2_input=_escape_md(str(t2["user_input"])),
                changed=", ".join(expected.get("changed_slots") or []),
                preserved=", ".join(expected.get("preserved_slots") or []),
                agents=expected.get("accepted_agent_sets"),
                tools=expected.get("accepted_tool_sets"),
                weather=expected.get("expected_weather_coverage_status") or expected.get("weather_date_policy") or "不适用",
                budget=expected.get("budget_scope") or "不适用",
            )
        )
    lines.extend(
        [
            "",
            "## 冻结前必须完成",
            "",
            "- 将全部“待确认”改为“确认”或写明修改意见。",
            "- 如果修改题目，需要重新运行生成/审计流程，保证 JSON 与审阅表一致。",
            "- 正式运行前再生成最终 `ctp30_multiturn_validation_v2.json`，并记录 dataset sha256。",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_audit_md(audit: Mapping[str, Any]) -> str:
    lines = [
        "# CTP30-v2 Draft Auto Audit",
        "",
        f"- status: `{audit.get('status')}`",
        f"- dataset_id: `{audit.get('dataset_id')}`",
        f"- dataset_sha256: `{audit.get('dataset_sha256')}`",
        f"- case_count: `{audit.get('case_count')}`",
        f"- turn_count: `{audit.get('turn_count')}`",
        f"- scenario_case_count: `{audit.get('scenario_case_count')}`",
        f"- target_turn_task_distribution: `{audit.get('target_turn_task_distribution')}`",
        f"- turn_task_distribution: `{audit.get('turn_task_distribution')}`",
        f"- city_distribution: `{audit.get('city_distribution')}`",
        f"- quality_status: `{audit.get('quality_status')}`",
        f"- quality_error_count: `{len(audit.get('quality_errors') or [])}`",
        f"- quality_warning_count: `{len(audit.get('quality_warnings') or [])}`",
        f"- cross_split_duplicate_count: `{len(audit.get('cross_split_duplicate_visible_input_groups') or [])}`",
        f"- cross_split_near_duplicate_count: `{len(audit.get('cross_split_near_duplicate_visible_input_pairs') or [])}`",
        "",
        "## Quality Errors",
        "",
    ]
    errors = audit.get("quality_errors") or []
    lines.extend([f"- {item}" for item in errors] or ["- None"])
    lines.extend(["", "## Quality Warnings", ""])
    warnings = audit.get("quality_warnings") or []
    lines.extend([f"- {item}" for item in warnings] or ["- None"])
    lines.extend(["", "## Cross-Split Near Duplicates", ""])
    near = audit.get("cross_split_near_duplicate_visible_input_pairs") or []
    if near:
        for item in near:
            lines.append(f"- {item}")
    else:
        lines.append("- None")
    lines.extend(["", f"Paper disclosure: {audit.get('paper_disclosure')}", ""])
    return "\n".join(lines)


def _escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
