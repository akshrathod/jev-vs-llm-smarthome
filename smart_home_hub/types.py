from __future__ import annotations

from typing import Any, Literal, TypedDict

AgentName = Literal["lighting", "climate", "security", "appliances"]
SystemName = Literal["A", "B"]

RELEVANCE = ("relevant", "not_relevant")
ACTION_CATEGORIES = ("adjust", "turn_on", "turn_off", "no_action")
LOG_CHOICES = ("needs_log", "no_log")
HOME_STATES = ("normal", "away_mode", "night_mode", "alert")


class Event(TypedDict, total=False):
    id: int
    text: str
    expected_agents: list[str]


class CostLatency(TypedDict):
    latency_ms: float
    cost_usd: float


class DecisionField(TypedDict):
    value: str
    confidence: float | None
    used_llm_fallback: bool
    fallback_changed_outcome: bool | None
    raw_jev_value: str | None


class AgentDecision(TypedDict):
    relevant: DecisionField
    tool_to_call: DecisionField
    action_category: DecisionField
    needs_written_log: DecisionField


class ToolRecord(TypedDict):
    tool: str
    output: dict[str, Any] | None


class AgentRun(TypedDict):
    decision: AgentDecision
    tool: ToolRecord
    confirmation: str | None


class BenchmarkRecord(TypedDict):
    event: Event
    system: SystemName
    agents: dict[str, AgentRun]
    overall_home_state: DecisionField
    latency_cost: dict[str, CostLatency]
    final_confirmation: str

