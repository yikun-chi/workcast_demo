"""Hosted-LLM policy adapter (Anthropic Messages API via httpx). Used only when a seat is configured for it.

The adapter receives the same Observation as a rule policy, renders it into a prompt, and must return one of
the kernel's valid options. Invalid or failed responses fall back to the rule policy, and the fallback is
recorded in the action params so traces show which decisions were model-made.
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .base import Action, Observation
from .rule import RulePolicy

DEFAULT_MODEL = "claude-sonnet-5-5"
API_URL = "https://api.anthropic.com/v1/messages"


class LLMPolicy:
    name = "llm"

    def __init__(self, model: str = DEFAULT_MODEL, system_prompt: str = "", api_key_env: str = "ANTHROPIC_API_KEY",
                 base_url: str = API_URL, max_tokens: int = 300, timeout: float = 30.0, params: dict[str, Any] | None = None) -> None:
        self.model, self.system_prompt, self.base_url = model, system_prompt, base_url
        self.api_key = os.environ.get(api_key_env, "")
        self.max_tokens, self.timeout = max_tokens, timeout
        self.params = params or {}
        self.fallback = RulePolicy()
        self.calls = 0
        self.failures = 0

    def _render(self, obs: Observation) -> str:
        opts = "\n".join(f"{i}. {json.dumps({k: v for k, v in o.items() if k != 'weight'}, default=str)}" for i, o in enumerate(obs.options))
        return (
            f"You are {obs.agent_id}, working as {obs.role}. Simulated time: {obs.sim_time}.\n"
            f"Situation:\n{json.dumps(obs.context, default=str, indent=1)}\n\n"
            f"Choose exactly one option by number and give a one-sentence reason.\n{opts}\n\n"
            'Respond as JSON: {"choice": <number>, "reason": "<one sentence>"}'
        )

    def decide(self, obs: Observation, rng: Any) -> Action:
        if not obs.options:
            return Action(kind="wait")
        if not self.api_key:
            a = self.fallback.decide(obs, rng)
            a.params["fallback"] = "no_api_key"
            return a
        self.calls += 1
        try:
            body = {"model": self.model, "max_tokens": self.max_tokens, "system": self.system_prompt or "You roleplay an employee inside an organization simulation. Be realistic and concise.",
                    "messages": [{"role": "user", "content": self._render(obs)}]}
            r = httpx.post(self.base_url, json=body, timeout=self.timeout,
                           headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
            r.raise_for_status()
            text = "".join(c.get("text", "") for c in r.json().get("content", []))
            start, end = text.find("{"), text.rfind("}")
            parsed = json.loads(text[start:end + 1])
            idx = int(parsed["choice"])
            choice = obs.options[idx]
            return Action(kind=choice.get("kind", "do_activity"), target=choice.get("target"), params={**choice.get("params", {}), "model": self.model}, rationale=str(parsed.get("reason", ""))[:300])
        except Exception as e:  # noqa: BLE001 - any failure falls back, recorded
            self.failures += 1
            a = self.fallback.decide(obs, rng)
            a.params["fallback"] = f"llm_error:{type(e).__name__}"
            return a

    def describe(self) -> dict[str, Any]:
        return {"adapter": "llm", "model": self.model, "api_key_present": bool(self.api_key), "calls": self.calls, "failures": self.failures}


class LocalModelPolicy(LLMPolicy):
    """Same contract against an OpenAI-compatible local server (e.g. a fine-tuned model behind vLLM/Ollama)."""

    name = "local"

    def __init__(self, model: str, base_url: str = "http://localhost:8000/v1/chat/completions", **kw: Any) -> None:
        super().__init__(model=model, base_url=base_url, api_key_env="LOCAL_MODEL_API_KEY", **kw)
        self.api_key = self.api_key or "local"

    def decide(self, obs: Observation, rng: Any) -> Action:
        if not obs.options:
            return Action(kind="wait")
        self.calls += 1
        try:
            body = {"model": self.model, "max_tokens": self.max_tokens,
                    "messages": [{"role": "system", "content": self.system_prompt or "You roleplay an employee inside an organization simulation."},
                                 {"role": "user", "content": self._render(obs)}]}
            r = httpx.post(self.base_url, json=body, timeout=self.timeout, headers={"authorization": f"Bearer {self.api_key}"})
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            parsed = json.loads(text[text.find("{"):text.rfind("}") + 1])
            choice = obs.options[int(parsed["choice"])]
            return Action(kind=choice.get("kind", "do_activity"), target=choice.get("target"), params={**choice.get("params", {}), "model": self.model}, rationale=str(parsed.get("reason", ""))[:300])
        except Exception as e:  # noqa: BLE001
            self.failures += 1
            a = self.fallback.decide(obs, rng)
            a.params["fallback"] = f"local_error:{type(e).__name__}"
            return a
