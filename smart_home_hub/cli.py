from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

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
                "fallback_cost_usd": 0.0,
                "fallback_latency_ms": 0.0,
                "tool_latency_ms": 0.0,
                "fallback_checks": 0,
                "fallbacks": 0,
                "fallback_changed_outcome": 0,
            },
        )
        bucket["events"] += 1
        costs = record["latency_cost"]
        bucket["decision_cost_usd"] += costs["decision_layer"]["cost_usd"]
        bucket["decision_latency_ms"] += costs["decision_layer"]["latency_ms"]
        bucket["fallback_cost_usd"] += costs["fallback_layer"]["cost_usd"]
        bucket["fallback_latency_ms"] += costs["fallback_layer"]["latency_ms"]
        bucket["tool_latency_ms"] += costs["tool_layer"]["latency_ms"]
        fields = [record["supervisor"]["target_domain"]]
        fields.extend((record.get("domain_decision") or {}).values())
        for field in fields:
            bucket["fallback_checks"] += 1
            if field["used_llm_fallback"]:
                bucket["fallbacks"] += 1
                if field["fallback_changed_outcome"]:
                    bucket["fallback_changed_outcome"] += 1
    for bucket in by_system.values():
        checks = bucket["fallback_checks"] or 1
        bucket["fallback_rate"] = bucket["fallbacks"] / checks
    by_system["evaluation"] = evaluate_records(records)
    return by_system


def evaluate_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    scores: dict[str, dict[str, int]] = {
        "A": {
            "categorical_correct": 0,
            "categorical_total": 0,
            "magnitude_correct": 0,
            "magnitude_total": 0,
        },
        "B": {
            "categorical_correct": 0,
            "categorical_total": 0,
            "magnitude_correct": 0,
            "magnitude_total": 0,
        },
    }
    by_event: dict[int, dict[str, dict[str, Any]]] = {}
    for record in records:
        system = record["system"]
        by_event.setdefault(record["event"]["id"], {})[system] = record
        expected = record["event"].get("expected", {})
        scores[system]["categorical_total"] += 1
        if record["domain"] == expected.get("target_domain"):
            scores[system]["categorical_correct"] += 1
            expected_decision = expected.get("domain_decision") or {}
            actual_decision = record.get("domain_decision") or {}
            for key, expected_value in expected_decision.items():
                actual = actual_decision.get(key, {}).get("value")
                if key in ("brightness", "target_temperature"):
                    scores[system]["magnitude_total"] += 1
                    if _magnitude_directionally_correct(record, key, actual, expected_value):
                        scores[system]["magnitude_correct"] += 1
                else:
                    scores[system]["categorical_total"] += 1
                    if actual == expected_value:
                        scores[system]["categorical_correct"] += 1
    agreement = {"domain": {"same": 0, "total": 0}, "domain_fields": {"same": 0, "total": 0}}
    for pair in by_event.values():
        if "A" not in pair or "B" not in pair:
            continue
        agreement["domain"]["total"] += 1
        if pair["A"]["domain"] == pair["B"]["domain"]:
            agreement["domain"]["same"] += 1
        a_decision = pair["A"].get("domain_decision") or {}
        b_decision = pair["B"].get("domain_decision") or {}
        for key in sorted(set(a_decision) | set(b_decision)):
            agreement["domain_fields"]["total"] += 1
            if a_decision.get(key, {}).get("value") == b_decision.get(key, {}).get("value"):
                agreement["domain_fields"]["same"] += 1
    return {
        "accuracy": {
            system: {
                "categorical": _ratio(
                    values["categorical_correct"], values["categorical_total"]
                ),
                "categorical_correct": values["categorical_correct"],
                "categorical_total": values["categorical_total"],
                "magnitude_directional": _ratio(
                    values["magnitude_correct"], values["magnitude_total"]
                ),
                "magnitude_correct": values["magnitude_correct"],
                "magnitude_total": values["magnitude_total"],
            }
            for system, values in scores.items()
        },
        "inter_system_agreement": {
            key: _ratio(value["same"], value["total"])
            for key, value in agreement.items()
        },
    }


