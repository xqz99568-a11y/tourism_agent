"""Human-friendly review batches for the frozen benchmark annotations.

This module deliberately renders only annotation evidence.  It does not read
model answers, run an experiment, or pre-fill a human approval decision.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


TASK_TYPE_LABELS = {
    "trip_planning": "完整旅游规划",
    "attraction_recommendation": "景点推荐",
    "weather_query": "天气查询",
    "budget_query": "预算查询",
    "partial_replan": "多轮局部修改",
    "weather_adjustment": "天气变化调整",
    "clarification": "信息不完整，需要澄清",
    "general_chat": "闲聊或非旅游任务",
}

CITY_LABELS = {
    "beijing": "北京",
    "hangzhou": "杭州",
    "xian": "西安",
    "shenzhen": "深圳",
    "guilin": "桂林",
}

SLOT_LABELS = {
    "destination": "城市",
    "start_date": "日期",
    "people_count": "人数",
    "duration_days": "天数",
    "budget_amount": "预算",
    "preferences": "偏好",
    "traveler_group": "出行人群",
    "special_requirements": "特殊要求",
    "weather_scenario": "天气情况",
    "budget_level": "消费档次",
}

AGENT_LABELS = {
    "attraction": "景点 Agent",
    "weather": "天气 Agent",
    "itinerary": "行程 Agent",
    "budget": "预算 Agent",
}

TOOL_LABELS = {
    "poi_search": "景点查询工具",
    "weather_query": "天气查询工具",
    "budget_calculator": "预算计算工具",
}

VALUE_LABELS = {
    "history_culture": "历史文化",
    "nature": "自然风景",
    "family": "亲子家庭",
    "indoor": "室内",
    "low_intensity": "低强度、少走路",
    "indoor_preferred": "室内优先",
    "avoidance_constraint": "避开拥挤或不适宜环境",
    "senior": "老年游客",
    "couple": "情侣或夫妻",
    "rain": "下雨",
    "high_temperature": "高温",
    "low_temperature": "低温",
    "low": "低消费",
    "medium": "中等消费",
    "high": "高消费",
}

PLAIN_REVIEW_FIELDS = (
    "编号",
    "用户问题",
    "任务类型",
    "城市/日期/人数/天数/预算",
    "变化条件",
    "保留条件",
    "需要的Agent",
    "需要的工具",
    "机器发现的问题",
    "你的决定",
    "你的备注",
)


def load_review_csv(path: str | Path) -> list[dict[str, str]]:
    """Load the current machine-prefilled review CSV."""
    review_path = Path(path)
    with review_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    return rows


def build_plain_review_row(row: Mapping[str, Any]) -> dict[str, str]:
    """Convert one annotation row into plain Chinese review fields."""
    row_number = _row_number(row.get("row_index"))
    unit_id = str(row.get("review_unit_id") or "").strip()
    gold = _json_mapping(row.get("gold_slots_json"))
    parsed = _json_mapping(
        row.get("current_parsed_slots_json") or row.get("parsed_slots_json")
    )
    required_tools = _csv_values(row.get("required_tools"))
    accepted_agents = _json_sets(row.get("accepted_agent_sets_json"))
    accepted_tools = _json_sets(row.get("accepted_tool_sets_json"))

    return {
        "编号": f"{row_number:03d}｜{unit_id}",
        "用户问题": str(row.get("user_input") or "").strip(),
        "任务类型": _task_type_text(row.get("task_type")),
        "城市/日期/人数/天数/预算": _core_slot_summary(
            gold,
            parsed,
            fallback_city=row.get("city_id"),
        ),
        "变化条件": _slot_change_summary(
            row.get("changed_slots_json"),
            gold,
            empty_text="无（本轮没有修改旧条件）",
        ),
        "保留条件": _slot_change_summary(
            row.get("preserved_slots_json"),
            gold,
            empty_text="无（单轮题目或本轮不需要保留旧条件）",
        ),
        "需要的Agent": _agent_sets_summary(accepted_agents),
        "需要的工具": _tool_summary(required_tools, accepted_tools),
        "机器发现的问题": _machine_issue_summary(row),
        "你的决定": "□ 通过　　□ 需要修改",
        "你的备注": "（由你填写；没有问题可以留空）",
    }


def write_plain_review_batches(
    *,
    review_csv_path: str | Path,
    output_dir: str | Path,
    batch_size: int = 10,
    expected_rows: int = 130,
) -> dict[str, Any]:
    """Write Markdown review batches and return a generation summary."""
    if batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")

    source = Path(review_csv_path)
    rows = load_review_csv(source)
    _validate_rows(rows, expected_rows=expected_rows)
    plain_rows = [build_plain_review_row(row) for row in rows]

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    batch_paths: list[Path] = []

    for offset in range(0, len(plain_rows), batch_size):
        batch_number = offset // batch_size + 1
        batch = plain_rows[offset : offset + batch_size]
        first_number = offset + 1
        last_number = offset + len(batch)
        batch_path = destination / (
            f"第{batch_number:02d}批_{first_number:03d}-{last_number:03d}.md"
        )
        batch_path.write_text(
            render_review_batch(
                batch,
                batch_number=batch_number,
                first_number=first_number,
                last_number=last_number,
                source_path=source,
                source_sha256=source_sha256,
            ),
            encoding="utf-8",
        )
        batch_paths.append(batch_path)

    index_path = destination / "00_审核说明与进度.md"
    index_path.write_text(
        render_review_index(
            batch_paths=batch_paths,
            row_count=len(plain_rows),
            batch_size=batch_size,
            source_path=source,
            source_sha256=source_sha256,
        ),
        encoding="utf-8",
    )
    return {
        "status": "generated",
        "source_csv": source.as_posix(),
        "source_sha256": source_sha256,
        "output_dir": destination.as_posix(),
        "row_count": len(plain_rows),
        "batch_size": batch_size,
        "batch_count": len(batch_paths),
        "index_path": index_path.as_posix(),
        "batch_paths": [path.as_posix() for path in batch_paths],
    }


def render_review_batch(
    rows: Sequence[Mapping[str, str]],
    *,
    batch_number: int,
    first_number: int,
    last_number: int,
    source_path: Path,
    source_sha256: str,
) -> str:
    lines = [
        f"# 第{batch_number:02d}批人工审核（{first_number:03d}—{last_number:03d}）",
        "",
        "本批只检查考试题和金标准是否可信，不检查模型答案、代码、Git或API。",
        "",
        f"- 来源：`{source_path.as_posix()}`",
        f"- 来源文件 SHA-256：`{source_sha256}`",
        f"- 本批数量：`{len(rows)}`",
        "",
        "审核时逐条阅读。如果十条都没有问题，完成后直接回复：",
        "",
        f"> 第{batch_number:02d}批：本批全部通过",
        "",
        "如果发现问题，请回复编号、问题和应改成什么；不要勉强填写通过。",
        "",
    ]
    for row in rows:
        display_number = row["编号"].split("｜", 1)[0]
        lines.extend(
            [
                f"## 第{display_number}条",
                "",
                "| 审核项 | 大白话内容 |",
                "|---|---|",
            ]
        )
        for field in PLAIN_REVIEW_FIELDS:
            lines.append(f"| {field} | {_escape_markdown_cell(row.get(field, ''))} |")
        lines.append("")

    lines.extend(
        [
            "## 本批最终回复",
            "",
            f"- 全部通过：`第{batch_number:02d}批：本批全部通过`",
            f"- 存在问题：`第{batch_number:02d}批：第___条需要修改，问题是___，建议改为___`",
            "",
        ]
    )
    return "\n".join(lines)


def render_review_index(
    *,
    batch_paths: Sequence[Path],
    row_count: int,
    batch_size: int,
    source_path: Path,
    source_sha256: str,
) -> str:
    lines = [
        "# Day7 正式测试集大白话人工审核",
        "",
        "## 你需要做什么",
        "",
        "从第01批开始，每次打开一个文件，认真检查其中10条题目和金标准。",
        "如果该批十条都正确，在对话中回复“第XX批：本批全部通过”；如果有问题，回复具体编号和修改意见。",
        "",
        "> 这些文件没有预填任何人工通过结论。只有你实际看完并回复后，才能记为人工审核完成。",
        "",
        "## 数据来源",
        "",
        f"- 当前复核表：`{source_path.as_posix()}`",
        f"- 来源文件 SHA-256：`{source_sha256}`",
        f"- 总评价轮次：`{row_count}`",
        f"- 每批：`{batch_size}` 条",
        f"- 批次数：`{len(batch_paths)}`",
        "",
        "## 审核进度",
        "",
    ]
    for batch_path in batch_paths:
        lines.append(f"- [ ] [{batch_path.stem}]({batch_path.name})")
    lines.extend(
        [
            "",
            "## 回复示例",
            "",
            "全部通过：",
            "",
            "> 第01批：本批全部通过",
            "",
            "发现问题：",
            "",
            "> 第03批：第027条需要修改。用户只要求景点推荐，不应要求天气工具。",
            "",
        ]
    )
    return "\n".join(lines)


def _validate_rows(rows: Sequence[Mapping[str, Any]], *, expected_rows: int) -> None:
    if len(rows) != expected_rows:
        raise ValueError(f"expected {expected_rows} review rows, found {len(rows)}")
    indices = [_row_number(row.get("row_index")) for row in rows]
    expected_indices = list(range(1, expected_rows + 1))
    if indices != expected_indices:
        raise ValueError("review rows must be ordered and numbered from 1 to expected_rows")
    unit_ids = [str(row.get("review_unit_id") or "").strip() for row in rows]
    if any(not unit_id for unit_id in unit_ids):
        raise ValueError("every review row must have a review_unit_id")
    if len(set(unit_ids)) != len(unit_ids):
        raise ValueError("review_unit_id values must be unique")


def _row_number(value: Any) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid review row_index: {value!r}") from exc
    if number <= 0:
        raise ValueError(f"invalid review row_index: {value!r}")
    return number


def _task_type_text(value: Any) -> str:
    task_type = str(value or "").strip()
    label = TASK_TYPE_LABELS.get(task_type, task_type or "未标注")
    return f"{label}（{task_type}）" if task_type else label


def _core_slot_summary(
    gold: Mapping[str, Any],
    parsed: Mapping[str, Any],
    *,
    fallback_city: Any,
) -> str:
    parts: list[str] = []
    fields = (
        ("destination", "城市"),
        ("start_date", "日期"),
        ("people_count", "人数"),
        ("duration_days", "天数"),
        ("budget_amount", "预算"),
    )
    for key, label in fields:
        gold_value = gold.get(key)
        parsed_value = parsed.get(key)
        if key == "destination" and gold_value in (None, "") and parsed_value in (None, ""):
            fallback = str(fallback_city or "").strip()
            if fallback:
                gold_value = fallback
        if gold_value in (None, "") and parsed_value in (None, ""):
            parts.append(f"{label}：未要求或未提供")
            continue
        if _values_equal(gold_value, parsed_value):
            parts.append(f"{label}：{_format_slot_value(key, gold_value)}（自动解析一致）")
            continue
        parts.append(
            f"{label}：金标={_format_slot_value(key, gold_value)}；"
            f"自动解析={_format_slot_value(key, parsed_value)}【请重点核对】"
        )
    return "；".join(parts)


def _slot_change_summary(value: Any, gold: Mapping[str, Any], *, empty_text: str) -> str:
    slots = _json_list(value)
    if not slots:
        return empty_text
    parts = []
    for slot in slots:
        key = str(slot)
        label = SLOT_LABELS.get(key, key)
        if key in gold:
            parts.append(f"{label}={_format_slot_value(key, gold.get(key))}")
        else:
            parts.append(label)
    return "；".join(parts)


def _agent_sets_summary(agent_sets: Sequence[Sequence[str]]) -> str:
    if not agent_sets or agent_sets == [[]]:
        return "无需调用旅游业务 Agent"
    rendered = []
    for index, agent_set in enumerate(agent_sets, start=1):
        names = [AGENT_LABELS.get(agent, agent) for agent in agent_set]
        content = " + ".join(names) if names else "无需业务 Agent"
        rendered.append(f"方案{index}：{content}")
    return "；".join(rendered)


def _tool_summary(
    required_tools: Sequence[str],
    accepted_tool_sets: Sequence[Sequence[str]],
) -> str:
    if not required_tools and (not accepted_tool_sets or accepted_tool_sets == [[]]):
        return "无需调用旅游工具"
    required = " + ".join(TOOL_LABELS.get(tool, tool) for tool in required_tools)
    parts = [f"最低需要：{required or '无'}"]
    alternatives = []
    for index, tool_set in enumerate(accepted_tool_sets, start=1):
        names = [TOOL_LABELS.get(tool, tool) for tool in tool_set]
        alternatives.append(f"方案{index}：{' + '.join(names) if names else '无需工具'}")
    if alternatives:
        parts.append(f"允许组合：{'；'.join(alternatives)}")
    return "；".join(parts)


def _machine_issue_summary(row: Mapping[str, Any]) -> str:
    issues: list[str] = []
    if not _truthy(row.get("parse_gold_match")):
        issues.append("自动解析与金标不一致")
    feasibility = str(row.get("offline_feasibility_status") or "").strip().lower()
    if feasibility == "failed":
        issues.append("离线资料无法支撑该题")
    machine_status = str(row.get("machine_review_status") or "").strip().lower()
    if machine_status == "needs_attention" and not issues:
        issues.append("机器标记为 needs_attention，但未给出更具体原因")
    if issues:
        return "；".join(f"【重点核对】{issue}" for issue in issues)
    if feasibility == "not_applicable":
        return "无明显问题：自动解析与金标一致；本题不需要离线旅游资料"
    return "无明显问题：自动解析与金标一致；离线资料可以支撑"


def _format_slot_value(key: str, value: Any) -> str:
    if value in (None, ""):
        return "未标注"
    if key == "destination":
        return CITY_LABELS.get(str(value), str(value))
    if key == "people_count":
        return f"{value}人"
    if key == "duration_days":
        return f"{value}天"
    if key == "budget_amount":
        return f"{value}元"
    if isinstance(value, list):
        return "、".join(VALUE_LABELS.get(str(item), str(item)) for item in value)
    return VALUE_LABELS.get(str(value), str(value))


def _values_equal(left: Any, right: Any) -> bool:
    if left in (None, "") and right in (None, ""):
        return True
    return left == right


def _json_mapping(value: Any) -> dict[str, Any]:
    parsed = _json_value(value, default={})
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _json_list(value: Any) -> list[Any]:
    parsed = _json_value(value, default=[])
    if isinstance(parsed, list):
        return list(parsed)
    if isinstance(parsed, Mapping):
        return list(parsed.keys())
    return []


def _json_sets(value: Any) -> list[list[str]]:
    parsed = _json_value(value, default=[])
    if not isinstance(parsed, list):
        return []
    output: list[list[str]] = []
    for item in parsed:
        if isinstance(item, list):
            output.append([str(entry) for entry in item])
    return output


def _json_value(value: Any, *, default: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    text = str(value or "").strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _csv_values(value: Any) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "passed"}


def _escape_markdown_cell(value: Any) -> str:
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "<br>")
        .replace("\n", "<br>")
        .strip()
    )
