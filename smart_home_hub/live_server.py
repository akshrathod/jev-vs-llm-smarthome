from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

from .cli import summarize
from .config import Settings
from .decisions import JevDecisionLayer, LLMDecisionLayer
from .graph import run_event
from .openrouter import OpenRouterClient, OpenRouterError
from .types import Event

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = ROOT / "dashboard"


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    client = OpenRouterClient(Settings())

    @app.get("/")
    def index():
        return send_from_directory(DASHBOARD_DIR, "index.html")

    @app.get("/runs/<path:path>")
    def run_files(path: str):
        return send_from_directory(ROOT / "runs", path)

    @app.get("/<path:path>")
    def static_files(path: str):
        return send_from_directory(DASHBOARD_DIR, path)

    @app.post("/api/run-command")
    def run_command():
        payload = request.get_json(silent=True) or {}
        command = str(payload.get("command", "")).strip()
        if not command:
            return jsonify({"error": "command is required"}), 400

        event: Event = {
            "id": 0,
            "text": command,
            "initial_state": _initial_state(payload.get("initial_state")),
        }

        try:
            records = [
                run_event(event, "A", LLMDecisionLayer(client)),
                run_event(event, "B", JevDecisionLayer(client)),
            ]
        except OpenRouterError as exc:
            return jsonify({"error": str(exc)}), 502

        return jsonify({"records": records, "summary": summarize(records)})

    return app


def _initial_state(value: Any) -> dict[str, dict[str, int]]:
    defaults = {
        "lighting": {"living_room": 50, "bedroom": 50, "kitchen": 50, "entrance": 50},
        "climate": {"living_room": 70, "bedroom": 70},
    }
    if not isinstance(value, dict):
        return defaults
    return {
        "lighting": {**defaults["lighting"], **_int_values(value.get("lighting"))},
        "climate": {**defaults["climate"], **_int_values(value.get("climate"))},
    }


def _int_values(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): int(raw)
        for key, raw in value.items()
        if isinstance(raw, int | float | str) and str(raw).strip()
    }


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False)
