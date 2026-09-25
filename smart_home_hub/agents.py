from __future__ import annotations

from typing import Any

from .tools import adjust_thermostat, control_appliance, set_door_lock, set_light
from .types import TargetDomain


def run_domain_tool(domain: TargetDomain, decision: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str]:
    if domain == "none" or decision is None:
        return None, "No smart-home action was taken."
    if domain == "climate":
        room = decision["target_room"]["value"]
        target = int(decision["target_temperature"]["value"])
        output = adjust_thermostat(room, target)
        return output, f"{room} thermostat set to {target}F."
    if domain == "lighting":
        room = decision["target_room"]["value"]
        brightness_choice = decision["brightness"]["value"]
        brightness = 0 if brightness_choice == "off" else int(brightness_choice)
        state = "off" if brightness_choice == "off" else "on"
        output = set_light(room, state, brightness=brightness)
        return output, f"{room} light set {state} at {brightness}%."
    if domain == "security":
        door = decision["door"]["value"]
        state = decision["state"]["value"]
        output = set_door_lock(door, state)
        return output, f"{door} set to {state}."
    if domain == "appliance":
        appliance = decision["appliance"]["value"]
        action = decision["action"]["value"]
        output = control_appliance(appliance, action)
        return output, f"{appliance} set to {action}."
    raise ValueError(f"Unknown domain: {domain}")