def _ratio(count: int, total: int) -> float:
    return count / total if total else 0.0


def _magnitude_directionally_correct(
    record: dict[str, Any], field: str, actual: str | None, expected: str
) -> bool:
    if actual is None:
        return False

    if field == "brightness":
        room = (record.get("domain_decision") or {}).get("target_room", {}).get("value")
        current = record["event"].get("initial_state", {}).get("lighting", {}).get(room, 50)
        options = ["off", "25", "50", "75", "100"]
        values = {"off": 0, "25": 25, "50": 50, "75": 75, "100": 100}
    else:
        room = (record.get("domain_decision") or {}).get("target_room", {}).get("value")
        current = record["event"].get("initial_state", {}).get("climate", {}).get(room, 70)
        options = ["65", "68", "72", "75", "78"]
        values = {option: int(option) for option in options}

    if actual not in values or expected not in values:
        return False

    current_index = min(
        range(len(options)), key=lambda index: abs(values[options[index]] - current)
    )
    actual_index = options.index(actual)
    expected_value = values[expected]
    actual_value = values[actual]
    if expected_value == current:
        return actual_value == current

    direction = 1 if expected_value > current else -1
    if direction > 0 and actual_value <= current:
        return False
    if direction < 0 and actual_value >= current:
        return False

    if direction > 0:
        return actual_index >= current_index + 2 or actual_index >= len(options) - 2
    return actual_index <= current_index - 2 or actual_index <= 1


def run_benchmark(args: argparse.Namespace) -> None:
    from .config import Settings
    from .decisions import JevDecisionLayer, LLMDecisionLayer
    from .graph import run_event
    from .openrouter import OpenRouterClient

    client = OpenRouterClient(Settings())
    records: list[dict[str, Any]] = []
    for event in load_events(args.events):
        if args.system in ("A", "both"):
            records.append(run_event(event, "A", LLMDecisionLayer(client)))
        if args.system in ("B", "both"):
            records.append(run_event(event, "B", JevDecisionLayer(client)))
    payload = {"records": records, "summary": summarize(records)}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(records)} records to {out}")


def combine_runs(args: argparse.Namespace) -> None:
    records: list[dict[str, Any]] = []
    for input_path in args.inputs:
        payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
        records.extend(payload.get("records", []))
    records.sort(key=lambda record: (record["event"]["id"], record["system"]))
    payload = {"records": records, "summary": summarize(records)}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(records)} combined records to {out}")


def quick_check(_args: argparse.Namespace) -> None:
    from .config import Settings
    from .decisions import JevDecisionLayer, LLMDecisionLayer
    from .openrouter import OpenRouterClient, OpenRouterError

    client = OpenRouterClient(Settings())
    event = load_events("docs/smart_home_events_test.json")[0]
    try:
        llm_supervisor, llm_metrics = LLMDecisionLayer(client).decide_supervisor(event)
        jev_supervisor, jev_metrics = JevDecisionLayer(client).decide_supervisor(event)
    except OpenRouterError as exc:
        print(f"Connectivity check skipped/failed: {exc}")
        return
    print(json.dumps({"system_a": llm_supervisor, "system_b": jev_supervisor, "metrics": {"A": llm_metrics, "B": jev_metrics}}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(required=True)
    run_parser = subcommands.add_parser("run")
    run_parser.add_argument("--events", default="docs/smart_home_events.json")
    run_parser.add_argument("--out", default="runs/latest.json")
    run_parser.add_argument("--system", choices=("A", "B", "both"), default="both")
    run_parser.set_defaults(func=run_benchmark)
    combine_parser = subcommands.add_parser("combine")
    combine_parser.add_argument("--inputs", nargs="+", required=True)
    combine_parser.add_argument("--out", required=True)
    combine_parser.set_defaults(func=combine_runs)
    check_parser = subcommands.add_parser("check")
    check_parser.set_defaults(func=quick_check)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
