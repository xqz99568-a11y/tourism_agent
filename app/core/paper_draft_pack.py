"""Paper draft package exporter for completed experiment runs.

This module turns the Day7 paper result pack into a manuscript-oriented draft.
It does not run experiments, call LLMs, fetch references, or modify measured
numbers.  The goal is to create a safe first-draft scaffold that tells the
author what can be written now and what still requires human writing.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.core.paper_result_pack import (
    PAPER_RESULT_PACK_JSON_NAME,
    PAPER_RESULT_PACK_SCHEMA_VERSION,
    build_paper_result_pack,
)


PAPER_DRAFT_PACK_SCHEMA_VERSION = "ctp-paper-draft-pack-v1"
PAPER_DRAFT_PACK_JSON_NAME = "paper_draft_pack.json"
PAPER_DRAFT_MD_NAME = "paper_draft.md"

DEFAULT_PAPER_TITLE = "面向约束旅游规划的目标—状态驱动多智能体协同调度方法"
TARGET_JOURNAL = "电信科学（拟投稿）"
METHOD_NAME = "目标—状态驱动的自适应多 Agent 协同调度方法"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PHASE0_PROTOCOL_PATH = _PROJECT_ROOT / "Phase0_实验协议.md"


def build_paper_draft_pack(
    run_dir: str | Path,
    *,
    profile: str = "auto",
    min_cases: Optional[int] = None,
    required_methods: Optional[Iterable[str]] = None,
    allow_mock_llm: bool = False,
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a manuscript draft package from saved experiment artifacts."""
    root = Path(run_dir)
    result_pack = build_paper_result_pack(
        root,
        profile=profile,
        min_cases=min_cases,
        required_methods=required_methods,
        allow_mock_llm=allow_mock_llm,
    )
    resolved_title = str(title or DEFAULT_PAPER_TITLE).strip() or DEFAULT_PAPER_TITLE
    readiness = _draft_readiness(result_pack)
    sections = _manuscript_sections(
        title=resolved_title,
        readiness=readiness,
        result_pack=result_pack,
    )
    pack = {
        "schema_version": PAPER_DRAFT_PACK_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": root.as_posix(),
        "target_journal": TARGET_JOURNAL,
        "title": resolved_title,
        "method_name": METHOD_NAME,
        "readiness": readiness,
        "paper_positioning": _paper_positioning(),
        "section_plan": _section_plan(readiness),
        "manuscript_sections": sections,
        "todo_list": _todo_list(readiness),
        "writing_boundaries": _dict(result_pack.get("writing_boundaries")),
        "source_artifacts": _source_artifacts(root, result_pack),
    }
    return pack


def write_paper_draft_pack(
    run_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
    profile: str = "auto",
    min_cases: Optional[int] = None,
    required_methods: Optional[Iterable[str]] = None,
    allow_mock_llm: bool = False,
    title: Optional[str] = None,
    attach_to_manifest: bool = True,
) -> Dict[str, Any]:
    """Write ``paper_draft_pack.json`` and ``paper_draft.md``."""
    root = Path(run_dir)
    output = Path(output_dir) if output_dir is not None else root
    output.mkdir(parents=True, exist_ok=True)
    pack = build_paper_draft_pack(
        root,
        profile=profile,
        min_cases=min_cases,
        required_methods=required_methods,
        allow_mock_llm=allow_mock_llm,
        title=title,
    )
    json_path = output / PAPER_DRAFT_PACK_JSON_NAME
    markdown_path = output / PAPER_DRAFT_MD_NAME
    pack["source_artifacts"]["paper_draft_pack_json"] = json_path.as_posix()
    pack["source_artifacts"]["paper_draft_md"] = markdown_path.as_posix()
    json_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_paper_draft_markdown(pack), encoding="utf-8")
    if attach_to_manifest:
        _attach_to_manifest(root, pack=pack, json_path=json_path, markdown_path=markdown_path)
    return {
        "status": "completed",
        "draft_status": pack["readiness"]["status"],
        "paper_claims_allowed": pack["readiness"]["paper_claims_allowed"],
        "failed_checks": pack["readiness"]["failed_checks"],
        "pack": pack,
        "json": json_path.as_posix(),
        "markdown": markdown_path.as_posix(),
    }


