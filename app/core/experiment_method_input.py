"""Generation-visible input construction for formal experiment methods."""
from __future__ import annotations

import re
from typing import Any, Mapping

from app.core.experiment_method_contract import EVALUATOR_ONLY_FIELDS
from app.core.goal_state_scheduler import normalize_slots


METHOD_INPUT_SCHEMA_VERSION = "ctp-method-input-v1"

GENERATION_COMPATIBILITY_FIELDS = (
    "case_id",
    "user_input",
    "dialogue_history",
    "history",
    "method_input",
    "method_previous_state",
    "previous_state",
    "session_id",
    "conversation_id",
    "thread_id",
    "evaluation_mode",
)

PREVIOUS_STATE_EVALUATOR_ONLY_FIELDS = (
    set(EVALUATOR_ONLY_FIELDS)
    - {"slots", "current_slots", "previous_slots", "changed_slots", "preserved_slots"}
) | {"evaluation", "metrics", "constraint_report"}

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

CITY_PATTERNS = (
    ("beijing", ("北京", "beijing")),
    ("hangzhou", ("杭州", "hangzhou")),
    ("xian", ("西安", "xian", "xi'an", "xi an")),
    ("guilin", ("桂林", "guilin")),
    ("shenzhen", ("深圳", "shenzhen")),
)


CHINESE_NUMBER_WORDS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "俩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

CHINESE_CITY_ALIASES = {
    "beijing": ("北京", "北京市"),
    "hangzhou": ("杭州", "杭州市"),
    "xian": ("西安", "西安市"),
    "guilin": ("桂林", "桂林市"),
    "shenzhen": ("深圳", "深圳市"),
}

NUMBER_WORDS.update(CHINESE_NUMBER_WORDS)
CITY_PATTERNS = tuple(
    (
        city_id,
        tuple(dict.fromkeys((*aliases, *CHINESE_CITY_ALIASES.get(city_id, ())))),
    )
    for city_id, aliases in CITY_PATTERNS
)


def build_generation_case(case: Mapping[str, Any], method: str) -> dict[str, Any]:
    """Return the case payload visible to a built-in generation method.

    The returned mapping deliberately excludes evaluator-only labels such as
    expected answers, gold task labels, and annotated current slots.  For
    backward compatibility with existing runner helpers, parser output is also
    available through ``slots``; those slots are derived only from visible
    request text and method-local previous state.
    """
    user_input = str(case.get("user_input") or "").strip()
    dialogue_history = _dialogue_history(case)
    parsed_slots = parse_visible_request_slots(user_input, dialogue_history=dialogue_history)
    current_turn_slots = normalize_slots(_parse_visible_text_slots(user_input))
    previous_state = sanitize_method_previous_state(case.get("previous_state"))
    method_input = {
        "schema_version": METHOD_INPUT_SCHEMA_VERSION,
        "method": str(method),
        "case_id": str(case.get("case_id") or ""),
        "user_input": user_input,
        "dialogue_history": dialogue_history,
        "parsed_slots": parsed_slots,
        "current_turn_slots": current_turn_slots,
        "method_previous_state": previous_state,
        "parser": {
            "name": "visible_text_rule_parser",
            "version": "2026-07-28",
            "source": "user_input_and_dialogue_history_only",
        },
        "visibility": {
            "gold_visible": False,
            "evaluator_only_fields_removed": [
                field for field in EVALUATOR_ONLY_FIELDS if field in case
            ],
        },
    }

    generation_case: dict[str, Any] = {
        "case_id": str(case.get("case_id") or ""),
        "user_input": user_input,
        "dialogue_history": dialogue_history,
        "method_input": method_input,
        "method_input_schema_version": METHOD_INPUT_SCHEMA_VERSION,
        "parsed_slots": parsed_slots,
        "current_turn_slots": current_turn_slots,
        "constraints": [],
        "evaluation_mode": str(case.get("evaluation_mode") or "end_to_end"),
    }
    if previous_state is not None:
        generation_case["method_previous_state"] = previous_state
        generation_case["previous_state"] = previous_state

    for key in ("session_id", "conversation_id", "thread_id"):
        if case.get(key):
            generation_case[key] = case[key]
    return generation_case


