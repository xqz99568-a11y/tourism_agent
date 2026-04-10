"""
Budget Agent
预算分析 Agent
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.agents.base import AgentCapability, AgentConfig, AgentResponse, AgentStatus, BaseAgent
from app.core.context import ExecutionContext, SessionContext
from app.core.llm.client import LLMMessage
from app.core.logger import get_logger

logger = get_logger(__name__)


# ==================== 预算估算常量集中管理 ====================

# 预算级别默认日均消费（兜底用）
DEFAULT_DAILY_BUDGET = {
    "economy": {"min": 200, "max": 400, "label": "经济型"},
    "medium": {"min": 500, "max": 800, "label": "舒适型"},
    "luxury": {"min": 1000, "max": 3000, "label": "豪华型"},
}

# 费用构成比例（按预算级别）
EXPENSE_RATIOS = {
    "经济型": {"transport": 0.22, "hotel": 0.27, "food": 0.22, "ticket": 0.14, "other": 0.15},
    "舒适型": {"transport": 0.18, "hotel": 0.32, "food": 0.22, "ticket": 0.14, "other": 0.14},
    "豪华型": {"transport": 0.12, "hotel": 0.45, "food": 0.22, "ticket": 0.11, "other": 0.10},
}

# 住宿日均价格（按预算级别，单位：元/晚）
HOTEL_DAILY_PRICE = {
    "economy": 150,
    "medium": 400,
    "luxury": 1200,
}

# 餐饮日均价格（按预算级别，单位：元/人/天）
FOOD_DAILY_PRICE = {
    "economy": 70,
    "medium": 120,
    "luxury": 250,
}

# 交通日均价格（按预算级别，单位：元/天）
TRANSPORT_DAILY_PRICE = {
    "economy": 50,
    "medium": 120,
    "luxury": 300,
}

# 目的地消费系数
DESTINATION_FACTORS = {
    "high": 1.3,
    "major": 1.15,
    "normal": 1.0,
}

HIGH_COST_DESTINATIONS = ["三亚", "丽江", "大理", "西藏", "新疆", "漠河", "九寨沟"]
MAJOR_CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "西安", "南京", "武汉", "厦门", "青岛", "天津"]

# 缓冲资金比例
DEFAULT_BUFFER_RATIO = 0.10

# 预算上限字段名（兼容多种命名）
BUDGET_LIMIT_FIELDS = [
    "budget_amount", "budget_limit", "total_budget", "budget", "max_budget",
    "budget_max", "budgetCeiling", "upper_budget",
]

# 景点/价格相关字段名
POI_FIELDS = ["poi_list", "pois", "attractions", "items", "activities", "places", "recommended_pois"]
TICKET_PRIMARY_FIELDS = ["ticket_price_value", "ticket_price", "adult_price", "ticket_cost"]
TICKET_SECONDARY_FIELDS = ["price", "fee"]
IGNORED_TICKET_FIELDS = ["estimated_cost", "cost"]
FREE_PRICE_MARKERS = (
    "\u514d\u8d39",
    "\u514d\u7968",
    "\u65e0\u9700\u95e8\u7968",
    "free",
)
UNKNOWN_PRICE_MARKERS = (
    "\u672a\u77e5",
    "\u5f85\u786e\u8ba4",
    "\u4fe1\u606f\u5f85\u786e\u8ba4",
    "\u8be6\u8be2",
    "\u6682\u65e0",
    "unknown",
    "tbd",
    "n/a",
    "none",
)
FEN_UNIT_MARKERS = ("\u5206", "fen", "cent", "cents")

# 天气相关字段名
WEATHER_RISK_FIELDS = ["weather_type", "risk_level", "risk_tags", "warnings"]


# Agent 配置
BUDGET_CONFIG = AgentConfig(
    name="budget",
    description="预算分析 Agent，负责估算和优化旅行预算",
    instructions="""你是一个精明的旅行预算顾问，擅长帮助用户花最少的钱获得最好的旅行体验。你了解各地的消费水平，知道哪里可以省钱，哪里值得花钱。

## 核心职责

1. **预算估算**：根据目的地和天数估算合理预算
2. **费用分解**：将总预算分解到各项费用
3. **消费指导**：根据预算水平给出消费建议
4. **省钱技巧**：提供实用的省钱方法和优惠信息
5. **性价比分析**：帮助用户在预算内获得最佳体验

## 预算分级标准

### 经济型（economy）
- 每人每天：200-400元
- 住宿：青旅、民宿、经济酒店
- 餐饮：当地小吃、路摊、快餐

### 舒适型（medium）
- 每人每天：500-800元
- 住宿：三星酒店、商务酒店、精品民宿
- 餐饮：特色餐厅为主

### 豪华型（luxury）
- 每人每天：1000元以上
- 住宿：五星酒店、度假村
- 餐饮：米其林餐厅、高端餐饮

## 费用构成比例

| 费用类别 | 经济型 | 舒适型 | 豪华型 |
|----------|--------|--------|--------|
| 交通 | 20-25% | 15-20% | 10-15% |
| 住宿 | 25-30% | 30-35% | 40-50% |
| 餐饮 | 20-25% | 20-25% | 20-25% |
| 门票/娱乐 | 10-15% | 10-15% | 10-15% |
| 购物/其他 | 10-15% | 10-15% | 10-15% |

## 输出格式

```markdown
## 💰 {destination} 旅行预算分析

### 预算概览
| 预算类型 | 每日/人 | 总计({duration}天/{num_travelers}人) |
|----------|---------|-------------------------------------|
| 经济型 | 200-400元 | xxx-xxx元 |
| 舒适型 | 500-800元 | xxx-xxx元 |
| 豪华型 | 1000+元 | xxx+元 |

### 📊 每日预算细分

| 类别 | 占比 | 金额/人/天 |
|------|------|-----------|
| 交通 | 20% | xxx元 |
| 住宿 | 35% | xxx元 |
| 餐饮 | 20% | xxx元 |
| 门票/娱乐 | 15% | xxx元 |
| 购物/其他 | 10% | xxx元 |

### 🏨 住宿建议
推荐3个不同价位的住宿选择

### 🍜 餐饮建议
推荐不同价位的餐厅类型

### 💡 省钱技巧

1. **交通省钱**
   - xxx

2. **住宿省钱**
   - xxx

3. **餐饮省钱**
   - xxx

4. **门票省钱**
   - xxx
```

## 注意事项

