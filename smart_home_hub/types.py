from __future__ import annotations

from typing import Any, Literal, TypedDict

SystemName = Literal["A", "B"]
TargetDomain = Literal["climate", "lighting", "security", "appliance", "none"]

TARGET_DOMAINS = ("climate", "lighting", "security", "appliance", "none")
CLIMATE_ROOMS = ("living_room", "bedroom")
CLIMATE_TARGET_TEMPERATURES = ("65", "68", "72", "75", "78")
LIGHTING_ROOMS = ("living_room", "bedroom", "kitchen", "entrance")
LIGHTING_BRIGHTNESS = ("off", "25", "50", "75", "100")
SECURITY_DOORS = ("entrance_front_door", "kitchen_back_door")
LOCK_STATES = ("locked", "unlocked")
APPLIANCES = ("fridge", "microwave", "stove")
APPLIANCE_ACTIONS = ("start", "stop")


class Event(TypedDict, total=False):
    id: int
    text: str
    expected: dict[str, Any]


class CostLatency(TypedDict):
    latency_ms: float
    cost_usd: float
    retried: bool


class DecisionField(TypedDict):
    value: str
    confidence: float | None
    confidence_threshold: float | None
    used_llm_fallback: bool
    fallback_changed_outcome: bool | None
    raw_jev_value: str | None


class SupervisorDecision(TypedDict):
    target_domain: DecisionField


class DomainDecision(TypedDict, total=False):
    target_room: DecisionField
    action: DecisionField
    state: DecisionField
    brightness: DecisionField
    target_temperature: DecisionField
    door: DecisionField
    appliance: DecisionField


class ToolRecord(TypedDict):
    tool: str
    output: dict[str, Any] | None


class BenchmarkRecord(TypedDict):
    event: Event
    system: SystemName
    supervisor: SupervisorDecision
    domain: TargetDomain
    domain_decision: DomainDecision | None
    tool: ToolRecord
    latency_cost: dict[str, CostLatency]
    final_confirmation: str