def parse_visible_request_slots(
    user_input: str,
    *,
    dialogue_history: Any = None,
) -> dict[str, Any]:
    """Parse basic tourism slots from generation-visible text only."""
    history_slots = _parse_visible_text_slots(_history_visible_text(dialogue_history))
    current_slots = _parse_visible_text_slots(str(user_input or ""))
    return normalize_slots({**history_slots, **current_slots})


def _parse_visible_text_slots(text: str) -> dict[str, Any]:
    slots: dict[str, Any] = {}

    city = _parse_city(text)
    if city:
        slots["destination"] = city

    duration = _parse_duration_days(text)
    if duration is not None:
        slots["duration_days"] = duration

    people = _parse_people_count(text)
    if people is not None:
        slots["people_count"] = people

    start_date = _parse_start_date(text)
    if start_date:
        slots["start_date"] = start_date

    budget_amount = _parse_budget_amount(text)
    if budget_amount is not None:
        slots["budget_amount"] = budget_amount

    budget_level = _parse_budget_level(text)
    if budget_level:
        slots["budget_level"] = budget_level

    traveler_group = _parse_traveler_group(text)
    if traveler_group:
        slots["traveler_group"] = traveler_group

    preferences = _parse_preferences(text)
    if preferences:
        slots["preferences"] = preferences

    weather_scenario = _parse_weather_scenario(text)
    if weather_scenario:
        slots["weather_scenario"] = weather_scenario

    special_requirements = _parse_special_requirements(text)
    if special_requirements:
        slots["special_requirements"] = special_requirements

    return slots


def sanitize_method_previous_state(previous_state: Any) -> dict[str, Any] | None:
    """Remove evaluator-only fields from method-visible previous state."""
    if not isinstance(previous_state, Mapping):
        return None
    sanitized = {
        str(key): value
        for key, value in previous_state.items()
        if str(key) not in PREVIOUS_STATE_EVALUATOR_ONLY_FIELDS
    }
    output = sanitized.get("output")
    if isinstance(output, Mapping):
        sanitized["output"] = {
            str(key): value
            for key, value in output.items()
            if str(key) not in PREVIOUS_STATE_EVALUATOR_ONLY_FIELDS
        }
    raw_output = sanitized.get("raw_output")
    if isinstance(raw_output, Mapping):
        sanitized["raw_output"] = {
            str(key): value
            for key, value in raw_output.items()
            if str(key) not in PREVIOUS_STATE_EVALUATOR_ONLY_FIELDS
        }
    return sanitized


def contains_evaluator_only_generation_fields(case: Mapping[str, Any]) -> bool:
    """Return True when a generation payload still exposes forbidden fields."""
    return any(field in case for field in EVALUATOR_ONLY_FIELDS)


def _combined_visible_text(user_input: str, dialogue_history: Any) -> str:
    parts = [str(user_input or "")]
    history_text = _history_visible_text(dialogue_history)
    if history_text:
        parts.append(history_text)
    return " ".join(part for part in parts if part)


def _history_visible_text(dialogue_history: Any) -> str:
    parts: list[str] = []
    if isinstance(dialogue_history, list):
        for item in dialogue_history:
            if isinstance(item, Mapping):
                parts.append(str(item.get("content") or item.get("text") or ""))
            else:
                parts.append(str(item))
    elif dialogue_history:
        parts.append(str(dialogue_history))
    return " ".join(part for part in parts if part)


def _dialogue_history(case: Mapping[str, Any]) -> list[Any]:
    for key in ("dialogue_history", "history"):
        value = case.get(key)
        if isinstance(value, list):
            return list(value)
    return []