def render_paper_draft_markdown(pack: Dict[str, Any]) -> str:
    """Render the manuscript-oriented Markdown draft."""
    readiness = _dict(pack.get("readiness"))
    lines = [
        f"# {pack.get('title')}",
        "",
        "> 自动生成的论文初稿包。它只整理已有实验产物，不新增实验结论，不生成参考文献。",
        "",
        "## 写作状态",
        "",
        f"- target_journal: `{pack.get('target_journal')}`",
        f"- draft_status: `{readiness.get('status')}`",
        f"- paper_claims_allowed: `{readiness.get('paper_claims_allowed')}`",
        f"- source_result_pack_status: `{readiness.get('source_result_pack_status')}`",
        f"- failed_checks: `{readiness.get('failed_checks') or []}`",
        f"- interpretation: {readiness.get('interpretation')}",
        "",
        "## 论文定位",
        "",
    ]
    positioning = _dict(pack.get("paper_positioning"))
    lines.append(f"- 方法名称：{positioning.get('method_name')}")
    lines.append(f"- 核心问题：{positioning.get('core_problem')}")
    lines.append(f"- 主要比较：{positioning.get('primary_comparison')}")
    lines.append("- 贡献点：")
    for item in _as_list(positioning.get("contributions")):
        lines.append(f"  - {item}")

    lines.extend(["", "## 章节计划", "", "| 章节 | 写作状态 | 主要证据 |", "|---|---|---|"])
    for section in pack.get("section_plan") or []:
        if not isinstance(section, dict):
            continue
        evidence = ", ".join(_as_list(section.get("evidence")))
        lines.append(f"| {section.get('title')} | {section.get('status')} | {evidence} |")

    for section in pack.get("manuscript_sections") or []:
        if not isinstance(section, dict):
            continue
        lines.extend(
            [
                "",
                f"## {section.get('title')}",
                "",
                str(section.get("content") or ""),
            ]
        )

    lines.extend(["", "## 待办清单", ""])
    for item in pack.get("todo_list") or []:
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

    lines.extend(["", "## 来源产物", "", "| Key | Value |", "|---|---|"])
    for key, value in _dict(pack.get("source_artifacts")).items():
        lines.append(f"| {key} | `{value}` |")
    return "\n".join(lines) + "\n"


def _draft_readiness(result_pack: Dict[str, Any]) -> Dict[str, Any]:
    source_readiness = _dict(result_pack.get("readiness"))
    claims_allowed = source_readiness.get("paper_claims_allowed") is True
    failed_checks = _as_list(source_readiness.get("failed_checks"))
    status = "draft_ready" if claims_allowed else "outline_only"
    return {
        "status": status,
        "paper_claims_allowed": claims_allowed,
        "source_result_pack_status": source_readiness.get("source_status"),
        "failed_checks": failed_checks,
        "independent_case_count": source_readiness.get("independent_case_count"),
        "raw_result_count": source_readiness.get("raw_result_count"),
        "paired_m3_m2_count": source_readiness.get("paired_m3_m2_count"),
        "interpretation": _readiness_interpretation(claims_allowed, failed_checks),
    }


def _paper_positioning() -> Dict[str, Any]:
    return {
        "method_name": METHOD_NAME,
        "core_problem": "多 Agent 旅游规划中，固定完整链路容易造成不必要的 Agent 与工具调用。",
        "primary_comparison": "M3 Proposed 与 M2 Fixed Multi-Agent 的配对比较。",
        "research_questions": [
            "RQ1：目标—状态调度是否能正确选择 Agent 与工具？",
            "RQ2：动态调度是否保持任务成功率和硬约束满足率？",
            "RQ3：动态调度是否降低调用次数、Token、成本和时延？",
        ],
        "contributions": [
            "提出面向约束旅游规划的目标—状态驱动多 Agent 协同调度方法。",
            "构建四方法公平比较框架，固定模型、数据、工具、输出格式和评价器。",
            "建立 Agent/工具选择、任务成功、硬约束满足和资源开销的可复现实验链路。",
        ],
    }


