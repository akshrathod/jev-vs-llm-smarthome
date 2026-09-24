from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .config import Settings
from .openrouter import OpenRouterClient, OpenRouterError
from .types import Event


def load_events(path: str) -> list[Event]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["events"]


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_system: dict[str, dict[str, Any]] = {}
    for record in records:
        system = record["system"]
        bucket = by_system.setdefault(
            system,
            {
                "events": 0,
                "decision_cost_usd": 0.0,
                "decision_latency_ms": 0.0,
                "generation_cost_usd": 0.0,
                "generation_latency_ms": 0.0,
                "fallback_cost_usd": 0.0,
                "fallback_latency_ms": 0.0,
                "fallback_checks": 0,
                "fallbacks": 0,
                "fallback_changed_outcome": 0,
            },
        )
        bucket["events"] += 1
        costs = record["latency_cost"]
        for name, prefix in (
            ("decision_layer", "decision"),
            ("generation_layer", "generation"),
            ("fallback_layer", "fallback"),
        ):
            bucket[f"{prefix}_cost_usd"] += costs[name]["cost_usd"]
            bucket[f"{prefix}_latency_ms"] += costs[name]["latency_ms"]
        for agent_run in record["agents"].values():
            for field in agent_run["decision"].values():
                bucket["fallback_checks"] += 1
                if field["used_llm_fallback"]:
                    bucket["fallbacks"] += 1
                    if field["fallback_changed_outcome"]:
                        bucket["fallback_changed_outcome"] += 1
        bucket["fallback_checks"] += 1
        overall = record["overall_home_state"]
        if overall["used_llm_fallback"]:
            bucket["fallbacks"] += 1
            if overall["fallback_changed_outcome"]:
                bucket["fallback_changed_outcome"] += 1
    for bucket in by_system.values():
        checks = bucket["fallback_checks"] or 1
        bucket["fallback_rate"] = bucket["fallbacks"] / checks
    return by_system


def run_benchmark(args: argparse.Namespace) -> None:
    from .decisions import JevDecisionLayer, LLMDecisionLayer
    from .graph import run_event

    client = OpenRouterClient(Settings())
    events = load_events(args.events)
    records: list[dict[str, Any]] = []
    for event in events:
        records.append(run_event(event, "A", LLMDecisionLayer(client), client))
        records.append(run_event(event, "B", JevDecisionLayer(client), client))
    payload = {"records": records, "summary": summarize(records)}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(records)} records to {out}")


def quick_check(_args: argparse.Namespace) -> None:
    from .decisions import JevDecisionLayer, LLMDecisionLayer

    client = OpenRouterClient(Settings())
    event = load_events("docs/smart_home_events.json")[0]
    try:
        llm_decisions, llm_overall, llm_metrics = LLMDecisionLayer(client).decide_agents(event)
        jev_decisions, jev_overall, jev_metrics = JevDecisionLayer(client).decide_agents(event)
    except OpenRouterError as exc:
        print(f"Connectivity check skipped/failed: {exc}")
        return
    print(
        json.dumps(
            {
                "event_id": event["id"],
                "system_a": {
                    "agents": llm_decisions,
                    "overall_home_state": llm_overall,
                    "metrics": llm_metrics,
                },
                "system_b": {
                    "agents": jev_decisions,
                    "overall_home_state": jev_overall,
                    "metrics": jev_metrics,
                },
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(required=True)
    run_parser = subcommands.add_parser("run")
    run_parser.add_argument("--events", default="docs/smart_home_events.json")
    run_parser.add_argument("--out", default="runs/latest.json")
    run_parser.set_defaults(func=run_benchmark)
    check_parser = subcommands.add_parser("check")
    check_parser.set_defaults(func=quick_check)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