def _parse_city(text: str) -> str | None:
    lowered = text.casefold()
    for city_id, aliases in CITY_PATTERNS:
        if any(alias.casefold() in lowered for alias in aliases):
            return city_id
    return None


def _parse_duration_days_chinese_terms(text: str) -> int | None:
    number = r"\d{1,2}|\u4e00|\u4e8c|\u4e24|\u4fe9|\u4e09|\u56db|\u4e94|\u516d|\u4e03|\u516b|\u4e5d|\u5341"
    patterns = (
        rf"(?:\u6539\u6210|\u6539\u5230|\u6539\u4e3a|\u8c03\u6574\u4e3a|\u53d8\u6210|\u5ef6\u957f\u5230|\u7f29\u77ed\u5230)\s*({number})\s*(?:\u5929|\u65e5)(?:\u6e38|\u884c\u7a0b|\u65c5\u884c|\u65c5\u7a0b|\u8ba1\u5212)?",
        rf"(?:\u73a9|\u6e38\u73a9|\u65c5\u884c|\u65c5\u6e38|\u884c\u7a0b|\u8ba1\u5212|\u5b89\u6392)\s*({number})\s*(?:\u5929|\u65e5)",
        rf"(?<!\d)(?<!\u7b2c)(?<!\u6708)({number})\s*(?:\u5929|\u65e5)[\u4e00-\u9fff]{{0,12}}(?:\u884c\u7a0b|\u65c5\u884c|\u65c5\u7a0b|\u65b9\u6848|\u5b89\u6392)",
        rf"(?<!\d)(?<!\u7b2c)(?<!\u6708)({number})\s*(?:\u5929|\u65e5)\s*(?:[\u3001\uff0c,;\uff1b]\s*)?(?=(?:{number})\s*(?:\u4eba|\u4f4d|\u540d|\u4e2a\u4eba)|(?:\u9884\u7b97|\u90fd\u4fdd\u6301|\u90fd\u4e0d\u53d8|\u4fdd\u6301\u4e0d\u53d8|\u4e0d\u53d8))",
        rf"(?<!\d)(?<!\u7b2c)(?<!\u6708)({number})\s*(?:\u5929|\u65e5)(?:\u6e38|\u884c\u7a0b|\u65c5\u884c|\u65c5\u7a0b|\u8ba1\u5212|\u5b89\u6392|\u5929\u6c14|\u5929\u6c14\u9884\u62a5|\u9884\u62a5|\u90fd\u4e0d\u53d8|\u4e0d\u53d8)",
    )
    return _first_bounded_number(text, patterns, minimum=1, maximum=5)


def _parse_duration_days(text: str) -> int | None:
    chinese_duration = _parse_duration_days_chinese_terms(text)
    if chinese_duration is not None:
        return chinese_duration
    if _has_cjk(text) and re.search(r"第\s*(?:\d{1,2}|一|二|两|俩|三|四|五|六|七|八|九|十)\s*天", text):
        return None
    patterns = (
        r"(?:改成|改到|调整为|变成|延长到|缩短到)\s*(\d{1,2}|一|二|两|俩|三|四|五|六|七|八|九|十)\s*(?:天|日)(?:游|行程|旅行|旅程|计划)?",
        r"(?:玩|游玩|旅行|旅游|行程|计划|安排)\s*(\d{1,2}|一|二|两|俩|三|四|五|六|七|八|九|十)\s*(?:天|日)",
        r"(?<!第)(\d{1,2}|一|二|两|俩|三|四|五|六|七|八|九|十)\s*(?:天|日)(?:游|行程|旅行|旅程|计划|安排)",
        r"(?:改成|改到|调整为|变成)\s*(\d{1,2})\s*(?:天|晚)",
        r"(?:改成|改到|调整为|变成)\s*([一二两三四五六七八九十])\s*(?:天|日|晚)",
        r"\b(?:change|adjust|switch|set)\b.*?\bto\s+(\d{1,2})\s*(?:days?|day)\b",
        r"\b(?:change|adjust|switch|set)\b.*?\bto\s+(one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:days?|day)\b",
        r"([一二两三四五六七八九十])\s*(?:天|日|晚)",
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten)[-\s]*(?:day|days)\b",
        r"(\d{1,2})\s*(?:天|晚|days?|day)",
    )
    return _first_bounded_number(text, patterns, minimum=1, maximum=5)


