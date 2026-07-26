#!/usr/bin/env python3
"""Shared READY/HOLD policy for bot runtime surfaces."""

from __future__ import annotations

import json
from functools import lru_cache

from repo_paths import REPO_ROOT

POLICY_PATH = REPO_ROOT / "config" / "research_policy.json"


@lru_cache(maxsize=1)
def load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


READY_MIN_RANK = int(load_policy()["ready"]["min_rank"])
READY_CONFIDENCE = tuple(
    str(value).lower() for value in load_policy()["ready"]["allowed_confidence"]
)
HOLD_MIN_RANK = int(load_policy()["hold"]["min_rank"])


def is_ready(rank: int, confidence: str) -> bool:
    return rank >= READY_MIN_RANK and confidence.lower() in READY_CONFIDENCE


def is_hold(rank: int, confidence: str) -> bool:
    return rank >= HOLD_MIN_RANK and not is_ready(rank, confidence)


def ready_gate_label() -> str:
    return f"Self-rank >= {READY_MIN_RANK}, {'/'.join(READY_CONFIDENCE)}"


def hold_gate_label() -> str:
    return f"rank {HOLD_MIN_RANK} - verify before surfacing"


def ready_gate_prompt_line() -> str:
    confidence = " or ".join(READY_CONFIDENCE)
    return (
        f"surface to Angela only if Self-rank >= {READY_MIN_RANK} "
        f"and confidence is {confidence}"
    )
