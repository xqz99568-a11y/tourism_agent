import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.base import AgentResponse, AgentStatus  # noqa: E402
from app.agents.planner import PlannerAgent  # noqa: E402
from app.core.context import ExecutionContext, SessionContext  # noqa: E402


def _build_context(destination: str) -> tuple[SessionContext, ExecutionContext]:
    session = SessionContext(session_id=f"{destination}-session")
    context = ExecutionContext(
        request_id=f"{destination}-request",
        session_id=session.session_id,
    )
    context.extracted_info = {
        "destination": destination,
        "duration": 3,
        "num_travelers": 2,
        "travel_styles": ["文化", "休闲"],
    }

    if destination == "北京":
        attraction_content = """## 北京目的地概览
### 🌸 最佳旅行季节
- ⭐ **最佳季节**：3-5月、9-11月
- ⭐ **最佳季节**：3-5月、9-11月
- 🌡️ **气候特点**：四季分明，春秋更适合步行游览
- 🎫 **淡旺季**：节假日和暑期客流较大，建议提前预约

### 🍜 必吃美食
1. **北京烤鸭** - 经典代表
2. **卤煮** - 老北京风味

### 🎁 必买特产
1. **景泰蓝工艺品** - 王府井周边
2. **景泰蓝工艺品** - 王府井周边
"""
        pois = [
            {"name": "故宫", "region": "东城区", "category": "历史文化", "tags": ["皇城", "经典"]},
            {"name": "景山公园", "region": "西城区", "category": "自然风光", "tags": ["登高", "城市视角"]},
            {"name": "南锣鼓巷", "region": "东城区", "category": "美食", "tags": ["老街", "小吃", "夜游"]},
            {"name": "天坛", "region": "东城区", "category": "历史文化", "tags": ["世界遗产", "古建筑"]},
        ]
        daily_plans = [
            {
                "day": 1,
                "theme": "皇城经典巡礼",
                "region": "东城区",
                "items": [
                    {"name": "故宫", "time_slot": "morning", "category": "sight", "notes": "建议上午先入场，参观节奏更从容。", "region": "东城区"},
                    {"name": "景山公园", "time_slot": "afternoon", "category": "sight", "notes": "适合下午登高看中轴线。", "region": "西城区"},
                    {"name": "南锣鼓巷", "time_slot": "evening", "category": "food", "notes": "适合夜间慢逛和补充小吃。", "region": "东城区"},
                ],
            },
            {
                "day": 2,
                "theme": "坛庙与胡同慢游",
                "region": "东城区",
                "items": [
                    {"name": "天坛", "time_slot": "morning", "category": "sight", "notes": "晨间游览更舒适。", "region": "东城区"},
                    {"name": "南锣鼓巷", "time_slot": "afternoon", "category": "food", "notes": "适合安排在地小吃和胡同漫步。", "region": "东城区"},
                ],
            },
            {
                "day": 3,
                "theme": "城市收尾",
                "region": "西城区",
                "items": [
                    {"name": "景山公园", "time_slot": "morning", "category": "sight", "notes": "适合作为收尾放松。", "region": "西城区"},
                ],
            },
        ]
        weather_rows = [
            {"date": "2026-04-09", "day_weather": "多云", "min_temp": 12, "max_temp": 22, "precipitation": 10, "wind_speed": 18, "risk_tags": ["temperature_gap"]},
            {"date": "2026-04-10", "day_weather": "晴", "min_temp": 13, "max_temp": 24, "precipitation": 5, "wind_speed": 12, "risk_tags": []},
            {"date": "2026-04-11", "day_weather": "多云", "min_temp": 11, "max_temp": 20, "precipitation": 20, "wind_speed": 16, "risk_tags": ["temperature_gap"]},
        ]
        packing_list = ["轻便鞋", "薄外套", "薄外套", "充电宝"]
    else:
        attraction_content = """## 杭州目的地概览
### 🌸 最佳旅行季节
- ⭐ **最佳季节**：3-5月、9-11月
- 🌡️ **气候特点**：湖景与城市漫游都适合春秋安排
- 🎫 **淡旺季**：周末和节假日西湖周边客流较集中

### 🍜 必吃美食
1. **杭帮菜** - 适合安排正餐
2. **片儿川** - 地方代表面食

### 🎁 必买特产
1. **龙井茶** - 西湖周边茶礼
2. **龙井茶** - 西湖周边茶礼
"""
        pois = [
            {"name": "西湖", "region": "西湖区", "category": "自然风光", "tags": ["湖景", "经典"]},
            {"name": "灵隐寺", "region": "西湖区", "category": "历史文化", "tags": ["寺庙", "文化"]},
            {"name": "河坊街", "region": "上城区", "category": "美食", "tags": ["老街", "美食", "夜游"]},
            {"name": "西溪湿地", "region": "西湖区", "category": "自然风光", "tags": ["湿地", "轻松"]},
        ]
        daily_plans = [
            {
                "day": 1,
                "theme": "西湖经典慢游",
                "region": "西湖区",
                "items": [
                    {"name": "西湖", "time_slot": "morning", "category": "sight", "notes": "建议把湖边步行安排在上午。", "region": "西湖区"},
                    {"name": "灵隐寺", "time_slot": "afternoon", "category": "sight", "notes": "下午安排文化体验更顺路。", "region": "西湖区"},
                    {"name": "河坊街", "time_slot": "evening", "category": "food", "notes": "晚上适合安排老街和小吃。", "region": "上城区"},
                ],
            },
            {
                "day": 2,
                "theme": "湿地与城市节奏",
                "region": "西湖区",
                "items": [
                    {"name": "西溪湿地", "time_slot": "morning", "category": "sight", "notes": "适合留足慢游时间。", "region": "西湖区"},
                    {"name": "河坊街", "time_slot": "afternoon", "category": "food", "notes": "可补充在地小吃体验。", "region": "上城区"},
                ],
            },
            {
                "day": 3,
                "theme": "城市收尾",
                "region": "西湖区",
                "items": [
                    {"name": "西湖", "time_slot": "morning", "category": "sight", "notes": "最后一天更适合轻松收尾。", "region": "西湖区"},
                ],
            },
        ]
        weather_rows = [
            {"date": "2026-04-09", "day_weather": "小雨", "min_temp": 15, "max_temp": 21, "precipitation": 70, "wind_speed": 14, "risk_tags": ["rain"]},
            {"date": "2026-04-10", "day_weather": "阴", "min_temp": 16, "max_temp": 22, "precipitation": 40, "wind_speed": 12, "risk_tags": ["rain"]},
            {"date": "2026-04-11", "day_weather": "多云", "min_temp": 14, "max_temp": 24, "precipitation": 20, "wind_speed": 10, "risk_tags": []},
        ]
        packing_list = ["轻便鞋", "雨具", "防滑鞋", "轻薄外套"]

    context.add_result(
        "attraction",
        AgentResponse(
            agent_name="attraction",
            status=AgentStatus.COMPLETED,
            content=attraction_content,
            data={
                "pois": pois,
                "attraction_summary": f"{destination} 这次行程覆盖经典景点、在地氛围与休闲收尾。",
            },
        ),
    )
    context.add_result(
        "itinerary",
        AgentResponse(
            agent_name="itinerary",
            status=AgentStatus.COMPLETED,
            content=f"第一天：{destination}深度游\n第一天：{destination}深度游\n第二天：{destination}深度游",
            data={
                "daily_plans": daily_plans,
                "days": 3,
            },
        ),
    )
    context.add_result(
        "budget",
        AgentResponse(
            agent_name="budget",
            status=AgentStatus.COMPLETED,
            content="## 预算总结与优化建议\n- 提前预订住宿和大交通\n- 提前预订住宿和大交通",
            data={
                "total_budget": 4800 if destination == "杭州" else 3200,
                "transport_cost": 900,
                "hotel_cost": 1800,
                "food_cost": 900,
                "ticket_cost": 600,
                "other_cost": 300,
                "buffer_cost": 300,
                "per_day_budget": 1600 if destination == "杭州" else 1066.67,
                "optimization_suggestions": [
                    {"category": "住宿", "suggestion": "提前预订住宿和大交通", "potential_savings": 300},
                    {"category": "住宿", "suggestion": "提前预订住宿和大交通", "potential_savings": 300},
                ],
                "day_count": 3,
            },
        ),
    )
    context.add_result(
        "weather",
        AgentResponse(
            agent_name="weather",
            status=AgentStatus.COMPLETED,
            content=f"## {destination} 天气\n- 数据来源：和风天气（QWeather）\n- 天气类型：cloudy_stable\n- 风险等级：medium",
            data={
                "destination": destination,
                "temperature_range": {"min": min(item["min_temp"] for item in weather_rows), "max": max(item["max_temp"] for item in weather_rows)},
                "daily_forecasts": weather_rows,
                "risk_tags": weather_rows[0]["risk_tags"],
                "packing_list": packing_list,
                "warnings": ["出发前请再次确认天气", "出发前请再次确认天气"],
                "alternatives": [{"condition": "rain", "action": "如遇天气变化，可优先切换室内备选方案。"}],
            },
        ),
    )
    return session, context


