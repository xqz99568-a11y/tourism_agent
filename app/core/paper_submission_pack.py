"""Submission archive package for paper-level experiment runs.

This module is the final Day7 evidence wrapper.  It does not run experiments,
call LLMs, or recompute evaluation scores.  It only checks and inventories the
already saved formal-run artifacts so the paper author has one place to verify
what can be submitted, what is still manual work, and how to reproduce the run.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.core.experiment_paper_analysis import DEFAULT_REQUIRED_METHODS
from app.core.formal_experiment_gate import FORMAL_EXPERIMENT_GATE_NAME
from app.core.paper_draft_pack import (
    PAPER_DRAFT_MD_NAME,
    PAPER_DRAFT_PACK_JSON_NAME,
    TARGET_JOURNAL,
)
from app.core.paper_result_pack import (
    PAPER_RESULT_PACK_JSON_NAME,
    PAPER_RESULT_PACK_MD_NAME,
)


PAPER_SUBMISSION_PACK_SCHEMA_VERSION = "ctp-paper-submission-pack-v1"
PAPER_SUBMISSION_PACK_JSON_NAME = "paper_submission_pack.json"
PAPER_SUBMISSION_CHECKLIST_MD_NAME = "paper_submission_checklist.md"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PHASE0_PROTOCOL_PATH = _PROJECT_ROOT / "Phase0_实验协议.md"

_RUN_ARTIFACTS = {
    "formal_preflight": "formal_preflight_report.json",
    "benchmark_results_csv": "benchmark_results.csv",
    "benchmark_results_json": "benchmark_results.json",
    "evaluation_summary": "evaluation_summary.json",
    "paper_tables": "paper_tables.md",
    "experiment_manifest": "experiment_manifest.json",
    "paper_analysis_json": "paper_analysis.json",
    "paper_analysis_md": "paper_analysis.md",
    "formal_experiment_gate": FORMAL_EXPERIMENT_GATE_NAME,
    "formal_experiment_report": "formal_experiment_report.md",
    "paper_result_pack_json": PAPER_RESULT_PACK_JSON_NAME,
    "paper_result_pack_md": PAPER_RESULT_PACK_MD_NAME,
    "paper_draft_pack_json": PAPER_DRAFT_PACK_JSON_NAME,
    "paper_draft_md": PAPER_DRAFT_MD_NAME,
}


def build_paper_submission_pack(
    run_dir: str | Path,
    *,
    min_cases: Optional[int] = None,
    required_methods: Optional[Iterable[str]] = None,
    allow_mock_llm: bool = False,
) -> Dict[str, Any]:
    """Build a submission-oriented archive package from saved artifacts."""
    root = Path(run_dir)
    required = _normalize_methods(required_methods or DEFAULT_REQUIRED_METHODS)
    gate = _read_json_object(root / FORMAL_EXPERIMENT_GATE_NAME)
    result_pack = _read_json_object(root / PAPER_RESULT_PACK_JSON_NAME)
    draft_pack = _read_json_object(root / PAPER_DRAFT_PACK_JSON_NAME)
    manifest = _read_json_object(root / "experiment_manifest.json")
    inventory = _artifact_inventory(root)
    readiness = _submission_readiness(
        root=root,
        gate=gate,
        result_pack=result_pack,
        draft_pack=draft_pack,
        inventory=inventory,
        required_methods=required,
        min_cases=_effective_min_cases(min_cases),
        allow_mock_llm=allow_mock_llm,
    )
    pack = {
        "schema_version": PAPER_SUBMISSION_PACK_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": root.as_posix(),
        "target_journal": TARGET_JOURNAL,
        "readiness": readiness,
        "source_status": _source_status(gate, result_pack, draft_pack, manifest),
        "evidence_chain": _evidence_chain(root, inventory),
        "artifact_inventory": inventory,
        "submission_checklist": _submission_checklist(readiness),
        "reproducibility": _reproducibility_block(root, readiness),
        "manual_next_steps": _manual_next_steps(readiness),
        "writing_boundaries": _writing_boundaries(result_pack, draft_pack),
        "submission_outputs": {},
    }
    return pack


def write_paper_submission_pack(
    run_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
    min_cases: Optional[int] = None,
    required_methods: Optional[Iterable[str]] = None,
    allow_mock_llm: bool = False,
    attach_to_manifest: bool = True,
) -> Dict[str, Any]:
    """Write ``paper_submission_pack.json`` and checklist Markdown."""
    root = Path(run_dir)
    output = Path(output_dir) if output_dir is not None else root
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / PAPER_SUBMISSION_PACK_JSON_NAME
    markdown_path = output / PAPER_SUBMISSION_CHECKLIST_MD_NAME
    pack = build_paper_submission_pack(
        root,
        min_cases=min_cases,
        required_methods=required_methods,
        allow_mock_llm=allow_mock_llm,
    )
    pack["submission_outputs"] = {
        "paper_submission_pack_json": json_path.as_posix(),
        "paper_submission_checklist_md": markdown_path.as_posix(),
    }
    if attach_to_manifest:
        _attach_to_manifest(
            root,
            pack=pack,
            json_path=json_path,
            markdown_path=markdown_path,
        )
        pack["artifact_inventory"] = _artifact_inventory(root)
        pack["evidence_chain"] = _evidence_chain(root, pack["artifact_inventory"])
    json_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_paper_submission_checklist(pack), encoding="utf-8")
    readiness = _dict(pack.get("readiness"))
    return {
        "status": "completed",
        "submission_status": readiness.get("status"),
        "paper_claims_allowed": readiness.get("paper_claims_allowed"),
        "failed_checks": readiness.get("failed_checks") or [],
        "pack": pack,
        "json": json_path.as_posix(),
        "markdown": markdown_path.as_posix(),
    }


def render_paper_submission_checklist(pack: Dict[str, Any]) -> str:
    """Render a human-readable submission checklist Markdown file."""
    readiness = _dict(pack.get("readiness"))
    reproducibility = _dict(pack.get("reproducibility"))
    lines = [
        "# Day7 小任务七：论文投稿归档包",
        "",
        "## 总状态",
        "",
        f"- submission_status: `{readiness.get('status')}`",
        f"- paper_claims_allowed: `{readiness.get('paper_claims_allowed')}`",
        f"- target_journal: `{pack.get('target_journal')}`",
        f"- failed_checks: `{readiness.get('failed_checks') or []}`",
        f"- interpretation: {readiness.get('interpretation')}",
        "",
        "## 投稿前检查清单",
        "",
        "| 类别 | 状态 | 检查项 | 证据 |",
        "|---|---|---|---|",
    ]
    for item in pack.get("submission_checklist") or []:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"| {item.get('group')} | `{item.get('status')}` "
            f"| {item.get('item')} | {item.get('evidence')} |"
        )

    lines.extend(["", "## 证据链", "", "| 顺序 | 证据 | 路径 | SHA-256 |", "|---:|---|---|---|"])
    for item in pack.get("evidence_chain") or []:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"| {item.get('order')} | {item.get('label')} "
            f"| `{item.get('path')}` | `{item.get('sha256') or ''}` |"
        )

    lines.extend(["", "## Artifact inventory", "", "| Artifact | Exists | Size | SHA-256 | Path |", "|---|---:|---:|---|---|"])
    for item in _as_dict_list(_nested(pack, "artifact_inventory", "files")):
        lines.append(
            f"| {item.get('key')} | `{item.get('exists')}` | {_fmt(item.get('size_bytes'))} "
            f"| `{item.get('sha256') or ''}` | `{item.get('path')}` |"
        )

    trace = _dict(_nested(pack, "artifact_inventory", "traces"))
    lines.extend(
        [
            "",
            "## Trace inventory",
            "",
            f"- trace_dir: `{trace.get('trace_dir')}`",
            f"- trace_file_count: `{trace.get('trace_file_count')}`",
            f"- trace_combined_sha256: `{trace.get('trace_combined_sha256')}`",
            "",
            "## 复现实验命令",
            "",
        ]
    )
    for command in _as_list(reproducibility.get("commands")):
        lines.append(f"```powershell\n{command}\n```")

    lines.extend(["", "## 手工待办", ""])
    for item in pack.get("manual_next_steps") or []:
        if not isinstance(item, dict):
            continue
        lines.append(f"- [{item.get('priority')}] {item.get('item')}")

    boundaries = _dict(pack.get("writing_boundaries"))
    lines.extend(["", "## 写作边界", "", "### 可以写", ""])
    for item in _as_list(boundaries.get("allowed_claims")):
        lines.append(f"- {item}")
    lines.extend(["", "### 不能写", ""])
    for item in _as_list(boundaries.get("forbidden_claims")):
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def _submission_readiness(
    *,
    root: Path,
    gate: Dict[str, Any],
    result_pack: Dict[str, Any],
    draft_pack: Dict[str, Any],
    inventory: Dict[str, Any],
    required_methods: List[str],
    min_cases: int,
    allow_mock_llm: bool,
) -> Dict[str, Any]:
    observed_methods = _as_list(gate.get("observed_methods"))
    missing_methods = [method for method in required_methods if method not in observed_methods]
    independent_case_count = _int(
        gate.get("independent_case_count"),
        _nested(result_pack, "readiness", "independent_case_count"),
        _nested(draft_pack, "readiness", "independent_case_count"),
        default=0,
    )
    trace = _dict(inventory.get("traces"))
    checks = {
        "run_dir_exists": root.exists(),
        "phase0_protocol_present": _PHASE0_PROTOCOL_PATH.exists(),
        "required_artifacts_present": _required_artifacts_present(inventory),
        "formal_gate_present": bool(gate),
        "formal_gate_passed": gate.get("status") == "passed",
        "formal_gate_claims_allowed": gate.get("paper_claims_allowed") is True,
        "paper_result_pack_present": bool(result_pack),
        "paper_result_pack_claims_allowed": _nested(result_pack, "readiness", "paper_claims_allowed") is True,
        "paper_draft_pack_present": bool(draft_pack),
        "paper_draft_markdown_present": (root / PAPER_DRAFT_MD_NAME).exists(),
        "paper_draft_claims_allowed": _nested(draft_pack, "readiness", "paper_claims_allowed") is True,
        "minimum_case_count_met": independent_case_count >= min_cases,
        "required_methods_present": not missing_methods,
        "trace_files_present": _int(trace.get("trace_file_count"), default=0) > 0,
        "trace_hash_recorded": _is_sha256(trace.get("trace_combined_sha256")),
        "artifact_hashes_recorded": _artifact_hashes_recorded(inventory),
        "no_mock_llm": bool(allow_mock_llm) or _int(_nested(gate, "trace_summary", "mock_llm_call_count"), default=0) == 0,
        "no_llm_fallback": _int(_nested(gate, "trace_summary", "fallback_llm_call_count"), default=0) == 0,
    }
    failed_checks = [key for key, value in checks.items() if not value]
    status = "submission_ready" if not failed_checks else "revision_needed"
    return {
        "status": status,
        "paper_claims_allowed": status == "submission_ready",
        "failed_checks": failed_checks,
        "checks": checks,
        "min_cases": min_cases,
        "independent_case_count": independent_case_count,
        "required_methods": required_methods,
        "missing_methods": missing_methods,
        "interpretation": _readiness_interpretation(status, failed_checks),
    }


def _artifact_inventory(root: Path) -> Dict[str, Any]:
    files = []
    phase0 = _artifact_item("phase0_protocol", _PHASE0_PROTOCOL_PATH)
    files.append(phase0)
    for key, filename in _RUN_ARTIFACTS.items():
        files.append(_artifact_item(key, root / filename))
    trace_dir = root / "traces"
    trace_files = sorted(trace_dir.glob("*.jsonl")) if trace_dir.exists() else []
    trace_hashes = [_file_sha256(path) for path in trace_files]
    return {
        "schema_version": "ctp-paper-submission-artifact-inventory-v1",
        "hash_strategy": "sha256_file_bytes_v1",
        "files": files,
        "traces": {
            "trace_dir": trace_dir.as_posix(),
            "trace_file_count": len(trace_files),
            "trace_combined_sha256": _combined_hash(trace_hashes),
            "trace_files": [
                {
                    "path": path.as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": trace_hashes[index],
                }
                for index, path in enumerate(trace_files)
            ],
        },
    }


def _artifact_item(key: str, path: Path) -> Dict[str, Any]:
    exists = path.exists()
    return {
        "key": key,
        "path": path.as_posix(),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else None,
        "sha256": _file_sha256(path) if exists else None,
    }


def _evidence_chain(root: Path, inventory: Dict[str, Any]) -> List[Dict[str, Any]]:
    file_by_key = {
        str(item.get("key")): item
        for item in _as_dict_list(inventory.get("files"))
    }
    ordered = [
        ("phase0_protocol", "Phase0 实验协议"),
        ("formal_preflight", "正式实验启动前门禁"),
        ("benchmark_results_json", "原始逐条实验结果"),
        ("evaluation_summary", "独立评价器汇总结果"),
        ("paper_analysis_json", "论文导向结果分析"),
        ("formal_experiment_gate", "正式证据门禁"),
        ("paper_result_pack_json", "论文结果材料包"),
        ("paper_draft_pack_json", "论文初稿包"),
        ("paper_draft_md", "论文初稿 Markdown"),
    ]
    chain = []
    for index, (key, label) in enumerate(ordered, start=1):
        item = _dict(file_by_key.get(key))
        chain.append(
            {
                "order": index,
                "key": key,
                "label": label,
                "path": item.get("path") or (root / _RUN_ARTIFACTS.get(key, "")).as_posix(),
                "exists": item.get("exists") is True,
                "sha256": item.get("sha256"),
            }
        )
    return chain


def _source_status(
    gate: Dict[str, Any],
    result_pack: Dict[str, Any],
    draft_pack: Dict[str, Any],
    manifest: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "run_id": manifest.get("run_id") or gate.get("run_id"),
        "formal_gate_status": gate.get("status") or "missing",
        "formal_gate_claims_allowed": gate.get("paper_claims_allowed"),
        "paper_result_pack_claims_allowed": _nested(result_pack, "readiness", "paper_claims_allowed"),
        "paper_draft_status": _nested(draft_pack, "readiness", "status") or "missing",
        "paper_draft_claims_allowed": _nested(draft_pack, "readiness", "paper_claims_allowed"),
    }


def _submission_checklist(readiness: Dict[str, Any]) -> List[Dict[str, str]]:
    checks = _dict(readiness.get("checks"))
    return [
        _check_item("实验归档", "Phase0 实验协议存在并记录 hash", checks.get("phase0_protocol_present"), "Phase0_实验协议.md"),
        _check_item("实验归档", "正式实验核心产物完整", checks.get("required_artifacts_present"), "run_dir/*.json, *.csv, *.md"),
        _check_item("论文证据", "formal gate 通过", checks.get("formal_gate_passed"), "formal_experiment_gate.json"),
        _check_item("论文证据", "结果材料包允许正式结论", checks.get("paper_result_pack_claims_allowed"), "paper_result_pack.json"),
        _check_item("论文证据", "论文初稿包允许正式结论", checks.get("paper_draft_claims_allowed"), "paper_draft_pack.json"),
        _check_item("复现审计", "trace 文件和 hash 已记录", checks.get("trace_hash_recorded"), "traces/*.jsonl"),
        _check_item("复现审计", "未使用 mock LLM 或 silent fallback", checks.get("no_mock_llm") and checks.get("no_llm_fallback"), "formal gate trace summary"),
        {
            "group": "人工写作",
            "status": "manual_required",
            "item": "人工补充真实相关工作和参考文献",
            "evidence": "paper_draft.md references section",
        },
        {
            "group": "人工写作",
            "status": "manual_required",
            "item": "按《电信科学》模板调整作者信息、图表编号和参考文献格式",
            "evidence": "journal template",
        },
    ]


def _check_item(group: str, item: str, passed: Any, evidence: str) -> Dict[str, str]:
    return {
        "group": group,
        "status": "done" if passed is True else "blocked",
        "item": item,
        "evidence": evidence,
    }


def _reproducibility_block(root: Path, readiness: Dict[str, Any]) -> Dict[str, Any]:
    min_cases = readiness.get("min_cases") or 100
    return {
        "note": "Commands are templates; credentials and .env values must not be committed.",
        "commands": [
            f"python experiments/run_formal_experiment.py --expected-cases {min_cases} --strict-paper-readiness",
            f"python experiments/finalize_formal_experiment.py --run-dir {root.as_posix()} --min-cases {min_cases} --strict",
            f"python experiments/export_paper_submission_pack.py --run-dir {root.as_posix()} --min-cases {min_cases} --strict",
        ],
    }


def _manual_next_steps(readiness: Dict[str, Any]) -> List[Dict[str, str]]:
    steps = []
    if readiness.get("paper_claims_allowed") is not True:
        failed = ", ".join(_as_list(readiness.get("failed_checks"))) or "unknown"
        steps.append({"priority": "P0", "item": f"先处理投稿归档阻塞项：{failed}"})
    steps.extend(
        [
            {"priority": "P0", "item": "人工补真实文献，尤其是 LLM 工具调用、多 Agent 协作调度、智慧旅游规划三类。"},
            {"priority": "P1", "item": "把 paper_draft.md 改写成期刊模板格式，避免保留自动生成提示语。"},
            {"priority": "P1", "item": "为方法部分补系统流程图或调度流程图，并保证图题与正文引用一致。"},
            {"priority": "P2", "item": "投稿前再次核对所有表格数字均来自 paper_result_pack 或 evaluation_summary。"},
        ]
    )
    return steps


def _writing_boundaries(result_pack: Dict[str, Any], draft_pack: Dict[str, Any]) -> Dict[str, List[str]]:
    boundaries = _dict(draft_pack.get("writing_boundaries")) or _dict(result_pack.get("writing_boundaries"))
    allowed = _as_list(boundaries.get("allowed_claims"))
    forbidden = _as_list(boundaries.get("forbidden_claims"))
    if not forbidden:
        forbidden = [
            "不要把 pilot 或未过门禁的结果写成正式结论",
            "不要声称使用实时、完整、商业级旅游数据",
            "不要声称真实用户满意度或商业部署可用性",
            "不要声称实验没有测量过的能力优势",
        ]
    return {"allowed_claims": allowed, "forbidden_claims": forbidden}


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
            "paper_submission_pack_json": json_path.as_posix(),
            "paper_submission_checklist_md": markdown_path.as_posix(),
        }
    )
    manifest["results"] = results
    manifest["paper_submission_pack"] = {
        "schema_version": PAPER_SUBMISSION_PACK_SCHEMA_VERSION,
        "status": readiness.get("status"),
        "paper_claims_allowed": readiness.get("paper_claims_allowed"),
        "failed_checks": readiness.get("failed_checks") or [],
        "json": json_path.as_posix(),
        "markdown": markdown_path.as_posix(),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _required_artifacts_present(inventory: Dict[str, Any]) -> bool:
    files = _as_dict_list(inventory.get("files"))
    return bool(files) and all(item.get("exists") is True for item in files)


def _artifact_hashes_recorded(inventory: Dict[str, Any]) -> bool:
    files = _as_dict_list(inventory.get("files"))
    return bool(files) and all(_is_sha256(item.get("sha256")) for item in files if item.get("exists") is True)


def _readiness_interpretation(status: str, failed_checks: List[str]) -> str:
    if status == "submission_ready":
        return "All machine-checkable evidence is archived for paper submission drafting."
    if failed_checks:
        return "Submission archive is blocked; fix failed_checks before treating results as final paper evidence."
    return "Submission archive is not ready for paper claims."


def _read_json_object(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _combined_hash(hashes: List[str]) -> Optional[str]:
    if not hashes:
        return None
    return hashlib.sha256("\n".join(sorted(hashes)).encode("utf-8")).hexdigest()


def _normalize_methods(methods: Iterable[str]) -> List[str]:
    normalized = [str(method).strip() for method in methods if str(method).strip()]
    if not normalized:
        raise ValueError("required_methods must not be empty")
    return normalized


def _effective_min_cases(value: Optional[int]) -> int:
    if value is None:
        return 100
    if isinstance(value, bool) or int(value) < 0:
        raise ValueError("min_cases must be a non-negative integer")
    return int(value)


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text.lower())


def _int(*values: Any, default: Optional[int] = None) -> Optional[int]:
    for value in values:
        number = _number(value)
        if number is not None:
            return int(number)
    return default


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


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


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return str(round(value, 4))
    return str(value)
