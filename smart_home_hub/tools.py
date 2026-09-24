from __future__ import annotations

from hashlib import sha256
from typing import Any


def _stable_int(seed: str, low: int, high: int) -> int:
    digest = sha256(seed.encode("utf-8")).hexdigest()
    return low + (int(digest[:8], 16) % (high - low + 1))


# MOCKED TOOL: synthetic ambient light sensor, not live device data.
def get_ambient_light_sensor(room: str) -> dict[str, Any]:
    lux = _stable_int(f"light:{room}", 40, 850)
    return {"room": room, "lux": lux, "mocked": True}


# MOCKED TOOL: synthetic light action, not live device control.
def set_light_level(room: str, level: int) -> dict[str, Any]:
    return {"room": room, "level": max(0, min(100, level)), "mocked": True}


# MOCKED TOOL: synthetic temperature sensor, not live device data.
def get_room_temperature(room: str) -> dict[str, Any]:
    temp_f = _stable_int(f"temp:{room}", 62, 78)
    return {"room": room, "temperature_f": temp_f, "mocked": True}


# MOCKED TOOL: synthetic thermostat action, not live device control.
def set_thermostat(room: str, target: int) -> dict[str, Any]:
    return {"room": room, "target_f": target, "mocked": True}


# MOCKED TOOL: synthetic entry sensor, not live device data.
def get_entry_sensor_status() -> dict[str, Any]:
    return {
        "front_door": "locked",
        "back_door": "closed",
        "garage": "closed",
        "mocked": True,
    }


# MOCKED TOOL: synthetic lock action, not live device control.
def set_lock_state(door: str, state: str) -> dict[str, Any]:
    return {"door": door, "state": state, "mocked": True}


# MOCKED TOOL: synthetic appliance status, not live device data.
def get_appliance_status(appliance: str) -> dict[str, Any]:
    cycle = ["idle", "running", "complete"][_stable_int(f"appliance:{appliance}", 0, 2)]
    return {"appliance": appliance, "status": cycle, "mocked": True}


# MOCKED TOOL: synthetic appliance action, not live device control.
def set_appliance_state(appliance: str, state: str) -> dict[str, Any]:
    return {"appliance": appliance, "state": state, "mocked": True}
