"""Generation-visible input construction for formal experiment methods."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Mapping

from app.core.experiment_method_contract import EVALUATOR_ONLY_FIELDS
from app.core.goal_state_scheduler import build_goal_state_ticket, normalize_slots
from app.core.intercity_transport_snapshot import (
    INTERCITY_SUPPORTED_DESTINATION_CITY_IDS,
    INTERCITY_SUPPORTED_ORIGIN_CITY_IDS,
)


METHOD_INPUT_SCHEMA_VERSION = "ctp-method-input-v1"
REQUEST_UNDERSTANDING_SCHEMA_VERSION = "ctp-visible-request-understanding-v1"
DAY8_REFERENCE_DATE = date(2026, 8, 6)

VISIBLE_EXTRA_SLOT_ORDER = (
    "budget_basis",
    "requested_budget_scope",
    "budget_scope",
    "intercity_transport_included",
    "mandatory_budget_disclaimer",
    "hotel_level",
    "food_level",
    "intercity_transport_mode",
    "intercity_seat_class",
)

GENERATION_COMPATIBILITY_FIELDS = (
    "case_id",
    "user_input",
    "dialogue_history",
    "history",
    "method_input",
    "method_previous_state",
    "previous_state",
    "weather_change",
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

LOCATION_PATTERNS = CITY_PATTERNS + (
    ("lhasa", ("拉萨", "lhasa")),
    ("guangzhou", ("广州", "guangzhou")),
    ("shanghai", ("上海", "shanghai")),
    ("chengdu", ("成都", "chengdu")),
    ("chongqing", ("重庆", "chongqing")),
    ("wuhan", ("武汉", "wuhan")),
    ("changsha", ("长沙", "changsha")),
    ("nanjing", ("南京", "nanjing")),
    ("zhengzhou", ("郑州", "zhengzhou")),
    ("nanchang", ("南昌", "nanchang")),
    ("guiyang", ("贵阳", "guiyang")),
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
LOCATION_PATTERNS = tuple(
    (
        city_id,
        tuple(dict.fromkeys((*aliases, *CHINESE_CITY_ALIASES.get(city_id, ())))),
    )
    for city_id, aliases in LOCATION_PATTERNS
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
    parsed_understanding = parse_visible_request_understanding(
        user_input,
        dialogue_history=dialogue_history,
    )
    parsed_slots = dict(parsed_understanding["slots"])
    current_turn_slots = dict(parsed_understanding["current_turn_slots"])
    previous_state = sanitize_method_previous_state(case.get("previous_state"))
    method_input = {
        "schema_version": METHOD_INPUT_SCHEMA_VERSION,
        "method": str(method),
        "case_id": str(case.get("case_id") or ""),
        "user_input": user_input,
        "dialogue_history": dialogue_history,
        "parsed_slots": parsed_slots,
        "parsed_understanding": parsed_understanding,
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
    if isinstance(case.get("weather_change"), Mapping):
        method_input["weather_change"] = dict(case.get("weather_change") or {})

    generation_case: dict[str, Any] = {
        "case_id": str(case.get("case_id") or ""),
        "user_input": user_input,
        "dialogue_history": dialogue_history,
        "method_input": method_input,
        "method_input_schema_version": METHOD_INPUT_SCHEMA_VERSION,
        "parsed_slots": parsed_slots,
        "parsed_understanding": parsed_understanding,
        "current_turn_slots": current_turn_slots,
        "constraints": [],
        "evaluation_mode": str(case.get("evaluation_mode") or "end_to_end"),
    }
    if isinstance(case.get("weather_change"), Mapping):
        generation_case["weather_change"] = dict(case.get("weather_change") or {})
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
    return _normalize_visible_slots({**history_slots, **current_slots})


def parse_visible_request_understanding(
    user_input: str,
    *,
    dialogue_history: Any = None,
) -> dict[str, Any]:
    """Return the shared visible-text understanding used by CLI and experiments."""
    text = str(user_input or "")
    slots = parse_visible_request_slots(text, dialogue_history=dialogue_history)
    current_turn_slots = _normalize_visible_slots(_parse_visible_text_slots(text))
    ticket = build_goal_state_ticket(user_input=text, current_slots=slots)
    return {
        "schema_version": REQUEST_UNDERSTANDING_SCHEMA_VERSION,
        "task_type": ticket.task_type,
        "slots": slots,
        "current_turn_slots": current_turn_slots,
        "missing_slots": list(ticket.missing_slots),
        "required_capabilities": list(ticket.required_capabilities),
        "parser": {
            "name": "visible_text_rule_parser",
            "version": "2026-08-08-task1",
            "source": "user_input_and_dialogue_history_only",
            "llm_fallback_required": False,
        },
    }


def _normalize_visible_slots(slots: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = normalize_slots(slots)
    if not isinstance(slots, Mapping):
        return normalized
    for key in VISIBLE_EXTRA_SLOT_ORDER:
        if key not in slots:
            continue
        value = slots.get(key)
        if _is_visible_empty_value(value):
            continue
        normalized[key] = value
    return normalized


def _is_visible_empty_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _parse_visible_text_slots(text: str) -> dict[str, Any]:
    slots: dict[str, Any] = {}

    location_slots = _parse_origin_destination(text)
    slots.update(location_slots)

    city = _parse_city(text)
    if city and not slots.get("destination") and not slots.get("origin"):
        slots["destination"] = city

    date_range = _parse_date_range(text)
    if date_range:
        slots.update(date_range)

    duration = _parse_duration_days(text)
    if duration is not None:
        slots["duration_days"] = duration

    people = _parse_people_count(text)
    if people is not None:
        slots["people_count"] = people

    start_date = slots.get("start_date") or _parse_start_date(text)
    if start_date:
        slots["start_date"] = start_date

    budget_amount, budget_basis = _parse_budget_amount_with_basis(text, people)
    if budget_amount is not None:
        slots["budget_amount"] = budget_amount
    if budget_basis:
        slots["budget_basis"] = budget_basis

    budget_level = _parse_budget_level(text)
    if budget_level:
        slots["budget_level"] = budget_level

    hotel_level = _parse_hotel_level(text)
    if hotel_level:
        slots["hotel_level"] = hotel_level

    food_level = _parse_food_level(text)
    if food_level:
        slots["food_level"] = food_level

    budget_scope_slots = _parse_budget_scope_slots(text, slots)
    if budget_scope_slots:
        slots.update(budget_scope_slots)

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


def _parse_origin_destination(text: str) -> dict[str, str]:
    raw = str(text or "")
    if not raw:
        return {}

    locations = _find_locations(raw, include_external=True)
    if not locations:
        return {}

    slots: dict[str, str] = {}
    lowered = raw.casefold()
    english_route = re.search(
        r"\bfrom\s+([a-z][a-z\s']{1,30}?)\s+(?:to|towards|for)\s+([a-z][a-z\s']{1,30}?)(?=\s+(?:for|on|with|in|during|$)|[,.!?]|$)",
        lowered,
    )
    if english_route:
        origin = _city_id_from_alias_text(english_route.group(1))
        destination = _city_id_from_alias_text(english_route.group(2))
        if origin:
            slots["origin"] = origin
        if destination:
            slots["destination"] = destination
    origin_markers = ("从", "由")
    destination_markers = ("去", "到", "前往")
    for location in locations:
        before = raw[max(0, location["start"] - 4) : location["start"]]
        after = raw[location["end"] : location["end"] + 8]
        city_id = str(location["city_id"])
        origin_before = any(marker in before for marker in origin_markers)
        stripped_after = after.lstrip()
        origin_after = stripped_after.startswith(("出发", "去", "到", "前往", "坐", "乘"))
        traveler_transition_after_origin = (
            origin_before
            and stripped_after.startswith(("带", "和", "跟", "同"))
            and any(marker in raw[location["end"] :] for marker in destination_markers)
        )
        if after.startswith("出发") or (
            origin_before and (origin_after or traveler_transition_after_origin)
        ):
            slots.setdefault("origin", city_id)
            continue
        if any(marker in before for marker in destination_markers):
            slots.setdefault("destination", city_id)

    if slots.get("origin") and not slots.get("destination"):
        for location in locations:
            city_id = str(location["city_id"])
            if city_id != slots["origin"]:
                slots["destination"] = city_id
                break

    return slots


def _city_id_from_alias_text(text: str) -> str | None:
    lowered = str(text or "").casefold().strip()
    if not lowered:
        return None
    for city_id, aliases in LOCATION_PATTERNS:
        for alias in aliases:
            alias_lower = str(alias).casefold().strip()
            if alias_lower and lowered == alias_lower:
                return str(city_id)
    return None


def _find_locations(text: str, *, include_external: bool = False) -> list[dict[str, Any]]:
    patterns = LOCATION_PATTERNS if include_external else CITY_PATTERNS
    lowered = str(text or "").casefold()
    found: list[dict[str, Any]] = []
    for city_id, aliases in patterns:
        for alias in sorted(aliases, key=len, reverse=True):
            alias_lower = alias.casefold()
            start = lowered.find(alias_lower)
            if start < 0:
                continue
            found.append(
                {
                    "city_id": city_id,
                    "alias": alias,
                    "start": start,
                    "end": start + len(alias),
                }
            )
            break
    return sorted(found, key=lambda item: int(item["start"]))


def _parse_date_range(text: str) -> dict[str, Any]:
    match = re.search(
        r"(?<!\d)(\d{1,2})月\s*(\d{1,2})(?:日|号)?\s*(?:到|至|-|—)\s*(?:(\d{1,2})月)?\s*(\d{1,2})(?:日|号)?",
        text,
    )
    if not match:
        return {}
    start_month = int(match.group(1))
    start_day = int(match.group(2))
    end_month = int(match.group(3) or start_month)
    end_day = int(match.group(4))
    start = _date_or_none(2026, start_month, start_day)
    end = _date_or_none(2026, end_month, end_day)
    if start is None or end is None or end < start:
        return {}
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "duration_days": (end - start).days + 1,
    }


def _parse_duration_days_chinese_terms(text: str) -> int | None:
    date_range = _parse_date_range(text)
    if date_range.get("duration_days"):
        return int(date_range["duration_days"])
    if "明天" in text and "后天" in text:
        return 2
    single_day_relative_weather_query = (
        ("明天" in text or "后天" in text)
        and (
            "只看天气" in text
            or "天气怎么样" in text
            or "会不会下雨" in text
            or "适不适合安排户外" in text
        )
    )

    number = r"\d{1,2}|\u4e00|\u4e8c|\u4e24|\u4fe9|\u4e09|\u56db|\u4e94|\u516d|\u4e03|\u516b|\u4e5d|\u5341"
    patterns = (
        rf"(?:\u4ece[\u4e00-\u9fff\d-]{{0,12}}\u5f00\u59cb)?(?:\u8fde\u7eed|\u8fde\u7740|\u672a\u6765)\s*({number})\s*(?:\u5929|\u65e5)(?:\u7684)?(?:\u5929\u6c14|\u5929\u6c14\u9884\u62a5|\u9884\u62a5)",
        rf"(?:\u6539\u6210|\u6539\u5230|\u6539\u4e3a|\u8c03\u6574\u4e3a|\u53d8\u6210|\u5ef6\u957f\u5230|\u7f29\u77ed\u5230)\s*({number})\s*(?:\u5929|\u65e5)(?:\u6e38|\u884c\u7a0b|\u65c5\u884c|\u65c5\u7a0b|\u8ba1\u5212)?",
        rf"(?:\u73a9|\u6e38\u73a9|\u65c5\u884c|\u65c5\u6e38|\u884c\u7a0b|\u8ba1\u5212|\u5b89\u6392)\s*({number})\s*(?:\u5929|\u65e5)",
        rf"(?<!\d)(?<!\u7b2c)(?<!\u6708)({number})\s*(?:\u5929|\u65e5)[\u4e00-\u9fff]{{0,12}}(?:\u884c\u7a0b|\u65c5\u884c|\u65c5\u7a0b|\u65b9\u6848|\u5b89\u6392)",
        rf"(?<!\d)(?<!\u7b2c)(?<!\u6708)({number})\s*(?:\u5929|\u65e5)\s*(?:[\u3001\uff0c,;\uff1b]\s*)?(?=(?:{number})\s*(?:\u4eba|\u4f4d|\u540d|\u4e2a\u4eba)|(?:\u9884\u7b97|\u90fd\u4fdd\u6301|\u90fd\u4e0d\u53d8|\u4fdd\u6301\u4e0d\u53d8|\u4e0d\u53d8))",
        rf"(?<!\d)(?<!\u7b2c)(?<!\u6708)({number})\s*(?:\u5929|\u65e5)(?:\u6e38|\u884c\u7a0b|\u65c5\u884c|\u65c5\u7a0b|\u8ba1\u5212|\u5b89\u6392|\u5929\u6c14|\u5929\u6c14\u9884\u62a5|\u9884\u62a5|\u90fd\u4e0d\u53d8|\u4e0d\u53d8)",
    )
    duration_days = _first_bounded_number(text, patterns, minimum=1, maximum=5)
    if duration_days is not None:
        return duration_days
    if single_day_relative_weather_query:
        return 1
    return None


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
    lowered = text.casefold()
    explicit_total = _parse_explicit_total_people_count(text)
    if explicit_total is not None:
        return explicit_total
    if any(term in lowered for term in ("带爸妈", "带父母")):
        return 3
    if any(term in lowered for term in ("带孩子", "和朋友", "跟朋友", "朋友们", "孩子们", "和对象", "对象")):
        return 2

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
        r"\bfor\s+(\d{1,2})\s+(?:people|persons|travelers|adults)\b",
        r"\b(\d{1,2})\s+(?:people|persons|travelers|adults)\b",
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


def _parse_explicit_total_people_count(text: str) -> int | None:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return None
    total_markers = (
        "现在一共",
        "目前一共",
        "现在总共",
        "目前总共",
        "一共",
        "总共",
        "合计",
    )
    number = r"\d{1,2}|一|二|两|俩|三|四|五|六|七|八|九|十"
    for marker in total_markers:
        pattern = rf"{marker}({number})(?:个)?(?:人|位|名)"
        match = re.search(pattern, compact)
        if not match:
            continue
        value = _number_value(match.group(1))
        if value is not None:
            return max(1, min(value, 20))
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
    lowered = text.casefold()
    if "明天" in lowered:
        return (DAY8_REFERENCE_DATE + timedelta(days=1)).isoformat()
    if "后天" in lowered:
        return (DAY8_REFERENCE_DATE + timedelta(days=2)).isoformat()
    if "一个月后" in lowered:
        return _same_day_next_month(DAY8_REFERENCE_DATE).isoformat()
    if "未来" in lowered and "天气" in lowered:
        return (DAY8_REFERENCE_DATE + timedelta(days=1)).isoformat()
    if "国庆" in lowered or re.search(r"(?<![一二三四五六七八九十\d])十一(?!月|月份|\d)", lowered):
        return "2026-10-01"

    match = re.search(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})(?:日|号)?", text)
    if match:
        year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return _format_date(year, month, day)
    match = re.search(r"(?<!\d)(\d{1,2})月\s*(\d{1,2})(?:日|号)?", text)
    if match:
        return _format_date(2026, int(match.group(1)), int(match.group(2)))
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日)?", text)
    if match:
        year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return _format_date(year, month, day)
    match = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})(?:日|号)", text)
    if match:
        return _format_date(2026, int(match.group(1)), int(match.group(2)))
    return None


def _same_day_next_month(value: date) -> date:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    return date(year, month, value.day)


def _parse_budget_amount(text: str) -> int | None:
    amount, _basis = _parse_budget_amount_with_basis(text, people_count=None)
    return amount


def _parse_budget_amount_with_basis(
    text: str,
    people_count: int | None,
) -> tuple[int | None, str | None]:
    raw = str(text or "")
    if not raw:
        return None, None

    per_person_patterns = (
        r"(?:每人|每个人|每位|人均|单人)(?:预算|费用|花费|最多花|上限|不超过|控制在)?\s*(\d+(?:\.\d+)?)\s*(万|w|W|千|k|K|元|块|人民币|rmb|cny|yuan)?",
        r"(?:预算|费用|花费|最多花|上限|不超过|控制在)\s*(\d+(?:\.\d+)?)\s*(万|w|W|千|k|K|元|块|人民币|rmb|cny|yuan)?\s*(?:每人|每个人|每位|人均|单人)",
    )
    per_person_amount = _first_budget_money(raw, per_person_patterns)
    if per_person_amount is not None:
        multiplier = people_count if people_count is not None else 1
        return _rounded_int(per_person_amount * multiplier), "per_person"

    total_patterns = (
        r"(?:预算|费用|花费|经费|总预算|总费用|总花费)[^，。；;,.!?？\n]{0,16}?(?:从|由)\s*(?:\d+(?:\.\d+)?)\s*(?:万|w|W|千|k|K|元|块|人民币|rmb|cny|yuan)?\s*(?:改成|改到|改为|调整为|提高到|降到|变成)\s*(\d+(?:\.\d+)?)\s*(万|w|W|千|k|K|元|块|人民币|rmb|cny|yuan)?",
        r"(?:总预算|整体预算|总共最多花|一共最多花|整个行程总预算|预算总共|预算合计|总费用|总花费|总价|总额)\s*(?:上限|最多|不超过|控制在|大概|大约|约|是|为|到|在)?\s*(\d+(?:\.\d+)?)\s*(万|w|W|千|k|K|元|块|人民币|rmb|cny|yuan)?",
        r"(?:预算|费用|花费|不超过|控制在|上限|经费|最多花|够不够|钱够吗|钱够不够)[^，。；;,.!?？\n]{0,24}?(?:改成|改到|改为|调整为|提高到|降到|是|为|到|在|约|大概|大约)?\s*(\d+(?:\.\d+)?)\s*(万|w|W|千|k|K|元|块|人民币|rmb|cny|yuan)?(?:左右|以内|上下)?",
        r"(\d+(?:\.\d+)?)\s*(万|w|W|千|k|K|元|块|人民币|rmb|cny|yuan)(?:左右|以内|上下|预算|经费)?",
        r"\b(?:under|within|budget|cost|price)\b.*?(\d+(?:\.\d+)?)\s*(rmb|cny|yuan|k|K)?",
    )
    total_amount = _first_budget_money(raw, total_patterns)
    if total_amount is None:
        return None, None
    return _rounded_int(total_amount), "total"


def _first_budget_money(text: str, patterns: tuple[str, ...]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        amount = _safe_float(match.group(1))
        if amount is None:
            continue
        unit = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
        if not unit and text[match.end(1) : match.end(1) + 1] in {"年", "-", "/", "."}:
            continue
        normalized = _normalize_budget_money(amount, str(unit or ""))
        if 1 <= normalized <= 999999:
            return normalized
    return None


def _normalize_budget_money(amount: float, unit: str) -> float:
    normalized_unit = str(unit or "").strip().casefold()
    if normalized_unit in {"万", "w"}:
        return amount * 10000
    if normalized_unit in {"千", "k"}:
        return amount * 1000
    return amount


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rounded_int(value: float) -> int:
    rounded = round(float(value), 2)
    return int(rounded) if rounded.is_integer() else int(round(rounded))


def _parse_budget_level(text: str) -> str | None:
    lowered = text.casefold()
    if any(term in lowered for term in ("省钱", "低预算", "预算紧", "尽量便宜", "穷游", "low budget", "cheap", "budget-friendly")):
        return "low"
    if any(term in lowered for term in ("高预算", "豪华游", "高端游", "整体高端", "整体豪华", "舒适优先", "luxury", "high budget")):
        return "high"
    if any(term in lowered for term in ("整体中等", "整体适中", "正常消费", "中等预算", "medium", "standard")):
        return "medium"
    return None


def _parse_hotel_level(text: str) -> str | None:
    lowered = str(text or "").casefold()
    hotel_context = r"(?:住宿|酒店|住|民宿|宾馆|客栈|accommodation|hotel|lodging)"
    premium_terms = r"(?:高端|豪华|五星|星级好一点|premium|luxury)"
    comfort_terms = r"(?:舒适|舒服|品质|中档|中等|住好一点|comfort|medium)"
    economy_terms = r"(?:经济|省钱|便宜|青旅|青年旅舍|economy|hostel|cheap)"
    window = r"[^，。；,;!?？]{0,12}"
    if re.search(rf"{hotel_context}{window}{premium_terms}|{premium_terms}{window}{hotel_context}", lowered):
        return "premium"
    if re.search(rf"{hotel_context}{window}{comfort_terms}|{comfort_terms}{window}{hotel_context}", lowered):
        return "comfort"
    if re.search(rf"{hotel_context}{window}{economy_terms}|{economy_terms}{window}{hotel_context}", lowered):
        return "economy"
    return None


def _parse_food_level(text: str) -> str | None:
    lowered = str(text or "").casefold()
    food_context = r"(?:餐饮|吃饭|吃|美食|饭|餐|food|dining|meal)"
    premium_terms = r"(?:高端|高档|豪华|米其林|premium|luxury)"
    comfort_terms = r"(?:舒适|舒服|品质|中档|中等|吃好一点|特色|当地美食|comfort|medium)"
    economy_terms = r"(?:经济|省钱|便宜|小吃|快餐|economy|cheap|snack)"
    window = r"[^，。；,;!?？]{0,12}"
    if re.search(rf"{food_context}{window}{premium_terms}|{premium_terms}{window}{food_context}", lowered):
        return "premium"
    if re.search(rf"{food_context}{window}{comfort_terms}|{comfort_terms}{window}{food_context}", lowered):
        return "comfort"
    if re.search(rf"{food_context}{window}{economy_terms}|{economy_terms}{window}{food_context}", lowered):
        return "economy"
    return None


def _parse_budget_scope_slots(text: str, slots: Mapping[str, Any]) -> dict[str, Any]:
    lowered = str(text or "").casefold()
    if not _has_budget_scope_context(lowered, slots):
        return {}
    if not slots.get("destination"):
        return {}

    origin = str(slots.get("origin") or "").strip()
    destination = str(slots.get("destination") or "").strip()
    local_only = _is_local_only_budget_request(lowered)
    requested_scope = (
        "destination_local_only"
        if local_only
        else (
            "local_plus_round_trip_intercity"
            if origin or _requests_intercity_or_full_trip_budget(lowered)
            else "destination_local_only"
        )
    )

    result: dict[str, Any] = {"requested_budget_scope": requested_scope}
    if local_only or not origin:
        result.update(
            {
                "budget_scope": "destination_local_only",
                "intercity_transport_included": False,
                "mandatory_budget_disclaimer": bool(not origin and not local_only),
            }
        )
        return result

    if destination and origin == destination:
        result.update(
            {
                "budget_scope": "destination_local_only",
                "intercity_transport_included": False,
                "mandatory_budget_disclaimer": False,
            }
        )
        return result

    route_supported = (
        origin in set(INTERCITY_SUPPORTED_ORIGIN_CITY_IDS)
        and destination in set(INTERCITY_SUPPORTED_DESTINATION_CITY_IDS)
    )
    if route_supported:
        result.update(
            {
                "budget_scope": "local_plus_round_trip_intercity",
                "intercity_transport_included": True,
                "mandatory_budget_disclaimer": False,
                "intercity_transport_mode": "high_speed_rail",
                "intercity_seat_class": "second_class",
            }
        )
        return result

    result.update(
        {
            "budget_scope": "local_only_route_uncovered",
            "intercity_transport_included": False,
            "mandatory_budget_disclaimer": True,
            "intercity_transport_mode": "high_speed_rail",
            "intercity_seat_class": "second_class",
        }
    )
    return result


def _has_budget_scope_context(text: str, slots: Mapping[str, Any]) -> bool:
    has_budgetish_text = any(
        term in text
        for term in (
            "预算",
            "费用",
            "花费",
            "多少钱",
            "钱够",
            "够不够",
            "剩多少",
            "大交通",
            "城际",
            "高铁",
            "动车",
            "当地吃住行",
            "旅行费用",
            "total cost",
            "budget",
            "cost",
        )
    )
    if slots.get("budget_amount") is not None:
        return True
    if (
        not has_budgetish_text
        and any(term in text for term in ("天气", "下雨", "降雨", "高温", "低温", "weather", "rain"))
    ):
        return False
    if slots.get("destination") and (slots.get("duration_days") or slots.get("people_count")):
        if any(term in text for term in ("玩", "行程", "安排", "规划", "旅游", "旅行", "trip", "itinerary", "plan")):
            return True
    return has_budgetish_text


def _is_local_only_budget_request(text: str) -> bool:
    return any(
        term in text
        for term in (
            "只算当地",
            "只计算当地",
            "只看当地",
            "当地费用",
            "当地旅行费用",
            "当地吃住行",
            "目的地当地",
            "不含大交通",
            "不包含大交通",
            "不算大交通",
            "不包括大交通",
            "不含城际",
            "不包含城际",
            "不算城际",
            "不包括城际",
            "local only",
            "destination local only",
        )
    )


def _requests_intercity_or_full_trip_budget(text: str) -> bool:
    return any(
        term in text
        for term in (
            "大交通也算",
            "大交通算进去",
            "把大交通算进去",
            "城际交通也算",
            "城际交通算进去",
            "往返高铁",
            "高铁算进去",
            "高铁也算",
            "动车也算",
            "覆盖旅行费用",
            "全部旅行费用",
            "所有旅行费用",
            "总旅行费用",
            "我还没确定从哪里出发",
            "还没确定从哪里出发",
            "还没确定出发地",
            "from where",
            "round trip",
            "intercity",
        )
    )


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
    if any(term in lowered for term in ("高温", "炎热", "酷热", "怕热", "hot", "high temperature")):
        return "high_temperature"
    if any(term in lowered for term in ("低温", "降温", "寒冷", "cold", "low temperature")):
        return "low_temperature"
    if any(term in lowered for term in ("下雨", "雨天", "有雨", "降雨", "雨水", "rain", "rainy")):
        return "rain"
    if any(term in lowered for term in ("高温", "炎热", "怕热", "hot", "high temperature")):
        return "high_temperature"
    if any(term in lowered for term in ("低温", "降温", "cold", "low temperature")):
        return "low_temperature"
    if any(term in lowered for term in ("下雨", "雨天", "降雨", "rain", "rainy")):
        return "rain"
    return None


def _parse_special_requirements(text: str) -> list[str]:
    lowered = text.casefold()
    requirements: list[str] = []
    if any(term in lowered for term in ("少走路", "轻松", "低强度", "少步行", "节奏放慢", "膝盖不太好", "长时间步行", "low intensity", "less walking")):
        requirements.append("low_intensity")
    if any(term in lowered for term in ("室内", "馆内", "怕晒", "防晒", "indoor")):
        requirements.append("indoor_preferred")
    if any(term in lowered for term in ("少走路", "轻松", "low intensity", "less walking")):
        requirements.append("low_intensity")
    if any(term in lowered for term in ("室内", "怕晒", "防晒", "indoor")):
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
        "不想坐船",
        "不要坐船",
        "不坐船",
        "不要游船",
        "不坐游船",
        "不要竹筏",
        "不坐竹筏",
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
    resolved = _date_or_none(year, month, day)
    return resolved.isoformat() if resolved else None


def _date_or_none(year: int, month: int, day: int) -> date | None:
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None
