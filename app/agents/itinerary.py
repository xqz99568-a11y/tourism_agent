"""
Itinerary Agent
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.agents.base import AgentCapability, AgentConfig, AgentResponse, AgentStatus, BaseAgent
from app.core.context import ExecutionContext, SessionContext
from app.core.logger import get_logger

logger = get_logger(__name__)

POI = Dict[str, Any]
DayPlan = Dict[str, Any]

TIME_SLOT_VALUES = {"morning", "afternoon", "evening", "flexible"}

LOCAL_POI_DIR = Path(__file__).resolve().parents[2] / "data" / "pois"


ITINERARY_CONFIG = AgentConfig(
    name="itinerary",
    description="行程规划 Agent，负责制定详细的每日行程",
    instructions="""你是一位专业的旅游行程规划师。
请基于已经筛选、分配并校验过的日程骨架，生成自然、清晰、实用的逐日行程文案。
不要随意增加未提供的核心景点，不要打乱既定顺序，不要突破给定的时间与约束。
""",
    capabilities=[
        AgentCapability.PLANNING,
        AgentCapability.REASONING,
    ],
    max_retries=3,
    timeout_seconds=45,
)


class ItineraryAgent(BaseAgent):
    """负责制定详细的旅行行程。"""

    def __init__(self, llm=None, **kwargs):
        super().__init__(ITINERARY_CONFIG, llm)
        self._local_poi_cache: Dict[str, List[POI]] = {}

    async def plan(self, session: SessionContext, context: ExecutionContext) -> List[str]:
        return ["get_attractions", "organize_by_day", "calculate_routes"]

    async def execute(self, session: SessionContext, context: ExecutionContext) -> AgentResponse:
        inputs = self._normalize_itinerary_inputs(session, context)
        destination = inputs.get("destination") or ""
        duration = self._extract_trip_days(inputs)
        start_date = inputs.get("start_date") or ""
        num_travelers = inputs.get("num_travelers") or 1
        total_budget = self._extract_budget(context)
        profile = self._build_traveler_profile(session, context)

        if not destination:
            return AgentResponse(
                agent_name=self.name,
                status=AgentStatus.COMPLETED,
                content="请先告诉我目的地，我再为您规划详细行程。",
            )

        attraction_result = context.get_result("attraction")
        normalized_pois = self._normalize_pois(self._extract_poi_list(attraction_result))

        if not normalized_pois:
            normalized_pois = self._normalize_pois(self._load_local_pois(destination))
        if not normalized_pois:
            normalized_pois = self._build_destination_anchor_pois(destination, duration)

        self._record_thinking_reasoning(
            context,
            step_name="收集信息",
            reasoning_content=(
                f"目的地：{destination}\n"
                f"天数：{duration}天\n"
                f"人数：{num_travelers}人\n"
                f"出发日期：{start_date if start_date else '待定'}\n"
                f"预算：{total_budget if total_budget else '未提供'}\n"
                f"画像：{profile['mode']}"
            ),
            reasoning_type="fact",
        )

        self._record_thinking_reasoning(
            context,
            step_name="分析景点",
            reasoning_content=f"已读取结构化 POI，共 {len(normalized_pois)} 个。\n{self._analyze_attractions(normalized_pois, '')}",
            reasoning_type="analysis",
        )

        constraints = self._build_constraints(duration, profile, total_budget, num_travelers)
        day_plans = self._build_daily_plans(normalized_pois, duration, constraints, profile)
        daily_plans_structured = self._build_daily_plans_structured(normalized_pois, duration, inputs)
        skeleton_text = self._format_day_plans(day_plans)

        if not self.llm:
            self._set_context_info("destination", destination)
            self._set_context_info("duration", duration)
            self._set_context_info("attractions_count", len(normalized_pois))
            self._record_thinking_reasoning(
                context,
                step_name="约束排程",
                reasoning_content=skeleton_text,
                reasoning_type="decision",
            )
            result_data = self._build_itinerary_result(
                inputs,
                daily_plans_structured,
                skeleton_text,
                normalized_pois,
                attraction_result,
            )
            return AgentResponse(
                agent_name=self.name,
                status=AgentStatus.COMPLETED,
                content=skeleton_text,
                data=result_data,
            )

        self._record_thinking_reasoning(
            context,
            step_name="约束排程",
            reasoning_content=skeleton_text,
            reasoning_type="decision",
        )

        self._set_context_info("destination", destination)
        self._set_context_info("duration", duration)
        self._set_context_info("attractions_count", len(normalized_pois))

        self._record_thinking_reasoning(
            context,
            step_name="制定策略",
            reasoning_content=self._generate_planning_strategy(duration, num_travelers, profile, constraints),
            reasoning_type="decision",
        )

        self._record_tool_usage(
            context,
            step_name="规划行程",
            tool_name="llm_itinerary_planner",
            arguments={
                "destination": destination,
                "duration": duration,
                "num_travelers": num_travelers,
                "structured_pois": len(normalized_pois),
            },
        )

        system_prompt = f"""你是一位专业的旅游行程规划师，正在为用户规划 {destination} 的 {duration} 天行程。

基础信息：
- 目的地：{destination}
- 行程天数：{duration}天
- 出发日期：{start_date if start_date else '待定'}
- 出行人数：{num_travelers}人
- 用户画像：{profile['mode']}
- 预算参考：{total_budget if total_budget else '未提供'}

已筛选并标准化的景点列表：
{self._format_pois_for_prompt(normalized_pois)}

下面是已经过约束校验的日程骨架，请严格基于该骨架润色输出，不要打乱既定顺序，不要新增核心景点：
{skeleton_text}

请输出完整的逐日行程文案。每一天都包含上午、中午、下午、晚上四段，并保留午餐/休息安排与通勤说明。最后补充简短预算提示。
"""

        try:
            self._record_thinking_reasoning(
                context,
                step_name="生成行程",
                reasoning_content="先完成约束分配，再基于日程骨架生成自然语言行程。",
                reasoning_type="inference",
            )
            response = await self.chat(self.build_messages(session, system_prompt))
            self._record_thinking_reasoning(
                context,
                step_name="行程完成",
                reasoning_content=(
                    f"{destination} {duration} 天行程规划完成。\n"
                    f"涉及地点约 {self._estimate_location_count(response.content, duration)} 处。"
                ),
                reasoning_type="decision",
            )
            result_data = self._build_itinerary_result(
                inputs,
                daily_plans_structured,
                response.content,
                normalized_pois,
                attraction_result,
            )
            return AgentResponse(
                agent_name=self.name,
                status=AgentStatus.COMPLETED,
                content=response.content,
                tokens_used=response.usage.get("total_tokens", 0),
                data=result_data,
            )
        except Exception as e:
            logger.exception(f"Itinerary agent failed: {e}")
            self._record_thinking_complete(context, step_name="行程规划失败", result_summary=f"行程规划失败: {str(e)}")
            return AgentResponse(agent_name=self.name, status=AgentStatus.FAILED, content="", error=str(e))

    async def _generate_with_fallback(
        self,
        session: SessionContext,
        destination: str,
        duration: int,
        start_date: str,
        num_travelers: int,
        attractions_summary: str,
        fallback_text: str,
    ) -> AgentResponse:
        system_prompt = f"""你是一位专业的旅游行程规划师，正在为用户规划 {destination} 的 {duration} 天行程。