def _parse_people_count(text: str) -> int | None:
    chinese_fallback = _parse_people_count_chinese_terms(text)
    if chinese_fallback is not None:
        return chinese_fallback
    if _has_cjk(text):
        return None
    patterns = (
        r"(?:人数|出行人数|游客数|同行人数|旅客数|人数改成|改成|改到|调整为|变成|换成)\s*(\d{1,2}|一|二|两|俩|三|四|五|六|七|八|九|十)\s*(?:人|位|名|个大人|个成人)?",
        r"(\d{1,2}|一|二|两|俩|三|四|五|六|七|八|九|十)\s*(?:人|位|名|个大人|个成人|名游客|名旅客)",
        r"(?:一家|家庭|亲子)\s*(\d{1,2}|一|二|两|俩|三|四|五|六|七|八|九|十)\s*口",
        r"\b(?:change|adjust|switch|set)\b.*?\bto\s+(\d{1,2})\s*(?:people|persons|travelers|adults)\b",
        r"\b(?:change|adjust|switch|set)\b.*?\bto\s+(one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:people|persons|travelers|adults)\b",
        r"(\d{1,2})\s*(?:人|位|个大人|名)",
        r"([一二两三四五六七八九十])\s*(?:人|位|个大人|名)",
        r"\bfor\s+(one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:people|persons|travelers|adults)\b",
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:people|persons|travelers|adults)\b",
    )
    parsed = _first_bounded_number(text, patterns, minimum=1, maximum=20)
    if parsed is not None:
        return parsed
    lowered = text.casefold()
    if any(term in lowered for term in ("情侣", "夫妻", "couple")):
        return 2
    return None


def _parse_people_count_chinese_terms(text: str) -> int | None:
    robust = _parse_people_count_chinese_terms_ascii(text)
    if robust is not None:
        return robust
    if _has_cjk(text):
        return None
    patterns = (
        r"(?:人数|出行人数|游客数|同行人数|旅客数|人数改成|改成|改到|调整为|变成|换成)\s*(\d{1,2}|一|二|两|俩|三|四|五|六|七|八|九|十)\s*(?:人|位|名|个大人|个成人)?",
        r"(\d{1,2}|一|二|两|俩|三|四|五|六|七|八|九|十)\s*(?:人|位|名|个人|个大人|个成人|名游客|名旅客)",
        r"(?:一家|家庭|亲子)\s*(\d{1,2}|一|二|两|俩|三|四|五|六|七|八|九|十)\s*口",
    )
    parsed = _first_bounded_number(text, patterns, minimum=1, maximum=20)
    if parsed is not None:
        return parsed
    lowered = text.casefold()
    if any(term in lowered for term in ("情侣", "夫妻", "双人")):
        return 2
    return None


