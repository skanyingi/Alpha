"""Hosted TypeSafe Jev client. Optional; harness falls back locally within the latency budget."""

from __future__ import annotations

from typing import Any

import httpx

from catmod.config import Settings
from catmod.jev.primitives import Question, parse_hosted_answer
from catmod.schemas import ChoiceAnswer, NoulAnswer, ScoreAnswer


class HostedJevClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.jev_api_key)

    def decide(
        self,
        state: Any,
        questions: dict[str, Question],
    ) -> dict[str, ChoiceAnswer | ScoreAnswer | NoulAnswer]:
        if not self.enabled:
            raise RuntimeError("JEV_API_KEY is not configured")
        timeout = max(self.settings.jev_timeout_ms, 50) / 1000.0
        payload = {
            "model": self.settings.jev_model,
            "state": state,
            "questions": questions,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.jev_api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=timeout) as client:
            response = client.post(self.settings.jev_base_url, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        answers = body.get("answers") or {}
        return {key: parse_hosted_answer(value) for key, value in answers.items()}
