from __future__ import annotations

from typing import Any

from .openrouter import OpenRouterClient
from .tools import get_ambient_light_sensor, get_room_temperature
from .types import (
    APPLIANCE_ACTIONS,
    APPLIANCES,
    CLIMATE_TARGET_TEMPERATURES,
    CLIMATE_ROOMS,
    LIGHTING_ROOMS,
    LIGHTING_BRIGHTNESS,
    LOCK_STATES,
    SECURITY_DOORS,
    TARGET_DOMAINS,
    DecisionField,
    DomainDecision,
    Event,
    SupervisorDecision,
    TargetDomain,
)

SUPERVISOR_CONFIDENCE_THRESHOLD = 0.65
DOMAIN_CONFIDENCE_THRESHOLDS = {
    "security": 0.8,
    "climate": 0.65,
    "appliance": 0.65,
    "lighting": 0.5,
}

DOMAIN_CRITERIA = {
    "climate": "Climate owns room temperature sensing and thermostat control for comfort commands about being too hot, too cold, warming up, cooling down, heat waves, chilly rooms, or target temperatures.",
    "lighting": "Lighting owns room light sensing and light control for commands about brightness, darkness, harsh lights, dimming, turning lights on, turning lights off, or setting a light level.",
    "security": "Security owns door lock control for commands about locking, unlocking, securing, opening access, front doors, back doors, or entry safety.",
    "appliance": "Appliance owns controllable kitchen appliances for commands about starting or stopping the fridge, microwave, or stove.",
    "none": "No smart-home domain should act when the event is only a status check, small talk, or does not request a home automation action.",
}

FIELD_CRITERIA = {
    "target_room": {
        "living_room": "The command explicitly mentions the living room or naturally refers to the main shared living area.",
        "bedroom": "The command explicitly mentions the bedroom or naturally refers to sleeping, bedtime, or the bedroom area.",
        "kitchen": "The command explicitly mentions the kitchen or naturally refers to kitchen lights or kitchen activity.",
        "entrance": "The command refers to the entrance, porch, entryway, front area, or doorway lighting.",
    },
    "brightness": {
        "off": "Turn the light fully off at 0% brightness when the user asks to kill, shut off, or turn off lights.",
        "25": "Set a low dim level for requests to dim harsh lights, make a room less bright, or create a subdued mood.",
        "50": "Set a moderate everyday level when the user wants balanced light, not notably dim or bright.",
        "75": "Set a bright level when the user wants more light but not the maximum possible brightness.",
        "100": "Set maximum brightness when the user says it is dark, asks to light something up, or needs full illumination.",
    },
    "target_temperature": {
        "65": "Choose a cool target for strong cooling requests, heat-wave language, or rooms that should become clearly cooler.",
        "68": "Choose a mildly cool target for ordinary cooling requests or when the room is somewhat too warm.",
        "72": "Choose a neutral comfort target when the request implies normal room temperature or only a slight adjustment.",
        "75": "Choose a warm target when the user asks to warm up a cool room.",
        "78": "Choose a very warm target for strong heating requests or rooms described as very cold.",
    },
    "door": {
        "entrance_front_door": "The command refers to the front door, entrance door, porch door, main entry, or general front access.",
        "kitchen_back_door": "The command refers to the back door, kitchen back door, rear entrance, or access through the kitchen.",
    },
    "state": {
        "locked": "Lock or secure the selected door so it cannot be opened freely.",
        "unlocked": "Unlock or open access through the selected door.",
    },
    "appliance": {
        "fridge": "The command refers to the fridge or refrigerator, including alarms or stopping fridge-related behavior.",
        "microwave": "The command refers to the microwave or heating food in the microwave.",
        "stove": "The command refers to the stove, burner, cooktop, or stovetop cooking.",
    },
    "action": {
        "start": "Start, turn on, or begin running the selected appliance.",
        "stop": "Stop, turn off, silence, or end operation of the selected appliance.",
    },
}


def _field(
    value: str,
    confidence: float | None,
    threshold: float | None = None,
    raw: str | None = None,
    fallback: bool = False,
    changed: bool | None = None,
) -> DecisionField:
    return {
        "value": value,
        "confidence": confidence,
        "confidence_threshold": threshold,
        "used_llm_fallback": fallback,
        "fallback_changed_outcome": changed,
        "raw_jev_value": raw,
    }


def empty_metrics() -> dict[str, dict[str, float]]:
    return {
        "decision_layer": {"latency_ms": 0.0, "cost_usd": 0.0, "retried": False},
        "fallback_layer": {"latency_ms": 0.0, "cost_usd": 0.0, "retried": False},
        "tool_layer": {"latency_ms": 0.0, "cost_usd": 0.0, "retried": False},
    }