当前未获得结构化景点数据，请仅基于下面的候选信息生成保守版本行程，不要自行扩展太多景点：

基础信息：
- 出发日期：{start_date if start_date else '待定'}
- 出行人数：{num_travelers}人

候选摘要：
{attractions_summary}

候选文本：
{fallback_text}
"""
        response = await self.chat(self.build_messages(session, system_prompt))
        return AgentResponse(
            agent_name=self.name,
            status=AgentStatus.COMPLETED,
            content=response.content,
            tokens_used=response.usage.get("total_tokens", 0),
            data={"destination": destination, "duration": duration, "itinerary_type": "daily"},
        )

    def _normalize_destination_key(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[\s\-_／/（）()]+", "", text)
        for suffix in ["特别行政区", "自治区", "自治州", "省", "市", "县", "区"]:
            text = text.replace(suffix, "")
        return text

    def _load_local_pois(self, destination: str) -> List[POI]:
        cache_key = self._normalize_destination_key(destination)
        if cache_key in self._local_poi_cache:
            return self._local_poi_cache[cache_key]

        local_pois: List[POI] = []
        if LOCAL_POI_DIR.exists():
            for path in LOCAL_POI_DIR.glob("*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue

                city_key = self._normalize_destination_key(payload.get("city") or payload.get("city_name"))
                if city_key and city_key != cache_key:
                    continue

                for poi in payload.get("pois", []):
                    if not isinstance(poi, dict):
                        continue
                    item = dict(poi)
                    item.setdefault("city", payload.get("city") or destination)
                    item["_source_file"] = path.name
                    local_pois.append(item)

        self._local_poi_cache[cache_key] = local_pois
        return local_pois

    def _build_destination_anchor_pois(self, destination: str, duration: int) -> List[POI]:
        if not destination:
            return []

        anchors: List[POI] = []

        # 城市特色锚点映射（城市 -> List[锚点]）
        city_specific_anchors = self._get_city_specific_anchors(destination)
        anchors.extend(city_specific_anchors)

        # 通用锚点兜底（只补充城市特色锚点不足时）
        generic_anchors: List[POI] = [
            {
                "name": f"{destination}老城/古城街区",
                "city": destination,
                "region": f"{destination}老城片区",
                "category": "local_area",
                "recommended_visit_duration_hours": 2.0,
                "best_time_to_visit": "morning",
                "estimated_cost": {"amount": 0, "currency": "CNY", "cost_level": "free"},
                "description": f"优先安排在 {destination} 的老城或古城街区，保守但更贴近当地步行体验。",
                "suitable_for": ["首次到访", "轻松游", "保守版"],
                "source": "itinerary_anchor",
                "priority": "high",
                "indoor_outdoor": "mixed",
                "coordinates": None,
                "opening_hours": "信息待确认",
                "tags": ["本地锚点", "老城", "步行"],
            },
            {
                "name": f"{destination}博物馆/文化场馆",
                "city": destination,
                "region": f"{destination}文化片区",
                "category": "museum",
                "recommended_visit_duration_hours": 2.0,
                "best_time_to_visit": "morning",
                "estimated_cost": {"amount": 0, "currency": "CNY", "cost_level": "free"},
                "description": f"用一处文化场馆作为 {destination} 的室内锚点，兼顾休息和在地信息获取。",
                "suitable_for": ["首次到访", "轻松游", "保守版"],
                "source": "itinerary_anchor",
                "priority": "high",
                "indoor_outdoor": "indoor",
                "coordinates": None,
                "opening_hours": "信息待确认",
                "tags": ["本地锚点", "文化", "室内"],
            },
            {
                "name": f"{destination}核心商圈/步行街",
                "city": destination,
                "region": f"{destination}商圈",
                "category": "urban_area",
                "recommended_visit_duration_hours": 2.0,
                "best_time_to_visit": "afternoon",
                "estimated_cost": {"amount": 0, "currency": "CNY", "cost_level": "free"},
                "description": f"围绕 {destination} 的商业街区和步行街安排午后段落，适合顺路用餐和补给。",
                "suitable_for": ["首次到访", "轻松游", "保守版"],
                "source": "itinerary_anchor",
                "priority": "medium",
                "indoor_outdoor": "mixed",
                "coordinates": None,
                "opening_hours": "信息待确认",
                "tags": ["本地锚点", "商圈", "步行街"],
            },
            {
                "name": f"{destination}本地夜市/夜游片区",
                "city": destination,
                "region": f"{destination}夜游片区",
                "category": "night_market",
                "recommended_visit_duration_hours": 1.5,
                "best_time_to_visit": "evening",
                "estimated_cost": {"amount": 0, "currency": "CNY", "cost_level": "free"},
                "description": f"晚间优先找 {destination} 的夜市、夜游步道或本地小吃集中的区域。",
                "suitable_for": ["首次到访", "轻松游", "保守版"],
                "source": "itinerary_anchor",
                "priority": "medium",
                "indoor_outdoor": "outdoor",
                "coordinates": None,
                "opening_hours": "信息待确认",
                "tags": ["本地锚点", "夜市", "夜游"],
            },
            {
                "name": f"{destination}城市公园/河岸漫步",
                "city": destination,
                "region": f"{destination}休闲片区",
                "category": "park",
                "recommended_visit_duration_hours": 1.5,
                "best_time_to_visit": "afternoon",
                "estimated_cost": {"amount": 0, "currency": "CNY", "cost_level": "free"},
                "description": f"如果需要放松节奏，可以用 {destination} 的公园、河岸或滨水步道做保守补位。",
                "suitable_for": ["首次到访", "轻松游", "保守版"],
                "source": "itinerary_anchor",
                "priority": "low",
                "indoor_outdoor": "outdoor",
                "coordinates": None,
                "opening_hours": "信息待确认",
                "tags": ["本地锚点", "公园", "休闲"],
            },
        ]

        # 合并城市特色锚点（去重：同名不重复添加）
        existing_names = {a["name"] for a in anchors}
        for generic in generic_anchors:
            if generic["name"] not in existing_names:
                anchors.append(generic)
                existing_names.add(generic["name"])

        return anchors[: max(3, min(len(anchors), duration))]

    def _get_city_specific_anchors(self, destination: str) -> List[POI]:
        """获取城市特色锚点，优先使用当地真实地名和特色"""
        city_anchors: Dict[str, List[POI]] = {
            "北京": [
                {"name": "故宫/天安门广场", "region": "北京老城", "category": "landmark", "tags": ["故宫", "天安门", "中轴线"], "description": "老城核心区，串联故宫、景山、前门等中轴线精华。", "best_time_to_visit": "morning"},
                {"name": "什刹海/南锣鼓巷", "region": "老北京胡同", "category": "nightlife", "tags": ["胡同", "老北京", "小吃"], "description": "胡同文化区，早晚均可安排，慢节奏感受老北京。", "best_time_to_visit": "afternoon"},
                {"name": "三里屯/工体", "region": "北京商圈", "category": "shopping", "tags": ["商圈", "美食", "夜生活"], "description": "现代商圈区，傍晚或晚间适合体验北京夜生活。", "best_time_to_visit": "evening"},
            ],
            "成都": [
                {"name": "宽窄巷子/锦里", "region": "成都老城", "category": "local_area", "tags": ["老街", "小吃", "川西文化"], "description": "老城双街，慢节奏感受成都烟火气，遍地小吃。", "best_time_to_visit": "morning"},
                {"name": "武侯祠/锦里", "region": "武侯区", "category": "history", "tags": ["三国", "祠堂", "老街"], "description": "三国文化圈，白天逛武侯祠，傍晚锦里夜景。", "best_time_to_visit": "afternoon"},
                {"name": "春熙路/太古里", "region": "成都商圈", "category": "shopping", "tags": ["商圈", "美食", "时尚"], "description": "成都核心商圈，晚间逛街吃饭两相宜。", "best_time_to_visit": "evening"},
            ],
            "泉州": [
                {"name": "西街/开元寺", "region": "泉州老城", "category": "history", "tags": ["闽南", "古城", "宗教"], "description": "古城核心，宋元泉州精华，开元寺双塔是地标。", "best_time_to_visit": "morning"},
                {"name": "关岳庙/清净寺", "region": "泉州老城", "category": "history", "tags": ["宗教", "多元文化", "关岳庙"], "description": "泉州宗教密度最高区域，香火旺盛，建筑独特。", "best_time_to_visit": "afternoon"},
                {"name": "中山路/金鱼巷", "region": "泉州老城", "category": "food", "tags": ["闽南小吃", "老街", "骑楼"], "description": "闽南骑楼老街，小吃密集，体现泉州市井生活。", "best_time_to_visit": "evening"},
            ],
            "洛阳": [
                {"name": "龙门石窟", "region": "洛阳南郊", "category": "landmark", "tags": ["石窟", "佛教艺术", "世界遗产"], "description": "中国石刻艺术巅峰，建议上午前往，光线好且人流相对少。", "best_time_to_visit": "morning"},
                {"name": "洛邑古城/丽景门", "region": "洛阳老城", "category": "local_area", "tags": ["古城", "汉服", "小吃"], "description": "老城夜景丰富，汉服文化浓郁，遍地小吃。", "best_time_to_visit": "evening"},
                {"name": "白马寺", "region": "洛阳东郊", "category": "history", "tags": ["佛教", "古刹", "首刹"], "description": "中国第一古刹，佛教传入中国后建的第一座寺院。", "best_time_to_visit": "afternoon"},
            ],
            "重庆": [
                {"name": "解放碑/洪崖洞", "region": "重庆商圈", "category": "landmark", "tags": ["夜景", "吊脚楼", "网红"], "description": "重庆地标商圈，洪崖洞夜景必看，江景壮观。", "best_time_to_visit": "evening"},
                {"name": "磁器口古镇", "region": "沙坪坝", "category": "local_area", "tags": ["古镇", "小吃", "码头"], "description": "老重庆缩影，麻花和火锅底料是特产。", "best_time_to_visit": "morning"},
                {"name": "长江索道/南山", "region": "南岸区", "category": "nightlife", "tags": ["夜景", "江景", "一棵树"], "description": "俯瞰两江夜景最佳视角，浪漫体验重庆夜景。", "best_time_to_visit": "evening"},
            ],
            "西安": [
                {"name": "城墙/钟鼓楼", "region": "西安老城", "category": "landmark", "tags": ["城墙", "明清", "古建"], "description": "老城双核，上午登城墙骑行，下午逛回民街。", "best_time_to_visit": "morning"},
                {"name": "大雁塔/大唐不夜城", "region": "曲江新区", "category": "landmark", "tags": ["盛唐", "夜景", "仿古"], "description": "盛唐文化代表，晚间大唐不夜城灯光秀值得一看。", "best_time_to_visit": "evening"},
                {"name": "小雁塔/碑林", "region": "西安城区", "category": "history", "tags": ["博物馆", "书法", "古迹"], "description": "西安博物院与小雁塔相连，文化底蕴深厚。", "best_time_to_visit": "afternoon"},
            ],
            "杭州": [
                {"name": "西湖/断桥", "region": "西湖区", "category": "landmark", "tags": ["西湖", "江南", "山水"], "description": "杭州灵魂，苏堤白堤慢走，沿湖茶馆小憩。", "best_time_to_visit": "morning"},
                {"name": "灵隐寺/龙井村", "region": "西湖区", "category": "history", "tags": ["佛教", "茶园", "山林"], "description": "灵隐香火旺，龙井茶园清幽，上午礼佛下午品茶。", "best_time_to_visit": "afternoon"},
                {"name": "河坊街/南宋御街", "region": "上城区", "category": "food", "tags": ["老街", "小吃", "文创"], "description": "老杭州味道，特色小吃和文创小店集中。", "best_time_to_visit": "evening"},
            ],
            "上海": [
                {"name": "外滩/南京路", "region": "黄浦区", "category": "landmark", "tags": ["万国建筑", "夜景", "商圈"], "description": "上海名片，外滩万国建筑博览，晚间灯光最美。", "best_time_to_visit": "evening"},
                {"name": "豫园/城隍庙", "region": "黄浦区", "category": "local_area", "tags": ["江南园林", "小吃", "老城"], "description": "老城厢精华，南翔小笼是必吃，早去人少。", "best_time_to_visit": "morning"},
                {"name": "武康路/衡山路", "region": "徐汇区", "category": "cultural", "tags": ["梧桐区", "历史建筑", "文艺"], "description": "梧桐区慢生活，历史建筑林立，咖啡馆众多。", "best_time_to_visit": "afternoon"},
            ],
        }

        matched_anchors: List[POI] = []
        for city_name, pois in city_anchors.items():
            if city_name in destination:
                for poi_info in pois:
                    matched_anchors.append({
                        "name": poi_info["name"],
                        "city": destination,
                        "region": poi_info["region"],
                        "category": poi_info["category"],
                        "recommended_visit_duration_hours": 2.0,
                        "best_time_to_visit": poi_info.get("best_time_to_visit", "flexible"),
                        "estimated_cost": {"amount": 0, "currency": "CNY", "cost_level": "free"},
                        "description": poi_info["description"],
                        "suitable_for": ["首次到访", "轻松游", "本地化"],
                        "source": "city_specific_anchor",
                        "priority": "high",
                        "indoor_outdoor": "mixed",
                        "coordinates": None,
                        "opening_hours": "信息待确认",
                        "tags": poi_info.get("tags", ["本地锚点"]),
                    })
                break

        return matched_anchors

    def _extract_budget(self, context: ExecutionContext) -> Optional[float]:
        budget_amount = context.extracted_info.get("budget_amount")
        if isinstance(budget_amount, (int, float)):
            return float(budget_amount)
        if isinstance(budget_amount, str):
            match = re.search(r"(\d+(?:\.\d+)?)", budget_amount)
            if match:
                return float(match.group(1))

        budget = context.extracted_info.get("budget")
        if isinstance(budget, (int, float)):
            return float(budget)
        if isinstance(budget, str):
            match = re.search(r"(\d+(?:\.\d+)?)", budget)
            if match:
                return float(match.group(1))
        return None

    def _build_traveler_profile(self, session: SessionContext, context: ExecutionContext) -> Dict[str, Any]:
        tourist_type = context.extracted_info.get("tourist_type") or (session.preferences.tourist_type if session and session.preferences else "general")
        travel_styles = context.extracted_info.get("travel_styles") or (session.preferences.travel_style if session and session.preferences else [])
        traveler_ages = session.trip_context.traveler_ages if session and session.trip_context else []
        recent_text = " ".join(turn.user_message for turn in session.get_recent_messages(3)) if session else ""

        is_family = tourist_type == "family" or "亲子" in travel_styles or any(k in recent_text for k in ["亲子", "带娃", "孩子", "小孩", "家庭"])
        is_senior = tourist_type == "senior" or any(age >= 60 for age in traveler_ages) or any(k in recent_text for k in ["老人", "长辈", "爸妈"])
        needs_relaxed = is_family or is_senior or "休闲" in travel_styles

        if is_family and is_senior:
            mode = "family_senior"
        elif is_family:
            mode = "family"
        elif is_senior:
            mode = "senior"
        elif needs_relaxed:
            mode = "relaxed"
        else:
            mode = "general"
        return {"mode": mode, "travel_styles": travel_styles, "tourist_type": tourist_type}

    def _build_constraints(self, duration: int, profile: Dict[str, Any], total_budget: Optional[float], num_travelers: int) -> Dict[str, Any]:
        relaxed_mode = profile["mode"] in {"family", "senior", "family_senior", "relaxed"}
        max_pois_per_day = 2 if profile["mode"] in {"senior", "family_senior"} else (3 if relaxed_mode else 4)
        max_visit_hours = 6.0 if profile["mode"] in {"senior", "family_senior"} else (7.0 if relaxed_mode else 8.0)
        daily_ticket_budget = None
        if total_budget:
            daily_ticket_budget = max(total_budget * 0.15 / max(duration, 1) / max(num_travelers, 1), 50)
        return {
            "max_pois_per_day": max_pois_per_day,
            "max_visit_hours": max_visit_hours,
            "lunch_start": 12 * 60,
            "lunch_end": 13 * 60,
            "day_start": 9 * 60,
            "day_end": 18 * 60,
            "daily_ticket_budget": daily_ticket_budget,
            "max_cross_region": 0 if relaxed_mode else 1,
        }

    def _get_structured_pois(self, attraction_result: Any) -> List[POI]:
        if not attraction_result:
            return []
        data = getattr(attraction_result, "data", None) or {}
        pois = data.get("pois")
        return pois if isinstance(pois, list) else []

    def _normalize_pois(self, pois: List[POI]) -> List[POI]:
        normalized: List[POI] = []
        seen_names = set()
        for poi in pois:
            if not isinstance(poi, dict):
                continue
            name = str(poi.get("name") or poi.get("title") or "").strip()
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            city = str(poi.get("city") or poi.get("destination") or "").strip()
            region = str(poi.get("region") or poi.get("district") or poi.get("area") or poi.get("location") or "").strip()
            category = str(poi.get("category") or poi.get("type") or "other").strip() or "other"
            priority = str(poi.get("priority") or "medium").strip().lower()
            if priority not in {"high", "medium", "low"}:
                priority = "medium"
            raw_best_time = poi.get("best_time_to_visit") or poi.get("best_time") or poi.get("time_slot") or "flexible"
            if isinstance(raw_best_time, list):
                raw_best_time = raw_best_time[0] if raw_best_time else "flexible"
            best_time = str(raw_best_time or "flexible").strip().lower()
            if best_time not in TIME_SLOT_VALUES:
                best_time = "flexible"
            opening_hours = str(poi.get("opening_hours") or poi.get("open_time") or poi.get("open_hours") or "").strip()
            ticket_price = str(poi.get("ticket_price") or poi.get("ticket") or poi.get("price") or "").strip()
            duration_value = poi.get("visit_duration_hours") or poi.get("suggested_duration_hours") or poi.get("duration") or poi.get("recommended_duration")
            tags = poi.get("tags") or poi.get("features") or poi.get("categories") or []
            if not isinstance(tags, list):
                tags = [str(tags)]
            suitable_for = poi.get("suitable_for")
            if not isinstance(suitable_for, list):
                suitable_for = [str(suitable_for)] if suitable_for else []
            normalized.append(
                {
                    "name": name,
                    "city": city or None,
                    "region": region or "未注明区域",
                    "category": category,
                    "visit_duration_hours": self._parse_duration_hours(duration_value),
                    "recommended_visit_duration_hours": self._parse_duration_hours(duration_value),
                    "best_time_to_visit": best_time,
                    "priority": priority,
                    "opening_hours": opening_hours or "未知",
                    "ticket_price": ticket_price or "未知",
                    "ticket_cost": self._parse_ticket_price(ticket_price),
                    "tags": [str(tag).strip() for tag in tags if str(tag).strip()],
                    "open_range": self._parse_opening_hours(opening_hours),
                    "description": str(poi.get("description") or "")[:240].strip() or None,
                    "suitable_for": [str(item).strip() for item in suitable_for if str(item).strip()],
                    "source": str(poi.get("source") or "itinerary").strip(),
                    "indoor_outdoor": str(poi.get("indoor_outdoor") or "").strip() or None,
                    "coordinates": poi.get("coordinates"),
                }
            )
        return sorted(normalized, key=lambda poi: (poi["ticket_cost"], poi["region"], poi["name"]))

    def _format_pois_for_prompt(self, pois: List[POI]) -> str:
        return "\n".join(
            [
                f"{index}. {poi['name']} | 区域：{poi['region']} | 游玩时长：{poi['visit_duration_hours']}小时 | 开放时间：{poi['opening_hours']} | 门票：{poi['ticket_price']} | 标签：{'、'.join(poi['tags']) if poi['tags'] else '无'}"
                for index, poi in enumerate(pois, start=1)
            ]
        )

    def _extract_attractions(self, content: str) -> str:
        if not content:
            return "景点待确认"
        return content[:1000]

    def _analyze_attractions(self, pois: List[POI], fallback_content: str) -> str:
        if pois:
            return "\n".join(
                [
                    f"景点：{poi['name']} | 区域：{poi['region']} | 时长：{poi['visit_duration_hours']}小时 | 开放：{poi['opening_hours']}"
                    for poi in pois[:5]
                ]
            )
        return fallback_content[:300] if fallback_content else "景点信息待确认"

    def _build_daily_plans(self, pois: List[POI], duration: int, constraints: Dict[str, Any], profile: Dict[str, Any]) -> List[DayPlan]:
        remaining = sorted(pois, key=lambda poi: self._poi_priority_key(poi, profile, constraints))
        day_plans: List[DayPlan] = []
        for day_index in range(duration):
            day_plans.append(self._build_single_day_plan(remaining, day_index + 1, constraints, profile))
        if remaining and day_plans:
            for poi in remaining:
                day_plans[-1].setdefault("unassigned", []).append(poi["name"])
        return day_plans

    def _build_single_day_plan(self, remaining: List[POI], day_number: int, constraints: Dict[str, Any], profile: Dict[str, Any]) -> DayPlan:
        current_time = constraints["day_start"]
        lunch_inserted = False
        selected: List[POI] = []
        blocks: List[Dict[str, Any]] = []
        total_visit_hours = 0.0
        total_commute_minutes = 0
        cross_region_count = 0
        last_poi: Optional[POI] = None
        ticket_cost_total = 0.0

        for poi in list(sorted(remaining, key=lambda item: self._poi_priority_key(item, profile, constraints))):
            if len(selected) >= constraints["max_pois_per_day"]:
                break
            commute_minutes = self._estimate_commute_minutes(last_poi, poi)
            region_changed = last_poi is not None and last_poi["region"] != poi["region"]
            projected_hours = total_visit_hours + poi["visit_duration_hours"] + commute_minutes / 60.0
            if projected_hours > constraints["max_visit_hours"]:
                continue
            if region_changed and cross_region_count >= constraints["max_cross_region"]:
                continue
            if constraints["daily_ticket_budget"] and ticket_cost_total + poi["ticket_cost"] > constraints["daily_ticket_budget"] * 1.3:
                continue

            arrival_time = current_time + commute_minutes
            if not lunch_inserted and arrival_time >= constraints["lunch_start"]:
                blocks.append({"type": "rest", "title": "午餐 / 休息", "start": constraints["lunch_start"], "end": constraints["lunch_end"]})
                lunch_inserted = True
                current_time = max(current_time, constraints["lunch_end"])
                arrival_time = current_time + commute_minutes

            visit_minutes = int(poi["visit_duration_hours"] * 60)
            adjusted_range = self._fit_visit_into_open_hours(arrival_time, visit_minutes, poi["open_range"])
            if adjusted_range is None:
                continue
            start_minutes, end_minutes = adjusted_range
            if end_minutes > constraints["day_end"]:
                continue

            if commute_minutes > 0:
                blocks.append({"type": "commute", "title": f"前往 {poi['name']}", "start": current_time, "end": current_time + commute_minutes, "minutes": commute_minutes})
            blocks.append({
                "type": "poi",
                "title": poi["name"],
                "start": start_minutes,
                "end": end_minutes,
                "region": poi["region"],
                "ticket_price": poi["ticket_price"],
                "opening_hours": poi["opening_hours"],
            })

            selected.append(poi)
            total_visit_hours += poi["visit_duration_hours"]
            total_commute_minutes += commute_minutes
            ticket_cost_total += poi["ticket_cost"]
            current_time = end_minutes
            if region_changed:
                cross_region_count += 1
            last_poi = poi

        if not lunch_inserted:
            lunch_start = max(constraints["lunch_start"], min(current_time, constraints["day_end"] - 60))
            blocks.append({"type": "rest", "title": "午餐 / 休息", "start": lunch_start, "end": min(lunch_start + 60, constraints["day_end"])})

        for poi in selected:
            if poi in remaining:
                remaining.remove(poi)

        return {
            "day": day_number,
            "theme": f"{selected[0]['region']} 深度游" if selected else "轻松自由活动",
            "blocks": sorted(blocks, key=lambda block: block["start"]),
            "selected_pois": [poi["name"] for poi in selected],
            "visit_hours": round(total_visit_hours, 1),
            "commute_minutes": total_commute_minutes,
            "ticket_cost_total": round(ticket_cost_total, 1),
            **self._validate_day_plan(blocks, constraints),
        }

    def _poi_priority_key(self, poi: POI, profile: Dict[str, Any], constraints: Dict[str, Any]) -> Tuple[int, float, str, str]:
        penalty = 0
        tags_text = " ".join(poi.get("tags", []))
        if profile["mode"] in {"family", "senior", "family_senior", "relaxed"}:
            if any(word in tags_text for word in ["徒步", "登山", "冒险", "高强度", "夜游"]):
                penalty += 5
            if poi["visit_duration_hours"] > 3.5:
                penalty += 2
        if constraints["daily_ticket_budget"] and poi["ticket_cost"] > constraints["daily_ticket_budget"]:
            penalty += 2
        return (penalty, poi["ticket_cost"], poi["region"], poi["name"])

    def _validate_day_plan(self, blocks: List[Dict[str, Any]], constraints: Dict[str, Any]) -> Dict[str, Any]:
        notes: List[str] = []
        poi_blocks = [block for block in blocks if block["type"] == "poi"]
        feasible = True
        if len(poi_blocks) > constraints["max_pois_per_day"]:
            feasible = False
            notes.append("景点数量超出上限")
        if not any(block["type"] == "rest" for block in blocks):
            feasible = False
            notes.append("缺少午餐/休息时间")
        total_minutes = sum(block["end"] - block["start"] for block in poi_blocks)
        if total_minutes / 60.0 > constraints["max_visit_hours"]:
            feasible = False
            notes.append("总游玩时长超出上限")
        return {"feasible": feasible, "notes": notes or ["约束检查通过"]}

    def _fit_visit_into_open_hours(self, arrival_time: int, visit_minutes: int, open_range: Optional[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
        if open_range is None:
            return arrival_time, arrival_time + visit_minutes
        open_start, open_end = open_range
        start_time = max(arrival_time, open_start)
        end_time = start_time + visit_minutes
        if end_time > open_end:
            return None
        return start_time, end_time

    def _estimate_commute_minutes(self, previous_poi: Optional[POI], next_poi: POI) -> int:
        if previous_poi is None:
            return 15
        if previous_poi["region"] == next_poi["region"]:
            return 20
        if "区" in previous_poi["region"] and "区" in next_poi["region"]:
            return 45
        return 60

    def _parse_duration_hours(self, value: Any) -> float:
        if isinstance(value, (int, float)):
            return max(float(value), 0.5)
        text = str(value or "").strip()
        if not text:
            return 2.0
        range_match = re.search(r"(\d+(?:\.\d+)?)\s*[-~到至]\s*(\d+(?:\.\d+)?)\s*小时", text)
        if range_match:
            return round((float(range_match.group(1)) + float(range_match.group(2))) / 2, 1)
        hour_match = re.search(r"(\d+(?:\.\d+)?)\s*小时", text)
        if hour_match:
            return float(hour_match.group(1))
        if "半天" in text:
            return 4.0
        if "一天" in text or "1天" in text:
            return 8.0
        return 2.0

    def _parse_ticket_price(self, ticket_price: str) -> float:
        if not ticket_price or ticket_price == "未知" or "免费" in ticket_price:
            return 0.0
        numbers = [float(match) for match in re.findall(r"\d+(?:\.\d+)?", ticket_price)]
        return min(numbers) if numbers else 0.0

    def _parse_opening_hours(self, opening_hours: str) -> Optional[Tuple[int, int]]:
        if not opening_hours or opening_hours == "未知":
            return None
        match = re.search(r"(\d{1,2}:\d{2})\s*[-~至到]\s*(\d{1,2}:\d{2})", opening_hours)
        if not match:
            return None
        return self._to_minutes(match.group(1)), self._to_minutes(match.group(2))

    def _to_minutes(self, time_text: str) -> int:
        hour, minute = time_text.split(":")
        return int(hour) * 60 + int(minute)

    def _format_day_plans(self, day_plans: List[DayPlan]) -> str:
        lines: List[str] = []
        for day_plan in day_plans:
            lines.append(f"Day {day_plan['day']} | 主题：{day_plan['theme']}")
            if not day_plan["blocks"]:
                lines.append("- 09:30-17:00 自由活动 / 机动安排")
            for block in day_plan["blocks"]:
                start = self._format_minutes(block["start"])
                end = self._format_minutes(block["end"])
                detail = f"- {start}-{end} {block['title']}"
                if block["type"] == "poi":
                    detail += f"（区域：{block['region']}，门票：{block['ticket_price']}）"
                elif block["type"] == "commute":
                    detail += f"（通勤 {block['minutes']} 分钟）"
                lines.append(detail)
            lines.append(f"- 约束摘要：景点 {len(day_plan['selected_pois'])} 个，游玩 {day_plan['visit_hours']} 小时，通勤 {day_plan['commute_minutes']} 分钟，校验：{'通过' if day_plan['feasible'] else '需关注'}")
            lines.append(f"- 备注：{'；'.join(day_plan['notes'])}")
        return "\n".join(lines)

    def _format_minutes(self, minutes: int) -> str:
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    def _generate_planning_strategy(self, duration: int, num_travelers: int, profile: Dict[str, Any], constraints: Dict[str, Any]) -> str:
        return "\n".join([
            "1. 先读取结构化 POI，再做日程分配，最后生成文案",
            f"2. 每天最多安排 {constraints['max_pois_per_day']} 个景点，总游玩时长控制在 {constraints['max_visit_hours']} 小时内",
            "3. 每个完整白天强制插入午餐/休息时间块",
            "4. 排序时优先同区域串联，并将通勤时间纳入总时长",
            "5. 若存在开放时间，则先做开放时间冲突检查再安排",
            f"6. 当前画像为 {profile['mode']}，已按低强度偏好调整安排",
            f"7. 当前人数 {num_travelers} 人，规划 {duration} 天保守可行行程",
        ])

    def _estimate_location_count(self, content: str, duration: int) -> int:
        markers = ["景点", "景区", "地点", "餐厅", "酒店"]
        return min(sum(content.count(marker) for marker in markers), duration * 5)

    def _normalize_itinerary_inputs(self, session: SessionContext, context: ExecutionContext) -> Dict[str, Any]:
        """兼容读取上游输入字段。"""
        extracted = context.extracted_info or {}
        session_ctx = session.trip_context if session else None
        session_prefs = session.preferences if session else None
        result: Dict[str, Any] = {
            "destination": str(extracted.get("destination") or "").strip(),
            "city": str(extracted.get("city") or "").strip(),
            "region": str(extracted.get("region") or "").strip(),
            "district": str(extracted.get("district") or "").strip(),
            "area": str(extracted.get("area") or "").strip(),
            "duration": int(extracted.get("duration") or extracted.get("days") or 3),
            "start_date": str(extracted.get("start_date") or "").strip(),
            "num_travelers": (
                extracted.get("num_travelers")
                or (session_ctx.num_travelers if session_ctx else None)
                or 1
            ),
            "preferences": session_prefs if session_prefs else {},
            "interests": self._normalize_list(extracted.get("interests")),
            "travel_style": self._normalize_list(extracted.get("travel_style")),
            "group_type": str(extracted.get("group_type") or "").strip(),
            "special_requirements": self._normalize_list(extracted.get("special_requirements")),
            "must_visit": self._normalize_list(extracted.get("must_visit")),
            "avoid": self._normalize_list(extracted.get("avoid")),
            "daily_plans_input": extracted.get("daily_plans"),
            "schedule": extracted.get("schedule"),
        }
        if not result["destination"] and result["city"]:
            result["destination"] = result["city"]
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

    def _extract_poi_list(self, attraction_result: Any) -> List[Dict[str, Any]]:
        """从 attraction 结果中提取结构化 poi_list，兼容多种字段名。"""
        if not attraction_result:
            return []
        data = getattr(attraction_result, "data", None) or {}
        candidates = [
            data.get("poi_list"),
            data.get("pois"),
            data.get("recommended_pois"),
            data.get("attractions"),
            data.get("items"),
            data.get("activities"),
        ]
        for candidate in candidates:
            if isinstance(candidate, list) and candidate:
                return self._normalize_attraction_pois(candidate)
        return []

    def _normalize_attraction_pois(self, pois: List[Any]) -> List[Dict[str, Any]]:
        """将 attraction 返回的 POI 列表统一标准化。"""
        result: List[Dict[str, Any]] = []
        seen = set()
        for poi in pois:
            if not isinstance(poi, dict):
                continue
            name = str(poi.get("name") or poi.get("title") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            priority_raw = str(poi.get("priority") or "medium").lower()
            priority = priority_raw if priority_raw in {"high", "medium", "low"} else "medium"
            duration_val = poi.get("recommended_visit_duration_hours") or poi.get("duration") or poi.get("estimated_duration") or 2.0
            duration_hours = self._parse_duration_hours(duration_val)
            best_time = str(poi.get("best_time_to_visit") or "flexible").lower()
            if best_time not in TIME_SLOT_VALUES:
                best_time = "flexible"
            cost_obj = poi.get("estimated_cost")
            cost_amount = None
            if isinstance(cost_obj, dict):
                cost_amount = cost_obj.get("amount")
            elif cost_obj is not None:
                cost_amount = self._parse_float(cost_obj)
            estimated_cost = {"amount": cost_amount, "currency": "CNY", "cost_level": None} if cost_amount is not None else None
            location = poi.get("coordinates") or poi.get("location") or {}
            if isinstance(location, dict):
                lat = location.get("lat") or location.get("latitude")
                lng = location.get("lng") or location.get("longitude")
                coordinates = {"lat": lat, "lng": lng} if lat is not None and lng is not None else None
            else:
                coordinates = None
            city = str(poi.get("city") or poi.get("destination") or "").strip()
            region = str(poi.get("region") or poi.get("district") or poi.get("area") or city).strip()
            suitable_for = poi.get("suitable_for")
            if not isinstance(suitable_for, list):
                if suitable_for:
                    suitable_for = [str(suitable_for)]
                else:
                    suitable_for = []
            result.append({
                "name": name,
                "city": city or None,
                "region": region,
                "category": str(poi.get("category") or "other").strip() or None,
                "recommended_visit_duration_hours": duration_hours,
                "best_time_to_visit": best_time,
                "estimated_cost": estimated_cost,
                "description": str(poi.get("description") or "")[:200].strip() or None,
                "suitable_for": suitable_for,
                "source": str(poi.get("source") or "attraction"),
                "priority": priority,
                "indoor_outdoor": str(poi.get("indoor_outdoor") or "mixed").strip() or None,
                "coordinates": coordinates,
                "opening_hours": str(poi.get("opening_hours") or poi.get("open_time") or "").strip() or None,
                "tags": self._normalize_list(poi.get("tags")),
            })
        return result

    def _parse_float(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def _sort_pois_for_scheduling(self, pois: List[Dict[str, Any]], inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
        """根据优先级、时段、时长对 POI 进行排序准备排程。"""
        priority_order = {"high": 0, "medium": 1, "low": 2}
        time_order = {"morning": 0, "afternoon": 1, "evening": 2, "flexible": 3}
        sorted_pois = sorted(
            pois,
            key=lambda p: (
                priority_order.get(str(p.get("priority") or "medium").lower(), 1),
                time_order.get(str(p.get("best_time_to_visit") or "flexible").lower(), 3),
                p.get("recommended_visit_duration_hours") or 2.0,
                p.get("name") or "",
            )
        )
        must_visit = set(inputs.get("must_visit") or [])
        avoid = set(inputs.get("avoid") or [])
        if must_visit:
            sorted_pois = sorted(sorted_pois, key=lambda p: (0 if p.get("name") in must_visit else 1,))
        if avoid:
            sorted_pois = [p for p in sorted_pois if p.get("name") not in avoid]
        return sorted_pois

    def _group_pois_by_region_or_city(self, pois: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """将 POI 按区域/城市分组。"""
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for poi in pois:
            region = str(poi.get("region") or poi.get("city") or "未知").strip()
            if region not in groups:
                groups[region] = []
            groups[region].append(poi)
        return groups

    def _assign_time_slot(self, best_time: str, day_slot_availability: Dict[str, bool]) -> str:
        """将 POI 的最佳时段映射到实际时间段。"""
        if best_time in TIME_SLOT_VALUES and day_slot_availability.get(best_time, True):
            return best_time
        for slot in TIME_SLOT_VALUES:
            if day_slot_availability.get(slot, True):
                return slot
        return "flexible"

    def _build_daily_plan_item(self, poi: Dict[str, Any], time_slot: str) -> Dict[str, Any]:
        """构建单个行程项。"""
        return {
            "name": poi.get("name"),
            "time_slot": time_slot,
            "category": poi.get("category"),
            "estimated_duration_hours": poi.get("recommended_visit_duration_hours"),
            "notes": poi.get("description"),
            "city": poi.get("city"),
            "region": poi.get("region"),
            "priority": poi.get("priority"),
            "estimated_cost": poi.get("estimated_cost"),
            "coordinates": poi.get("coordinates"),
            "best_time_to_visit": poi.get("best_time_to_visit"),
            "source_poi_index": None,
        }

    def _build_daily_plans_structured(
        self,
        pois: List[Dict[str, Any]],
        duration: int,
        inputs: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """构建标准化的按天行程结构。"""
        if not pois:
            return []
        sorted_pois = self._sort_pois_for_scheduling(pois, inputs)
        region_groups = self._group_pois_by_region_or_city(sorted_pois)
        sorted_regions = sorted(region_groups.keys(), key=lambda r: len(region_groups[r]), reverse=True)
        assigned_pois: set = set()
        daily_plans: List[Dict[str, Any]] = []
        for day_idx in range(duration):
            day_number = day_idx + 1
            day_slot_availability: Dict[str, bool] = {"morning": True, "afternoon": True, "evening": True, "flexible": True}
            morning_pois = []
            afternoon_pois = []
            evening_pois = []
            flexible_pois = []
            remaining_slots = {"morning": True, "afternoon": True, "evening": True}
            for region in sorted_regions:
                for poi in region_groups[region]:
                    if poi.get("name") in assigned_pois:
                        continue
                    if len(morning_pois) + len(afternoon_pois) + len(evening_pois) >= 3:
                        continue
                    total_hours = (
                        sum(p.get("recommended_visit_duration_hours") or 2.0 for p in morning_pois + afternoon_pois + evening_pois)
                        + (poi.get("recommended_visit_duration_hours") or 2.0)
                    )
                    if total_hours > 7.0:
                        continue
                    best_time = str(poi.get("best_time_to_visit") or "flexible").lower()
                    poi_name = str(poi.get("name") or "").lower()
                    poi_category = str(poi.get("category") or "").lower()
                    poi_tags_text = " ".join(str(t).lower() for t in (poi.get("tags") or []) if str(t).strip())
                    poi_combined = f"{poi_name} {poi_category} {poi_tags_text}"

                    # 【本轮修复】白天型景点强制不允许进 evening slot
                    # 规则：若 best_time 为 flexible 但景点类型属于白天型，则优先 morning/afternoon
                    day_only_keywords = ["博物馆", "美术馆", "展馆", "纪念馆", "故宫", "天坛", "天安门", "图书馆", "寺庙主体", "石窟", "宫殿主体", "城墙", "钟楼", "鼓楼"]
                    if best_time == "flexible" and any(kw in poi_combined for kw in day_only_keywords):
                        # 博物馆/故宫等：优先 morning，其次 afternoon，拒绝 evening
                        if remaining_slots.get("morning"):
                            best_time = "morning"
                        elif remaining_slots.get("afternoon"):
                            best_time = "afternoon"
                        else:
                            # morning/afternoon 都满了，跳过这个 POI（不塞进 evening）
                            continue

                    if best_time == "morning" and remaining_slots.get("morning"):
                        morning_pois.append(poi)
                        assigned_pois.add(poi.get("name"))
                        remaining_slots["morning"] = False
                    elif best_time == "afternoon" and remaining_slots.get("afternoon"):
                        afternoon_pois.append(poi)
                        assigned_pois.add(poi.get("name"))
                        remaining_slots["afternoon"] = False
                    elif best_time == "evening" and remaining_slots.get("evening"):
                        evening_pois.append(poi)
                        assigned_pois.add(poi.get("name"))
                        remaining_slots["evening"] = False
                    else:
                        flexible_pois.append(poi)
            # 【本轮修复】Day 3 空白填充：前两天后 POIs 耗尽时，Day 3 slot 也要尝试从剩余 POIs 池补充
            # 先尝试从 flexible_pois（best_time=flexible 且未分配的 POIs）补充
            for slot_list, slot_name in [(morning_pois, "morning"), (afternoon_pois, "afternoon"), (evening_pois, "evening")]:
                if slot_list:
                    continue
                for poi in flexible_pois:
                    if poi.get("name") in assigned_pois:
                        continue
                    slot_list.append(poi)
                    assigned_pois.add(poi.get("name"))
                    break
            # 如果 Day 3 的 slot 仍然为空（前两天耗尽了所有 flexible POIs），从剩余 POIs 池补充
            # 注意：仅对 Day 3 应用此宽松策略，避免打乱前两天的已优化安排
            if day_idx >= 2:  # Day 3 及之后
                remaining_unscheduled = [poi for poi in sorted_pois if poi.get("name") not in assigned_pois]
                for slot_list, slot_name in [(morning_pois, "morning"), (afternoon_pois, "afternoon"), (evening_pois, "evening")]:
                    if slot_list:
                        continue
                    for poi in remaining_unscheduled:
                        if poi.get("name") in assigned_pois:
                            continue
                        # 【本轮修复】白天型景点禁止进 evening slot
                        poi_combined = f"{poi.get('name', '')} {poi.get('category', '')} {' '.join(str(t) for t in (poi.get('tags') or []) if str(t).strip())}".lower()
                        day_only_keywords = ["博物馆", "美术馆", "展馆", "纪念馆", "故宫", "天坛", "天安门", "图书馆", "寺庙主体", "石窟", "宫殿主体", "城墙", "钟楼", "鼓楼"]
                        if slot_name == "evening" and any(kw in poi_combined for kw in day_only_keywords):
                            continue
                        slot_list.append(poi)
                        assigned_pois.add(poi.get("name"))
                        break
            items: List[Dict[str, Any]] = []
            for poi in morning_pois:
                items.append(self._build_daily_plan_item(poi, "morning"))
            if morning_pois and afternoon_pois:
                items.append({"name": "午餐 / 休息", "time_slot": None, "category": "rest", "estimated_duration_hours": 1.0, "notes": "午餐及休息时间", "city": None, "region": None})
            for poi in afternoon_pois:
                items.append(self._build_daily_plan_item(poi, "afternoon"))
            if afternoon_pois and evening_pois:
                items.append({"name": "晚餐 / 休息", "time_slot": None, "category": "rest", "estimated_duration_hours": 1.0, "notes": "晚餐及休息时间", "city": None, "region": None})
            for poi in evening_pois:
                items.append(self._build_daily_plan_item(poi, "evening"))
            used_regions = list(dict.fromkeys(str(item.get("region") or item.get("city") or "") for item in items if item.get("name") not in ["午餐 / 休息", "晚餐 / 休息"]))
            theme = "、".join(used_regions[:2]) + " 深度游" if used_regions else "轻松自由活动"
            daily_plans.append({
                "day": day_number,
                "theme": theme,
                "region": used_regions[0] if used_regions else None,
                "items": items,
            })
        unscheduled = [poi for poi in sorted_pois if poi.get("name") not in assigned_pois]
        if unscheduled and daily_plans:
            daily_plans[-1]["items"].append({
                "name": "备选景点（未排入）",
                "time_slot": None,
                "category": None,
                "estimated_duration_hours": None,
                "notes": "、".join([p.get("name") for p in unscheduled[:5]]),
                "city": None,
                "region": None,
            })
        return daily_plans

    def _build_itinerary_result(
        self,
        inputs: Dict[str, Any],
        daily_plans: List[Dict[str, Any]],
        content: str,
        normalized_pois: List[Any],
        attraction_result: Any,
    ) -> Dict[str, Any]:
        """构建完整的 itinerary 结果。"""
        destination = inputs.get("destination") or ""
        duration = inputs.get("duration") or 3
        selected_pois = []
        unscheduled_pois = []
        for plan in daily_plans:
            for item in plan.get("items", []):
                if item.get("name") not in ["午餐 / 休息", "晚餐 / 休息", "备选景点（未排入）"]:
                    selected_pois.append(item.get("name"))
        if normalized_pois:
            selected_names = set(selected_pois)
            unscheduled_pois = [p.get("name") for p in normalized_pois if p.get("name") not in selected_names]
        result: Dict[str, Any] = {
            "destination": destination,
            "duration": duration,
            "itinerary_type": "daily",
            "daily_plans": daily_plans,
            "day_count": len(daily_plans) if daily_plans else duration,
        }
        if daily_plans:
            result["optimized_plan"] = (
                f"共规划 {len(daily_plans)} 天行程，"
                f"覆盖 {len(selected_pois)} 个景点，"
                f"每天约 {len(selected_pois) // max(len(daily_plans), 1)} 个点。"
            )
            result["itinerary_summary"] = f"{destination} {duration} 天行程已生成，每天包含上午、下午、晚上三段行程，共涉及 {len(selected_pois)} 个景点。"
        result["selected_pois"] = selected_pois
        result["unscheduled_pois"] = unscheduled_pois
        result["planning_rules"] = {
            "max_pois_per_day": 3,
            "max_visit_hours": 7.0,
            "time_slots": list(TIME_SLOT_VALUES),
        }
        result["applied_preferences"] = {
            "destination": destination,
            "duration": duration,
            "interests": inputs.get("interests") or [],
            "travel_style": inputs.get("travel_style") or [],
            "group_type": inputs.get("group_type") or None,
        }
        return result