def _section_plan(readiness: Dict[str, Any]) -> List[Dict[str, Any]]:
    result_status = "可写入正式结果" if readiness.get("paper_claims_allowed") else "只能保留模板"
    return [
        {
            "section_id": "abstract",
            "title": "摘要",
            "status": "需人工润色",
            "evidence": ["Phase0 实验协议", "paper_result_pack"],
        },
        {
            "section_id": "introduction",
            "title": "1 引言",
            "status": "需人工扩写问题背景",
            "evidence": ["研究问题", "贡献点"],
        },
        {
            "section_id": "related_work",
            "title": "2 相关工作",
            "status": "必须人工补真实文献",
            "evidence": ["禁止自动编造引用"],
        },
        {
            "section_id": "method",
            "title": "3 方法",
            "status": "可作为初稿基础",
            "evidence": ["M0-M3 定义", "目标—状态调度", "复用策略"],
        },
        {
            "section_id": "experiment",
            "title": "4 实验设计",
            "status": "可作为初稿基础",
            "evidence": ["CTP-120", "四方法公平性", "RQ 指标"],
        },
        {
            "section_id": "results",
            "title": "5 实验结果与分析",
            "status": result_status,
            "evidence": ["RQ1/RQ2/RQ3 表格", "M3 vs M2 配对统计"],
        },
        {
            "section_id": "conclusion",
            "title": "6 结论",
            "status": "随结果门禁决定强弱",
            "evidence": ["paper_claims_allowed", "写作边界"],
        },
    ]


def _manuscript_sections(
    *,
    title: str,
    readiness: Dict[str, Any],
    result_pack: Dict[str, Any],
) -> List[Dict[str, str]]:
    return [
        {
            "section_id": "abstract",
            "title": "摘要（初稿）",
            "content": _abstract_text(readiness, result_pack),
        },
        {
            "section_id": "keywords",
            "title": "关键词",
            "content": "多智能体；大语言模型；旅游规划；任务调度；工具调用；约束满足",
        },
        {
            "section_id": "introduction",
            "title": "1 引言（初稿）",
            "content": _introduction_text(title),
        },
        {
            "section_id": "related_work",
            "title": "2 相关工作（占位稿）",
            "content": _related_work_text(),
        },
        {
            "section_id": "method",
            "title": "3 目标—状态驱动的多 Agent 协同调度方法（初稿）",
            "content": _method_text(),
        },
        {
            "section_id": "experiment",
            "title": "4 实验设计（初稿）",
            "content": _experiment_text(readiness),
        },
        {
            "section_id": "results",
            "title": "5 实验结果与分析（由结果包生成）",
            "content": _results_text(readiness, result_pack),
        },
        {
            "section_id": "discussion",
            "title": "6 讨论与局限性（初稿）",
            "content": _discussion_text(result_pack),
        },
        {
            "section_id": "conclusion",
            "title": "7 结论（初稿）",
            "content": _conclusion_text(readiness),
        },
        {
            "section_id": "references",
            "title": "参考文献（待人工补充）",
            "content": _reference_todo_text(),
        },
    ]


def _abstract_text(readiness: Dict[str, Any], result_pack: Dict[str, Any]) -> str:
    if readiness.get("paper_claims_allowed") is not True:
        return (
            "【待正式实验通过后定稿】本文面向约束旅游规划场景，研究大语言模型系统中多 Agent "
            "协作、调度与工具调用问题。当前实验产物尚未通过正式论文证据门禁，因此摘要中的实验结果句"
            "只能保留为模板，不能写成正式结论。"
        )
    rq_text = " ".join(
        str(row.get("suggested_statement") or "")
        for row in result_pack.get("research_questions") or []
        if isinstance(row, dict)
    )
    return (
        "针对约束旅游规划任务中固定多 Agent 链路可能带来冗余调用和资源开销的问题，"
        f"本文提出{METHOD_NAME}。该方法将用户目标、已知条件、缺失条件和状态变化统一表示为任务状态，"
        "并基于能力依赖选择最小必要 Agent 与离线工具，在多轮任务中复用未失效结果。"
        f"实验在 {readiness.get('independent_case_count')} 个独立测试案例上比较 M0 Direct LLM、"
        "M1 Single Agent、M2 Fixed Multi-Agent 与 M3 Proposed 四种方法，采用任务成功率、硬约束满足率、"
        f"Agent/工具选择 F1 以及调用开销等指标进行评价。{rq_text}"
    )


