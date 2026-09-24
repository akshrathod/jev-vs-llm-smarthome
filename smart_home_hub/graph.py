from __future__ import annotations

import operator
import time
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph

from .agents import AGENTS, call_selected_tool
from .decisions import DecisionLayer
from .openrouter import OpenRouterClient
from .types import AgentDecision, AgentName, BenchmarkRecord, DecisionField, Event


def _merge_metrics(left: dict[str, dict[str, float]], right: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    merged = {bucket: values.copy() for bucket, values in left.items()}
    for bucket, values in right.items():
        target = merged.setdefault(bucket, {"latency_ms": 0.0, "cost_usd": 0.0})
        target["latency_ms"] = target.get("latency_ms", 0.0) + values.get("latency_ms", 0.0)
        target["cost_usd"] = target.get("cost_usd", 0.0) + values.get("cost_usd", 0.0)
    return merged


class HubState(TypedDict):
    event: Event
    decisions: dict[str, AgentDecision]
    agent_runs: Annotated[dict[str, Any], operator.or_]
    overall_home_state: DecisionField | None
    final_confirmation: str
    metrics: Annotated[dict[str, dict[str, float]], _merge_metrics]


def _empty_metrics() -> dict[str, dict[str, float]]:
    return {
        "decision_layer": {"latency_ms": 0.0, "cost_usd": 0.0},
        "fallback_layer": {"latency_ms": 0.0, "cost_usd": 0.0},
        "generation_layer": {"latency_ms": 0.0, "cost_usd": 0.0},
        "tool_layer": {"latency_ms": 0.0, "cost_usd": 0.0},
    }


def _add_metrics(base: dict[str, dict[str, float]], extra: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    return _merge_metrics(base, extra)


def build_graph(decision_layer: DecisionLayer, client: OpenRouterClient):
    def decide_node(state: HubState) -> dict[str, Any]:
        decisions, overall_home_state, metrics = decision_layer.decide_agents(state["event"])
        return {
            "decisions": decisions,
            "overall_home_state": overall_home_state,
            "metrics": metrics,
        }

    def route_relevant_agents(state: HubState) -> list[str]:
        nodes = [
            f"{agent}_agent"
            for agent, decision in state["decisions"].items()
            if decision["relevant"]["value"] == "relevant"
        ]
        return nodes or ["aggregate_node"]

    def make_agent_node(agent: AgentName):
        def agent_node(state: HubState) -> dict[str, Any]:
            event = state["event"]
            decision = state["decisions"][agent]
            tool_name = decision["tool_to_call"]["value"]
            action_category = decision["action_category"]["value"]
            started = time.perf_counter()
            tool_output = call_selected_tool(agent, tool_name, action_category, event["text"])
            tool_latency = (time.perf_counter() - started) * 1000
            confirmation = None
            metrics = _empty_metrics()
            metrics["tool_layer"]["latency_ms"] += tool_latency
            if decision["needs_written_log"]["value"] == "needs_log":
                confirmation, latency, cost = generate_confirmation(client, agent, event, decision, tool_output)
                metrics["generation_layer"]["latency_ms"] += latency
                metrics["generation_layer"]["cost_usd"] += cost
            return {
                "agent_runs": {
                    agent: {
                        "decision": decision,
                        "tool": {"tool": tool_name, "output": tool_output},
                        "confirmation": confirmation,
                    }
                },
                "metrics": metrics,
            }

        return agent_node

    def aggregate_node(state: HubState) -> dict[str, Any]:
        confirmations = [
            run["confirmation"]
            for run in state["agent_runs"].values()
            if run.get("confirmation")
        ]
        final_confirmation = " ".join(confirmations) if confirmations else "No specialist action was logged."
        return {
            "overall_home_state": state["overall_home_state"],
            "final_confirmation": final_confirmation,
            "metrics": _empty_metrics(),
        }

    graph = StateGraph(HubState)
    graph.add_node("decide_node", decide_node)
    for agent in AGENTS:
        graph.add_node(f"{agent}_agent", make_agent_node(agent))
    graph.add_node("aggregate_node", aggregate_node)
    graph.set_entry_point("decide_node")
    graph.add_conditional_edges("decide_node", route_relevant_agents)
    for agent in AGENTS:
        graph.add_edge(f"{agent}_agent", "aggregate_node")
    graph.add_edge("aggregate_node", END)
    return graph.compile()


def generate_confirmation(
    client: OpenRouterClient,
    agent: str,
    event: Event,
    decision: AgentDecision,
    tool_output: dict[str, Any] | None,
) -> tuple[str, float, float]:
    system = "Write one short smart-home confirmation sentence. No JSON."
    user = (
        f"Command: {event['text']}\n"
        f"Agent: {agent}\n"
        f"Decision: {decision}\n"
        f"Mocked tool output: {tool_output}\n"
        "Write one concise confirmation sentence."
    )
    return client.chat_text(system, user)


def run_event(event: Event, system: str, decision_layer: DecisionLayer, client: OpenRouterClient) -> BenchmarkRecord:
    app = build_graph(decision_layer, client)
    initial: HubState = {
        "event": event,
        "decisions": {},
        "agent_runs": {},
        "overall_home_state": None,
        "final_confirmation": "",
        "metrics": _empty_metrics(),
    }
    result = app.invoke(initial)
    agents: dict[str, Any] = {}
    for agent in AGENTS:
        if agent in result["agent_runs"]:
            agents[agent] = result["agent_runs"][agent]
        else:
            agents[agent] = {
                "decision": result["decisions"][agent],
                "tool": {"tool": "none", "output": None},
                "confirmation": None,
            }
    return {
        "event": event,
        "system": system,  # type: ignore[typeddict-item]
        "agents": agents,
        "overall_home_state": result["overall_home_state"],
        "latency_cost": result["metrics"],
        "final_confirmation": result["final_confirmation"],
    }
