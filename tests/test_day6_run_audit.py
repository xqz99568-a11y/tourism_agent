import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.experiment_run_audit import RUN_AUDIT_SCHEMA_VERSION
from app.core.experiment_runner import (
    RESEARCH_AGENT_DECISION_SCHEMA_VERSION,
    ExperimentRunner,
)
from app.core.llm.client import ToolCall
from app.schemas.experiment import EXPERIMENT_OUTPUT_SCHEMA_VERSION
from app.tools.research_tools import GENERATION_TOOL_NAMES


class _AgentJSONLLM:
    async def chat(self, messages, tools=None):
        payload = self._agent_payload(messages)
        content = self._agent_decision_content(payload) if payload else "tool-grounded multi-agent answer"
        return SimpleNamespace(content=content, tool_calls=[], usage={"total_tokens": 1})

    def _agent_payload(self, messages):
        try:
            payload = json.loads(messages[-1].content)
        except (json.JSONDecodeError, TypeError, AttributeError, IndexError):
            return {}
        return payload if isinstance(payload, dict) and payload.get("agent_name") else {}

    def _agent_decision_content(self, payload):
        agent_name = str(payload.get("agent_name") or "")
        tool_evidence = payload.get("tool_evidence") if isinstance(payload.get("tool_evidence"), dict) else {}
        attractions = self._attractions(tool_evidence)
        selected_ids = [str(item.get("poi_id")) for item in attractions[:4] if item.get("poi_id")]
        task_slots = payload.get("task_slots") if isinstance(payload.get("task_slots"), dict) else {}
        days = int(task_slots.get("duration_days") or 2)
        if agent_name == "attraction":
            decisions = {"selected_poi_ids": selected_ids}
        elif agent_name == "weather":
            decisions = {"risk_days": [], "adjustment_required": False}
        elif agent_name == "itinerary":
            decisions = {
                "daily_itinerary": [
                    {
                        "day": day,
                        "attraction_poi_ids": selected_ids[(day - 1) * 2 : day * 2] or selected_ids[:1],
                    }
                    for day in range(1, days + 1)
                ]
            }
        elif agent_name == "budget":
            decisions = {"feasibility": "feasible", "budget_notes": "test"}
        else:
            decisions = {}
        return json.dumps(
            {
                "schema_version": RESEARCH_AGENT_DECISION_SCHEMA_VERSION,
                "agent_name": agent_name,
                "summary": f"{agent_name} test decision",
                "decisions": decisions,
                "risks": [],
                "confidence": 1.0,
            },
            ensure_ascii=False,
        )

    def _tool_data(self, result):
        if not isinstance(result, dict):
            return {}
        data = result.get("data")
        return data if isinstance(data, dict) else {}

    def _attractions(self, tool_evidence):
        data = self._tool_data(tool_evidence.get("poi_search"))
        attractions = data.get("attractions") if isinstance(data, dict) else []
        return [item for item in attractions or [] if isinstance(item, dict)]


def test_day6_run_audit_is_attached_to_result_metrics_and_csv(tmp_path: Path) -> None:
    class FakeLLM:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="budget-1",
                            name="budget_calculator",
                            arguments=json.dumps(
                                {
                                    "city": "Hangzhou",
                                    "people_count": 2,
                                    "days": 2,
                                    "spending_level": "medium",
                                }
                            ),
                        )
                    ],
                    usage={"total_tokens": 10},
                )
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "schema_version": EXPERIMENT_OUTPUT_SCHEMA_VERSION,
                        "case_id": "day6-run-audit-m1",
                        "method": "single_agent",
                        "task_type": "trip_planning",
                        "planned_agents": ["single_agent"],
                        "used_agents": ["single_agent"],
                        "planned_tools": [],
                        "called_tools": [],
                        "tool_results": {},
                        "attractions": [],
                        "trip_days": 2,
                        "daily_itinerary": [{"day": 1, "attractions": []}],
                        "budget": {"total": 1200},
                        "weather": None,
                        "weather_adjustments": [],
                        "execution_status": "completed",
                        "final_answer": "budget-backed answer",
                        "metadata": {"structured_by_llm": True},
                    },
                    ensure_ascii=False,
                ),
                tool_calls=[],
                usage={"total_tokens": 20},
            )

    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=FakeLLM)
    result = runner.run(
        {
            "case_id": "day6-run-audit-m1",
            "user_input": "Plan a two day Hangzhou trip for two people.",
        },
        method="single_agent",
    )

    audit = result["run_audit"]
    audit_metrics = audit["metrics"]

    assert audit["schema_version"] == RUN_AUDIT_SCHEMA_VERSION
    assert result["audit"] == audit
    assert result["output"]["metadata"]["run_audit_schema_version"] == RUN_AUDIT_SCHEMA_VERSION
    assert audit["planned_agents"] == ["single_agent"]
    assert audit["executed_agents"] == ["single_agent"]
    assert audit["planned_tools"] == ["budget_calculator"]
    assert audit["called_tools"] == ["budget_calculator"]
    assert audit_metrics["planned_agent_count"] == 1
    assert audit_metrics["executed_agent_count"] == 1
    assert audit_metrics["agent_call_count"] == 1
    assert audit_metrics["successful_agent_call_count"] == 1
    assert audit_metrics["failed_agent_call_count"] == 0
    assert audit_metrics["planned_tool_count"] == 1
    assert audit_metrics["called_tool_count"] == 1
    assert audit_metrics["executed_tool_count"] == 1
    assert audit_metrics["successful_tool_call_count"] == 1
    assert audit_metrics["failed_tool_call_count"] == 0
    assert audit_metrics["planned_executed_tool_coverage"] == 1.0
    assert result["metrics"]["called_tool_count"] == 1
    assert result["metrics"]["successful_tool_call_count"] == 1

    csv_path = tmp_path / "results.csv"
    runner.export_csv([result], csv_path)
    row = next(csv.DictReader(csv_path.open(encoding="utf-8-sig")))

    assert row["run_audit_schema_version"] == RUN_AUDIT_SCHEMA_VERSION
    assert row["agent_call_count"] == "1"
    assert row["called_tool_count"] == "1"
    assert row["successful_tool_call_count"] == "1"


def test_day6_m2_and_m3_raw_outputs_follow_unified_schema(tmp_path: Path) -> None:
    runner = ExperimentRunner(trace_dir=tmp_path / "traces", llm_factory=_AgentJSONLLM)
    case = {
        "case_id": "day6-multi-agent-raw-schema",
        "user_input": "Plan a two day Hangzhou trip on 2026-08-01 for two people.",
    }

    for method in ("fixed_multi_agent", "adaptive_multi_agent"):
        result = runner.run(case, method=method)
        raw = result["raw_output"]

        assert raw["schema_version"] == EXPERIMENT_OUTPUT_SCHEMA_VERSION
        assert raw["case_id"] == "day6-multi-agent-raw-schema"
        assert raw["method"] == method
        assert raw["planned_tools"] == list(GENERATION_TOOL_NAMES)
        assert [call["tool_name"] for call in raw["called_tools"]] == list(
            GENERATION_TOOL_NAMES
        )
        assert raw["tool_results"].keys() >= set(GENERATION_TOOL_NAMES)
        assert result["output"]["tool_results"] == raw["tool_results"]
        assert result["output"]["metadata"]["run_audit_schema_version"] == RUN_AUDIT_SCHEMA_VERSION
