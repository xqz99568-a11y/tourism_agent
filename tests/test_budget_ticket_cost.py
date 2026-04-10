import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.attraction import AttractionAgent
from app.agents.base import AgentResponse, AgentStatus
from app.agents.budget import BudgetAgent
from app.core.context import ExecutionContext


def test_attraction_estimated_cost_does_not_reuse_trip_budget() -> None:
    agent = AttractionAgent(llm=None)

    assert agent._build_estimated_cost(None, 4000, 4000) is None
    assert agent._build_estimated_cost(45, 4000, 4000) == {
        "amount": 45,
        "currency": "CNY",
        "cost_level": "low",
    }


def test_budget_ignores_estimated_cost_when_selecting_ticket_source() -> None:
    agent = BudgetAgent(llm=None)

    data = {
        "poi_list": [
            {"name": "河坊街", "estimated_cost": {"amount": 4000, "currency": "CNY", "cost_level": "high"}},
            {"name": "武林夜市", "estimated_cost": {"amount": 4000, "currency": "CNY", "cost_level": "high"}},
        ],
        "pois": [
            {"name": "西湖", "ticket_price": "免费", "ticket_price_value": 0},
            {"name": "灵隐寺", "ticket_price": "45元", "ticket_price_value": 45},
        ],
    }

    pois, field = agent._select_poi_source_for_budget(data)

    assert field == "pois"
    assert [poi["name"] for poi in pois] == ["西湖", "灵隐寺"]
    assert agent._extract_poi_price({"name": "河坊街", "estimated_cost": {"amount": 4000}}) is None


def test_budget_ticket_breakdown_handles_free_unknown_and_fen_units() -> None:
    agent = BudgetAgent(llm=None)

    breakdown = agent._build_ticket_cost_breakdown(
        [
            {"name": "西湖", "ticket_price": "免费"},
            {"name": "灵隐寺", "ticket_price_value": 45},
            {"name": "雷峰塔", "ticket_price": {"amount": 4000, "unit": "fen"}},
            {"name": "河坊街", "ticket_price": "未知"},
            {"name": "武林夜市", "estimated_cost": {"amount": 4000, "currency": "CNY", "cost_level": "high"}},
        ],
        num_travelers=1,
        budget_level="medium",
        source_field="poi_list",
    )

    assert breakdown["ticket_cost"] == 85.0
    assert breakdown["ticket_cost_per_person"] == 85.0
    assert breakdown["summary"] == {
        "fallback_applied": False,
        "poi_source_field": "poi_list",
        "source": "poi_ticket_fields",
        "known_ticket_count": 2,
        "free_ticket_count": 1,
        "pending_confirmation_count": 1,
        "pending_confirmation_pois": ["河坊街"],
        "ignored_non_ticket_count": 1,
    }

    details = breakdown["details"]
    assert details[0]["status"] == "free"
    assert details[0]["counted_amount_yuan"] == 0.0
    assert details[1]["parsed_ticket_yuan"] == 45.0
    assert details[2]["input_unit"] == "fen"
    assert details[2]["parsed_ticket_yuan"] == 40.0
    assert details[2]["cumulative_group_yuan"] == 85.0
    assert details[3]["status"] == "unknown"
    assert details[4]["status"] == "ignored_non_ticket_field"


def test_hangzhou_case_prefers_real_ticket_fields_over_trip_budget_estimate() -> None:
    agent = BudgetAgent(llm=None)
    context = ExecutionContext(request_id="budget-hangzhou", session_id="budget-hangzhou")
    context.add_result(
        "attraction",
        AgentResponse(
            agent_name="attraction",
            status=AgentStatus.COMPLETED,
            content="",
            data={
                "poi_list": [
                    {"name": "河坊街", "estimated_cost": {"amount": 4000, "currency": "CNY", "cost_level": "high"}},
                    {"name": "武林夜市", "estimated_cost": {"amount": 4000, "currency": "CNY", "cost_level": "high"}},
                    {"name": "钱江新城灯光秀", "estimated_cost": {"amount": 4000, "currency": "CNY", "cost_level": "high"}},
                    {"name": "浙江省博物馆", "estimated_cost": {"amount": 4000, "currency": "CNY", "cost_level": "high"}},
                ],
                "pois": [
                    {"name": "西湖", "ticket_price": "免费", "ticket_price_value": 0},
                    {"name": "灵隐寺", "ticket_price": "45元", "ticket_price_value": 45},
                    {"name": "河坊街", "ticket_price": "", "ticket_price_value": None},
                    {"name": "武林夜市", "ticket_price": "", "ticket_price_value": None},
                    {"name": "钱江新城灯光秀", "ticket_price": "", "ticket_price_value": None},
                    {"name": "浙江省博物馆", "ticket_price": "免费", "ticket_price_value": 0},
                ],
            },
        ),
    )

    pois, ticket_sum, source_field = agent._extract_attraction_data(context)
    breakdown = agent._build_ticket_cost_breakdown(
        pois,
        num_travelers=1,
        budget_level="medium",
        source_field=source_field,
    )

    assert source_field == "pois"
    assert ticket_sum == 45.0
    assert breakdown["ticket_cost"] == 45.0
    assert breakdown["summary"]["pending_confirmation_count"] == 3


