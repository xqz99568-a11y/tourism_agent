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


def summarize(trace_dir: Path) -> dict[str, Any]:
    records = list(_iter_trace_records(trace_dir))
    status_counts: Counter[str] = Counter()
    agent_counts: Counter[str] = Counter()
    agent_durations: defaultdict[str, list[float]] = defaultdict(list)
    agent_llm_counts: Counter[str] = Counter()
    total_latencies: list[float] = []
    body_ttfts: list[float] = []
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
            owner = call.get("agent_name") or call.get("component") or "unknown"
            agent_llm_counts[str(owner)] += 1
            if call.get("mock_used") or call.get("mock"):
                mock_count += 1
            if call.get("fallback_used") or call.get("fallback"):
                fallback_count += 1
            if call.get("cache_hit"):
                cache_hit_count += 1

        for call_group in ("tool_calls", "api_calls"):
            for call in record.get(call_group) or []:
                if call.get("fallback_used"):
                    fallback_count += 1
                if call.get("cache_hit"):
                    cache_hit_count += 1

    return {
        "trace_count": len(records),
        "unique_request_count": len({record.get("request_id") for record in records if record.get("request_id")}),
        "status_distribution": dict(status_counts),
        "agent_calls": {
            agent: {
                "count": count,
                "duration_ms": _latency_summary(agent_durations.get(agent, [])),
            }
            for agent, count in sorted(agent_counts.items())
        },
        "agent_llm_calls": dict(sorted(agent_llm_counts.items())),
        "mock_count": mock_count,
        "fallback_count": fallback_count,
        "cache_hit_count": cache_hit_count,
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