def _add_metric(metrics: dict[str, dict[str, Any]], bucket: str, latency: float, cost: float, retried: bool = False) -> None:
    metrics[bucket]["latency_ms"] += latency
    metrics[bucket]["cost_usd"] += cost
    metrics[bucket]["retried"] = bool(metrics[bucket].get("retried") or retried)


def _supervisor_question(event: Event) -> dict[str, dict[str, object]]:
    return {
        "target_domain": {
            "type": "choice",
            "instructions": "Which single smart-home domain should handle this event?",
            "options": list(TARGET_DOMAINS),
            "criteria": {option: DOMAIN_CRITERIA[option] for option in TARGET_DOMAINS},
        }
    }


def _domain_questions(domain: TargetDomain, event: Event) -> dict[str, dict[str, object]]:
    text = event["text"]
    if domain == "climate":
        return {
            "target_room": {
                "type": "choice",
                "instructions": "Which room should the climate action adjust?",
                "options": list(CLIMATE_ROOMS),
                "criteria": {option: FIELD_CRITERIA["target_room"][option] for option in CLIMATE_ROOMS},
            },
            "target_temperature": {
                "type": "choice",
                "instructions": "What target temperature should the thermostat use?",
                "options": list(CLIMATE_TARGET_TEMPERATURES),
                "criteria": {option: FIELD_CRITERIA["target_temperature"][option] for option in CLIMATE_TARGET_TEMPERATURES},
            },
        }
    if domain == "lighting":
        return {
            "target_room": {
                "type": "choice",
                "instructions": "Which room should the lighting action change?",
                "options": list(LIGHTING_ROOMS),
                "criteria": {option: FIELD_CRITERIA["target_room"][option] for option in LIGHTING_ROOMS},
            },
            "brightness": {
                "type": "choice",
                "instructions": "What brightness percentage should the light use?",
                "options": list(LIGHTING_BRIGHTNESS),
                "criteria": {option: FIELD_CRITERIA["brightness"][option] for option in LIGHTING_BRIGHTNESS},
            },
        }
    if domain == "security":
        return {
            "door": {
                "type": "choice",
                "instructions": "Which door should be locked or unlocked?",
                "options": list(SECURITY_DOORS),
                "criteria": {option: FIELD_CRITERIA["door"][option] for option in SECURITY_DOORS},
            },
            "state": {
                "type": "choice",
                "instructions": "Should the selected door be locked or unlocked?",
                "options": list(LOCK_STATES),
                "criteria": {option: FIELD_CRITERIA["state"][option] for option in LOCK_STATES},
            },
        }
    if domain == "appliance":
        return {
            "appliance": {
                "type": "choice",
                "instructions": "Which appliance should be controlled?",
                "options": list(APPLIANCES),
                "criteria": {option: FIELD_CRITERIA["appliance"][option] for option in APPLIANCES},
            },
            "action": {
                "type": "choice",
                "instructions": "Should the selected appliance start or stop?",
                "options": list(APPLIANCE_ACTIONS),
                "criteria": {option: FIELD_CRITERIA["action"][option] for option in APPLIANCE_ACTIONS},
            },
        }
    return {}


def _domain_context(domain: TargetDomain, event: Event) -> str:
    if domain == "lighting":
        readings = [
            f"{room}={get_ambient_light_sensor(room, event)['brightness']}%"
            for room in LIGHTING_ROOMS
        ]
        return f"Current brightness readings: {', '.join(readings)}."
    if domain == "climate":
        readings = [
            f"{room}={get_room_temperature(room, event)['temperature_f']}F"
            for room in CLIMATE_ROOMS
        ]
        return f"Current temperature readings: {', '.join(readings)}."
    return ""


class DecisionLayer:
    system_name = "base"

    def decide_supervisor(self, event: Event) -> tuple[SupervisorDecision, dict[str, dict[str, float]]]:
        raise NotImplementedError

    def decide_domain(self, domain: TargetDomain, event: Event) -> tuple[DomainDecision | None, dict[str, dict[str, float]]]:
        raise NotImplementedError


