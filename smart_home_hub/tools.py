from __future__ import annotations

from typing import Any


# MOCKED TOOL: synthetic ambient light sensor, not live device data.
def get_ambient_light_sensor(room: str, event: dict[str, Any] | None = None) -> dict[str, Any]:
    lighting_state = (event or {}).get("initial_state", {}).get("lighting", {})
    brightness = int(lighting_state.get(room, 50))
    return {"room": room, "brightness": brightness, "mocked": True}


# MOCKED TOOL: synthetic temperature sensor, not live device data.
def get_room_temperature(room: str, event: dict[str, Any] | None = None) -> dict[str, Any]:
    climate_state = (event or {}).get("initial_state", {}).get("climate", {})
    temperature_f = int(climate_state.get(room, 70))
    return {"room": room, "temperature_f": temperature_f, "mocked": True}


# MOCKED TOOL: synthetic thermostat action, not live device control.
def adjust_thermostat(room: str, target: int) -> dict[str, Any]:
    return {"room": room, "target_f": target, "mocked": True}


# MOCKED TOOL: synthetic light action, not live device control.
def set_light(room: str, state: str, brightness: int = 100) -> dict[str, Any]:
    return {"room": room, "state": state, "brightness": brightness, "mocked": True}


# MOCKED TOOL: synthetic lock action, not live device control.
def set_door_lock(door: str, state: str) -> dict[str, Any]:
    return {"door": door, "state": state, "mocked": True}


# MOCKED TOOL: synthetic appliance action, not live device control.
def control_appliance(appliance: str, action: str) -> dict[str, Any]:
    return {"appliance": appliance, "action": action, "mocked": True}
