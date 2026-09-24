from __future__ import annotations

from typing import Any, Callable

from .tools import (
    get_ambient_light_sensor,
    get_appliance_status,
    get_entry_sensor_status,
    get_room_temperature,
    set_appliance_state,
    set_light_level,
    set_lock_state,
    set_thermostat,
)
from .types import AgentName

AGENTS: tuple[AgentName, ...] = ("lighting", "climate", "security", "appliances")

TOOLS: dict[AgentName, dict[str, Callable[..., dict[str, Any]]]] = {
    "lighting": {
        "get_ambient_light_sensor": get_ambient_light_sensor,
        "set_light_level": set_light_level,
    },
    "climate": {
        "get_room_temperature": get_room_temperature,
        "set_thermostat": set_thermostat,
    },
    "security": {
        "get_entry_sensor_status": get_entry_sensor_status,
        "set_lock_state": set_lock_state,
    },
    "appliances": {
        "get_appliance_status": get_appliance_status,
        "set_appliance_state": set_appliance_state,
    },
}


def agent_tool_names(agent: AgentName) -> tuple[str, str]:
    names = tuple(TOOLS[agent].keys())
    return names[0], names[1]


def infer_room(event_text: str) -> str:
    lowered = event_text.lower()
    for room in ("living room", "bedroom", "kitchen", "porch", "hallway", "garage"):
        if room in lowered:
            return room
    return "whole_home"


def infer_door(event_text: str) -> str:
    lowered = event_text.lower()
    for door in ("front door", "back door", "garage"):
        if door in lowered:
            return door.replace(" ", "_")
    return "all_doors"


def infer_appliance(event_text: str) -> str:
    lowered = event_text.lower()
    for appliance in ("dishwasher", "oven", "washing machine", "coffee maker"):
        if appliance in lowered:
            return appliance.replace(" ", "_")
    return "major_appliances"


def call_selected_tool(agent: AgentName, tool_name: str, action_category: str, event_text: str) -> dict[str, Any] | None:
    if tool_name == "none":
        return None
    if agent == "lighting":
        room = infer_room(event_text)
        if tool_name == "get_ambient_light_sensor":
            return get_ambient_light_sensor(room)
        level = 25 if action_category in ("adjust", "turn_off") else 80
        if "off" in event_text.lower():
            level = 0
        return set_light_level(room, level)
    if agent == "climate":
        room = infer_room(event_text)
        if tool_name == "get_room_temperature":
            return get_room_temperature(room)
        target = 68
        lowered = event_text.lower()
        if "warm" in lowered or "cold" in lowered:
            target = 72
        if "cool" in lowered or "heatwave" in lowered:
            target = 66
        return set_thermostat(room, target)
    if agent == "security":
        if tool_name == "get_entry_sensor_status":
            return get_entry_sensor_status()
        state = "unlocked" if "unlock" in event_text.lower() else "locked"
        return set_lock_state(infer_door(event_text), state)
    if agent == "appliances":
        appliance = infer_appliance(event_text)
        if tool_name == "get_appliance_status":
            return get_appliance_status(appliance)
        state = "on" if action_category == "turn_on" else "off"
        return set_appliance_state(appliance, state)
    return None
