import json
from pathlib import Path


CATALOG_PATH = Path(__file__).resolve().parents[1] / "experiments" / "evaluation_rule_catalog.json"

TASK_TYPES = {
    "trip_planning",
    "attraction_recommendation",
    "weather_query",
    "budget_query",
    "partial_replan",
    "weather_adjustment",
    "clarification",
    "general_chat",
}

RULE_IDS = [
    "G_SCHEMA_VALID",
    "G_EXECUTION_STATUS_VALID",
    "G_FINAL_ANSWER_CONSISTENT",
    "G_TASK_TYPE_MATCH",
    "H_TRIP_DAYS",
    "H_ATTRACTION_COUNT_BOUNDS",
    "H_DAILY_LOAD_LIMIT",
    "H_BUDGET_LIMIT",
    "H_POI_GROUNDED",
    "H_NO_DUPLICATE_POIS",
    "H_MUST_INCLUDE_POIS",
    "H_FORBIDDEN_POIS",
    "H_RAIN_SUITABILITY",
    "H_SENIOR_ACCESSIBILITY",
    "H_WEATHER_ADJUSTMENT_REQUIRED",
    "H_WEATHER_EVIDENCE",
    "H_NO_DATE_WEATHER_REMINDER",
    "H_BUDGET_EVIDENCE",
    "H_BUDGET_POLICY_VERSION",
    "H_BUDGET_ACCOMMODATION_NIGHTS",
    "H_BUDGET_CONTINGENCY_LOCAL_ONLY",
    "H_BUDGET_TOTAL_FORMULA",
    "H_BUDGET_ITINERARY_CONSISTENCY",
    "H_BUDGET_UPGRADE_POLICY",
    "H_BUDGET_INDEPENDENT_RECALCULATION",
    "H_INTERCITY_SCOPE",
    "H_INTERCITY_COST",
    "H_INTERCITY_EVIDENCE",
    "H_TOOL_EVIDENCE",
    "T_CLARIFICATION_MISSING_FIELDS",
    "T_CLARIFICATION_NO_PREMATURE_PLAN",
    "T_GENERAL_CHAT_NO_BUSINESS_EXECUTION",
    "T_GENERAL_CHAT_NO_TRIP_ARTIFACT",
    "T_ATTRACTION_SINGLE_SCOPE",
    "T_WEATHER_SINGLE_SCOPE",
    "T_BUDGET_SINGLE_SCOPE",
    "T_PARTIAL_CHANGED_SLOTS_APPLIED",
    "T_PARTIAL_PRESERVED_SLOTS_KEPT",
    "T_PARTIAL_REUSE_VALIDITY",
    "T_WEATHER_AFFECTED_CONTENT_ADJUSTED",
    "T_WEATHER_UNAFFECTED_CONTENT_PRESERVED",
    "S_AGENT_SET_MATCH",
    "S_TOOL_SET_MATCH",
    "S_PLANNED_ACTUAL_AGENT_CONSISTENCY",
    "S_PLANNED_ACTUAL_TOOL_CONSISTENCY",
    "S_FORBIDDEN_GENERATION_TOOLS",
]


def _catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_rule_catalog_keeps_frozen_contract() -> None:
    catalog = _catalog()

    assert catalog["schema_version"] == "ctp-evaluation-rule-catalog-v1"
    assert catalog["catalog_id"] == "day8_formal_independent_evaluator_rules"
    assert catalog["status_values"] == ["passed", "failed", "na"]
    assert set(catalog["task_types"]) == TASK_TYPES
    assert catalog["task_aliases"]["budget_control"] == "budget_query"
    assert [rule["id"] for rule in catalog["rules"]] == RULE_IDS


def test_rules_are_minimal_and_machine_gradable() -> None:
    catalog = _catalog()
    valid_tasks = set(catalog["task_types"]) | {"*"}
    valid_usages = set(catalog["score_usages"])

    failure_codes = set()
    for rule in catalog["rules"]:
        assert set(rule) == {
            "id",
            "usage",
            "tasks",
            "inputs",
            "passed",
            "failed",
            "na",
            "failure_code",
        }
        assert rule["usage"] in valid_usages
        assert set(rule["tasks"]) <= valid_tasks
        assert rule["inputs"]
        assert rule["passed"] and rule["failed"] and rule["na"]
        assert rule["failure_code"] not in failure_codes
        failure_codes.add(rule["failure_code"])


def test_task_and_metric_coverage() -> None:
    catalog = _catalog()
    rules = catalog["rules"]

    for task_type in TASK_TYPES:
        applicable = [rule for rule in rules if "*" in rule["tasks"] or task_type in rule["tasks"]]
        assert applicable, task_type
        assert any(rule["usage"] == "stsr_gate" for rule in applicable), task_type

    hcsr_tasks = {
        task
        for rule in rules
        if rule["usage"] == "hcsr"
        for task in rule["tasks"]
        if task != "*"
    }
    assert TASK_TYPES - {"clarification", "general_chat"} <= hcsr_tasks


def test_independent_evaluator_guards_are_declared() -> None:
    assert set(_catalog()["evaluator_guards"]) == {
        "method_blind",
        "no_llm_or_live_api",
        "no_output_repair",
        "structured_fields_only",
        "append_only_evidence",
    }