def _introduction_text(title: str) -> str:
    return (
        "随着大语言模型在复杂任务求解中的应用增加，多 Agent 系统逐渐被用于将用户请求分解为若干"
        "专业子任务，并结合外部工具获得可验证证据。旅游规划是一类典型的约束密集型任务，用户请求通常"
        "同时包含目的地、日期、预算、人群偏好、天气风险和多轮修改等条件。如果系统始终执行固定完整"
        "Agent 链路，虽然实现简单，但容易在单项查询、澄清请求和局部修改场景中产生不必要的 Agent 调用、"
        "工具调用和 Token 消耗。"
        "\n\n"
        f"围绕上述问题，本文以“{title}”为研究主题，关注多 Agent 系统中的协同调度而非单纯的文本生成质量。"
        "本文的核心假设是：在相同模型、相同离线数据、相同工具和相同评价器条件下，若调度器能够根据用户"
        "目标和状态变化选择最小必要 Agent 集合，并复用未失效结果，则有机会在保持任务正确性的同时降低"
        "系统执行开销。"
        "\n\n"
        "本文贡献包括：第一，提出目标—状态驱动的自适应多 Agent 协同调度方法；第二，构建包含 Direct LLM、"
        "Single Agent、Fixed Multi-Agent 和 Proposed Method 的公平比较框架；第三，建立覆盖 Agent 选择、"
        "工具选择、任务成功、硬约束满足和资源开销的可复现实验流程。"
    )


def _related_work_text() -> str:
    return (
        "本节必须由作者人工补充真实参考文献，不能由程序自动编造引用。建议按三条线组织："
        "\n\n"
        "1. 大语言模型驱动的任务规划与工具调用：说明 LLM 如何进行函数调用、工具选择和结构化输出。"
        "\n"
        "2. 多 Agent 协作与调度：说明固定协作、动态调度、角色分工和通信机制的已有研究。"
        "\n"
        "3. 智慧旅游与约束规划：说明旅游推荐、行程规划、预算约束和天气因素在旅游系统中的建模方式。"
        "\n\n"
        "写作时应优先使用近三年高质量论文，并在每一类相关工作末尾明确本文差异：本文不主张构建完整"
        "实时旅游数据库，而是研究受控离线数据下的多 Agent 调度、工具调用和可复现实验评价。"
    )


def _method_text() -> str:
    return (
        "本文方法由统一目标决策、依赖驱动调度和状态感知复用三部分组成。首先，系统将当前用户输入与"
        "上一轮状态转换为结构化任务单，任务单包含任务类型、已知条件、缺失条件、本轮变化条件、需保留"
        "条件、所需能力和证据需求。其次，调度器根据任务单中的能力依赖，从景点、天气、行程和预算四类"
        "业务 Agent 中选择最小必要子集，并决定是否需要调用 poi_search、weather_query 和 budget_calculator "
        "等固定离线工具。最后，在多轮对话中，系统判断上一轮结果中哪些 Agent 输出仍然有效；未受新条件影响"
        "的结果可以复用，受影响的 Agent 才重新执行。"
        "\n\n"
        "为了保证论文比较公平，本文设置四种方法。M0 Direct LLM 不使用 Agent 和工具，作为无工具能力下限；"
        "M1 Single Agent 使用一个通用 Agent 自主完成任务和工具调用；M2 Fixed Multi-Agent 固定执行完整业务"
        "Agent 链路；M3 Proposed 使用本文的目标—状态驱动调度和局部复用机制。M2 与 M3 使用相同业务 Agent、"
        "相同离线工具和相同评价器，二者核心差异只体现在固定完整执行与动态最小必要执行。"
    )