1. **实事求是**：预算是基于实际消费水平
2. **因地制宜**：不同目的地消费水平差异大
3. **留有余地**：建议留10-15%的缓冲资金""",
    capabilities=[
        AgentCapability.CALCULATION,
        AgentCapability.REASONING,
    ],
    max_retries=3,
    timeout_seconds=30,
)


class BudgetAgent(BaseAgent):
    """
    Budget Agent
    负责预算分析和优化建议
    """

    def __init__(self, llm=None, **kwargs):
        super().__init__(BUDGET_CONFIG, llm)

    async def plan(
        self,
        session: SessionContext,
        context: ExecutionContext,
    ) -> List[str]:
        """分析任务"""
        return ["calculate_total_budget", "breakdown_expenses", "suggest_savings"]

    async def execute(
        self,
        session: SessionContext,
        context: ExecutionContext,
    ) -> AgentResponse:
        """执行预算分析任务 - 增强版"""

        destination = context.extracted_info.get("destination", "")
        duration = self._normalize_duration(context.extracted_info.get("duration"))
        num_travelers = self._normalize_travelers(
            context.extracted_info.get("num_travelers"),
            session.trip_context.num_travelers if session and session.trip_context else None
        )
        budget_level = context.extracted_info.get("budget_level", session.preferences.budget_level or "medium")
        budget_level = self._normalize_budget_level(budget_level)

        if not destination:
            return AgentResponse(
                agent_name=self.name,
                status=AgentStatus.COMPLETED,
                content="请告诉我目的地和行程天数，我可以为您估算预算。",
            )

        # 获取用户设置的预算上限
        budget_limit = self._extract_budget_limit(context.extracted_info, session)

        # 获取景点门票数据
        pois, ticket_cost, poi_source_field = self._extract_attraction_data(context)

        # 获取行程天数/区域分布
        itinerary_data = self._extract_itinerary_data(context)
        daily_plans = itinerary_data.get("daily_plans")
        duration = self._normalize_duration(itinerary_data.get("days") or context.extracted_info.get("duration"))

        # 获取天气风险数据
        weather_risks = self._extract_weather_data(context)

        # 提取用户偏好
        user_prefs = self._extract_user_preferences(context, session)

        # 获取目的地系数
        dest_factor = self._get_destination_factor(destination)

        # 判断是否基于结构化数据估算（主路径）
        has_poi_list = bool(pois)
        has_daily_plans = bool(daily_plans)
        estimated_by = "poi_list_daily_plans" if (has_poi_list and has_daily_plans) else ("poi_list" if has_poi_list else ("daily_plans" if has_daily_plans else "budget_level"))

        # 计算各项费用（优先走结构化 POI 路径）
        if has_poi_list:
            ticket_breakdown = self._build_ticket_cost_breakdown(
                pois,
                num_travelers,
                budget_level,
                source_field=poi_source_field,
            )
            computed_ticket_cost = ticket_breakdown["ticket_cost"]
        else:
            computed_ticket_cost = self._estimate_ticket_cost(ticket_cost, duration, num_travelers, pois, user_prefs)
            ticket_breakdown = {
                "ticket_cost": round(computed_ticket_cost, 2),
                "ticket_cost_per_person": round(computed_ticket_cost / max(num_travelers, 1), 2),
                "details": [],
                "summary": {
                    "fallback_applied": True,
                    "poi_source_field": poi_source_field,
                    "source": "budget_level",
                    "known_ticket_count": 0,
                    "free_ticket_count": 0,
                    "pending_confirmation_count": 0,
                    "pending_confirmation_pois": [],
                    "ignored_non_ticket_count": 0,
                },
            }

        if has_daily_plans:
            transport_cost = self._estimate_transport_cost_from_daily_plans(daily_plans, duration, num_travelers, budget_level, dest_factor, user_prefs)
            hotel_cost = self._estimate_hotel_cost_from_daily_plans(daily_plans, duration, num_travelers, budget_level, dest_factor, user_prefs)
            food_cost = self._estimate_food_cost_from_daily_plans(destination, daily_plans, duration, num_travelers, budget_level, dest_factor, user_prefs)
            other_cost = self._estimate_other_cost_from_daily_plans(daily_plans, duration, num_travelers, budget_level, dest_factor, user_prefs)
        else:
            transport_cost = self._estimate_transport_cost(duration, num_travelers, budget_level, dest_factor, weather_risks, user_prefs)
            hotel_cost = self._estimate_hotel_cost(duration, num_travelers, budget_level, dest_factor, user_prefs)
            food_cost = self._estimate_food_cost(destination, duration, num_travelers, budget_level, dest_factor, user_prefs)
            other_cost = self._estimate_other_cost(duration, num_travelers, budget_level, dest_factor, user_prefs)

        buffer_cost = self._calculate_buffer_cost(transport_cost + hotel_cost + food_cost + computed_ticket_cost + other_cost)

        # 计算总预算
        total_estimated = transport_cost + hotel_cost + food_cost + computed_ticket_cost + other_cost
        total_with_buffer = total_estimated + buffer_cost

        # 判断是否超预算
        is_over_budget = budget_limit is not None and total_with_buffer > budget_limit

        # 如果有预算限制且超预算，计算建议调整
        optimization_suggestions = []
        if is_over_budget and budget_limit:
            optimization_suggestions = self._generate_optimization_suggestions(
                total_with_buffer, budget_limit, transport_cost, hotel_cost, food_cost, computed_ticket_cost, other_cost, budget_level
            )

        # 记录详细思考过程
        budget_info = DEFAULT_DAILY_BUDGET.get(budget_level, DEFAULT_DAILY_BUDGET["medium"])
        self._record_thinking_reasoning(
            context,
            step_name="分析需求",
            reasoning_content=(
                f"💰 预算分析参数：\n"
                f"📍 目的地：{destination}\n"
                f"📅 天数：{duration}天\n"
                f"👥 人数：{num_travelers}人\n"
                f"💵 预算级别：{budget_info['label']}\n"
                f"🎯 目的地系数：{dest_factor}x"
            ),
            reasoning_type="fact",
        )

        self._record_thinking_reasoning(
            context,
            step_name="费用估算",
            reasoning_content=(
                f"📊 费用估算明细：\n"
                f"🚌 交通：{transport_cost:.0f}元\n"
                f"🏨 住宿：{hotel_cost:.0f}元\n"
                f"🍜 餐饮：{food_cost:.0f}元\n"
                f"🎫 门票：{computed_ticket_cost:.0f}元\n"
                f"🛍️ 其他：{other_cost:.0f}元\n"
                f"📦 缓冲：{buffer_cost:.0f}元\n"
                f"💰 合计：{total_with_buffer:.0f}元"
            ),
            reasoning_type="analysis",
        )

        # 设置上下文
        self._set_context_info("destination", destination)
        self._set_context_info("budget_level", budget_level)
        self._set_context_info("total_budget", int(total_with_buffer))
        self._set_context_info("per_person_budget", int(total_with_buffer // num_travelers))

        # 记录工具调用
        self._record_tool_usage(
            context,
            step_name="生成预算",
            tool_name="llm_budget_analyzer",
            arguments={"destination": destination, "duration": duration, "budget_level": budget_level},
        )

        # 构建提示词
        system_prompt = self._build_system_prompt(
            destination, duration, num_travelers, budget_level, budget_limit,
            transport_cost, hotel_cost, food_cost, computed_ticket_cost, other_cost, buffer_cost,
            total_estimated, total_with_buffer, pois, optimization_suggestions, weather_risks, ticket_breakdown
        )

        inputs_for_result = self._normalize_budget_inputs(context, session)
        messages = self.build_messages(session, system_prompt)

        try:
            # 记录省钱技巧分析
            self._record_thinking_reasoning(
                context,
                step_name="分析省钱策略",
                reasoning_content=f"💡 省钱策略分析：\n🛫 交通：关注早鸟票、联程优惠\n🏨 住宿：选择位置便利的经济型酒店\n🍜 餐饮：品尝当地小吃、避开景区餐厅\n🎫 门票：提前网上预订、关注联票优惠",
                reasoning_type="decision",
            )

            response = await self.chat(messages)

            # 记录完成
            self._record_thinking_reasoning(
                context,
                step_name="预算完成",
                reasoning_content=f"✅ 预算分析完成！\n💰 总预算：{total_with_buffer:.0f}元\n👤 人均：约{total_with_buffer // num_travelers:.0f}元/天",
                reasoning_type="decision",
            )

            result_data = self._build_budget_result(
                inputs_for_result,
                transport_cost,
                hotel_cost,
                food_cost,
                computed_ticket_cost,
                other_cost,
                buffer_cost,
                total_with_buffer,
                budget_limit,
                pois,
                daily_plans,
                optimization_suggestions,
                estimated_by,
                ticket_breakdown,
                poi_source_field,
                duration,
                num_travelers,
            )

            return AgentResponse(
                agent_name=self.name,
                status=AgentStatus.COMPLETED,
                content=response.content,
                tokens_used=response.usage.get("total_tokens", 0),
                data=result_data,
            )

        except Exception as e:
            logger.exception(f"Budget agent failed: {e}")

            # 记录失败
            self._record_thinking_complete(
                context,
                step_name="预算分析失败",
                result_summary=f"❌ 预算分析失败: {str(e)}",
            )

            return AgentResponse(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                content="",
                error=str(e),
            )

    # ==================== 私有辅助方法 ====================

    def _normalize_duration(self, duration: Any) -> int:
        """规范化天数"""
        if isinstance(duration, int):
            return max(duration, 1)
        if isinstance(duration, float):
            return max(int(duration), 1)
        if isinstance(duration, str):
            match = re.search(r"\d+", duration)
            if match:
                return max(int(match.group()), 1)
        return 3

    def _normalize_travelers(self, num_travelers: Any, session_travelers: Any) -> int:
        """规范化人数"""
        if isinstance(num_travelers, int):
            return max(num_travelers, 1)
        if isinstance(num_travelers, str):
            match = re.search(r"\d+", num_travelers)
            if match:
                return max(int(match.group()), 1)
        if session_travelers is not None:
            return max(int(session_travelers), 1)
        return 1

    def _normalize_budget_level(self, budget_level: str) -> str:
        """规范化预算级别"""
        if budget_level in DEFAULT_DAILY_BUDGET:
            return budget_level
        level_map = {
            "经济型": "economy",
            "省钱型": "economy",
            "穷游型": "economy",
            "舒适型": "medium",
            "标准型": "medium",
            "品质型": "medium",
            "豪华型": "luxury",
            "奢侈型": "luxury",
            "高端型": "luxury",
        }
        return level_map.get(budget_level, "medium")

    def _extract_budget_limit(self, extracted_info: Dict[str, Any], session: SessionContext) -> Optional[float]:
        """从多种来源提取预算上限"""
        for field in BUDGET_LIMIT_FIELDS:
            value = extracted_info.get(field)
            if value is not None:
                parsed = self._parse_number(value)
                if parsed is not None and parsed > 0:
                    return parsed

        if session and hasattr(session, "trip_context"):
            budget = getattr(session.trip_context, "budget_amount", None)
            if budget:
                return self._parse_number(budget)

        return None

    def _parse_number(self, value: Any) -> Optional[float]:
        """解析数字"""
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.strip()
            match = re.search(r"(\d+(?:\.\d+)?)", text)
            if match:
                num = float(match.group(1))
                if "万" in text:
                    num *= 10000
                return num
        return None

    def _extract_attraction_data(self, context: ExecutionContext) -> tuple[List[Dict], float, Optional[str]]:
        """提取景点门票数据。"""
        attraction_result = context.get_result("attraction")
        pois: List[Dict[str, Any]] = []
        total_ticket = 0.0
        selected_field: Optional[str] = None

        if attraction_result:
            data = getattr(attraction_result, "data", None) or {}
            if not isinstance(data, dict):
                data = {}

            pois, selected_field = self._select_poi_source_for_budget(data)

            for poi in pois:
                if not isinstance(poi, dict):
                    continue
                parsed_price = self._extract_poi_price(poi)
                if parsed_price is not None:
                    total_ticket += parsed_price

        return pois, total_ticket, selected_field

    def _select_poi_source_for_budget(self, data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        best_pois: List[Dict[str, Any]] = []
        best_field: Optional[str] = None
        best_score: Tuple[int, int, int, int] = (-1, -1, -1, -1)

        for index, field in enumerate(POI_FIELDS):
            pois_data = data.get(field)
            if not isinstance(pois_data, list) or not pois_data:
                continue

            explicit_count = 0
            ticket_like_count = 0
            dict_count = 0
            for poi in pois_data:
                if not isinstance(poi, dict):
                    continue
                dict_count += 1
                first_ticket_field = self._find_first_ticket_field(poi)
                if first_ticket_field is not None:
                    explicit_count += 1
                    ticket_like_count += 1
                elif any(poi.get(name) not in (None, "") for name in IGNORED_TICKET_FIELDS):
                    ticket_like_count += 1

            score = (explicit_count, ticket_like_count, dict_count, -index)
            if score > best_score:
                best_score = score
                best_field = field
                best_pois = [poi for poi in pois_data if isinstance(poi, dict)]

        return best_pois, best_field

    def _find_first_ticket_field(self, poi: Dict[str, Any]) -> Optional[str]:
        for field in TICKET_PRIMARY_FIELDS + TICKET_SECONDARY_FIELDS:
            if poi.get(field) not in (None, ""):
                return field
        return None

    def _is_free_price_text(self, value: Any) -> bool:
        text = str(value or "").strip().lower()
        return any(marker in text for marker in FREE_PRICE_MARKERS)

    def _is_unknown_price_text(self, value: Any) -> bool:
        text = str(value or "").strip().lower()
        return any(marker in text for marker in UNKNOWN_PRICE_MARKERS)

    def _normalize_ticket_amount(self, amount: float, unit_hint: Any) -> Tuple[float, str]:
        text = str(unit_hint or "").strip().lower()
        if any(marker in text for marker in FEN_UNIT_MARKERS) and not any(marker in text for marker in ("元", "yuan", "cny")):
            return round(amount / 100.0, 2), "fen"
        return round(amount, 2), "yuan"

    def _parse_ticket_price_value(self, value: Any) -> Tuple[Optional[float], Optional[str], str]:
        if value is None or value == "":
            return None, None, "missing"

        if isinstance(value, dict):
            amount = value.get("amount")
            unit_hint = " ".join(
                str(value.get(key) or "")
                for key in ("unit", "amount_unit", "currency_unit", "currency", "display_unit")
            ).strip()
            if amount is None:
                text_hint = " ".join(
                    str(value.get(key) or "")
                    for key in ("display", "label", "note", "description", "cost_level")
                ).strip()
                if self._is_free_price_text(text_hint):
                    return 0.0, "yuan", "free"
                if self._is_unknown_price_text(text_hint):
                    return None, None, "unknown"
                return None, None, "missing"
            parsed_amount = self._parse_number(amount)
            if parsed_amount is None:
                return None, None, "unknown" if self._is_unknown_price_text(amount) else "missing"
            parsed_yuan, unit = self._normalize_ticket_amount(parsed_amount, unit_hint)
            return parsed_yuan, unit, "free" if parsed_yuan == 0 else "known"

        if isinstance(value, (int, float)):
            amount = max(float(value), 0.0)
            return round(amount, 2), "yuan", "free" if amount == 0 else "known"

        text = str(value).strip()
        if not text:
            return None, None, "missing"
        if self._is_free_price_text(text):
            return 0.0, "yuan", "free"
        if self._is_unknown_price_text(text):
            return None, None, "unknown"

        parsed_amount = self._parse_number(text)
        if parsed_amount is None:
            return None, None, "unknown"
        parsed_yuan, unit = self._normalize_ticket_amount(parsed_amount, text)
        return parsed_yuan, unit, "free" if parsed_yuan == 0 else "known"

    def _extract_poi_price_detail(self, poi: Dict[str, Any]) -> Dict[str, Any]:
        name = str(poi.get("name") or poi.get("title") or poi.get("poi_name") or "未命名景点").strip()

        for field in TICKET_PRIMARY_FIELDS + TICKET_SECONDARY_FIELDS:
            raw_value = poi.get(field)
            if raw_value in (None, ""):
                continue
            parsed_yuan, unit, status = self._parse_ticket_price_value(raw_value)
            return {
                "name": name,
                "input_field": field,
                "input_value": raw_value,
                "input_unit": unit,
                "parsed_ticket_yuan": parsed_yuan,
                "status": status,
                "note": None if status in {"known", "free"} else "ticket price pending confirmation",
            }

        for field in IGNORED_TICKET_FIELDS:
            raw_value = poi.get(field)
            if raw_value in (None, ""):
                continue
            return {
                "name": name,
                "input_field": field,
                "input_value": raw_value,
                "input_unit": None,
                "parsed_ticket_yuan": None,
                "status": "ignored_non_ticket_field",
                "note": f"{field} is ignored because it is not a real ticket field",
            }

        return {
            "name": name,
            "input_field": None,
            "input_value": None,
            "input_unit": None,
            "parsed_ticket_yuan": None,
            "status": "missing",
            "note": "ticket price missing",
        }

    def _extract_poi_price(self, poi: Dict[str, Any]) -> Optional[float]:
        """从 POI 中提取门票价格，支持多种格式。"""
        detail = self._extract_poi_price_detail(poi)
        if detail["status"] in {"known", "free"}:
            return float(detail["parsed_ticket_yuan"] or 0.0)
        return None

    def _extract_itinerary_data(self, context: ExecutionContext) -> Dict[str, Any]:
        """提取行程数据"""
        itinerary_result = context.get_result("itinerary")
        result = {
            "days": context.extracted_info.get("duration"),
            "daily_plans": None,
            "regions": [],
            "area": None,
        }

        if itinerary_result:
            data = getattr(itinerary_result, "data", None) or {}
            if isinstance(data, dict):
                result["days"] = data.get("days") or data.get("duration") or result["days"]
                result["daily_plans"] = data.get("daily_plans") or data.get("schedule")

        return result

    def _extract_weather_data(self, context: ExecutionContext) -> Dict[str, Any]:
        """提取天气数据"""
        weather_result = context.get_result("weather")
        result = {
            "weather_type": None,
            "risk_level": None,
            "risk_tags": [],
            "warnings": [],
        }

        if weather_result:
            data = getattr(weather_result, "data", None) or {}
            if isinstance(data, dict):
                result["weather_type"] = data.get("weather_type")
                result["risk_level"] = data.get("risk_level")
                result["risk_tags"] = data.get("risk_tags") or []
                result["warnings"] = data.get("warnings") or []

        return result

    def _extract_user_preferences(self, context: ExecutionContext, session: SessionContext) -> Dict[str, Any]:
        """提取用户偏好"""
        prefs = {
            "budget_level": "medium",
            "travel_style": None,
            "hotel_level": None,
            "food_level": None,
            "transport_mode": None,
            "special_requirements": [],
        }

        extracted = context.extracted_info or {}
        prefs["budget_level"] = extracted.get("budget_level", session.preferences.budget_level if session and session.preferences else "medium") or "medium"
        prefs["travel_style"] = extracted.get("travel_style") or extracted.get("travel_styles")
        prefs["hotel_level"] = extracted.get("hotel_level")
        prefs["food_level"] = extracted.get("food_level")
        prefs["transport_mode"] = extracted.get("transport_mode")
        prefs["special_requirements"] = extracted.get("special_requirements") or []

        if session and session.preferences:
            prefs["travel_style"] = prefs["travel_style"] or session.preferences.travel_style
            prefs["hotel_level"] = prefs["hotel_level"] or getattr(session.preferences, "hotel_level", None)
            prefs["food_level"] = prefs["food_level"] or getattr(session.preferences, "food_level", None)
            prefs["transport_mode"] = prefs["transport_mode"] or getattr(session.preferences, "transport_mode", None)

        return prefs

    def _get_destination_factor(self, destination: str) -> float:
        """获取目的地消费系数"""
        if not destination:
            return 1.0
        for city in HIGH_COST_DESTINATIONS:
            if city in destination:
                return DESTINATION_FACTORS["high"]
        for city in MAJOR_CITIES:
            if city in destination:
                return DESTINATION_FACTORS["major"]
        return DESTINATION_FACTORS["normal"]

    def _get_food_destination_factor(self, destination: str) -> float:
        """获取餐饮消费的城市差异系数。"""
        if not destination:
            return 1.0

        city_factors = {
            "北京": 1.25,
            "上海": 1.30,
            "广州": 1.15,
            "深圳": 1.22,
            "杭州": 1.18,
            "成都": 0.85,
            "重庆": 0.88,
            "西安": 0.82,
            "南京": 0.95,
            "武汉": 0.90,
            "厦门": 1.12,
            "青岛": 1.00,
            "天津": 0.95,
            "泉州": 0.72,
            "洛阳": 0.70,
        }
        for city, factor in city_factors.items():
            if city in destination:
                return factor
        for city in HIGH_COST_DESTINATIONS:
            if city in destination:
                return 1.35
        for city in MAJOR_CITIES:
            if city in destination:
                return 1.05
        return 0.80

    def _estimate_transport_cost(
        self,
        duration: int,
        num_travelers: int,
        budget_level: str,
        dest_factor: float,
        weather_risks: Dict[str, Any],
        user_prefs: Dict[str, Any],
    ) -> float:
        """估算交通费用"""
        base_price = TRANSPORT_DAILY_PRICE.get(budget_level, TRANSPORT_DAILY_PRICE["medium"])

        transport_mode = user_prefs.get("transport_mode")
        if transport_mode:
            if "飞机" in str(transport_mode) or "flight" in str(transport_mode).lower():
                base_price *= 3.0
            elif "火车" in str(transport_mode) or "高铁" in str(transport_mode):
                base_price *= 1.5
            elif "自驾" in str(transport_mode) or "租车" in str(transport_mode):
                base_price *= 2.0

        if weather_risks.get("risk_level") == "high":
            base_price *= 1.2

        return base_price * duration * dest_factor

    def _estimate_hotel_cost(
        self,
        duration: int,
        num_travelers: int,
        budget_level: str,
        dest_factor: float,
        user_prefs: Dict[str, Any],
    ) -> float:
        """估算住宿费用"""
        num_rooms = max((num_travelers + 1) // 2, 1)
        base_price = HOTEL_DAILY_PRICE.get(budget_level, HOTEL_DAILY_PRICE["medium"])

        hotel_level = user_prefs.get("hotel_level")
        if hotel_level:
            if "五星" in str(hotel_level) or "豪华" in str(hotel_level):
                base_price = HOTEL_DAILY_PRICE["luxury"]
            elif "经济" in str(hotel_level) or "青旅" in str(hotel_level):
                base_price = HOTEL_DAILY_PRICE["economy"]

        hotel_days = max(duration - 1, 1)

        return base_price * num_rooms * hotel_days * dest_factor

    def _estimate_food_cost(
        self,
        destination: str,
        duration: int,
        num_travelers: int,
        budget_level: str,
        dest_factor: float,
        user_prefs: Dict[str, Any],
    ) -> float:
        """估算餐饮费用"""
        base_price = FOOD_DAILY_PRICE.get(budget_level, FOOD_DAILY_PRICE["medium"])

        food_level = user_prefs.get("food_level")
        if food_level:
            if "高档" in str(food_level) or "米其林" in str(food_level):
                base_price = FOOD_DAILY_PRICE["luxury"] * 1.5
            elif "经济" in str(food_level) or "快餐" in str(food_level):
                base_price = FOOD_DAILY_PRICE["economy"]

        food_dest_factor = self._get_food_destination_factor(destination)
        return base_price * duration * num_travelers * dest_factor * food_dest_factor

    def _estimate_ticket_cost(
        self,
        extracted_ticket: float,
        duration: int,
        num_travelers: int,
        pois: List[Dict],
        user_prefs: Dict[str, Any],
    ) -> float:
        """估算门票费用"""
        budget_level = user_prefs.get("budget_level", "medium")

        if extracted_ticket > 0 and pois:
            return extracted_ticket * num_travelers

        if pois:
            avg_ticket = extracted_ticket if extracted_ticket > 0 else 80
            estimated_tickets = min(len(pois), int(duration * 1.5))
            return avg_ticket * max(estimated_tickets, 1) * num_travelers

        fallback = {"economy": 60, "medium": 120, "luxury": 250}
        return fallback.get(budget_level, 120) * duration * num_travelers

    def _estimate_other_cost(
        self,
        duration: int,
        num_travelers: int,
        budget_level: str,
        dest_factor: float,
        user_prefs: Dict[str, Any],
    ) -> float:
        """估算其他费用（购物、娱乐等）"""
        base_prices = {"economy": 50, "medium": 100, "luxury": 250}
        base_price = base_prices.get(budget_level, 100)
        return base_price * duration * num_travelers * dest_factor

    def _generate_optimization_suggestions(
        self,
        total: float,
        budget_limit: float,
        transport: float,
        hotel: float,
        food: float,
        ticket: float,
        other: float,
        budget_level: str,
    ) -> List[Dict[str, Any]]:
        """生成预算优化建议"""
        gap = total - budget_limit
        suggestions = []

        if gap <= 0:
            return suggestions

        categories = [
            ("住宿", hotel, 0.3),
            ("餐饮", food, 0.2),
            ("交通", transport, 0.2),
            ("门票", ticket, 0.15),
            ("其他", other, 0.1),
        ]

        remaining_gap = gap
        for name, current, ratio in categories:
            if remaining_gap <= 0:
                break
            savings = min(remaining_gap * ratio, current * 0.3)
            if savings > 10:
                suggestions.append({
                    "category": name,
                    "current_cost": int(current),
                    "potential_savings": int(savings),
                    "suggestion": self._get_category_suggestion(name, budget_level),
                })
                remaining_gap -= savings

        return suggestions

    def _get_category_suggestion(self, category: str, budget_level: str) -> str:
        """获取分类优化建议"""
        suggestions = {
            "住宿": {
                "economy": "考虑经济型酒店或民宿，或选择稍远区域节省费用",
                "medium": "可考虑商务酒店或精品民宿，提前预订通常有优惠",
                "luxury": "可选择四星酒店替代五星，节省约 20-30%",
            },
            "餐饮": {
                "economy": "选择当地小吃和路边店，比餐厅便宜一半以上",
                "medium": "品尝当地特色美食，可选择午餐套餐更划算",
                "luxury": "可减少高端餐厅频次，选择特色中档餐厅",
            },
            "交通": {
                "economy": "关注早鸟票和联程优惠，使用公共交通",
                "medium": "提前预订机票火车票，选择经济舱",
                "luxury": "可考虑高铁替代短途航班，或拼车节省",
            },
            "门票": {
                "economy": "关注免费景点，使用旅游年卡或联票优惠",
                "medium": "提前网上购票，通常有 9 折优惠",
                "luxury": "可关注套票或VIP通道，避免排队",
            },
            "其他": {
                "economy": "减少购物支出，选择免费娱乐项目",
                "medium": "选择性购物，留出预算弹性",
                "luxury": "可延迟购物计划，留待返程再决定",
            },
        }
        return suggestions.get(category, {}).get(budget_level, "建议合理规划支出")

    def _build_system_prompt(
        self,
        destination: str,
        duration: int,
        num_travelers: int,
        budget_level: str,
        budget_limit: Optional[float],
        transport_cost: float,
        hotel_cost: float,
        food_cost: float,
        ticket_cost: float,
        other_cost: float,
        buffer_cost: float,
        total_estimated: float,
        total_with_buffer: float,
        pois: List[Dict],
        optimization_suggestions: List[Dict],
        weather_risks: Dict[str, Any],
        ticket_breakdown: Optional[Dict[str, Any]] = None,
    ) -> str:
        """构建系统提示词"""
        budget_info = DEFAULT_DAILY_BUDGET.get(budget_level, DEFAULT_DAILY_BUDGET["medium"])

        prompt = f"""你是一个专业的旅行预算顾问，正在为用户规划{destination}旅行的预算。

