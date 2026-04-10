"""
Review Agent
结果审查 Agent
负责审查和优化其他 Agent 的结果
支持 review_only / review_and_fix 两种模式
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional

from app.agents.base import AgentCapability, AgentConfig, AgentResponse, AgentStatus, BaseAgent
from app.core.context import ExecutionContext, SessionContext
from app.core.llm.client import LLMMessage
from app.core.logger import get_logger

logger = get_logger(__name__)


class ReviewMode(str, Enum):
    """Review 模式枚举"""
    REVIEW_ONLY = "review_only"     # 只做审查，不修正
    REVIEW_AND_FIX = "review_and_fix"  # 审查 + 轻量修正


# ==================== 评分常量 ====================

# 评分维度权重
SCORE_WEIGHTS = {
    "completeness": 0.25,
    "consistency": 0.20,
    "feasibility": 0.25,
    "personalization": 0.15,
    "constraint_satisfaction": 0.15,
}

# 评分范围
SCORE_MIN = 0
SCORE_MAX = 10

# 完整性检查项
COMPLETENESS_CHECKS = [
    ("destination", "目的地介绍", ["目的地", "城市", "简介", "特色"]),
    ("daily_plans", "每日行程", ["Day", "第", "天", "上午", "下午", "晚上"]),
    ("attractions", "景点推荐", ["景点", "景区", "推荐", "游览"]),
    ("budget", "预算分析", ["预算", "费用", "花费", "价格"]),
    ("weather", "天气预报", ["天气", "温度", "晴", "雨", "气温"]),
    ("tips", "实用贴士", ["注意", "建议", "贴士", "提示"]),
]

# 一致性检查关键词
CONSISTENCY_KEYWORDS = [
    "冲突", "矛盾", "不一致", "矛盾", "重复",
]

# 可行性检查关键词
FEASIBILITY_KEYWORDS = [
    "合理", "可行", "合适", "适中",
    "过多", "过少", "太长", "疲劳", "冲突",
]


# Agent 配置
REVIEW_CONFIG = AgentConfig(
    name="review",
    description="结果审查 Agent，负责审查和优化规划结果",
    instructions="""你是一个严格的质量审查员，拥有10年旅游行业经验。你对旅行规划有着近乎苛刻的要求，任何一个细节的疏漏都逃不过你的眼睛。

## 核心职责

1. **完整性检查**：确保规划包含所有必要内容
2. **一致性检查**：确保各部分信息协调统一
3. **可行性检查**：确保行程安排合理可行
4. **个性化检查**：确保规划符合用户需求
5. **优化建议**：发现问题并提供改进方案

## 审查标准

### 完整性标准（必须包含）
- [ ] 目的地介绍
- [ ] 每日行程安排
- [ ] 景点推荐及理由
- [ ] 预算估算明细
- [ ] 天气预报（如适用）
- [ ] 实用贴士和注意事项

### 一致性标准
- [ ] 景点数量与天数匹配
- [ ] 行程时间无冲突
- [ ] 预算与风格一致
- [ ] 交通方式前后一致
- [ ] 餐饮安排合理

### 可行性标准
- [ ] 每天景点数量合理（2-4个）
- [ ] 景点间交通时间合理
- [ ] 考虑了开放时间和预约
- [ ] 留有休息和用餐时间
- [ ] 无过度疲劳的安排

## 评分体系

| 维度 | 8-10分 | 5-7分 | 1-4分 |
|------|--------|-------|-------|
| 内容质量 | 详尽专业 | 基本完整 | 缺失较多 |
| 实用性 | 具体可操作 | 较模糊 | 难以执行 |
| 个性化 | 高度匹配 | 有待提高 | 模板化 |

## 输出格式