async def _collect_stream_output(planner: PlannerAgent, session: SessionContext, context: ExecutionContext) -> tuple[str, AgentResponse]:
    chunks: list[str] = []
    final_response = None
    async for item in planner.execute_stream(session, context):
        if isinstance(item, str):
            chunks.append(item)
        else:
            final_response = item
    assert final_response is not None
    return "".join(chunks), final_response


def test_planner_renders_rich_sections_for_beijing_and_hangzhou() -> None:
    planner = PlannerAgent(llm=None)

    for destination in ("北京", "杭州"):
        session, context = _build_context(destination)
        response = asyncio.run(planner.execute(session, context))

        assert response.status == AgentStatus.COMPLETED
        assert f"# 🧭 {destination} 旅行规划" in response.content
        assert "## 🌟 1️⃣ 目的地概览" in response.content
        assert "## 📆 2️⃣ 每日行程安排（3天）" in response.content
        assert "## 💰 3️⃣ 预算估算" in response.content
        assert "## ⚠️ 4️⃣ 实用贴士" in response.content
        assert "## 🌤️ 5️⃣ 天气信息" in response.content
        assert "| 类别 | 预计费用 | 说明 |" in response.content
        assert "| 日期 | 天气 | 温度 | 出行提示 |" in response.content
        assert "Day 1️⃣" in response.content
        assert "Day 2️⃣" in response.content
        assert "Day 3️⃣" in response.content
        assert "数据来源：和风天气（QWeather）" not in response.content
        assert "天气来源：" not in response.content
        assert "天气类型：" not in response.content
        assert "风险等级：" not in response.content
        assert response.content.count("景泰蓝工艺品") <= 1
        assert response.content.count("龙井茶") <= 1


