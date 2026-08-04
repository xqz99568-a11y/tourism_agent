"""Final Day7 delivery package for paper-level experiment evidence.

This module is intentionally thin.  It does not run benchmarks, call LLMs, or
re-score saved results.  It reads the already generated formal-run artifacts
and the Day7 submission archive, then writes one final handoff report that says
whether the run is ready to support paper writing.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.core.experiment_paper_analysis import DEFAULT_REQUIRED_METHODS
from app.core.paper_submission_pack import (
    PAPER_SUBMISSION_CHECKLIST_MD_NAME,
    PAPER_SUBMISSION_PACK_JSON_NAME,
    build_paper_submission_pack,
)


DAY7_DELIVERY_PACK_SCHEMA_VERSION = "ctp-day7-delivery-pack-v1"
DAY7_DELIVERY_PACK_JSON_NAME = "day7_delivery_pack.json"
DAY7_DELIVERY_REPORT_MD_NAME = "day7_delivery_report.md"


def build_day7_delivery_pack(
    run_dir: str | Path,
    *,
    min_cases: Optional[int] = None,
    required_methods: Optional[Iterable[str]] = None,
    allow_mock_llm: bool = False,
) -> Dict[str, Any]:
    """Build the final Day7 handoff package from saved formal-run artifacts."""
    root = Path(run_dir)
    required = _normalize_methods(required_methods or DEFAULT_REQUIRED_METHODS)
    submission_pack = build_paper_submission_pack(
        root,
        min_cases=min_cases,
        required_methods=required,
        allow_mock_llm=allow_mock_llm,
    )
    inventory = _delivery_inventory(root)
    readiness = _delivery_readiness(
        root=root,
        submission_pack=submission_pack,
        inventory=inventory,
    )
    return {
        "schema_version": DAY7_DELIVERY_PACK_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": root.as_posix(),
        "readiness": readiness,
        "source_submission": _source_submission(submission_pack),
        "day7_phases": _day7_phases(submission_pack, inventory, readiness),
        "artifact_inventory": inventory,
        "handoff_commands": _handoff_commands(root, readiness),
        "manual_next_steps": _manual_next_steps(readiness, submission_pack),
        "writing_boundaries": _dict(submission_pack.get("writing_boundaries")),
        "delivery_outputs": {},
    }


def write_day7_delivery_pack(
    run_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
    min_cases: Optional[int] = None,
    required_methods: Optional[Iterable[str]] = None,
    allow_mock_llm: bool = False,
    attach_to_manifest: bool = True,
) -> Dict[str, Any]:
    """Write ``day7_delivery_pack.json`` and ``day7_delivery_report.md``."""
    root = Path(run_dir)
    output = Path(output_dir) if output_dir is not None else root
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / DAY7_DELIVERY_PACK_JSON_NAME
    markdown_path = output / DAY7_DELIVERY_REPORT_MD_NAME
    pack = build_day7_delivery_pack(
        root,
        min_cases=min_cases,
        required_methods=required_methods,
        allow_mock_llm=allow_mock_llm,
    )
    pack["delivery_outputs"] = {
        "day7_delivery_pack_json": json_path.as_posix(),
        "day7_delivery_report_md": markdown_path.as_posix(),
    }
    if attach_to_manifest:
        _attach_to_manifest(
            root,
            pack=pack,
            json_path=json_path,
            markdown_path=markdown_path,
        )
    json_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_day7_delivery_report(pack), encoding="utf-8")
    readiness = _dict(pack.get("readiness"))
    return {
        "status": "completed",
        "delivery_status": readiness.get("status"),
        "paper_claims_allowed": readiness.get("paper_claims_allowed"),
        "failed_checks": readiness.get("failed_checks") or [],
        "pack": pack,
        "json": json_path.as_posix(),
        "markdown": markdown_path.as_posix(),
    }


def render_day7_delivery_report(pack: Dict[str, Any]) -> str:
    """Render a human-readable final Day7 delivery report."""
    readiness = _dict(pack.get("readiness"))
    lines = [
        "# Day7 小任务八：最终交付验收报告",
        "",
        "## 总状态",
        "",
        f"- delivery_status: `{readiness.get('status')}`",
        f"- paper_claims_allowed: `{readiness.get('paper_claims_allowed')}`",
        f"- failed_checks: `{readiness.get('failed_checks') or []}`",
        f"- interpretation: {readiness.get('interpretation')}",
        "",
        "## Day7 链路阶段",
        "",
        "| 阶段 | 状态 | 证据 | 说明 |",
        "|---|---|---|---|",
    ]
    for phase in pack.get("day7_phases") or []:
        if not isinstance(phase, dict):
            continue
        lines.append(
            f"| {phase.get('phase')} | `{phase.get('status')}` "
            f"| `{phase.get('evidence')}` | {phase.get('note')} |"
        )

    lines.extend(
        [
            "",
            "## 最终交付文件",
            "",
            "| 文件 | Exists | SHA-256 | Path |",
            "|---|---:|---|---|",
        ]
    )
    for item in _as_dict_list(pack.get("artifact_inventory")):
        lines.append(
            f"| {item.get('key')} | `{item.get('exists')}` "
            f"| `{item.get('sha256') or ''}` | `{item.get('path')}` |"
        )

    lines.extend(["", "## 下一步最短路径", ""])
    for item in pack.get("manual_next_steps") or []:
        if not isinstance(item, dict):
            continue
        lines.append(f"- [{item.get('priority')}] {item.get('item')}")

    lines.extend(["", "## 可复制命令", ""])
    for command in pack.get("handoff_commands") or []:
        if not isinstance(command, dict):
            continue
        lines.append(f"### {command.get('name')}")
        lines.append("")
        lines.append(f"```powershell\n{command.get('command')}\n```")
        lines.append("")

    boundaries = _dict(pack.get("writing_boundaries"))
    lines.extend(["## 写作边界", "", "### 可以写", ""])
    for item in _as_list(boundaries.get("allowed_claims")):
        lines.append(f"- {item}")
    lines.extend(["", "### 不能写", ""])
    for item in _as_list(boundaries.get("forbidden_claims")):
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def _delivery_readiness(
    *,
    root: Path,
    submission_pack: Dict[str, Any],
    inventory: List[Dict[str, Any]],
) -> Dict[str, Any]:
    submission_readiness = _dict(submission_pack.get("readiness"))
    checks = {
        "run_dir_exists": root.exists(),
        "submission_status_ready": submission_readiness.get("status") == "submission_ready",
        "submission_claims_allowed": submission_readiness.get("paper_claims_allowed") is True,
        "submission_failed_checks_empty": not _as_list(submission_readiness.get("failed_checks")),
        "submission_pack_json_present": (root / PAPER_SUBMISSION_PACK_JSON_NAME).exists(),
        "submission_checklist_md_present": (root / PAPER_SUBMISSION_CHECKLIST_MD_NAME).exists(),
        "delivery_artifact_hashes_recorded": _all_existing_hashes_recorded(inventory),
    }
    failed_checks = [key for key, value in checks.items() if not value]
    status = "delivery_ready" if not failed_checks else "delivery_blocked"
    return {
        "status": status,
        "paper_claims_allowed": status == "delivery_ready",
        "failed_checks": failed_checks,
        "checks": checks,
        "min_cases": submission_readiness.get("min_cases"),
        "independent_case_count": submission_readiness.get("independent_case_count"),
        "submission_status": submission_readiness.get("status"),
        "submission_failed_checks": submission_readiness.get("failed_checks") or [],
        "interpretation": _delivery_interpretation(status, failed_checks),
    }


def _delivery_inventory(root: Path) -> List[Dict[str, Any]]:
    return [
        _artifact_item("paper_submission_pack_json", root / PAPER_SUBMISSION_PACK_JSON_NAME),
        _artifact_item("paper_submission_checklist_md", root / PAPER_SUBMISSION_CHECKLIST_MD_NAME),
        _artifact_item("experiment_manifest", root / "experiment_manifest.json"),
        _artifact_item("paper_draft_md", root / "paper_draft.md"),
        _artifact_item("paper_result_pack_md", root / "paper_result_pack.md"),
        _artifact_item("formal_experiment_report", root / "formal_experiment_report.md"),
    ]


def _artifact_item(key: str, path: Path) -> Dict[str, Any]:
    exists = path.exists()
    return {
        "key": key,
        "path": path.as_posix(),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else None,
        "sha256": _file_sha256(path) if exists else None,
    }


def _source_submission(submission_pack: Dict[str, Any]) -> Dict[str, Any]:
    readiness = _dict(submission_pack.get("readiness"))
    source = _dict(submission_pack.get("source_status"))
    return {
        "schema_version": submission_pack.get("schema_version"),
        "status": readiness.get("status"),
        "paper_claims_allowed": readiness.get("paper_claims_allowed"),
        "failed_checks": readiness.get("failed_checks") or [],
        "run_id": source.get("run_id"),
        "formal_gate_status": source.get("formal_gate_status"),
        "paper_draft_status": source.get("paper_draft_status"),
    }


def _day7_phases(
    submission_pack: Dict[str, Any],
    inventory: List[Dict[str, Any]],
    readiness: Dict[str, Any],
) -> List[Dict[str, str]]:
    submission_readiness = _dict(submission_pack.get("readiness"))
    submission_checks = _dict(submission_readiness.get("checks"))
    artifact_by_key = {str(item.get("key")): item for item in inventory}
    return [
        _phase(
            "Phase0 实验协议",
            submission_checks.get("phase0_protocol_present"),
            "Phase0_实验协议.md",
            "论文实验边界和指标口径已经固定。",
        ),
        _phase(
            "正式实验核心产物",
            submission_checks.get("required_artifacts_present"),
            "benchmark_results / evaluation_summary / manifest",
            "四方法实验结果和独立评价汇总存在。",
        ),
        _phase(
            "正式证据门禁",
            submission_checks.get("formal_gate_passed"),
            "formal_experiment_gate.json",
            "确认不是 mock、不是 fallback，并且 trace 可审计。",
        ),
        _phase(
            "论文结果材料包",
            submission_checks.get("paper_result_pack_claims_allowed"),
            "paper_result_pack.json",
            "论文结果表和 RQ 口径可以引用。",
        ),
        _phase(
            "论文初稿包",
            submission_checks.get("paper_draft_claims_allowed"),
            "paper_draft_pack.json / paper_draft.md",
            "初稿结构已生成，但文献和期刊格式仍需人工处理。",
        ),
        _phase(
            "投稿归档包",
            bool(artifact_by_key.get("paper_submission_pack_json", {}).get("exists"))
            and bool(artifact_by_key.get("paper_submission_checklist_md", {}).get("exists"))
            and submission_readiness.get("status") == "submission_ready",
            "paper_submission_pack.json / paper_submission_checklist.md",
            "投稿前机器可检查材料已经装箱。",
        ),
        _phase(
            "Day7 最终交付验收",
            readiness.get("status") == "delivery_ready",
            "day7_delivery_pack.json / day7_delivery_report.md",
            "本报告给出最终能否进入论文人工改稿的结论。",
        ),
    ]


def _phase(phase: str, passed: Any, evidence: str, note: str) -> Dict[str, str]:
    return {
        "phase": phase,
        "status": "done" if passed is True else "blocked",
        "evidence": evidence,
        "note": note,
    }


def _handoff_commands(root: Path, readiness: Dict[str, Any]) -> List[Dict[str, str]]:
    min_cases = readiness.get("min_cases")
    if min_cases is None:
        min_cases = 100
    return [
        {
            "name": "先做小样本 pilot",
            "command": "python experiments/run_day7_pilot.py --max-cases 3",
        },
        {
            "name": "正式实验预检查",
            "command": (
                "python experiments/run_formal_experiment.py "
                f"--expected-cases {min_cases} --preflight-only"
            ),
        },
        {
            "name": "正式实验全链路运行",
            "command": (
                "python experiments/run_formal_experiment.py "
                f"--expected-cases {min_cases} --strict-paper-readiness"
            ),
        },
        {
            "name": "对已保存 formal run 重新生成论文材料",
            "command": (
                "python experiments/finalize_formal_experiment.py "
                f"--run-dir {root.as_posix()} --min-cases {min_cases} --strict"
            ),
        },
        {
            "name": "重新导出 Day7 最终交付验收报告",
            "command": (
                "python experiments/export_day7_delivery_pack.py "
                f"--run-dir {root.as_posix()} --min-cases {min_cases} --strict"
            ),
        },
    ]


def _manual_next_steps(
    readiness: Dict[str, Any],
    submission_pack: Dict[str, Any],
) -> List[Dict[str, str]]:
    steps: List[Dict[str, str]] = []
    if readiness.get("paper_claims_allowed") is not True:
        failed = ", ".join(_as_list(readiness.get("failed_checks"))) or "unknown"
        steps.append({"priority": "P0", "item": f"先修复 Day7 最终交付阻塞项：{failed}"})
    steps.extend(_as_dict_list(submission_pack.get("manual_next_steps")))
    if readiness.get("paper_claims_allowed") is True:
        steps.insert(
            0,
            {
                "priority": "P0",
                "item": "可以进入人工改稿：补真实参考文献、改期刊模板、核对图表编号。",
            },
        )
    return steps


def _attach_to_manifest(
    run_dir: Path,
    *,
    pack: Dict[str, Any],
    json_path: Path,
    markdown_path: Path,
) -> None:
    manifest_path = run_dir / "experiment_manifest.json"
    manifest = _read_json_object(manifest_path)
    if not manifest:
        return
    readiness = _dict(pack.get("readiness"))
    results = _dict(manifest.get("results"))
    results.update(
        {
            "day7_delivery_pack_json": json_path.as_posix(),
            "day7_delivery_report_md": markdown_path.as_posix(),
        }
    )
    manifest["results"] = results
    manifest["day7_delivery_pack"] = {
        "schema_version": DAY7_DELIVERY_PACK_SCHEMA_VERSION,
        "status": readiness.get("status"),
        "paper_claims_allowed": readiness.get("paper_claims_allowed"),
        "failed_checks": readiness.get("failed_checks") or [],
        "json": json_path.as_posix(),
        "markdown": markdown_path.as_posix(),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _delivery_interpretation(status: str, failed_checks: List[str]) -> str:
    if status == "delivery_ready":
        return "Day7 machine-checkable evidence is ready for paper drafting handoff."
    if failed_checks:
        return "Day7 delivery is blocked; fix failed_checks before treating this run as final evidence."
    return "Day7 delivery is not ready."


def _all_existing_hashes_recorded(items: List[Dict[str, Any]]) -> bool:
    return all(_is_sha256(item.get("sha256")) for item in items if item.get("exists") is True)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_object(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _normalize_methods(methods: Iterable[str]) -> List[str]:
    normalized = [str(method).strip() for method in methods if str(method).strip()]
    if not normalized:
        raise ValueError("required_methods must not be empty")
    return normalized


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text.lower())


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, tuple | set):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
    return [str(value)]


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