💰 基本信息：
- 目的地：{destination}
- 行程天数：{duration}天
- 出行人数：{num_travelers}人
- 预算水平：{budget_info['label']}
{f'- 预算上限：{budget_limit:.0f}元' if budget_limit else ''}

📊 基于结构化数据计算的预算明细：

| 费用类别 | 金额 | 占比 |
|----------|------|------|
| 交通 | {transport_cost:.0f}元 | {transport_cost/total_with_buffer*100:.0f}% |
| 住宿 | {hotel_cost:.0f}元 | {hotel_cost/total_with_buffer*100:.0f}% |
| 餐饮 | {food_cost:.0f}元 | {food_cost/total_with_buffer*100:.0f}% |
| 门票/娱乐 | {ticket_cost:.0f}元 | {ticket_cost/total_with_buffer*100:.0f}% |
| 购物/其他 | {other_cost:.0f}元 | {other_cost/total_with_buffer*100:.0f}% |
| 缓冲资金 | {buffer_cost:.0f}元 | {buffer_cost/total_with_buffer*100:.0f}% |
| **合计** | **{total_with_buffer:.0f}元** | 100% |

"""

        if budget_limit:
            prompt += f"\n⚠️ 注意：您设置的预算上限为 {budget_limit:.0f} 元，当前估算为 {total_with_buffer:.0f} 元"
            if total_with_buffer > budget_limit:
                prompt += f"（超出 {total_with_buffer - budget_limit:.0f} 元）。\n"
                if optimization_suggestions:
                    prompt += "\n📝 优化建议：\n"
                    for sg in optimization_suggestions[:3]:
                        prompt += f"- {sg['category']}：可节省约 {sg['potential_savings']:.0f} 元。{sg['suggestion']}\n"
            else:
                prompt += "，估算在预算范围内。\n"

        if pois:
            poi_names = [p.get("name", "") for p in pois[:5] if isinstance(p, dict)]
            if poi_names:
                prompt += f"\n📍 已规划景点：{', '.join(poi_names)}\n"

        ticket_summary = (ticket_breakdown or {}).get("summary") or {}
        pending_count = int(ticket_summary.get("pending_confirmation_count") or 0)
        ignored_count = int(ticket_summary.get("ignored_non_ticket_count") or 0)
        if pending_count or ignored_count:
            prompt += (
                "\n🧾 门票说明：当前门票合计仅统计已知票价。"
                f"待确认景点 {pending_count} 个，忽略的非门票字段 {ignored_count} 个，"
                "不会用未知门票补大额默认值。\n"
            )

        if weather_risks.get("risk_tags"):
            prompt += f"\n🌤️ 天气风险提示：{', '.join(weather_risks['risk_tags'])}，可能影响交通和行程安排。\n"

        prompt += """