```markdown
## 📋 旅行规划质量审查报告

### ✅ 完整性检查

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 目的地介绍 | ✅ 通过 | xxx |
| 每日行程 | ⚠️ 建议补充 | 缺少xxx |

### ⚠️ 一致性问题

| 问题 | 位置 | 建议 |
|------|------|------|
| 时间冲突 | 第2天下午 | 调整游览顺序 |

### 🎯 可行性分析

| 日期 | 景点数 | 游览时长 | 评估 |
|------|--------|----------|------|
| 第1天 | 3个 | 6小时 | ⭐⭐⭐⭐ 合理 |

### 📊 质量评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 内容质量 | X/10 | xxx |
| 实用性 | X/10 | xxx |
| 个性化 | X/10 | xxx |

### 💡 优化建议
1. 必须改进：xxx
2. 建议优化：xxx

### ✨ 最终评价
[整体评价]
```""",
    capabilities=[
        AgentCapability.REASONING,
        AgentCapability.REVIEW,
    ],
    max_retries=2,
    timeout_seconds=30,
)


class ReviewAgent(BaseAgent):
    """
    Review Agent
    负责审查和优化其他 Agent 的结果
    支持 review_only 和 review_and_fix 两种模式
    """

    def __init__(self, llm=None, **kwargs):
        super().__init__(REVIEW_CONFIG, llm)

    async def plan(
        self,
        session: SessionContext,
        context: ExecutionContext,
    ) -> List[str]:
        """分析审查任务"""
        return ["collect_results", "quality_check", "generate_improvements"]

    async def execute(
        self,
        session: SessionContext,
        context: ExecutionContext,
    ) -> AgentResponse:
        """
        执行审查任务

        Args:
            session: 会话上下文
            context: 执行上下文（mode 从 context.extracted_info.get("review_mode") 获取）
        """
        # 从 context 获取模式（支持实验配置）
        mode = context.extracted_info.get("review_mode", "review_only") if context.extracted_info else "review_only"
        
        # 规范化模式
        if mode == ReviewMode.REVIEW_AND_FIX.value:
            review_mode = ReviewMode.REVIEW_AND_FIX
        else:
            review_mode = ReviewMode.REVIEW_ONLY

        # 收集所有 Agent 的结果
        agent_results = context.agent_results

        if not agent_results:
            return self._build_empty_response(review_mode)

        # 收集审查数据
        review_data = self._collect_review_data(agent_results, context)

        if not review_data["has_content"]:
            return self._build_empty_response(review_mode)

        # 执行评分
        scores = self._calculate_scores(review_data)

        # 收集问题和建议
        issues = self._collect_issues(review_data, scores)
        warnings = self._collect_warnings(review_data, scores)
        suggestions = self._collect_suggestions(review_data, scores, issues)

        # 根据模式决定是否修正
        fixed_result = None
        has_been_fixed = False

        if review_mode == ReviewMode.REVIEW_AND_FIX and self._needs_fix(issues, warnings):
            fixed_result, has_been_fixed = self._apply_review_fixes(
                agent_results, review_data, issues, warnings, suggestions, session, context
            )

        # 构建报告内容
        report_content = self._build_review_report(review_data, scores, issues, warnings, suggestions, review_mode)

        # 构建返回数据
        data = self._build_review_data(
            review_mode, scores, issues, warnings, suggestions,
            has_been_fixed, fixed_result, agent_results, review_data
        )

        return AgentResponse(
            agent_name=self.name,
            status=AgentStatus.COMPLETED,
            content=report_content,
            tokens_used=0,
            data=data,
        )

    # ==================== 私有辅助方法 ====================

    def _normalize_review_input(self, content: Any) -> str:
        """规范化输入内容"""
        if not content:
            return ""
        return str(content).strip()

    def _normalize_list(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return [str(value).strip()]

    def _extract_structured_results(self, agent_results: Dict[str, Any]) -> Dict[str, Any]:
        """从 agent_results 中提取结构化数据。"""
        result: Dict[str, Any] = {
            "attraction": {},
            "itinerary": {},
            "budget": {},
            "weather": {},
            "planner": {},
        }
        for agent_name, result_obj in agent_results.items():
            if not result_obj:
                continue
            data = getattr(result_obj, "data", None) or {}
            if isinstance(data, dict):
                if agent_name in result:
                    result[agent_name] = data
                else:
                    result[agent_name] = data
        return result

    def _extract_daily_plans(self, structured: Dict[str, Any]) -> Optional[List[Any]]:
        """从结构化数据中提取 daily_plans。"""
        itinerary = structured.get("itinerary", {})
        daily_plans = itinerary.get("daily_plans")
        if isinstance(daily_plans, list):
            return daily_plans
        schedule = itinerary.get("schedule")
        if isinstance(schedule, list):
            return schedule
        optimized_plan = itinerary.get("optimized_plan")
        if isinstance(optimized_plan, list):
            return optimized_plan
        return None

    def _extract_poi_list(self, structured: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从结构化数据中提取 POI 列表。"""
        attraction = structured.get("attraction", {})
        for field in ["poi_list", "pois", "recommended_pois", "attractions", "items", "activities"]:
            pois = attraction.get(field)
            if isinstance(pois, list):
                return [p for p in pois if isinstance(p, dict)]
        return []

    def _extract_budget_data(self, structured: Dict[str, Any]) -> Dict[str, Any]:
        """从结构化数据中提取预算数据。"""
        budget = structured.get("budget", {})
        if not isinstance(budget, dict):
            return {}
        return {
            "total_budget": budget.get("total_budget"),
            "budget_limit": budget.get("budget_limit"),
            "per_day_budget": budget.get("per_day_budget"),
            "ticket_cost": budget.get("ticket_cost"),
            "hotel_cost": budget.get("hotel_cost"),
            "food_cost": budget.get("food_cost"),
            "transport_cost": budget.get("transport_cost"),
            "other_cost": budget.get("other_cost"),
            "is_over_budget": budget.get("is_over_budget"),
            "budget_breakdown": budget.get("budget_breakdown"),
            "budget_level": budget.get("budget_level"),
        }

    def _extract_weather_data(self, structured: Dict[str, Any]) -> Dict[str, Any]:
        """从结构化数据中提取天气数据。"""
        weather = structured.get("weather", {})
        if not isinstance(weather, dict):
            return {}
        return {
            "weather_type": weather.get("weather_type"),
            "daily_forecasts": weather.get("daily_forecasts"),
            "forecast": weather.get("forecast"),
            "warnings": weather.get("warnings") or [],
            "risk_level": weather.get("risk_level"),
        }

    def _extract_preferences(self, structured: Dict[str, Any]) -> Dict[str, Any]:
        """从结构化数据中提取用户偏好。"""
        extracted: Dict[str, Any] = {}
        for agent_name in ["attraction", "itinerary", "budget"]:
            agent_data = structured.get(agent_name, {})
            if isinstance(agent_data, dict):
                prefs = agent_data.get("applied_preferences") or agent_data.get("preferences") or {}
                if isinstance(prefs, dict):
                    if not extracted:
                        extracted = dict(prefs)
                    else:
                        for k, v in prefs.items():
                            if k not in extracted or not extracted[k]:
                                extracted[k] = v
        return extracted

    def _extract_destination_info(self, structured: Dict[str, Any]) -> Dict[str, Any]:
        """从结构化数据中提取目的地信息。"""
        result: Dict[str, Any] = {}
        for agent_name in ["attraction", "itinerary", "budget", "planner"]:
            agent_data = structured.get(agent_name, {})
            if isinstance(agent_data, dict):
                dest = agent_data.get("destination") or agent_data.get("city")
                if dest and "destination" not in result:
                    result["destination"] = str(dest).strip()
                region = agent_data.get("region") or agent_data.get("area") or agent_data.get("district")
                if region and "region" not in result:
                    result["region"] = str(region).strip()
        return result

    def _collect_review_data(self, agent_results: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        """收集审查数据（含结构化信息）"""
        result = {
            "has_content": False,
            "agent_contents": {},
            "agent_data": {},
            "planner_content": "",
            "attraction_content": "",
            "itinerary_content": "",
            "budget_content": "",
            "weather_content": "",
            "all_text": "",
            "structured": {},
            "daily_plans": None,
            "poi_list": [],
            "budget_data": {},
            "weather_data": {},
            "preferences": {},
            "destination_info": {},
            "duration": None,
            "trip_days": None,
        }

        structured = self._extract_structured_results(agent_results)
        result["structured"] = structured
        result["daily_plans"] = self._extract_daily_plans(structured)
        result["poi_list"] = self._extract_poi_list(structured)
        result["budget_data"] = self._extract_budget_data(structured)
        result["weather_data"] = self._extract_weather_data(structured)
        result["preferences"] = self._extract_preferences(structured)
        result["destination_info"] = self._extract_destination_info(structured)

        itinerary_struct = structured.get("itinerary", {})
        result["duration"] = itinerary_struct.get("duration") or itinerary_struct.get("days") or itinerary_struct.get("day_count")
        result["trip_days"] = itinerary_struct.get("trip_days") or result["duration"]

        for agent_name, result_obj in agent_results.items():
            if not result_obj:
                continue

            content = self._normalize_review_input(getattr(result_obj, "content", None))
            data = getattr(result_obj, "data", None) or {}

            if content:
                result["has_content"] = True
                result["agent_contents"][agent_name] = content
                result["all_text"] += content + "\n"

                if agent_name == "planner":
                    result["planner_content"] = content
                elif agent_name == "attraction":
                    result["attraction_content"] = content
                elif agent_name == "itinerary":
                    result["itinerary_content"] = content
                elif agent_name == "budget":
                    result["budget_content"] = content
                elif agent_name == "weather":
                    result["weather_content"] = content

            if data:
                result["agent_data"][agent_name] = data

        return result

    def _score_completeness(self, review_data: Dict[str, Any]) -> float:
        """评分：完整性（基于结构化数据）"""
        score = 6.0
        all_text = review_data.get("all_text", "")
        daily_plans = review_data.get("daily_plans")
        poi_list = review_data.get("poi_list") or []
        budget_data = review_data.get("budget_data") or {}
        destination_info = review_data.get("destination_info") or {}
        weather_data = review_data.get("weather_data") or {}

        checked = 0
        total_checks = 5

        if destination_info.get("destination") or "destination" in review_data.get("agent_data", {}).get("attraction", {}):
            checked += 1
        elif self._check_keywords_in_text(all_text, ["目的地", "城市", "简介", "特色"]):
            checked += 1

        if daily_plans and isinstance(daily_plans, list) and len(daily_plans) > 0:
            checked += 1
        elif self._check_keywords_in_text(all_text, ["Day", "第", "天", "上午", "下午", "晚上"]):
            checked += 1

        if poi_list and len(poi_list) > 0:
            checked += 1
        elif self._check_keywords_in_text(all_text, ["景点", "景区", "推荐", "游览"]):
            checked += 1

        if budget_data.get("total_budget") or budget_data.get("per_day_budget"):
            checked += 1
        elif self._check_keywords_in_text(all_text, ["预算", "费用", "花费", "价格"]):
            checked += 1

        if weather_data.get("weather_type") or weather_data.get("daily_forecasts"):
            checked += 1
        elif weather_data.get("warnings"):
            checked += 1
        elif weather_data.get("risk_level"):
            checked += 0.5
        elif not self._check_keywords_in_text(all_text, ["天气", "温度", "晴", "雨"]):
            checked += 0.5

        ratio = checked / total_checks
        if ratio >= 0.9:
            score = 9.0
        elif ratio >= 0.7:
            score = 7.5
        elif ratio >= 0.5:
            score = 6.0
        elif ratio >= 0.3:
            score = 4.0
        else:
            score = 2.0

        return round(max(min(score, SCORE_MAX), SCORE_MIN), 1)

    def _score_consistency(self, review_data: Dict[str, Any]) -> float:
        """评分：一致性（基于结构化数据）"""
        score = 8.0
        all_text = review_data.get("all_text", "")
        daily_plans = review_data.get("daily_plans")
        budget_data = review_data.get("budget_data") or {}
        duration = review_data.get("duration") or review_data.get("trip_days")
        poi_list = review_data.get("poi_list") or []

        conflict_count = sum(1 for kw in CONSISTENCY_KEYWORDS if kw in all_text)
        if conflict_count > 3:
            score = 4.0
        elif conflict_count > 1:
            score = 6.0
        elif conflict_count > 0:
            score = 7.0

        if daily_plans and isinstance(daily_plans, list):
            num_plans = len(daily_plans)
            if duration:
                try:
                    declared_days = int(duration)
                    if abs(num_plans - declared_days) > 1:
                        score = min(score, 6.0)
                except (ValueError, TypeError):
                    pass

        day_patterns = re.findall(r"第?\s*([一二三四五六七八九十\d]+)\s*天", all_text)
        if len(set(day_patterns)) != len(day_patterns) and len(day_patterns) > 1:
            score = min(score, 6.0)

        if budget_data.get("total_budget") and budget_data["total_budget"] > 0:
            score = min(score + 0.5, SCORE_MAX)
        if poi_list and len(poi_list) > 0 and daily_plans and len(daily_plans) > 0:
            total_items = sum(len(plan.get("items", [])) if isinstance(plan, dict) else 0 for plan in daily_plans)
            if total_items > 0 and len(poi_list) > 0:
                score = min(score + 0.5, SCORE_MAX)

        return round(max(min(score, SCORE_MAX), SCORE_MIN), 1)

    def _score_feasibility(self, review_data: Dict[str, Any]) -> float:
        """评分：可行性（基于结构化数据）"""
        score = 7.0
        all_text = review_data.get("all_text", "")
        daily_plans = review_data.get("daily_plans")

        feasible_count = sum(1 for kw in FEASIBILITY_KEYWORDS[:4] if kw in all_text)
        infeasible_count = sum(1 for kw in FEASIBILITY_KEYWORDS[4:] if kw in all_text)
        score = 7.0 + feasible_count * 0.5 - infeasible_count * 1.0

        if daily_plans and isinstance(daily_plans, list):
            poi_counts = []
            for plan in daily_plans:
                if isinstance(plan, dict):
                    items = plan.get("items", [])
                    if isinstance(items, list):
                        poi_count = sum(
                            1 for item in items
                            if isinstance(item, dict) and item.get("name")
                            and item.get("name") not in ["午餐 / 休息", "晚餐 / 休息", "备选景点（未排入）"]
                        )
                        poi_counts.append(poi_count)
            if poi_counts:
                avg_pois = sum(poi_counts) / len(poi_counts)
                if avg_pois < 1 or avg_pois > 5:
                    score -= 1.0
                if max(poi_counts) > 4:
                    score -= 0.5

        if "午餐" in all_text or "早餐" in all_text or "晚餐" in all_text:
            score = min(score + 0.5, SCORE_MAX)

        return round(max(min(score, SCORE_MAX), SCORE_MIN), 1)

    def _score_personalization(self, review_data: Dict[str, Any]) -> float:
        """评分：个性化（基于结构化数据）"""
        score = 6.0
        all_text = review_data.get("all_text", "")
        agent_data = review_data.get("agent_data", {})
        preferences = review_data.get("preferences") or {}
        poi_list = review_data.get("poi_list") or []

        preference_keywords = [
            "亲子", "家庭", "老人", "情侣", "朋友", "商务",
            "休闲", "探险", "文化", "美食", "购物",
        ]
        matched_prefs = [kw for kw in preference_keywords if kw in all_text]
        score = min(6.0 + len(matched_prefs) * 0.5, SCORE_MAX)

        if preferences:
            prefs_values = list(preferences.values())
            non_empty_prefs = sum(1 for v in prefs_values if v)
            if non_empty_prefs >= 3:
                score = min(score + 1.0, SCORE_MAX)
            elif non_empty_prefs >= 1:
                score = min(score + 0.5, SCORE_MAX)

        budget_data = agent_data.get("budget", {})
        if budget_data.get("budget_level"):
            score = min(score + 0.5, SCORE_MAX)

        if poi_list:
            for poi in poi_list[:3]:
                if isinstance(poi, dict):
                    suitable_for = poi.get("suitable_for")
                    if suitable_for and len(suitable_for) > 0:
                        score = min(score + 0.3, SCORE_MAX)
                        break

        return round(max(min(score, SCORE_MAX), SCORE_MIN), 1)

    def _score_constraint_satisfaction(self, review_data: Dict[str, Any]) -> float:
        """评分：约束满足度（基于结构化数据）"""
        score = 7.0
        all_text = review_data.get("all_text", "")
        budget_data = review_data.get("budget_data") or {}
        preferences = review_data.get("preferences") or {}
        weather_data = review_data.get("weather_data") or {}
        poi_list = review_data.get("poi_list") or []

        constraint_keywords = [
            "预算", "时间", "人数", "天数", "偏好",
            "交通", "住宿", "门票", "开放时间",
        ]
        satisfied = sum(1 for kw in constraint_keywords if kw in all_text)
        ratio = satisfied / len(constraint_keywords)

        if ratio >= 0.8:
            score = 8.5
        elif ratio >= 0.6:
            score = 7.0
        elif ratio >= 0.4:
            score = 5.5
        else:
            score = 4.0

        if budget_data.get("is_over_budget") is True:
            score -= 1.5

        if budget_data.get("budget_limit") and budget_data.get("total_budget"):
            limit = float(budget_data["budget_limit"])
            total = float(budget_data["total_budget"])
            if limit > 0 and total <= limit:
                score = min(score + 0.5, SCORE_MAX)

        must_visit = self._normalize_list(preferences.get("must_visit"))
        avoid = self._normalize_list(preferences.get("avoid"))
        if poi_list and (must_visit or avoid):
            poi_names = [str(p.get("name") or "").strip() for p in poi_list]
            if must_visit:
                matched = sum(1 for mv in must_visit if any(mv in name for name in poi_names))
                if must_visit and matched == len(must_visit):
                    score = min(score + 1.0, SCORE_MAX)
                elif must_visit and matched > 0:
                    score = min(score + 0.5, SCORE_MAX)
            if avoid:
                violated = sum(1 for av in avoid if any(av in name for name in poi_names))
                if violated > 0:
                    score -= 1.0

        if weather_data.get("risk_level") in ["high", "medium"]:
            if "雨" in all_text or "高温" in all_text or "台风" in all_text:
                score -= 0.5

        return round(max(min(score, SCORE_MAX), SCORE_MIN), 1)

    def _calculate_scores(self, review_data: Dict[str, Any]) -> Dict[str, float]:
        """计算所有评分"""
        scores = {
            "completeness": self._score_completeness(review_data),
            "consistency": self._score_consistency(review_data),
            "feasibility": self._score_feasibility(review_data),
            "personalization": self._score_personalization(review_data),
            "constraint_satisfaction": self._score_constraint_satisfaction(review_data),
        }

        # 计算加权总分
        overall = sum(scores[k] * SCORE_WEIGHTS[k] for k in SCORE_WEIGHTS)
        scores["overall"] = round(overall, 1)

        return scores

    def _build_overall_score(self, scores: Dict[str, float]) -> Dict[str, Any]:
        """构建总分评价"""
        overall = scores.get("overall", 0)
        if overall >= 8:
            grade = "A"
            label = "优秀"
        elif overall >= 7:
            grade = "B"
            label = "良好"
        elif overall >= 5:
            grade = "C"
            label = "一般"
        else:
            grade = "D"
            label = "需改进"

        return {
            "score": overall,
            "grade": grade,
            "label": label,
        }

    def _collect_issues(self, review_data: Dict[str, Any], scores: Dict[str, float]) -> List[Dict[str, Any]]:
        """收集问题列表"""
        issues = []
        all_text = review_data.get("all_text", "")

        # 完整性问题
        if scores.get("completeness", 10) < 7:
            for check_key, check_name, keywords in COMPLETENESS_CHECKS:
                if not self._check_keywords_in_text(all_text, keywords):
                    issues.append({
                        "type": "completeness",
                        "severity": "warning",
                        "category": check_name,
                        "description": f"缺少{check_name}相关内容",
                        "suggestion": f"建议补充{check_name}",
                    })

        # 一致性问题
        conflict_keywords = re.findall(r".*?(冲突|矛盾|不一致).*?", all_text)
        if conflict_keywords:
            issues.append({
                "type": "consistency",
                "severity": "warning",
                "category": "一致性",
                "description": "检测到可能的一致性问题",
                "suggestion": "建议检查行程安排的逻辑一致性",
            })

        # 可行性问题
        if scores.get("feasibility", 10) < 6:
            if "疲劳" in all_text or "过长" in all_text:
                issues.append({
                    "type": "feasibility",
                    "severity": "info",
                    "category": "行程强度",
                    "description": "行程可能安排过紧",
                    "suggestion": "建议增加休息时间或减少景点数量",
                })

        return issues

    def _collect_warnings(self, review_data: Dict[str, Any], scores: Dict[str, float]) -> List[str]:
        """收集警告列表"""
        warnings = []
        all_text = review_data.get("all_text", "")

        # 天气风险警告
        weather_keywords = ["雨", "高温", "寒冷", "大风", "台风"]
        if review_data.get("weather_content"):
            weather_text = review_data.get("weather_content", "")
            for kw in weather_keywords:
                if kw in weather_text:
                    warnings.append(f"天气预报包含{kw}相关提示，请关注")
                    break

        # 预算警告
        budget_data = review_data.get("agent_data", {}).get("budget", {})
        if budget_data.get("is_over_budget"):
            warnings.append("当前预算可能超出设置上限")

        # 个性化警告
        if scores.get("personalization", 10) < 5:
            warnings.append("行程个性化程度较低，可能未充分考虑用户偏好")

        return warnings

    def _collect_suggestions(
        self,
        review_data: Dict[str, Any],
        scores: Dict[str, float],
        issues: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """收集建议列表"""
        suggestions = []

        # 基于评分生成建议
        if scores.get("completeness", 10) < 7:
            suggestions.append({
                "priority": "high",
                "category": "完整性",
                "content": "建议补充缺失的规划内容",
            })

        if scores.get("consistency", 10) < 6:
            suggestions.append({
                "priority": "high",
                "category": "一致性",
                "content": "建议检查并修正行程中的不一致之处",
            })

        if scores.get("feasibility", 10) < 6:
            suggestions.append({
                "priority": "medium",
                "category": "可行性",
                "content": "建议优化行程安排，确保合理可行",
            })

        if scores.get("personalization", 10) < 6:
            suggestions.append({
                "priority": "low",
                "category": "个性化",
                "content": "建议根据用户偏好调整行程细节",
            })

        # 基于问题生成建议
        for issue in issues:
            if issue.get("suggestion"):
                suggestions.append({
                    "priority": "high" if issue.get("severity") == "warning" else "medium",
                    "category": issue.get("category", "通用"),
                    "content": issue.get("suggestion", ""),
                })

        return suggestions

    def _needs_fix(self, issues: List[Dict[str, Any]], warnings: List[str]) -> bool:
        """判断是否需要修正"""
        # 高优先级问题超过阈值
        high_priority_issues = [i for i in issues if i.get("severity") == "warning"]
        return len(high_priority_issues) >= 2 or len(warnings) >= 2

    async def _apply_review_fixes(
        self,
        agent_results: Dict[str, Any],
        review_data: Dict[str, Any],
        issues: List[Dict[str, Any]],
        warnings: List[str],
        suggestions: List[Dict[str, Any]],
        session: SessionContext,
        context: ExecutionContext,
    ) -> tuple[Optional[Dict[str, Any]], bool]:
        """
        应用轻量修正（保守、局部）

        允许修正：
        - 补足必要缺失项
        - 修正明显结构不一致
        - 修正明显不可行安排
        - 回填关键信息

        禁止修正：
        - 重写整个 itinerary
        - 重新生成全新方案
        - 大规模重排
        """
        has_been_fixed = False
        fixed_result: Optional[Dict[str, Any]] = None

        high_priority_issues = [i for i in issues if i.get("severity") == "warning"]
        if not high_priority_issues and not warnings:
            return None, False

        itinerary_result = agent_results.get("itinerary")
        if itinerary_result:
            data = getattr(itinerary_result, "data", None) or {}
            if isinstance(data, dict):
                fixed_data = dict(data)
                daily_plans = review_data.get("daily_plans")
                budget_data = review_data.get("budget_data") or {}
                poi_list = review_data.get("poi_list") or []

                if not fixed_data.get("itinerary_summary") and daily_plans:
                    fixed_data["itinerary_summary"] = (
                        f"经审查修正后，共 {len(daily_plans)} 天行程，"
                        f"覆盖 {sum(len(p.get('items', [])) if isinstance(p, dict) else 0 for p in daily_plans)} 个景点。"
                    )
                    has_been_fixed = True

                if budget_data.get("is_over_budget") and not fixed_data.get("review_warnings"):
                    fixed_data.setdefault("review_warnings", [])
                    if isinstance(fixed_data["review_warnings"], list):
                        fixed_data["review_warnings"].append("预算超出限制，请关注")
                        has_been_fixed = True

                if poi_list and not fixed_data.get("poi_count"):
                    fixed_data["poi_count"] = len(poi_list)
                    has_been_fixed = True

                if fixed_data != data:
                    fixed_result = {
                        "itinerary": fixed_data,
                        "fix_applied_rules": [],
                        "issue_count_fixed": len(high_priority_issues),
                    }
                    if daily_plans:
                        fixed_result["fix_applied_rules"].append("itinerary_summary_patch")
                    if budget_data.get("is_over_budget"):
                        fixed_result["fix_applied_rules"].append("budget_warning_patch")
                    if poi_list:
                        fixed_result["fix_applied_rules"].append("poi_count_patch")
                    has_been_fixed = True
                else:
                    fixed_result = None

        if not has_been_fixed and self.llm:
            planner_content = review_data.get("planner_content", "")
            if planner_content:
                fix_prompt = self._build_fix_prompt(
                    planner_content, review_data, issues, warnings, suggestions
                )
                messages = self.build_messages(session, fix_prompt)
                try:
                    response = await self.chat(messages)
                    if response and response.content and len(response.content) > len(planner_content) * 0.5:
                        fixed_result = {
                            "planner": response.content,
                            "fix_applied_rules": ["llm_fallback_fix"],
                            "issue_count_fixed": len(high_priority_issues),
                        }
                        has_been_fixed = True
                except Exception as e:
                    logger.warning(f"Review LLM fix failed: {e}")

        return fixed_result, has_been_fixed

    def _build_fix_prompt(
        self,
        original_content: str,
        review_data: Dict[str, Any],
        issues: List[Dict[str, Any]],
        warnings: List[str],
        suggestions: List[Dict[str, Any]],
    ) -> str:
        """构建修正提示词"""
        prompt = f"""你是一个旅游规划助手，正在对现有旅行规划进行轻量修正。

## 原规划（仅作参考，不要完全重写）
{original_content[:2000]}

## 发现的问题
"""

        if issues:
            for i, issue in enumerate(issues[:5], 1):
                prompt += f"\n{i}. [{issue.get('type', '未知')}] {issue.get('description', '')}"
                prompt += f"\n   建议：{issue.get('suggestion', '')}"

        if warnings:
            prompt += "\n\n## 警告信息\n"
            for w in warnings[:3]:
                prompt += f"- {w}\n"

        if suggestions:
            prompt += "\n## 优化建议\n"
            for s in suggestions[:5]:
                priority = s.get("priority", "medium")
                prompt += f"- [{priority.upper()}] {s.get('content', '')}\n"

        prompt += """

## 修正要求
1. 只做局部修正，不要完全重写
2. 保持原方案的主体结构
3. 针对上述问题和建议进行针对性修改
4. 输出修正后的规划内容

请直接输出修正后的规划，不要额外解释。"""

        return prompt

    def _build_review_report(
        self,
        review_data: Dict[str, Any],
        scores: Dict[str, float],
        issues: List[Dict[str, Any]],
        warnings: List[str],
        suggestions: List[Dict[str, Any]],
        review_mode: ReviewMode,
    ) -> str:
        """构建审查报告内容"""
        overall = self._build_overall_score(scores)
        agent_names = list(review_data.get("agent_contents", {}).keys())

        lines = [
            "## 📋 旅行规划质量审查报告",
            "",
            f"**审查模式**: {'review_and_fix' if review_mode == ReviewMode.REVIEW_AND_FIX else 'review_only'}",
            f"**审查时间**: 自动生成",
            "",
            "### 📊 质量评分",
            "",
            "| 维度 | 评分 | 评价 |",
            "|------|------|------|",
            f"| 完整性 | {scores.get('completeness', 0):.1f}/10 | {'优秀' if scores.get('completeness', 0) >= 8 else '良好' if scores.get('completeness', 0) >= 6 else '需改进'} |",
            f"| 一致性 | {scores.get('consistency', 0):.1f}/10 | {'优秀' if scores.get('consistency', 0) >= 8 else '良好' if scores.get('consistency', 0) >= 6 else '需改进'} |",
            f"| 可行性 | {scores.get('feasibility', 0):.1f}/10 | {'优秀' if scores.get('feasibility', 0) >= 8 else '良好' if scores.get('feasibility', 0) >= 6 else '需改进'} |",
            f"| 个性化 | {scores.get('personalization', 0):.1f}/10 | {'优秀' if scores.get('personalization', 0) >= 8 else '良好' if scores.get('personalization', 0) >= 6 else '需改进'} |",
            f"| 约束满足 | {scores.get('constraint_satisfaction', 0):.1f}/10 | {'优秀' if scores.get('constraint_satisfaction', 0) >= 8 else '良好' if scores.get('constraint_satisfaction', 0) >= 6 else '需改进'} |",
            "",
            f"**综合评分**: {overall['score']:.1f}/10 | 等级: {overall['grade']} | {overall['label']}",
            "",
        ]

        if issues:
            lines.append("### ⚠️ 发现的问题")
            lines.append("")
            for i, issue in enumerate(issues[:5], 1):
                lines.append(f"{i}. **[{issue.get('type', '未知')}]** {issue.get('description', '')}")
                lines.append(f"   建议：{issue.get('suggestion', '')}")
            lines.append("")

        if warnings:
            lines.append("### 🚨 警告信息")
            lines.append("")
            for w in warnings:
                lines.append(f"- {w}")
            lines.append("")

        if suggestions:
            lines.append("### 💡 优化建议")
            lines.append("")
            for s in suggestions[:5]:
                priority = s.get("priority", "medium")
                icon = "🔴" if priority == "high" else "🟡" if priority == "medium" else "🟢"
                lines.append(f"{icon} **[{priority.upper()}]** {s.get('content', '')}")
            lines.append("")

        lines.append("### ✨ 审查结论")
        lines.append("")
        lines.append(f"本次审查了 {len(agent_names)} 个模块，综合评分为 {overall['score']:.1f} 分（{overall['label']}）。")
        lines.append(f"发现 {len(issues)} 个问题，{len(warnings)} 个警告。")

        return "\n".join(lines)

    def _build_review_data(
        self,
        review_mode: ReviewMode,
        scores: Dict[str, float],
        issues: List[Dict[str, Any]],
        warnings: List[str],
        suggestions: List[Dict[str, Any]],
        has_been_fixed: bool,
        fixed_result: Optional[Dict[str, Any]],
        agent_results: Dict[str, Any],
        review_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """构建返回数据"""
        overall = self._build_overall_score(scores)
        issue_count = len(issues) if issues else 0
        warning_count = len(warnings) if warnings else 0

        result: Dict[str, Any] = {
            "agents_reviewed": list(agent_results.keys()),
            "all_complete": len(agent_results) >= 4,
            "review_mode": review_mode.value,
            "review_scores": {
                "completeness": scores.get("completeness", 0),
                "consistency": scores.get("consistency", 0),
                "feasibility": scores.get("feasibility", 0),
                "personalization": scores.get("personalization", 0),
                "constraint_satisfaction": scores.get("constraint_satisfaction", 0),
                "overall": scores.get("overall", 0),
            },
            "review_summary": overall["label"] or f"评分 {overall['score']:.1f}",
            "review_summary_detail": {
                "grade": overall["grade"],
                "label": overall["label"],
                "score": overall["score"],
            },
            "review_issues": issues,
            "review_warnings": warnings,
            "review_suggestions": suggestions,
            "has_been_fixed": has_been_fixed,
            "fixed_result": fixed_result,
            "issue_count": issue_count,
            "warning_count": warning_count,
            "experiment_meta": {
                "review_mode": review_mode.value,
                "has_review": True,
                "has_fix": has_been_fixed,
                "mode_label": self._get_mode_label(review_mode, has_been_fixed),
            },
        }

        if review_data:
            poi_list = review_data.get("poi_list") or []
            budget_data = review_data.get("budget_data") or {}
            daily_plans = review_data.get("daily_plans")
            if poi_list:
                result["poi_count"] = len(poi_list)
            if budget_data.get("total_budget"):
                result["total_budget"] = budget_data["total_budget"]
            if budget_data.get("is_over_budget"):
                result["is_over_budget"] = budget_data["is_over_budget"]
            if daily_plans:
                result["day_count"] = len(daily_plans)

        if has_been_fixed and fixed_result:
            fix_rules = fixed_result.get("fix_applied_rules") or []
            result["fix_applied_rules"] = fix_rules
            result["issue_count_fixed"] = fixed_result.get("issue_count_fixed", 0)

        return result

    def _get_mode_label(self, mode: ReviewMode, has_fixed: bool) -> str:
        """获取实验模式标签"""
        if mode == ReviewMode.REVIEW_ONLY:
            return "review_only"
        elif has_fixed:
            return "review_and_fix"
        else:
            return "review_only"

    def _build_empty_response(self, review_mode: ReviewMode) -> AgentResponse:
        """构建空结果响应"""
        return AgentResponse(
            agent_name=self.name,
            status=AgentStatus.COMPLETED,
            content="暂无其他 Agent 的结果需要审查。",
            data={
                "agents_reviewed": [],
                "all_complete": False,
                "review_mode": review_mode.value,
                "review_scores": {
                    "completeness": 0,
                    "consistency": 0,
                    "feasibility": 0,
                    "personalization": 0,
                    "constraint_satisfaction": 0,
                    "overall": 0,
                },
                "review_summary": "无内容",
                "review_summary_detail": {
                    "grade": "N/A",
                    "label": "无内容",
                    "score": 0,
                },
                "review_issues": [],
                "review_warnings": [],
                "review_suggestions": [],
                "has_been_fixed": False,
                "fixed_result": None,
                "issue_count": 0,
                "warning_count": 0,
                "experiment_meta": {
                    "review_mode": review_mode.value,
                    "has_review": False,
                    "has_fix": False,
                    "mode_label": "no_review",
                },
            },
        )

    def _check_keywords_in_text(self, text: str, keywords: List[str]) -> bool:
        """检查文本中是否包含关键词"""
        if not text:
            return False
        return any(kw in text for kw in keywords)
