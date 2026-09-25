from __future__ import annotations

import time
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph

from .agents import run_domain_tool
from .decisions import DecisionLayer, empty_metrics
from .types import BenchmarkRecord, DomainDecision, Event, SupervisorDecision, TargetDomain


def _merge_metrics(left: dict[str, dict[str, float]], right: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    merged = {bucket: values.copy() for bucket, values in left.items()}
    for bucket, values in right.items():
        target = merged.setdefault(bucket, {"latency_ms": 0.0, "cost_usd": 0.0})
        target["latency_ms"] = target.get("latency_ms", 0.0) + values.get("latency_ms", 0.0)
        target["cost_usd"] = target.get("cost_usd", 0.0) + values.get("cost_usd", 0.0)
        target["retried"] = bool(target.get("retried") or values.get("retried"))
    return merged


class HubState(TypedDict):
    event: Event
    supervisor: SupervisorDecision | None
    domain: TargetDomain
    domain_decision: DomainDecision | None
    tool: dict[str, Any]
    final_confirmation: str
    metrics: Annotated[dict[str, dict[str, float]], _merge_metrics]


def build_graph(decision_layer: DecisionLayer):
    def supervisor_node(state: HubState) -> dict[str, Any]:
        supervisor, metrics = decision_layer.decide_supervisor(state["event"])
        return {
            "supervisor": supervisor,
            "domain": supervisor["target_domain"]["value"],
            "metrics": metrics,
        }

    def route_domain(state: HubState) -> str:
        domain = state["domain"]
        if domain == "none":
            return "aggregate_node"
        return f"{domain}_agent"

    def make_domain_node(domain: TargetDomain):
        def domain_node(state: HubState) -> dict[str, Any]:
            decision, decision_metrics = decision_layer.decide_domain(domain, state["event"])
            started = time.perf_counter()
            output, confirmation = run_domain_tool(domain, decision)
            tool_latency = (time.perf_counter() - started) * 1000
            metrics = _merge_metrics(empty_metrics(), decision_metrics)
            metrics["tool_layer"]["latency_ms"] += tool_latency
            return {
                "domain_decision": decision,
                "tool": {"tool": _tool_name(domain), "output": output},
                "final_confirmation": confirmation,
                "metrics": metrics,
            }

        return domain_node

    def aggregate_node(state: HubState) -> dict[str, Any]:
        return {
            "final_confirmation": state["final_confirmation"] or "No smart-home action was taken.",
            "metrics": empty_metrics(),
        }

    graph = StateGraph(HubState)
    graph.add_node("supervisor_node", supervisor_node)
    for domain in ("climate", "lighting", "security", "appliance"):
        graph.add_node(f"{domain}_agent", make_domain_node(domain))  # type: ignore[arg-type]
    graph.add_node("aggregate_node", aggregate_node)
    graph.set_entry_point("supervisor_node")
    graph.add_conditional_edges("supervisor_node", route_domain)
    for domain in ("climate", "lighting", "security", "appliance"):
        graph.add_edge(f"{domain}_agent", "aggregate_node")
    graph.add_edge("aggregate_node", END)
    return graph.compile()


def _tool_name(domain: TargetDomain) -> str:
    return {
        "climate": "adjust_thermostat",
        "lighting": "set_light",
        "security": "set_door_lock",
        "appliance": "control_appliance",
        "none": "none",
    }[domain]


def run_event(event: Event, system: str, decision_layer: DecisionLayer) -> BenchmarkRecord:
    app = build_graph(decision_layer)
    initial: HubState = {
        "event": event,
        "supervisor": None,
        "domain": "none",
        "domain_decision": None,
        "tool": {"tool": "none", "output": None},
        "final_confirmation": "",
        "metrics": empty_metrics(),
    }
    result = app.invoke(initial)
    return {
        "event": event,
        "system": system,  # type: ignore[typeddict-item]
        "supervisor": result["supervisor"],
        "domain": result["domain"],
        "domain_decision": result["domain_decision"],
        "tool": result["tool"],
        "latency_cost": result["metrics"],
        "final_confirmation": result["final_confirmation"],
    }