def test_planner_execute_stream_matches_execute_output() -> None:
    planner = PlannerAgent(llm=None)
    session, context = _build_context("北京")
    execute_response = asyncio.run(planner.execute(session, context))

    stream_session, stream_context = _build_context("北京")
    streamed_text, streamed_response = asyncio.run(
        _collect_stream_output(planner, stream_session, stream_context)
    )

    assert streamed_response.status == AgentStatus.COMPLETED
    assert streamed_text == streamed_response.content
    assert streamed_response.content == execute_response.content


def _build_budget_semantics_context(
    destination: str,
    *,
    pois: list[dict],
    budget_data: dict,
    budget_content: str = "## 预算总结与优化建议\n- 提前预订住宿和大交通\n- 门票建议提前查看预约政策",
) -> tuple[SessionContext, ExecutionContext]:
    session = SessionContext(session_id=f"{destination}-budget-semantics-session")
    context = ExecutionContext(
        request_id=f"{destination}-budget-semantics-request",
        session_id=session.session_id,
    )
    context.extracted_info = {
        "destination": destination,
        "duration": 3,
        "num_travelers": 1,
        "budget_amount": 4000 if destination == "杭州" else 3000,
        "travel_styles": ["美食", "休闲"],
    }

    context.add_result(
        "attraction",
        AgentResponse(
            agent_name="attraction",
            status=AgentStatus.COMPLETED,
            content=f"## {destination} 目的地概览\n### 必吃美食\n1. 杭帮菜\n2. 小吃街",
            data={
                "pois": pois,
                "attraction_summary": f"{destination} 这次行程覆盖经典景点与城市漫游。",
            },
        ),
    )
    context.add_result(
        "itinerary",
        AgentResponse(
            agent_name="itinerary",
            status=AgentStatus.COMPLETED,
            content="Day 1\n午餐\nDay 2\n休息\nDay 3\n自由活动",
            data={
                "days": 3,
                "daily_plans": [
                    {
                        "day": 1,
                        "theme": "城市经典",
                        "region": "核心城区",
                        "items": [
                            {"name": pois[0]["name"], "time_slot": "morning", "category": "sight", "region": "核心城区"},
                        ],
                    },
                    {
                        "day": 2,
                        "theme": "慢游",
                        "region": "核心城区",
                        "items": [
                            {"name": pois[min(1, len(pois) - 1)]["name"], "time_slot": "afternoon", "category": "sight", "region": "核心城区"},
                        ],
                    },
                    {
                        "day": 3,
                        "theme": "收尾",
                        "region": "核心城区",
                        "items": [
                            {"name": pois[0]["name"], "time_slot": "evening", "category": "food", "region": "核心城区"},
                        ],
                    },
                ],
            },
        ),
    )
    context.add_result(
        "budget",
        AgentResponse(
            agent_name="budget",
            status=AgentStatus.COMPLETED,
            content=budget_content,
            data=budget_data,
        ),
    )
    context.add_result(
        "weather",
        AgentResponse(
            agent_name="weather",
            status=AgentStatus.COMPLETED,
            content=f"## {destination} 天气\n- 以多云为主",
            data={
                "destination": destination,
                "temperature_range": {"min": 15, "max": 25},
                "daily_forecasts": [
                    {"date": "2026-05-01", "day_weather": "多云", "min_temp": 15, "max_temp": 25, "precipitation": 20, "wind_speed": 8, "risk_tags": []},
                    {"date": "2026-05-02", "day_weather": "晴", "min_temp": 17, "max_temp": 26, "precipitation": 10, "wind_speed": 10, "risk_tags": []},
                    {"date": "2026-05-03", "day_weather": "多云", "min_temp": 16, "max_temp": 24, "precipitation": 15, "wind_speed": 9, "risk_tags": []},
                ],
                "risk_tags": [],
                "packing_list": ["舒适步行鞋"],
                "warnings": [],
                "alternatives": [],
            },
        ),
    )
    return session, context


