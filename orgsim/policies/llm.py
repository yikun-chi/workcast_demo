"""Hosted-LLM policy adapter (Anthropic Messages API via httpx). Used only when a seat is configured for it.

The adapter receives the same Observation as a rule policy, renders it into a prompt, and must return one of
the kernel's valid options. Invalid or failed responses fall back to the rule policy, and the fallback is
recorded in the action params so traces show which decisions were model-made.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
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


class OpenAIPolicy(LLMPolicy):
    """OpenAI Chat Completions seat with a response cache and a spending cap.

    Every response is appended to a JSONL cache keyed by the exact request (model, temperature, seed, messages), so a
    rerun reproduces the same decisions without new calls, and the record outlives the model's retirement. Each cached
    line carries the token usage and its cost at the configured prices; the cap applies to the cache's running total.
    Beyond single choices (decide), the seat can answer with a number for each option (estimate)."""

    name = "openai"

    def __init__(self, model: str, system_prompt: str = "", temperature: float = 0.0, seed: int = 7, cache: str | None = None,
                 max_usd: float | None = None, usd_per_mtok: dict[str, float] | None = None, api_key_env: str = "OPENAI_API_KEY",
                 base_url: str = "https://api.openai.com/v1/chat/completions", max_tokens: int = 1200, timeout: float = 60.0) -> None:
        super().__init__(model=model, system_prompt=system_prompt, api_key_env=api_key_env, base_url=base_url, max_tokens=max_tokens, timeout=timeout)
        self.temperature, self.seed = temperature, seed
        self.cache_path = Path(cache) if cache else None
        self.max_usd = max_usd
        self.rates = usd_per_mtok or {}
        self.cache: dict[str, dict[str, Any]] = {}
        self.hits = 0
        if self.cache_path and self.cache_path.exists():
            for line in self.cache_path.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.cache[rec["key"]] = rec

    def spent_usd(self) -> float:
        return float(sum(r.get("usd", 0.0) for r in self.cache.values()))

    def _chat(self, user: str) -> str:
        messages = [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user}]
        key = hashlib.sha256(json.dumps([self.model, self.temperature, self.seed, messages], sort_keys=True).encode()).hexdigest()
        if key in self.cache:
            self.hits += 1
            return self.cache[key]["text"]
        if not self.api_key:
            raise RuntimeError("no_api_key")
        if self.max_usd is not None and self.spent_usd() >= self.max_usd:
            raise RuntimeError("budget_cap")
        body = {"model": self.model, "messages": messages, "temperature": self.temperature, "seed": self.seed,
                "max_tokens": self.max_tokens, "response_format": {"type": "json_object"}}
        for attempt in range(4):
            r = httpx.post(self.base_url, json=body, timeout=self.timeout, headers={"authorization": f"Bearer {self.api_key}"})
            if r.status_code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 ** attempt * 3)
                continue
            r.raise_for_status()
            break
        self.calls += 1
        out = r.json()
        u = out.get("usage", {})
        usd = (u.get("prompt_tokens", 0) * self.rates.get("input", 0.0) + u.get("completion_tokens", 0) * self.rates.get("output", 0.0)) / 1e6
        rec = {"key": key, "model": out.get("model", self.model), "requested": self.model, "created": out.get("created"), "usage": u, "usd": usd,
               "system_fingerprint": out.get("system_fingerprint"), "messages": messages, "text": out["choices"][0]["message"]["content"]}
        self.cache[key] = rec
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("a") as fh:
                fh.write(json.dumps(rec) + "\n")
        return rec["text"]

    def decide(self, obs: Observation, rng: Any) -> Action:
        if not obs.options:
            return Action(kind="wait")
        try:
            parsed = json.loads(self._chat(self._render(obs)))
            choice = obs.options[int(parsed["choice"])]
            return Action(kind=choice.get("kind", "do_activity"), target=choice.get("target"), params={**choice.get("params", {}), "model": self.model}, rationale=str(parsed.get("reason", ""))[:300])
        except Exception as e:  # noqa: BLE001
            self.failures += 1
            a = self.fallback.decide(obs, rng)
            a.params["fallback"] = f"openai_error:{type(e).__name__}"
            return a

    def estimate(self, obs: Observation) -> dict[str, float] | None:
        """A number for each option target (the question is in the observation); None (the caller falls back) on failure."""
        try:
            parsed = json.loads(self._chat(render_options(obs)))
            vals = parsed.get(obs.context.get("answer_key", "estimate"), parsed)
            targets = {str(o["target"]).lower(): str(o["target"]) for o in obs.options}
            out = {targets[str(k).lower()]: float(v) for k, v in vals.items() if str(k).lower() in targets and v is not None}
            if not out:
                raise ValueError("no estimate for any option")
            return out
        except Exception:  # noqa: BLE001
            self.failures += 1
            return None

    def describe(self) -> dict[str, Any]:
        return {"adapter": "openai", "model": self.model, "temperature": self.temperature, "api_key_present": bool(self.api_key), "calls": self.calls,
                "cache_hits": self.hits, "failures": self.failures, "spent_usd": round(self.spent_usd(), 4), "max_usd": self.max_usd}


def render_options(obs: Observation) -> str:
    """Prompt for a question over several options: the situation in the observation's brief, one line per option with
    its attributes, then the answer format."""
    cols = list(obs.options[0].get("show", {})) if obs.options else []
    rows = [" | ".join(["id", *cols])]
    rows += [" | ".join([str(o["target"]), *[str(o.get("show", {}).get(c, "")) for c in cols]]) for o in obs.options]
    return f"{obs.context.get('brief', '')}\n\n" + "\n".join(rows) + f"\n\nRespond as JSON: {obs.context.get('format', '')}"
