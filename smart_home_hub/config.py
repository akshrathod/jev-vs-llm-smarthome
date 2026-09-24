from __future__ import annotations

import os

from dotenv import load_dotenv


class Settings:
    def __init__(self) -> None:
        load_dotenv()
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.chat_model = os.getenv("OPENROUTER_CHAT_MODEL", "openai/gpt-4o-mini")
        self.jev_model = os.getenv("OPENROUTER_JEV_MODEL", "typesafe/jev-1.13")
        self.chat_url = "https://openrouter.ai/api/v1/chat/completions"
        self.decisions_url = "https://openrouter.ai/api/alpha/decisions"
        self.site_url = os.getenv("OPENROUTER_SITE_URL", "http://localhost")
        self.app_name = os.getenv("OPENROUTER_APP_NAME", "Smart Home Hub Benchmark")