def test_planner_budget_section_distinguishes_confirmed_and_pending_tickets_for_hangzhou() -> None:
    planner = PlannerAgent(llm=None)
    pois = [
        {"name": "西湖", "ticket_price": "免费", "region": "西湖区", "category": "自然风光"},
        {"name": "浙江省博物馆", "ticket_price": "免费", "region": "西湖区", "category": "文化"},
        {"name": "城市阳台", "ticket_price": "", "region": "上城区", "category": "城市漫游"},
        {"name": "钱江世纪公园", "ticket_price": "", "region": "滨江区", "category": "公园"},
        {"name": "清河坊历史文化特色街区", "ticket_price": "", "region": "上城区", "category": "老街"},
        {"name": "五柳巷历史街区", "ticket_price": "", "region": "上城区", "category": "老街"},
    ]
    budget_data = {
        "total_budget": 2150.5,
        "confirmed_total_cost": 2150.5,
        "transport_cost": 320.0,
        "hotel_cost": 980.0,
        "food_cost": 520.0,
        "ticket_cost": 0.0,
        "confirmed_ticket_cost": 0.0,
        "other_cost": 135.0,
        "buffer_cost": 195.5,
        "per_day_budget": 716.83,
        "budget_limit": 4000.0,
        "is_over_budget": False,
        "pending_ticket_count": 4,
        "pending_ticket_pois": ["城市阳台", "钱江世纪公园", "清河坊历史文化特色街区", "五柳巷历史街区"],
        "free_ticket_count": 2,
        "has_pending_ticket_cost": True,
        "optimization_suggestions": [
            {"category": "门票", "suggestion": "关注联票优惠", "potential_savings": 120},
            {"category": "住宿", "suggestion": "提前预订住宿和大交通", "potential_savings": 300},
        ],
    }

    session, context = _build_budget_semantics_context("杭州", pois=pois, budget_data=budget_data)
    response = asyncio.run(planner.execute(session, context))

    assert "景点门票（已确认）" in response.content
    assert "待确认门票" in response.content
    assert "合计（已确认）" in response.content
    assert "不含待确认门票" in response.content
    assert "当前已确认预算为" in response.content
    assert "4 个景点门票待确认" in response.content
    assert "城市阳台" in response.content
    assert "门票/体验" not in response.content
    assert "可节省约 ¥120" not in response.content
    assert "部分景点票价待确认" in response.content