def _parse_people_count_chinese_terms_ascii(text: str) -> int | None:
    number = r"\d{1,2}|\u4e00|\u4e8c|\u4e24|\u4fe9|\u4e09|\u56db|\u4e94|\u516d|\u4e03|\u516b|\u4e5d|\u5341"
    patterns = (
        rf"(?:\u4eba\u6570|\u51fa\u884c\u4eba\u6570|\u6e38\u5ba2\u6570|\u540c\u884c\u4eba\u6570|\u65c5\u5ba2\u6570)\s*(?:\u6539\u6210|\u6539\u5230|\u8c03\u6574\u4e3a|\u53d8\u6210|\u6362\u6210)?\s*({number})\s*(?:\u4eba|\u4f4d|\u540d|\u4e2a\u4eba|\u4e2a\u5927\u4eba|\u4e2a\u6210\u4eba)",
        rf"(?:\u6539\u6210|\u6539\u5230|\u8c03\u6574\u4e3a|\u53d8\u6210|\u6362\u6210)\s*({number})\s*(?:\u4eba|\u4f4d|\u540d|\u4e2a\u4eba|\u4e2a\u5927\u4eba|\u4e2a\u6210\u4eba)",
        rf"({number})\s*(?:\u4eba|\u4f4d|\u540d|\u4e2a\u4eba|\u4e2a\u5927\u4eba|\u4e2a\u6210\u4eba|\u540d\u6e38\u5ba2|\u540d\u65c5\u5ba2)",
        rf"(?:\u4e00\u5bb6|\u5bb6\u5ead|\u4eb2\u5b50)\s*({number})\s*\u53e3",
    )
    parsed = _first_bounded_number(text, patterns, minimum=1, maximum=20)
    if parsed is not None:
        return parsed
    lowered = text.casefold()
    if any(term in lowered for term in ("\u60c5\u4fa3", "\u592b\u59bb", "\u53cc\u4eba")):
        return 2
    return None


def _parse_start_date(text: str) -> str | None:
    match = re.search(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日?", text)
    if match:
        year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return _format_date(year, month, day)
    match = re.search(r"(?<!\d)(\d{1,2})月\s*(\d{1,2})日?", text)
    if match:
        return _format_date(2026, int(match.group(1)), int(match.group(2)))
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日)?", text)
    if match:
        year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return _format_date(year, month, day)
    match = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})日", text)
    if match:
        return _format_date(2026, int(match.group(1)), int(match.group(2)))
    return None


def _parse_budget_amount(text: str) -> int | None:
    patterns = (
        r"(?:预算|费用|花费|总预算|上限).*?(?:改成|改到|改为|调整为)\s*(\d{2,6})\s*(?:元|块|人民币|rmb|cny|yuan)?",
        r"(?:预算|费用|花费|不超过|控制在|上限|经费)\s*(\d{2,6})\s*(?:元|块|人民币|rmb|cny|yuan)?",
        r"(\d{2,6})\s*(?:元|块|人民币|rmb|cny|yuan)",
        r"(?:预算|费用|花费|不超过|控制在|under|within|budget)\s*(\d{2,6})\s*(?:元|块|rmb|cny|yuan)?",
        r"(\d{2,6})\s*(?:元|块|rmb|cny|yuan)",
    )
    return _first_bounded_number(text, patterns, minimum=1, maximum=999999)


def _parse_budget_level(text: str) -> str | None:
    lowered = text.casefold()
    if any(term in lowered for term in ("省钱", "低预算", "经济", "便宜", "穷游")):
        return "low"
    if any(term in lowered for term in ("豪华", "高预算", "高端", "舒适优先")):
        return "high"
    if any(term in lowered for term in ("中等", "标准", "适中", "正常消费")):
        return "medium"
    if any(term in lowered for term in ("省钱", "低预算", "经济", "便宜", "low budget", "cheap", "budget-friendly")):
        return "low"
    if any(term in lowered for term in ("豪华", "高预算", "高端", "luxury", "high budget")):
        return "high"
    if any(term in lowered for term in ("中等", "标准", "适中", "medium", "standard")):
        return "medium"
    return None