def test_budget_result_exposes_pending_ticket_fields_for_free_and_missing_pois() -> None:
    agent = BudgetAgent(llm=None)
    pois = [
        {"name": "西湖", "ticket_price": "免费"},
        {"name": "浙江省博物馆", "ticket_price": "免费"},
        {"name": "城市阳台", "ticket_price": ""},
        {"name": "钱江世纪公园", "ticket_price": "待确认"},
        {"name": "清河坊历史文化特色街区", "ticket_price": None},
        {"name": "五柳巷历史街区", "ticket_price_value": None},
    ]

    breakdown = agent._build_ticket_cost_breakdown(
        pois,
        num_travelers=1,
        budget_level="medium",
        source_field="pois",
    )
    result = agent._build_budget_result(
        inputs={"budget_level": "medium"},
        transport_cost=380.0,
        hotel_cost=960.0,
        food_cost=580.0,
        ticket_cost=breakdown["ticket_cost"],
        other_cost=35.0,
        buffer_cost=195.5,
        total_with_buffer=2150.5,
        budget_limit=4000.0,
        pois=pois,
        daily_plans=None,
        optimization_suggestions=[],
        estimated_by="poi_list",
        ticket_breakdown=breakdown,
        poi_source_field="pois",
        duration=3,
        num_travelers=1,
    )

    assert breakdown["ticket_cost"] == 0.0
    assert breakdown["summary"]["free_ticket_count"] == 2
    assert breakdown["summary"]["pending_confirmation_count"] == 4
    assert breakdown["summary"]["pending_confirmation_pois"] == [
        "城市阳台",
        "钱江世纪公园",
        "清河坊历史文化特色街区",
        "五柳巷历史街区",
    ]
    assert result["confirmed_ticket_cost"] == 0.0
    assert result["pending_ticket_count"] == 4
    assert result["pending_ticket_pois"] == [
        "城市阳台",
        "钱江世纪公园",
        "清河坊历史文化特色街区",
        "五柳巷历史街区",
    ]
    assert result["free_ticket_count"] == 2
    assert result["has_pending_ticket_cost"] is True
    assert result["confirmed_total_cost"] == 2150.5


def test_budget_result_exposes_paid_free_missing_ticket_fields() -> None:
    agent = BudgetAgent(llm=None)
    pois = [
        {"name": "灵隐寺", "ticket_price_value": 60},
        {"name": "西湖", "ticket_price": "免费"},
        {"name": "城市阳台", "ticket_price": ""},
        {"name": "钱江世纪公园", "ticket_price": "待确认"},
    ]

    breakdown = agent._build_ticket_cost_breakdown(
        pois,
        num_travelers=1,
        budget_level="medium",
        source_field="pois",
    )
    result = agent._build_budget_result(
        inputs={"budget_level": "medium"},
        transport_cost=300.0,
        hotel_cost=720.0,
        food_cost=460.0,
        ticket_cost=breakdown["ticket_cost"],
        other_cost=80.0,
        buffer_cost=162.0,
        total_with_buffer=1782.0,
        budget_limit=3000.0,
        pois=pois,
        daily_plans=None,
        optimization_suggestions=[],
        estimated_by="poi_list",
        ticket_breakdown=breakdown,
        poi_source_field="pois",
        duration=3,
        num_travelers=1,
    )

    assert breakdown["ticket_cost"] == 60.0
    assert breakdown["summary"]["known_ticket_count"] == 1
    assert breakdown["summary"]["free_ticket_count"] == 1
    assert breakdown["summary"]["pending_confirmation_count"] == 2
    assert result["confirmed_ticket_cost"] == 60.0
    assert result["pending_ticket_count"] == 2
    assert result["pending_ticket_pois"] == ["城市阳台", "钱江世纪公园"]
    assert result["has_pending_ticket_cost"] is True