def test_planner_budget_section_handles_paid_free_and_missing_tickets() -> None:
    planner = PlannerAgent(llm=None)
    pois = [
        {"name": "灵隐寺", "ticket_price": "60元", "region": "西湖区", "category": "文化"},
        {"name": "西湖", "ticket_price": "免费", "region": "西湖区", "category": "自然风光"},
        {"name": "城市阳台", "ticket_price": "", "region": "上城区", "category": "城市漫游"},
        {"name": "钱江世纪公园", "ticket_price": "", "region": "滨江区", "category": "公园"},
    ]
    budget_data = {
        "total_budget": 1782.0,
        "confirmed_total_cost": 1782.0,
        "transport_cost": 260.0,
        "hotel_cost": 760.0,
        "food_cost": 460.0,
        "ticket_cost": 60.0,
        "confirmed_ticket_cost": 60.0,
        "other_cost": 80.0,
        "buffer_cost": 162.0,
        "per_day_budget": 594.0,
        "budget_limit": 3000.0,
        "is_over_budget": False,
        "pending_ticket_count": 2,
        "pending_ticket_pois": ["城市阳台", "钱江世纪公园"],
        "free_ticket_count": 1,
        "has_pending_ticket_cost": True,
        "optimization_suggestions": [
            {"category": "门票", "suggestion": "关注联票优惠", "potential_savings": 50},
        ],
    }

    session, context = _build_budget_semantics_context("北京", pois=pois, budget_data=budget_data)
    response = asyncio.run(planner.execute(session, context))

    assert "景点门票（已确认）" in response.content
    assert "待确认门票" in response.content
    assert "合计（已确认）" in response.content
    assert "2 个景点门票待确认" in response.content
    assert "¥60" in response.content
    assert "当前已确认预算为" in response.content
    assert "可节省约 ¥50" not in response.content


def test_planner_budget_section_keeps_normal_labels_when_all_tickets_known() -> None:
    planner = PlannerAgent(llm=None)
    pois = [
        {"name": "灵隐寺", "ticket_price": "60元", "region": "西湖区", "category": "文化"},
        {"name": "雷峰塔", "ticket_price": "40元", "region": "西湖区", "category": "文化"},
        {"name": "西湖", "ticket_price": "免费", "region": "西湖区", "category": "自然风光"},
    ]
    budget_data = {
        "total_budget": 1850.0,
        "confirmed_total_cost": 1850.0,
        "transport_cost": 280.0,
        "hotel_cost": 780.0,
        "food_cost": 430.0,
        "ticket_cost": 100.0,
        "confirmed_ticket_cost": 100.0,
        "other_cost": 90.0,
        "buffer_cost": 170.0,
        "per_day_budget": 616.67,
        "budget_limit": 3000.0,
        "is_over_budget": False,
        "pending_ticket_count": 0,
        "pending_ticket_pois": [],
        "free_ticket_count": 1,
        "has_pending_ticket_cost": False,
        "optimization_suggestions": [],
    }

    session, context = _build_budget_semantics_context("杭州", pois=pois, budget_data=budget_data)
    response = asyncio.run(planner.execute(session, context))

    assert "景点门票" in response.content
    assert "景点门票（已确认）" not in response.content
    assert "待确认门票" not in response.content
    assert "合计（已确认）" not in response.content
    assert "| **合计** |" in response.content
    assert "门票/体验" not in response.content
