"""Question drafters — turn a clustered topic + signals into a market question.

``TemplateDrafter`` is deterministic and dependency-free (dev/CI/fallback).
``LLMDrafter`` uses a HuggingFace text-generation pipeline on the GPU (lazy).
Both satisfy the ``Drafter`` protocol so the service and generator don't care which
is loaded.
"""
from __future__ import annotations

from typing import List, Protocol


class Drafter(Protocol):
    name: str

    def draft(self, topic: str, signals: List[str], category: str = "") -> str: ...


# Topic -> question template. Mirrors the generator's catalog so the drafted
# question stays resolvable by an available oracle feed.
_TEMPLATES = {
    "us-rates": "Will US CPI print below 2.6% YoY for the next release?",
    "eu-fx": "Will EUR/USD close at or above 1.10 at market settlement?",
    "geopolitics": "Will a ceasefire in the Eastern corridor hold through the settlement date?",
    "eth-staking": "Will the ETH staking ratio exceed 32% before settlement?",
    "volatility": "Will BTC 30d implied volatility exceed 55 at settlement?",
    "hurricane": "Will the Atlantic season record at least 4 Category-5 hurricanes?",
}


class TemplateDrafter:
    name = "template-v1"

    def draft(self, topic: str, signals: List[str], category: str = "") -> str:
        if topic in _TEMPLATES:
            return _TEMPLATES[topic]
        # generic fallback for an unseen topic
        subject = topic.replace("-", " ").strip() or "this event"
        return f"Will {subject} resolve YES by the settlement date?"


class LLMDrafter:
    """Text-generation drafting via HuggingFace Transformers (GPU path)."""

    name = "llm"

    def __init__(self, model_name: str = "Qwen/Qwen2.5-1.5B-Instruct", device: str = "cuda"):
        self.model_name = model_name
        self.device = device
        self._pipe = None

    def _lazy(self):  # pragma: no cover - requires transformers + GPU
        if self._pipe is None:
            from transformers import pipeline

            self._pipe = pipeline("text-generation", model=self.model_name, device_map=self.device)
        return self._pipe

    def draft(self, topic: str, signals: List[str], category: str = "") -> str:  # pragma: no cover
        prompt = (
            "You write crisp, resolvable binary (YES/NO) prediction-market questions.\n"
            f"Topic: {topic}\nCategory: {category}\nSignals:\n- "
            + "\n- ".join(signals[:6])
            + "\nWrite one question that resolves against an objective, dated criterion:\n"
        )
        out = self._lazy()(prompt, max_new_tokens=48, do_sample=False)[0]["generated_text"]
        line = out[len(prompt):].strip().splitlines()[0] if out.startswith(prompt) else out.strip().splitlines()[-1]
        return line.strip().strip('"') or TemplateDrafter().draft(topic, signals, category)