def _experiment_text(readiness: Dict[str, Any]) -> str:
    case_count = readiness.get("independent_case_count")
    return (
        "本文实验采用受控离线旅游数据，不访问实时地图、天气、酒店或订票 API。测试集案例由人工设计与"
        "标注，覆盖完整旅游规划、信息不足澄清、单项查询、多轮条件修改、天气调整和闲聊/无关问题等任务。"
        f"当前结果包记录的独立案例数为 {case_count}。"
        "\n\n"
        "实验比较 M0、M1、M2 和 M3 四种方法，统一模型配置、温度、最大 Token、重试规则、输出 Schema、"
        "离线工具和独立评价器。主要指标分为三类：调度正确性指标包括 Agent Selection F1 和 Tool Selection F1；"
        "任务正确性指标包括严格任务成功率 STSR 和硬约束满足率 HCSR；效率指标包括 LLM 调用次数、Agent 调用"
        "次数、工具调用次数、Token、估算成本和端到端时延。M3 与 M2 的比较采用配对统计，并报告均值差、"
        "置信区间和相应统计检验。"
    )


def _results_text(readiness: Dict[str, Any], result_pack: Dict[str, Any]) -> str:
    warning = ""
    if readiness.get("paper_claims_allowed") is not True:
        warning = (
            "【重要】当前结果尚未通过正式论文证据门禁，以下内容只能用于检查写作结构，不能作为论文正式"
            "实验结论。\n\n"
        )
    copy_text = _dict(result_pack.get("copy_ready_text"))
    tables = _dict(result_pack.get("tables"))
    parts = [
        warning,
        str(copy_text.get("result_paragraph") or ""),
        "\n\n",
        str(copy_text.get("method_comparison_paragraph") or ""),
        "\n\n### RQ1 调度正确性\n\n",
        _render_table(_dict(tables.get("rq1_scheduler"))),
        "\n\n### RQ2 任务正确性\n\n",
        _render_table(_dict(tables.get("rq2_task_success"))),
        "\n\n### RQ3 执行效率\n\n",
        _render_table(_dict(tables.get("rq3_efficiency"))),
        "\n\n### M3 与 M2 配对统计\n\n",
        _render_table(_dict(tables.get("m3_m2_paired"))),
        "\n\n### 失败规则诊断\n\n",
        _render_table(_dict(tables.get("failure_diagnosis"))),
    ]
    return "".join(parts).strip()


def _discussion_text(result_pack: Dict[str, Any]) -> str:
    copy_text = _dict(result_pack.get("copy_ready_text"))
    limitation = str(copy_text.get("limitation_paragraph") or "")
    return (
        f"{limitation}\n\n"
        "此外，本文实验关注多 Agent 调度与工具调用链路，不评价自然语言表达的主观优美程度，也不将系统自身"
        "Review 分数作为主要证据。若后续希望扩展到真实用户满意度、实时旅游数据或商业部署可用性，需要重新"
        "设计数据来源、用户实验和外部系统稳定性评价。"
    )


def _conclusion_text(readiness: Dict[str, Any]) -> str:
    if readiness.get("paper_claims_allowed") is not True:
        return (
            "当前只能保留结论写作模板：本文提出目标—状态驱动的自适应多 Agent 协同调度方法，并构建公平"
            "实验链路。待正式实验通过证据门禁后，再根据 RQ1/RQ2/RQ3 的实际结果填写是否保持正确性、是否降低"
            "调用开销以及结论边界。"
        )
    return (
        "本文面向约束旅游规划任务，提出目标—状态驱动的自适应多 Agent 协同调度方法。实验结果表明，"
        "在已测任务类型和固定受控离线数据范围内，该方法能够以可审计方式进行 Agent 与工具选择，并可结合"
        "M3 与 M2 的配对统计讨论动态调度对系统开销的影响。本文结论仅限于实验协议定义的任务、数据、指标"
        "和模型配置，不扩展为实时旅游数据准确性或真实用户满意度结论。"
    )


