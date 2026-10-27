"""Seat -> policy assignment from instances/<id>/policies/seats.yaml.

seats.yaml:
  default: {adapter: rule}
  seats:
    accounts_payable: {adapter: llm, model: claude-sonnet-5-5, system_prompt: "..."}
    executive:        {adapter: local, model: my-finetune, base_url: http://localhost:8000/v1/chat/completions}
    buyer:            {adapter: openai, model: gpt-4.1-mini-2025-04-14, cache: data/llm/buyer.jsonl, max_usd: 20}
"""
from __future__ import annotations

from typing import Any

from ..instances import InstanceContext
from .base import Policy
from .llm import LLMPolicy, LocalModelPolicy, OpenAIPolicy
from .rule import RulePolicy


def make_policy(cfg: dict[str, Any]) -> Policy:
    adapter = (cfg or {}).get("adapter", "rule")
    if adapter == "rule":
        return RulePolicy(params=cfg.get("params"))
    if adapter == "llm":
        return LLMPolicy(model=cfg.get("model", "claude-sonnet-5-5"), system_prompt=cfg.get("system_prompt", ""), params=cfg.get("params"))
    if adapter == "local":
        return LocalModelPolicy(model=cfg["model"], base_url=cfg.get("base_url", "http://localhost:8000/v1/chat/completions"), system_prompt=cfg.get("system_prompt", ""))
    if adapter == "openai":
        return OpenAIPolicy(model=cfg["model"], system_prompt=cfg.get("system_prompt", ""), temperature=float(cfg.get("temperature", 0.0)), seed=int(cfg.get("seed", 7)),
                            cache=cfg.get("cache"), max_usd=cfg.get("max_usd"), usd_per_mtok=cfg.get("usd_per_mtok"))
    raise ValueError(f"unknown policy adapter {adapter}")


class PolicyRegistry:
    def __init__(self, default: dict[str, Any] | None = None, seats: dict[str, dict[str, Any]] | None = None) -> None:
        self.default_cfg = default or {"adapter": "rule"}
        self.seat_cfgs = seats or {}
        self._cache: dict[str, Policy] = {}

    def for_seat(self, seat: str) -> Policy:
        if seat not in self._cache:
            self._cache[seat] = make_policy(self.seat_cfgs.get(seat, self.default_cfg))
        return self._cache[seat]

    def describe(self) -> dict[str, Any]:
        return {"default": self.default_cfg, "seats": {s: self.for_seat(s).describe() for s in set(self.seat_cfgs) | set(self._cache)}}


def load_registry(ctx: InstanceContext, overrides: dict[str, Any] | None = None) -> PolicyRegistry:
    cfg = ctx.yaml("policies/seats.yaml")
    for seat_cfg in (cfg.get("seats") or {}).values():          # cache paths are relative to the instance folder
        if seat_cfg and seat_cfg.get("cache") and not str(seat_cfg["cache"]).startswith("/"):
            seat_cfg["cache"] = str(ctx.root / seat_cfg["cache"])
    if overrides:
        cfg = {**cfg, **overrides, "seats": {**cfg.get("seats", {}), **overrides.get("seats", {})}}
    return PolicyRegistry(default=cfg.get("default"), seats=cfg.get("seats"))