class LLMDecisionLayer(DecisionLayer):
    system_name = "A"

    def __init__(self, client: OpenRouterClient) -> None:
        self.client = client

    def decide_supervisor(self, event: Event) -> tuple[SupervisorDecision, dict[str, dict[str, float]]]:
        metrics = empty_metrics()
        domain_definitions = {option: DOMAIN_CRITERIA[option] for option in TARGET_DOMAINS}
        system = (
            "You are a smart-home supervisor. Return strict JSON only. "
            f"Use these domain definitions: {domain_definitions}. "
            f"Choose target_domain from {list(TARGET_DOMAINS)}. "
            'Return {"target_domain": {"value": one_option, "confidence": number}}.'
        )
        data, latency, cost, retried = self.client.chat_json(system, event["text"])
        _add_metric(metrics, "decision_layer", latency, cost, retried)
        value, confidence = _coerce_choice(data.get("target_domain"), TARGET_DOMAINS, "none")
        return {"target_domain": _field(value, confidence)}, metrics

    def decide_domain(self, domain: TargetDomain, event: Event) -> tuple[DomainDecision | None, dict[str, dict[str, float]]]:
        metrics = empty_metrics()
        questions = _domain_questions(domain, event)
        if not questions:
            return None, metrics
        schema = {key: question["options"] for key, question in questions.items()}
        criteria = {key: question["criteria"] for key, question in questions.items()}
        context = _domain_context(domain, event)
        system = (
            f"You are the {domain} smart-home domain agent. Return strict JSON only. "
            f"Choose exactly one value for each field from this schema: {schema}. "
            f"Use these option definitions: {criteria}. "
            'Return {field: {"value": one_option, "confidence": number}}.'
        )
        user = event["text"] if not context else f"{event['text']}\n{context}"
        data, latency, cost, retried = self.client.chat_json(system, user)
        _add_metric(metrics, "decision_layer", latency, cost, retried)
        return {
            key: _field(*_coerce_choice(data.get(key), tuple(str(option) for option in question["options"]), str(question["options"][0])))
            for key, question in questions.items()
        }, metrics


class JevDecisionLayer(DecisionLayer):
    system_name = "B"

    def __init__(self, client: OpenRouterClient) -> None:
        self.client = client

    def decide_supervisor(self, event: Event) -> tuple[SupervisorDecision, dict[str, dict[str, float]]]:
        metrics = empty_metrics()
        questions = _supervisor_question(event)
        answers, latency, cost, retried, _raw = self.client.jev_choices(f"Smart-home event: {event['text']}", questions)
        _add_metric(metrics, "decision_layer", latency, cost, retried)
        field = self._jev_field("target_domain", answers, SUPERVISOR_CONFIDENCE_THRESHOLD)
        self._apply_fallbacks({"target_domain": field}, questions, SUPERVISOR_CONFIDENCE_THRESHOLD, metrics)
        return {"target_domain": field}, metrics

    def decide_domain(self, domain: TargetDomain, event: Event) -> tuple[DomainDecision | None, dict[str, dict[str, float]]]:
        metrics = empty_metrics()
        questions = _domain_questions(domain, event)
        if not questions:
            return None, metrics
        context = _domain_context(domain, event)
        state = f"Smart-home event: {event['text']}"
        if context:
            state = f"{state}\n{context}"
        answers, latency, cost, retried, _raw = self.client.jev_choices(state, questions)
        _add_metric(metrics, "decision_layer", latency, cost, retried)
        threshold = DOMAIN_CONFIDENCE_THRESHOLDS[domain]
        decision = {key: self._jev_field(key, answers, threshold) for key in questions}
        self._apply_fallbacks(decision, questions, threshold, metrics)
        return decision, metrics

    @staticmethod
    def _jev_field(key: str, answers: dict[str, tuple[str, float]], threshold: float) -> DecisionField:
        value, confidence = answers[key]
        return _field(value, confidence, threshold, value)

    def _apply_fallbacks(
        self,
        fields: dict[str, DecisionField],
        questions: dict[str, dict[str, object]],
        threshold: float,
        metrics: dict[str, dict[str, float]],
    ) -> None:
        fallback_keys = [
            key for key, field in fields.items()
            if field["confidence"] is not None and field["confidence"] < threshold
        ]
        if not fallback_keys:
            return
        prompt_questions = {
            key: {"question": questions[key]["instructions"], "options": questions[key]["options"]}
            for key in fallback_keys
        }
        system = "Resolve low-confidence smart-home choices. Return strict JSON only."
        user = f"Answer each question with exactly one option:\n{prompt_questions}\nReturn {{\"answers\": {{field_name: option}}}}."
        data, latency, cost, retried = self.client.chat_json(system, user)
        _add_metric(metrics, "fallback_layer", latency, cost, retried)
        answers = data.get("answers", data)
        for key in fallback_keys:
            options = tuple(str(option) for option in questions[key]["options"])
            fallback_value = str(answers.get(key))
            if fallback_value not in options:
                fallback_value = fields[key]["value"]
            raw_value = fields[key]["value"]
            fields[key]["value"] = fallback_value
            fields[key]["used_llm_fallback"] = True
            fields[key]["fallback_changed_outcome"] = fallback_value != raw_value


def _coerce_choice(item: Any, options: tuple[str, ...], default: str) -> tuple[str, float]:
    if isinstance(item, dict):
        value = str(item.get("value", default))
        confidence = float(item.get("confidence", 1.0))
    else:
        value = str(item if item is not None else default)
        confidence = 1.0
    if value not in options:
        lowered = value.lower()
        value = next((option for option in options if option in lowered), default)
    return value, confidence
