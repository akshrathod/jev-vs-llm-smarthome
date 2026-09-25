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
            "instructions": f"Which single smart-home domain should handle this event: '{event['text']}'?",
            "options": list(TARGET_DOMAINS),
        }
    }


def _domain_questions(domain: TargetDomain, event: Event) -> dict[str, dict[str, object]]:
    text = event["text"]
    if domain == "climate":
        return {
            "target_room": {
                "type": "choice",
                "instructions": f"For the climate command '{text}', which room should be adjusted?",
                "options": list(CLIMATE_ROOMS),
            },
            "target_temperature": {
                "type": "choice",
                "instructions": f"For the climate command '{text}', what target temperature should the thermostat use?",
                "options": list(CLIMATE_TARGET_TEMPERATURES),
            },
        }
    if domain == "lighting":
        return {
            "target_room": {
                "type": "choice",
                "instructions": f"For the lighting command '{text}', which room should be changed?",
                "options": list(LIGHTING_ROOMS),
            },
            "brightness": {
                "type": "choice",
                "instructions": f"For the lighting command '{text}', what brightness percentage should the light use?",
                "options": list(LIGHTING_BRIGHTNESS),
            },
        }
    if domain == "security":
        return {
            "door": {
                "type": "choice",
                "instructions": f"For the security command '{text}', which door should be locked or unlocked?",
                "options": list(SECURITY_DOORS),
            },
            "state": {
                "type": "choice",
                "instructions": f"For the security command '{text}', should the door be locked or unlocked?",
                "options": list(LOCK_STATES),
            },
        }
    if domain == "appliance":
        return {
            "appliance": {
                "type": "choice",
                "instructions": f"For the appliance command '{text}', which appliance should be controlled?",
                "options": list(APPLIANCES),
            },
            "action": {
                "type": "choice",
                "instructions": f"For the appliance command '{text}', should the appliance start or stop?",
                "options": list(APPLIANCE_ACTIONS),
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
        system = (
            "You are a smart-home supervisor. Return strict JSON only. "
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
        context = _domain_context(domain, event)
        system = (
            f"You are the {domain} smart-home domain agent. Return strict JSON only. "
            f"Choose exactly one value for each field from this schema: {schema}. "
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
