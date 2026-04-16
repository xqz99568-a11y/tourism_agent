from __future__ import annotations

import json
from typing import Any, Dict


INTRO_LINES = (
    "=" * 64,
    "旅游规划 Agent 系统 (CLI)",
    "=" * 64,
    "输入你的旅游需求，或使用 /help /new /reset /json /exit",
)

HELP_LINES = (
    "可用命令：",
    "/help  查看帮助",
    "/new   新建一个会话",
    "/reset 重置当前会话",
    "/json  切换是否显示 JSON",
    "/exit  退出",
)


def print_intro(*, session_id: str) -> None:
    for line in INTRO_LINES:
        print(line)
    print(f"当前会话: {session_id}")


def print_help() -> None:
    for line in HELP_LINES:
        print(line)


def print_message(message: str) -> None:
    if message:
        print(message)


def print_error(exc: Exception) -> None:
    print(f"系统> 处理失败: {exc}")


def _pick(out: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in out:
            return out.get(key)
    return None


def _pick_nested_dict(out: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    picked = _pick(out, *keys)
    if isinstance(picked, dict):
        return picked
    for value in out.values():
        if isinstance(value, dict) and any(key in value for key in ("mode", "ask_question", "issues", "draft", "缂哄け鏍稿績瀛楁")):
            return value
    return {}


def print_app_result(out: Dict[str, Any], *, show_json: bool) -> None:
    followup = _pick_nested_dict(out, "追问状态", "杩介棶鐘舵€?")
    display = _pick_nested_dict(out, "展示", "灞曠ず")
    mode = str(display.get("mode") or "")
    cli_streamed = bool(_pick(out, "cli_streamed"))
    reply = str(_pick(out, "系统答复", "绯荤粺绛斿") or "").strip()
    session_id = _pick(out, "会话ID", "浼氳瘽ID")
    turn_no = _pick(out, "轮次", "杞")

    print("\n系统> 处理完成")
    print(f"[会话] {session_id} | 第 {turn_no} 轮")

    if mode == "need_info":
        ask_question = str(_pick(display, "ask_question") or "请补充关键信息。")
        if not ask_question.strip().strip("?？"):
            ask_question = "玩几天？"
        missing = (
            followup.get("缺失核心字段")
            if isinstance(followup.get("缺失核心字段"), list)
            else (followup.get("缂哄け鏍稿績瀛楁") if isinstance(followup.get("缂哄け鏍稿績瀛楁"), list) else [])
        )
        missing_text = "" if ask_question == "玩几天？" else (f"（待补充：{'、'.join(str(x) for x in missing)}）" if missing else "")
        print(f"\n系统> 为便于继续规划，请补充：{ask_question}{missing_text}")
    elif mode == "need_revision":
        issues = display.get("issues") if isinstance(display.get("issues"), list) else []
        if issues:
            print("\n系统> 当前方案还需要继续优化，这里先给你可参考版本：")
            for idx, msg in enumerate(issues, start=1):
                print(f"{idx}. {msg}")
        if reply:
            print("\n系统> 当前建议版本：")
            print(reply)
        draft = display.get("draft") if isinstance(display.get("draft"), dict) else {}
        should_show_draft = bool(draft) and (not reply or len(reply) < 80)
        if should_show_draft:
            print("\n系统> 草案摘要：")
            _print_draft_summary(draft)
    elif not cli_streamed:
        print("系统> 最终答复：")
        if reply:
            print(reply)

    if show_json:
        print("\n--- JSON ---")
        print(json.dumps(out, ensure_ascii=False, indent=2))


def _print_draft_summary(draft: Dict[str, Any]) -> None:
    title = str(draft.get("标题") or "").strip()
    if title:
        print(title)
    pace = str(draft.get("节奏") or "").strip()
    if pace:
        print(f"节奏：{pace}")
    day_lines = draft.get("day_lines") if isinstance(draft.get("day_lines"), list) else []
    for line in day_lines[:10]:
        print(str(line))
    if draft.get("预算估算") is not None:
        print(f"预算估算：约 {draft.get('预算估算')} 元")
    if draft.get("预算上限") is not None:
        print(f"预算上限：{draft.get('预算上限')} 元")
    conclusion = str(draft.get("预算结论") or "").strip()
    if conclusion:
        print(f"预算结论：{conclusion}")
