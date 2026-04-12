from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
from uuid import uuid4

from app import cli_presenter


KNOWN_COMMANDS = {
    "/help": "help",
    "/new": "new",
    "/reset": "reset",
    "/json": "json",
    "/quit": "exit",
    "/exit": "exit",
}

COMPAT_COMMANDS = {
    "help": "/help",
    "new": "/new",
    "reset": "/reset",
}

EXIT_ALIASES = {"quit", "exit", "q", "/quit", "/exit"}


@dataclass(frozen=True)
class CLICommandMatch:
    kind: str
    raw_text: str
    normalized_text: str = ""
    command: str = ""
    compat_target: str = ""

    @property
    def is_command(self) -> bool:
        return self.kind in {"known", "unknown", "compat"}


@dataclass
class CLITurnResult:
    session_id: str
    show_json: bool
    should_exit: bool = False
    message: str = ""
    show_help: bool = False
    app_output: Dict[str, Any] | None = None


def normalize_cli_input(text: str) -> str:
    return str(text or "").strip()


def parse_cli_command(text: str) -> CLICommandMatch:
    normalized = normalize_cli_input(text)
    lowered = normalized.lower()
    if not lowered:
        return CLICommandMatch(kind="empty", raw_text=normalized, normalized_text=lowered)
    if lowered in EXIT_ALIASES:
        return CLICommandMatch(
            kind="known",
            raw_text=normalized,
            normalized_text=lowered,
            command="exit",
        )
    if lowered.startswith("/"):
        if lowered in KNOWN_COMMANDS:
            return CLICommandMatch(
                kind="known",
                raw_text=normalized,
                normalized_text=lowered,
                command=KNOWN_COMMANDS[lowered],
            )
        return CLICommandMatch(kind="unknown", raw_text=normalized, normalized_text=lowered)
    compat_target = COMPAT_COMMANDS.get(lowered)
    if compat_target:
        return CLICommandMatch(
            kind="compat",
            raw_text=normalized,
            normalized_text=lowered,
            compat_target=compat_target,
        )
    return CLICommandMatch(kind="natural", raw_text=normalized, normalized_text=lowered)


def classify_cli_text(text: str) -> str:
    return parse_cli_command(text).kind


def build_available_commands_text() -> str:
    return "可用命令：/help /new /reset /json /exit"


def build_unknown_command_response(text: str) -> str:
    return f"未知命令：{normalize_cli_input(text)}。{build_available_commands_text()}"


def build_compat_command_response(text: str, *, compat_target: Optional[str] = None) -> str:
    target = compat_target or COMPAT_COMMANDS.get(normalize_cli_input(text).lower()) or "/help"
    return f"如需执行命令，请输入 {target}。{build_available_commands_text()}"


def process_cli_turn(app: Any, *, raw_text: str, session_id: str, show_json: bool) -> CLITurnResult:
    normalized = str(raw_text or "").strip()
    if not normalized:
        return CLITurnResult(session_id=session_id, show_json=show_json)

    command = parse_cli_command(normalized)
    if command.kind == "known" and command.command == "exit":
        return CLITurnResult(
            session_id=session_id,
            show_json=show_json,
            should_exit=True,
            message="已退出。",
        )
    if command.kind == "known" and command.command == "help":
        return CLITurnResult(session_id=session_id, show_json=show_json, show_help=True)
    if command.kind == "known" and command.command == "new":
        new_session_id = f"cli-{uuid4().hex[:8]}"
        app.get_or_create_session(new_session_id)
        return CLITurnResult(
            session_id=new_session_id,
            show_json=show_json,
            message=f"已创建新会话: {new_session_id}",
        )
    if command.kind == "known" and command.command == "reset":
        app.reset_session(session_id)
        return CLITurnResult(
            session_id=session_id,
            show_json=show_json,
            message=f"已重置会话: {session_id}",
        )
    if command.kind == "known" and command.command == "json":
        toggled = not show_json
        return CLITurnResult(
            session_id=session_id,
            show_json=toggled,
            message=f"JSON显示: {'开启' if toggled else '关闭'}",
        )

    out = app.handle_query(normalized, session_id=session_id)
    return CLITurnResult(session_id=session_id, show_json=show_json, app_output=out)


def run_cli(app: Any, *, session_id: str = "cli-default", show_json: bool = False) -> None:
    current_session = session_id
    verbose_json = bool(show_json)
    cli_presenter.print_intro(session_id=current_session)
    runtime_prepared = False

    while True:
        try:
            raw = input("\n你> ")
        except (EOFError, KeyboardInterrupt):
            cli_presenter.print_message("\n已退出。")
            return

        try:
            if not runtime_prepared:
                command_probe = parse_cli_command(raw)
                if command_probe.kind == "natural" and hasattr(app, "ensure_runtime_initialized"):
                    if hasattr(app, "_print_thinking_steps"):
                        app._print_thinking_steps([
                            {
                                "agent": "系统",
                                "step": "运行时初始化",
                                "detail": "🔧 正在初始化核心组件...",
                                "status": "running",
                            }
                        ])
                    app.ensure_runtime_initialized()
                    runtime_prepared = True
                    if hasattr(app, "_print_thinking_steps"):
                        app._print_thinking_steps([
                            {
                                "agent": "系统",
                                "step": "运行时初始化",
                                "detail": "✅ 核心组件初始化完成",
                                "status": "completed",
                            }
                        ])

            turn = process_cli_turn(
                app,
                raw_text=raw,
                session_id=current_session,
                show_json=verbose_json,
            )
        except Exception as exc:
            cli_presenter.print_error(exc)
            continue

        current_session = turn.session_id
        verbose_json = turn.show_json

        if turn.show_help:
            cli_presenter.print_help()
            continue
        if turn.message:
            cli_presenter.print_message(turn.message)
        if turn.should_exit:
            return
        if turn.app_output is not None:
            cli_presenter.print_app_result(turn.app_output, show_json=verbose_json)
