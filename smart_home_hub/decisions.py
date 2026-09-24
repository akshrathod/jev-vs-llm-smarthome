from __future__ import annotations

from typing import Any

from .agents import AGENTS, agent_tool_names
from .openrouter import OpenRouterClient
from .types import ACTION_CATEGORIES, HOME_STATES, LOG_CHOICES, RELEVANCE, AgentDecision, DecisionField, Event

FALLBACK_CONFIDENCE_THRESHOLD = 0.6


def _field(value: str, confidence: float | None, fallback: bool = False, changed: bool | None = None, raw: str | None = None) -> DecisionField:
    return {
        "value": value,
        "confidence": confidence,
        "used_llm_fallback": fallback,
        "fallback_changed_outcome": changed,
        "raw_jev_value": raw,
    }


def _empty_metrics() -> dict[str, dict[str, float]]:
    return {
        "decision_layer": {"latency_ms": 0.0, "cost_usd": 0.0},
        "fallback_layer": {"latency_ms": 0.0, "cost_usd": 0.0},
        "generation_layer": {"latency_ms": 0.0, "cost_usd": 0.0},
        "tool_layer": {"latency_ms": 0.0, "cost_usd": 0.0},
    }


class DecisionLayer:
    system_name = "base"

    def decide_agents(self, event: Event) -> tuple[dict[str, AgentDecision], DecisionField, dict[str, dict[str, float]]]:
        raise NotImplementedError


class LLMDecisionLayer(DecisionLayer):
    system_name = "A"

    def __init__(self, client: OpenRouterClient) -> None:
        self.client = client

    def decide_agents(self, event: Event) -> tuple[dict[str, AgentDecision], DecisionField, dict[str, dict[str, float]]]:
        metrics = _empty_metrics()
        schema_hint = {
            agent: {
                "relevant": list(RELEVANCE),
                "tool_to_call": [*agent_tool_names(agent), "none"],
                "action_category": list(ACTION_CATEGORIES),
                "needs_written_log": list(LOG_CHOICES),
            }
            for agent in AGENTS
        }
        system = "You make structured smart-home routing decisions. Return strict JSON only."
        user = (
            f"Event: {event['text']}\n"
            f"For every agent, choose exactly one value for each field from this schema:\n{schema_hint}\n"
            f"Also choose overall_home_state from {list(HOME_STATES)} based on the event text. "
            "Return JSON shaped as {\"agents\": {agent: {field: {\"value\": option, \"confidence\": number}}}, "
            "\"overall_home_state\": {\"value\": option, \"confidence\": number}}."
        )
        data, latency, cost = self.client.chat_json(system, user)
        metrics["decision_layer"]["latency_ms"] += latency
        metrics["decision_layer"]["cost_usd"] += cost
        return self._normalize_agent_decisions(data), self._normalize_overall_state(data), metrics

    @staticmethod
    def _normalize_agent_decisions(data: dict[str, Any]) -> dict[str, AgentDecision]:
        source = data.get("agents", data)
        normalized: dict[str, AgentDecision] = {}
        for agent in AGENTS:
            agent_data = source[agent]
            normalized[agent] = {
                "relevant": _field(agent_data["relevant"]["value"], float(agent_data["relevant"].get("confidence", 1.0))),
                "tool_to_call": _field(agent_data["tool_to_call"]["value"], float(agent_data["tool_to_call"].get("confidence", 1.0))),
                "action_category": _field(agent_data["action_category"]["value"], float(agent_data["action_category"].get("confidence", 1.0))),
                "needs_written_log": _field(agent_data["needs_written_log"]["value"], float(agent_data["needs_written_log"].get("confidence", 1.0))),
            }
        return normalized

    @staticmethod
    def _normalize_overall_state(data: dict[str, Any]) -> DecisionField:
        item = data["overall_home_state"]
        return _field(str(item["value"]), float(item.get("confidence", 1.0)))


class JevDecisionLayer(DecisionLayer):
    system_name = "B"

    def __init__(self, client: OpenRouterClient) -> None:
        self.client = client

    def decide_agents(self, event: Event) -> tuple[dict[str, AgentDecision], DecisionField, dict[str, dict[str, float]]]:
        metrics = _empty_metrics()
        questions = self._agent_questions(event)
        answers, latency, cost, _raw = self.client.jev_choices(f"Smart-home command: {event['text']}", questions)
        metrics["decision_layer"]["latency_ms"] += latency
        metrics["decision_layer"]["cost_usd"] += cost
        decisions: dict[str, AgentDecision] = {}
        for agent in AGENTS:
            decisions[agent] = {
                "relevant": self._answer_field(f"{agent}_relevant", answers, questions, metrics),
                "tool_to_call": self._answer_field(f"{agent}_tool_to_call", answers, questions, metrics),
                "action_category": self._answer_field(f"{agent}_action_category", answers, questions, metrics),
                "needs_written_log": self._answer_field(f"{agent}_needs_written_log", answers, questions, metrics),
            }
        overall = self._answer_field("overall_home_state", answers, questions, metrics)
        return decisions, overall, metrics

    def _answer_field(
        self,
        key: str,
        answers: dict[str, tuple[str, float]],
        questions: dict[str, dict[str, object]],
        metrics: dict[str, dict[str, float]],
    ) -> DecisionField:
        value, confidence = answers[key]
        if confidence >= FALLBACK_CONFIDENCE_THRESHOLD:
            return _field(value, confidence, False, None, value)
        question = str(questions[key]["instructions"])
        options = list(questions[key]["options"])
        fallback_value, fallback_latency, fallback_cost = self._fallback_choice(question, options)
        metrics["fallback_layer"]["latency_ms"] += fallback_latency
        metrics["fallback_layer"]["cost_usd"] += fallback_cost
        return _field(
            fallback_value,
            confidence,
            True,
            fallback_value != value,
            value,
        )

    @staticmethod
    def _agent_questions(event: Event) -> dict[str, dict[str, object]]:
        questions: dict[str, dict[str, object]] = {}
        for agent in AGENTS:
            read_tool, action_tool = agent_tool_names(agent)
            questions[f"{agent}_relevant"] = {
                "instructions": f"Is the {agent} agent relevant to this smart-home command: '{event['text']}'?",
                "options": list(RELEVANCE),
            }
            questions[f"{agent}_tool_to_call"] = {
                "instructions": f"For the {agent} agent handling command '{event['text']}', which tool should be called?",
                "options": [read_tool, action_tool, "none"],
            }
            questions[f"{agent}_action_category"] = {
                "instructions": f"For the {agent} agent handling command '{event['text']}', what action category applies?",
                "options": list(ACTION_CATEGORIES),
            }
            questions[f"{agent}_needs_written_log"] = {
                "instructions": f"Should the {agent} agent write a short confirmation log for command '{event['text']}'?",
                "options": list(LOG_CHOICES),
            }
        questions["overall_home_state"] = {
            "instructions": f"Given smart-home command '{event['text']}', choose the overall home state.",
            "options": list(HOME_STATES),
        }
        return questions

    def _fallback_choice(self, question: str, options: list[str]) -> tuple[str, float, float]:
        system = "Answer a single structured decision as JSON only."
        user = f"{question}\nOptions: {options}\nReturn {{\"value\": one_option}}."
        data, latency, cost = self.client.chat_json(system, user)
        value = str(data.get("value"))
        if value not in options:
            raise ValueError(f"Fallback returned invalid option {value!r}; expected one of {options}")
        return value, latency, cost