def _reference_todo_text() -> str:
    return (
        "TODO：人工补充真实参考文献。建议至少覆盖："
        "\n\n"
        "- LLM tool use / function calling；"
        "\n"
        "- LLM-based agents / multi-agent collaboration；"
        "\n"
        "- task planning and constraint satisfaction；"
        "\n"
        "- tourism recommendation / itinerary planning；"
        "\n"
        "- evaluation of agent systems。"
        "\n\n"
        "注意：不要把未核验来源写进参考文献。"
    )


def _todo_list(readiness: Dict[str, Any]) -> List[Dict[str, str]]:
    todos = []
    if readiness.get("paper_claims_allowed") is not True:
        failed = ", ".join(_as_list(readiness.get("failed_checks"))) or "unknown"
        todos.append(
            {
                "priority": "P0",
                "item": f"先修复正式证据门禁失败项：{failed}",
            }
        )
    todos.extend(
        [
            {
                "priority": "P0",
                "item": "人工补充真实相关工作和参考文献，严禁自动编造引用。",
            },
            {
                "priority": "P1",
                "item": "根据期刊模板调整标题、摘要、图表编号、作者信息和参考文献格式。",
            },
            {
                "priority": "P1",
                "item": "为方法部分补一张系统流程图或调度流程图。",
            },
            {
                "priority": "P2",
                "item": "人工润色摘要、引言和讨论，降低代码报告痕迹。",
            },
        ]
    )
    return todos


def _source_artifacts(root: Path, result_pack: Dict[str, Any]) -> Dict[str, Any]:
    protocol_hash = _file_sha256(_PHASE0_PROTOCOL_PATH) if _PHASE0_PROTOCOL_PATH.exists() else None
    return {
        "run_dir": root.as_posix(),
        "paper_result_pack_schema_version": PAPER_RESULT_PACK_SCHEMA_VERSION,
        "paper_result_pack_json": (root / PAPER_RESULT_PACK_JSON_NAME).as_posix(),
        "paper_result_pack_json_exists": (root / PAPER_RESULT_PACK_JSON_NAME).exists(),
        "paper_result_pack_readiness": _nested(
            result_pack,
            "readiness",
            "paper_claims_allowed",
        ),
        "formal_experiment_gate": _nested(
            result_pack,
            "source_artifacts",
            "formal_experiment_gate",
        ),
        "phase0_protocol": _PHASE0_PROTOCOL_PATH.as_posix(),
        "phase0_protocol_sha256": protocol_hash,
    }


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
    results = _dict(manifest.get("results"))
    results.update(
        {
            "paper_draft_pack_json": json_path.as_posix(),
            "paper_draft_md": markdown_path.as_posix(),
        }
    )
    manifest["results"] = results
    manifest["paper_draft_pack"] = {
        "schema_version": PAPER_DRAFT_PACK_SCHEMA_VERSION,
        "status": _nested(pack, "readiness", "status"),
        "paper_claims_allowed": _nested(pack, "readiness", "paper_claims_allowed"),
        "failed_checks": _nested(pack, "readiness", "failed_checks") or [],
        "json": json_path.as_posix(),
        "markdown": markdown_path.as_posix(),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _render_table(table: Dict[str, Any]) -> str:
    columns = _as_list(table.get("columns"))
    rows = [row for row in table.get("rows") or [] if isinstance(row, dict)]
    if not columns:
        return "_No table data._"
    lines = [
        "| " + " | ".join(columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_fmt_table(row.get(column)) for column in columns) + " |")
    return "\n".join(lines)


def _readiness_interpretation(claims_allowed: bool, failed_checks: List[str]) -> str:
    if claims_allowed:
        return "The draft can include measured formal result statements within the recorded boundaries."
    if failed_checks:
        return "The draft is an outline only until failed_checks are fixed."
    return "The draft is an outline only and cannot support formal result claims yet."


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


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [value] if value else []
    return [str(value)]


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _fmt_table(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_fmt_table(item) for item in value) + "]"
    if value is None:
        return ""
    if isinstance(value, float):
        return str(round(value, 4))
    return str(value)
