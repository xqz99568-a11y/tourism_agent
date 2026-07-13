from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


def _iter_trace_records(trace_dir: Path) -> Iterable[dict[str, Any]]:
    for path in sorted(trace_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    yield json.loads(line)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return round(ordered[index], 2)


def _latency_summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "p50": None, "p90": None, "p95": None}
    return {
        "mean": round(mean(values), 2),
        "p50": _percentile(values, 0.50),
        "p90": _percentile(values, 0.90),
        "p95": _percentile(values, 0.95),
    }


def _slowest_by_mean(duration_map: dict[str, list[float]]) -> dict[str, float | str] | None:
    candidates = [
        (name, mean(values))
        for name, values in duration_map.items()
        if values
    ]
    if not candidates:
        return None
    name, avg_ms = max(candidates, key=lambda item: item[1])
    return {"name": name, "mean_ms": round(avg_ms, 2)}


def summarize(trace_dir: Path) -> dict[str, Any]:
    records = list(_iter_trace_records(trace_dir))
    status_counts: Counter[str] = Counter()
    stage_durations: defaultdict[str, list[float]] = defaultdict(list)
    agent_counts: Counter[str] = Counter()
    agent_durations: defaultdict[str, list[float]] = defaultdict(list)
    agent_llm_counts: Counter[str] = Counter()
    agent_tool_counts: Counter[str] = Counter()
    agent_api_counts: Counter[str] = Counter()
    total_latencies: list[float] = []
    body_ttfts: list[float] = []
    llm_call_count = 0
    tool_call_count = 0
    api_call_count = 0
    mock_count = 0
    fallback_count = 0
    cache_hit_count = 0

    for record in records:
        status_counts[str(record.get("status") or "unknown")] += 1
        if isinstance(record.get("total_duration_ms"), (int, float)):
            total_latencies.append(float(record["total_duration_ms"]))
        ttft = record.get("first_body_token_ms", record.get("first_token_ms"))
        if isinstance(ttft, (int, float)):
            body_ttfts.append(float(ttft))

        for stage, duration_ms in (record.get("stage_timings") or {}).items():
            if isinstance(duration_ms, (int, float)):
                stage_durations[str(stage)].append(float(duration_ms))

        agent_runs = record.get("agent_runs") or []
        if agent_runs:
            for run in agent_runs:
                agent_name = str(run.get("agent_name") or "unknown")
                agent_counts[agent_name] += 1
                if isinstance(run.get("duration_ms"), (int, float)):
                    agent_durations[agent_name].append(float(run["duration_ms"]))
        else:
            for agent_name, timing in (record.get("agent_timings") or {}).items():
                agent_counts[str(agent_name)] += 1
                if isinstance(timing, dict) and isinstance(timing.get("duration_ms"), (int, float)):
                    agent_durations[str(agent_name)].append(float(timing["duration_ms"]))

        for call in record.get("llm_calls") or []:
            llm_call_count += 1
            owner = call.get("agent_name") or call.get("component") or "unknown"
            agent_llm_counts[str(owner)] += 1
            if call.get("mock_used") or call.get("mock"):
                mock_count += 1
            if call.get("fallback_used") or call.get("fallback"):
                fallback_count += 1
            if call.get("cache_hit"):
                cache_hit_count += 1

        for call in record.get("tool_calls") or []:
            tool_call_count += 1
            owner = call.get("agent_name") or call.get("component") or "unknown"
            agent_tool_counts[str(owner)] += 1
            if call.get("fallback_used"):
                fallback_count += 1
            if call.get("cache_hit"):
                cache_hit_count += 1

        for call in record.get("api_calls") or []:
            api_call_count += 1
            owner = call.get("agent_name") or call.get("component") or "unknown"
            agent_api_counts[str(owner)] += 1
            if call.get("fallback_used"):
                fallback_count += 1
            if call.get("cache_hit"):
                cache_hit_count += 1

    return {
        "trace_count": len(records),
        "unique_request_count": len({record.get("request_id") for record in records if record.get("request_id")}),
        "status_distribution": dict(status_counts),
        "stage_timings": {
            stage: _latency_summary(values)
            for stage, values in sorted(stage_durations.items())
        },
        "agent_calls": {
            agent: {
                "count": count,
                "duration_ms": _latency_summary(agent_durations.get(agent, [])),
            }
            for agent, count in sorted(agent_counts.items())
        },
        "llm_call_count": llm_call_count,
        "tool_call_count": tool_call_count,
        "api_call_count": api_call_count,
        "agent_llm_calls": dict(sorted(agent_llm_counts.items())),
        "agent_tool_calls": dict(sorted(agent_tool_counts.items())),
        "agent_api_calls": dict(sorted(agent_api_counts.items())),
        "mock_count": mock_count,
        "fallback_count": fallback_count,
        "cache_hit_count": cache_hit_count,
        "slowest_stage_by_mean_ms": _slowest_by_mean(dict(stage_durations)),
        "slowest_agent_by_mean_ms": _slowest_by_mean(dict(agent_durations)),
        "total_duration_ms": _latency_summary(total_latencies),
        "first_body_token_ms": _latency_summary(body_ttfts),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize Tourism Agent trace JSONL files.")
    parser.add_argument(
        "trace_dir",
        nargs="?",
        default="experiments/results/traces",
        help="Directory containing one-record JSONL trace files.",
    )
    args = parser.parse_args()
    summary = summarize(Path(args.trace_dir))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
