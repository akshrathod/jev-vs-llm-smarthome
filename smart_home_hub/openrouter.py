from __future__ import annotations

import json
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import Settings


class OpenRouterError(RuntimeError):
    pass


class OpenRouterClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=1.0,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=frozenset({"POST"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _headers(self) -> dict[str, str]:
        if not self.settings.openrouter_api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is not set.")
        return {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.settings.site_url,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            "X-Title": self.settings.app_name,
        }

    def _post(self, url: str, payload: dict[str, Any]) -> tuple[dict[str, Any], float, bool]:
        started = time.perf_counter()
        try:
            response = self.session.post(url, headers=self._headers(), json=payload, timeout=60)
        except requests.RequestException as exc:
            raise OpenRouterError(f"OpenRouter request failed after retries: {exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        retries = getattr(getattr(response, "raw", None), "retries", None)
        retried = bool(getattr(retries, "history", None))
        if response.status_code >= 400:
            raise OpenRouterError(f"OpenRouter HTTP {response.status_code}: {response.text}")
        try:
            return response.json(), latency_ms, retried
        except json.JSONDecodeError as exc:
            raise OpenRouterError(f"OpenRouter returned invalid JSON: {response.text}") from exc

    @staticmethod
    def estimate_cost(response: dict[str, Any]) -> float:
        usage = response.get("usage") or {}
        if "cost" in usage:
            return float(usage["cost"] or 0)
        if "total_cost" in usage:
            return float(usage["total_cost"] or 0)
        return 0.0

    def chat_json(self, system: str, user: str, model: str | None = None) -> tuple[dict[str, Any], float, float, bool]:
        payload = {
            "model": model or self.settings.chat_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        response, latency_ms, retried = self._post(self.settings.chat_url, payload)
        content = response["choices"][0]["message"]["content"]
        return json.loads(content), latency_ms, self.estimate_cost(response), retried

    def jev_choices(
        self,
        state: str,
        questions: dict[str, dict[str, object]],
    ) -> tuple[dict[str, tuple[str, float]], float, float, bool, dict[str, Any]]:
        payload = {
            "model": self.settings.jev_model,
            "state": state,
            "questions": {
                key: self._format_jev_question(question)
                for key, question in questions.items()
            },
        }
        response, latency_ms, retried = self._post(self.settings.decisions_url, payload)
        answers = self._parse_jev_choices(response, questions.keys())
        return answers, latency_ms, self.estimate_cost(response), retried, response

    @staticmethod
    def _format_jev_question(question: dict[str, object]) -> dict[str, object]:
        return {
            "type": "choice",
            "instructions": str(question["instructions"]),
            "criteria": {option: option for option in question["options"]},
        }

    @staticmethod
    def _parse_jev_choice(response: dict[str, Any]) -> tuple[str, float]:
        candidates = [
            response,
            response.get("answers", {}).get("choice") if isinstance(response.get("answers"), dict) else None,
            response.get("decision") if isinstance(response.get("decision"), dict) else None,
            response.get("output") if isinstance(response.get("output"), dict) else None,
            response.get("result") if isinstance(response.get("result"), dict) else None,
        ]
        for item in candidates:
            if not item:
                continue
            value = item.get("choice")
            if value is None:
                value = item.get("value") or item.get("answer")
            confidence = item.get("confidence")
            if value is not None:
                return str(value), float(confidence if confidence is not None else 1.0)
        raise OpenRouterError(f"Could not parse Jev Choice response: {response}")

    @classmethod
    def _parse_jev_choices(cls, response: dict[str, Any], keys: object) -> dict[str, tuple[str, float]]:
        parsed: dict[str, tuple[str, float]] = {}
        answers = response.get("answers")
        if isinstance(answers, dict):
            for key in keys:
                key_str = str(key)
                item = answers.get(key_str)
                if not isinstance(item, dict):
                    raise OpenRouterError(f"Missing Jev answer for {key_str}: {response}")
                parsed[key_str] = cls._parse_jev_choice(item)
            return parsed
        if len(list(keys)) == 1:
            key = str(next(iter(keys)))
            parsed[key] = cls._parse_jev_choice(response)
            return parsed
        raise OpenRouterError(f"Could not parse Jev Choices response: {response}")