请用 Markdown 格式输出，包含：
1. 预算总结和评价
2. 分项费用的合理性说明
3. 针对超预算情况的优化建议
4. 实用的省钱技巧

请保持专业、简洁、实用的风格。"""

        return prompt

    def _calculate_expense_breakdown(self, budget_level: str, duration: int, num_travelers: int) -> str:
        """计算费用分解（兼容旧方法）"""
        ratios = EXPENSE_RATIOS.get(budget_level, EXPENSE_RATIOS["舒适型"])
        total = sum(ratios.values())
        parts = []
        for category, ratio in ratios.items():
            display_ratio = ratio / total * 100
            category_cn = {
                "transport": "交通",
                "hotel": "住宿",
                "food": "餐饮",
                "ticket": "门票/娱乐",
                "other": "购物/其他",
            }.get(category, category)
            parts.append(f"🚗 {category_cn}：{display_ratio:.0f}%")
        return "\n".join(parts)

    def _normalize_budget_inputs(self, context: ExecutionContext, session: SessionContext) -> Dict[str, Any]:
        """兼容读取上游输入字段。"""
        extracted = context.extracted_info or {}
        session_ctx = session.trip_context if session else None
        session_prefs = session.preferences if session else None
        result: Dict[str, Any] = {
            "destination": str(extracted.get("destination") or "").strip(),
            "duration": self._normalize_duration(extracted.get("duration")),
            "num_travelers": self._normalize_travelers(extracted.get("num_travelers"), session_ctx.num_travelers if session_ctx else None),
            "budget_level": self._normalize_budget_level(extracted.get("budget_level") or (session_prefs.budget_level if session_prefs else "medium") or "medium"),
            "budget_amount": extracted.get("budget_amount"),
            "budget_limit": extracted.get("budget_limit"),
            "total_budget": extracted.get("total_budget"),
            "budget": extracted.get("budget"),
            "max_budget": extracted.get("max_budget"),
            "travel_style": self._normalize_list(extracted.get("travel_style")),
            "group_type": str(extracted.get("group_type") or "").strip(),
            "special_requirements": self._normalize_list(extracted.get("special_requirements")),
            "hotel_level": str(extracted.get("hotel_level") or "").strip(),
            "food_level": str(extracted.get("food_level") or "").strip(),
            "transport_mode": str(extracted.get("transport_mode") or "").strip(),
            "daily_plans_input": extracted.get("daily_plans"),
        }
        return result

    def _normalize_list(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return [str(value).strip()]

    def _extract_trip_days(self, inputs: Dict[str, Any]) -> int:
        days = inputs.get("duration") or 3
        try:
            return int(days)
        except (ValueError, TypeError):
            return 3

    def _extract_budget_limit_from_inputs(self, inputs: Dict[str, Any]) -> Optional[float]:
        """从 inputs 中提取预算上限。"""
        for field in ["budget_amount", "budget_limit", "total_budget", "budget", "max_budget"]:
            value = inputs.get(field)
            if value is not None:
                parsed = self._parse_number(value)
                if parsed is not None and parsed > 0:
                    return parsed
        return None

    def _build_ticket_cost_breakdown(
        self,
        pois: List[Dict[str, Any]],
        num_travelers: int,
        budget_level: str,
        source_field: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not pois:
            fallback = {"economy": 60, "medium": 120, "luxury": 250}
            fallback_cost = fallback.get(budget_level, 120) * max(num_travelers, 1)
            return {
                "ticket_cost": round(fallback_cost, 2),
                "ticket_cost_per_person": round(fallback_cost / max(num_travelers, 1), 2),
                "details": [],
                "summary": {
                    "fallback_applied": True,
                    "poi_source_field": source_field,
                    "source": "budget_level",
                    "known_ticket_count": 0,
                    "free_ticket_count": 0,
                    "pending_confirmation_count": 0,
                    "pending_confirmation_pois": [],
                    "ignored_non_ticket_count": 0,
                },
            }

        per_person_total = 0.0
        details: List[Dict[str, Any]] = []
        known_count = 0
        free_count = 0
        pending_count = 0
        pending_names: List[str] = []
        ignored_count = 0

        for poi in pois:
            if not isinstance(poi, dict):
                continue

            detail = self._extract_poi_price_detail(poi)
            status = detail["status"]
            counted_amount = 0.0

            if status == "known":
                counted_amount = float(detail["parsed_ticket_yuan"] or 0.0)
                per_person_total += counted_amount
                known_count += 1
            elif status == "free":
                free_count += 1
            elif status == "ignored_non_ticket_field":
                ignored_count += 1
            else:
                pending_count += 1
                if detail.get("name"):
                    pending_names.append(str(detail["name"]))

            detail["counted_amount_yuan"] = round(counted_amount, 2)
            detail["cumulative_per_person_yuan"] = round(per_person_total, 2)
            detail["cumulative_group_yuan"] = round(per_person_total * max(num_travelers, 1), 2)
            details.append(detail)

        return {
            "ticket_cost": round(per_person_total * max(num_travelers, 1), 2),
            "ticket_cost_per_person": round(per_person_total, 2),
            "details": details,
            "summary": {
                "fallback_applied": False,
                "poi_source_field": source_field,
                "source": "poi_ticket_fields",
                "known_ticket_count": known_count,
                "free_ticket_count": free_count,
                "pending_confirmation_count": pending_count,
                "pending_confirmation_pois": pending_names,
                "ignored_non_ticket_count": ignored_count,
            },
        }

    def _estimate_ticket_cost_from_poi_list(
        self,
        pois: List[Dict[str, Any]],
        duration: int,
        num_travelers: int,
        budget_level: str,
    ) -> float:
        """优先基于 poi_list 估算门票费用。"""
        return float(
            self._build_ticket_cost_breakdown(
                pois,
                num_travelers,
                budget_level,
            )["ticket_cost"]
        )

    def _estimate_transport_cost_from_daily_plans(
        self,
        daily_plans: Optional[List[Any]],
        duration: int,
        num_travelers: int,
        budget_level: str,
        dest_factor: float,
        user_prefs: Dict[str, Any],
    ) -> float:
        """基于 daily_plans 估算交通费用。"""
        if daily_plans:
            regions = set()
            for plan in daily_plans:
                if isinstance(plan, dict):
                    region = plan.get("region")
                    if region:
                        regions.add(str(region))
                    for item in plan.get("items", []):
                        if isinstance(item, dict) and item.get("region"):
                            regions.add(str(item["region"]))
            num_regions = len(regions) if regions else 1
            inter_region_trips = max(num_regions - 1, 0)
            base_inter = 150.0 * dest_factor
            intra_daily = duration * 50 * dest_factor
            return (base_inter * inter_region_trips + intra_daily) * num_travelers
        return self._estimate_transport_cost(duration, num_travelers, budget_level, dest_factor, {}, user_prefs)

    def _estimate_hotel_cost_from_daily_plans(
        self,
        daily_plans: Optional[List[Any]],
        duration: int,
        num_travelers: int,
        budget_level: str,
        dest_factor: float,
        user_prefs: Dict[str, Any],
    ) -> float:
        """基于 daily_plans 估算住宿费用。"""
        num_rooms = max((num_travelers + 1) // 2, 1)
        base_price = HOTEL_DAILY_PRICE.get(budget_level, HOTEL_DAILY_PRICE["medium"])
        hotel_level = user_prefs.get("hotel_level")
        if hotel_level:
            if "五星" in str(hotel_level) or "豪华" in str(hotel_level):
                base_price = HOTEL_DAILY_PRICE["luxury"]
            elif "经济" in str(hotel_level) or "青旅" in str(hotel_level):
                base_price = HOTEL_DAILY_PRICE["economy"]
        hotel_days = max(duration - 1, 1)
        return base_price * num_rooms * hotel_days * dest_factor

    def _estimate_food_cost_from_daily_plans(
        self,
        destination: str,
        daily_plans: Optional[List[Any]],
        duration: int,
        num_travelers: int,
        budget_level: str,
        dest_factor: float,
        user_prefs: Dict[str, Any],
    ) -> float:
        """基于 daily_plans 估算餐饮费用。"""
        base_price = FOOD_DAILY_PRICE.get(budget_level, FOOD_DAILY_PRICE["medium"])
        food_level = user_prefs.get("food_level")
        if food_level:
            if "高档" in str(food_level) or "米其林" in str(food_level):
                base_price = FOOD_DAILY_PRICE["luxury"] * 1.5
            elif "经济" in str(food_level) or "快餐" in str(food_level):
                base_price = FOOD_DAILY_PRICE["economy"]
        food_dest_factor = self._get_food_destination_factor(destination)
        return base_price * duration * num_travelers * dest_factor * food_dest_factor

    def _estimate_other_cost_from_daily_plans(
        self,
        daily_plans: Optional[List[Any]],
        duration: int,
        num_travelers: int,
        budget_level: str,
        dest_factor: float,
        user_prefs: Dict[str, Any],
    ) -> float:
        """基于 daily_plans 估算其他费用。"""
        base_prices = {"economy": 50, "medium": 100, "luxury": 250}
        base_price = base_prices.get(budget_level, 100)
        return base_price * duration * num_travelers * dest_factor

    def _calculate_buffer_cost(self, total: float) -> float:
        """基于总费用计算缓冲资金。"""
        return total * DEFAULT_BUFFER_RATIO

    def _is_over_budget(self, total_with_buffer: float, budget_limit: Optional[float]) -> bool:
        """判断是否超预算。"""
        return budget_limit is not None and total_with_buffer > budget_limit

    def _build_budget_result(
        self,
        inputs: Dict[str, Any],
        transport_cost: float,
        hotel_cost: float,
        food_cost: float,
        ticket_cost: float,
        other_cost: float,
        buffer_cost: float,
        total_with_buffer: float,
        budget_limit: Optional[float],
        pois: List[Dict[str, Any]],
        daily_plans: Optional[List[Any]],
        optimization_suggestions: List[Dict[str, Any]],
        estimated_by: str,
        ticket_breakdown: Dict[str, Any],
        poi_source_field: Optional[str],
        duration: int,
        num_travelers: int,
    ) -> Dict[str, Any]:
        """构建完整的结构化预算结果。"""
        per_day_total = total_with_buffer / max(duration, 1)
        per_day_per_person = total_with_buffer / max(duration, 1) / max(num_travelers, 1)
        budget_gap = None
        if budget_limit is not None:
            budget_gap = round(total_with_buffer - budget_limit, 2) if total_with_buffer > budget_limit else 0.0
        applied_rules = []
        if pois:
            applied_rules.append("poi_list_price_extraction")
        if daily_plans:
            applied_rules.append("daily_plans_based_estimation")
        if not pois and not daily_plans:
            applied_rules.append("budget_level_fallback")
        ticket_summary = ticket_breakdown.get("summary") or {}
        if ticket_summary.get("pending_confirmation_count"):
            applied_rules.append("ticket_known_prices_only")
        if ticket_summary.get("ignored_non_ticket_count"):
            applied_rules.append("ignored_non_ticket_fields")
        pending_ticket_count = int(ticket_summary.get("pending_confirmation_count") or 0)
        pending_ticket_pois = [
            str(name).strip()
            for name in (ticket_summary.get("pending_confirmation_pois") or [])
            if str(name).strip()
        ]
        result: Dict[str, Any] = {
            "budget_level": inputs.get("budget_level") or "medium",
            "total_budget": round(total_with_buffer, 2),
            "confirmed_total_cost": round(total_with_buffer, 2),
            "per_person_budget": round(total_with_buffer / max(num_travelers, 1), 2),
            "daily_budget": round(total_with_buffer / max(duration, 1), 2),
            "per_day_budget": round(per_day_total, 2),
            "per_day_per_person_budget": round(per_day_per_person, 2),
            "transport_cost": round(transport_cost, 2),
            "hotel_cost": round(hotel_cost, 2),
            "food_cost": round(food_cost, 2),
            "ticket_cost": round(ticket_cost, 2),
            "confirmed_ticket_cost": round(ticket_cost, 2),
            "other_cost": round(other_cost, 2),
            "buffer_cost": round(buffer_cost, 2),
            "is_over_budget": self._is_over_budget(total_with_buffer, budget_limit),
            "budget_limit": budget_limit,
            "budget_gap": budget_gap,
            "estimated_by": estimated_by,
            "ticket_poi_source_field": poi_source_field,
            "ticket_cost_per_person": round(ticket_breakdown.get("ticket_cost_per_person") or 0.0, 2),
            "confirmed_ticket_cost_per_person": round(ticket_breakdown.get("ticket_cost_per_person") or 0.0, 2),
            "ticket_cost_details": ticket_breakdown.get("details") or [],
            "ticket_cost_summary": ticket_summary,
            "pending_ticket_count": pending_ticket_count,
            "pending_ticket_pois": pending_ticket_pois,
            "has_pending_ticket_cost": pending_ticket_count > 0,
            "free_ticket_count": int(ticket_summary.get("free_ticket_count") or 0),
            "known_ticket_count": int(ticket_summary.get("known_ticket_count") or 0),
            "ignored_non_ticket_count": int(ticket_summary.get("ignored_non_ticket_count") or 0),
            "budget_breakdown": {
                "transport": round(transport_cost, 2),
                "hotel": round(hotel_cost, 2),
                "food": round(food_cost, 2),
                "ticket": round(ticket_cost, 2),
                "other": round(other_cost, 2),
                "buffer": round(buffer_cost, 2),
            },
            "optimization_suggestions": optimization_suggestions,
        }
        if pois:
            result["poi_count"] = len(pois)
            result["avg_ticket_per_poi"] = round(ticket_cost / max(len(pois), 1) / max(num_travelers, 1), 2)
        result["duration"] = duration
        result["num_travelers"] = num_travelers
        result["day_count"] = len(daily_plans) if daily_plans else duration
        if daily_plans:
            result["regions"] = list(set(
                str(plan.get("region") or "") for plan in daily_plans if isinstance(plan, dict)
            ))
        result["applied_rules"] = applied_rules
        result["applied_preferences"] = {
            "budget_level": inputs.get("budget_level"),
            "travel_style": inputs.get("travel_style") or [],
            "hotel_level": inputs.get("hotel_level") or None,
            "food_level": inputs.get("food_level") or None,
            "transport_mode": inputs.get("transport_mode") or None,
        }
        return result