def _parse_traveler_group(text: str) -> str | None:
    lowered = text.casefold()
    if any(term in lowered for term in ("老人", "老年", "长辈", "senior", "elderly")):
        return "senior"
    if any(term in lowered for term in ("亲子", "儿童", "孩子", "家庭", "带娃", "family", "kids", "children")):
        return "family"
    if any(term in lowered for term in ("情侣", "夫妻", "couple")):
        return "couple"
    if any(term in lowered for term in ("老人", "老年", "senior", "elderly")):
        return "senior"
    if any(term in lowered for term in ("亲子", "儿童", "孩子", "family", "kids", "children")):
        return "family"
    if any(term in lowered for term in ("情侣", "夫妻", "couple")):
        return "couple"
    return None


def _parse_preferences(text: str) -> list[str]:
    lowered = text.casefold()
    preferences: list[str] = []
    mapping = (
        ("history_culture", ("历史", "文化", "博物馆", "古迹", "museum", "history", "culture")),
        ("nature", ("自然", "山水", "公园", "风景", "户外", "nature", "park", "scenery")),
        ("family", ("亲子", "儿童", "孩子", "家庭", "带娃", "family", "kids", "children")),
        ("indoor", ("室内", "馆内", "indoor")),
        ("history_culture", ("历史", "文化", "博物馆", "museum", "history", "culture")),
        ("nature", ("自然", "山水", "公园", "风景", "nature", "park", "scenery")),
        ("family", ("亲子", "儿童", "孩子", "family", "kids", "children")),
        ("indoor", ("室内", "indoor")),
    )
    for preference, terms in mapping:
        if any(term in lowered for term in terms):
            preferences.append(preference)
    return preferences


def _parse_weather_scenario(text: str) -> str | None:
    lowered = text.casefold()
    if any(term in lowered for term in ("高温", "炎热", "酷热", "hot", "high temperature")):
        return "high_temperature"
    if any(term in lowered for term in ("低温", "降温", "寒冷", "cold", "low temperature")):
        return "low_temperature"
    if any(term in lowered for term in ("下雨", "雨天", "有雨", "rain", "rainy")):
        return "rain"
    if any(term in lowered for term in ("高温", "炎热", "hot", "high temperature")):
        return "high_temperature"
    if any(term in lowered for term in ("低温", "降温", "cold", "low temperature")):
        return "low_temperature"
    if any(term in lowered for term in ("下雨", "雨天", "rain", "rainy")):
        return "rain"
    return None


def _parse_special_requirements(text: str) -> list[str]:
    lowered = text.casefold()
    requirements: list[str] = []
    if any(term in lowered for term in ("少走路", "轻松", "低强度", "少步行", "low intensity", "less walking")):
        requirements.append("low_intensity")
    if any(term in lowered for term in ("室内", "馆内", "indoor")):
        requirements.append("indoor_preferred")
    if any(term in lowered for term in ("少走路", "轻松", "low intensity", "less walking")):
        requirements.append("low_intensity")
    if any(term in lowered for term in ("室内", "indoor")):
        requirements.append("indoor_preferred")
    travel_avoidance_terms = (
        "避开拥挤",
        "避开人流",
        "避开高峰",
        "避开排队",
        "避开户外",
        "避免拥挤",
        "避免人流",
        "避免高峰",
        "避免排队",
        "避免户外",
        "避免暴晒",
        "不想走太多",
        "不要太赶",
        "avoid crowds",
        "avoid crowded",
        "avoid queues",
        "avoid outdoor",
        "avoid heat",
        "not too rushed",
    )
    if any(term in lowered for term in travel_avoidance_terms):
        requirements.append("avoidance_constraint")
    return requirements


def _first_bounded_number(
    text: str,
    patterns: tuple[str, ...],
    *,
    minimum: int,
    maximum: int,
) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = _number_value(match.group(1))
        if value is None:
            continue
        return max(minimum, min(value, maximum))
    return None


def _number_value(value: str) -> int | None:
    raw = str(value or "").strip().casefold()
    if raw.isdigit():
        return int(raw)
    return NUMBER_WORDS.get(raw)


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in str(text or ""))


def _format_date(year: int, month: int, day: int) -> str | None:
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"
