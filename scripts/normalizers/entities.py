#!/usr/bin/env python3
"""Entity, inventor, model, and part normalization."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from repo_paths import REPO_ROOT

ALIASES_PATH = REPO_ROOT / "config" / "entity_aliases.json"


@dataclass(slots=True)
class EntityNormalizationResult:
    raw_input: str
    canonical: str
    matched_alias: str
    aliases: list[str]
    predecessors: list[str]
    subsidiaries: list[str]


@lru_cache(maxsize=1)
def _load_aliases() -> dict:
    return json.loads(ALIASES_PATH.read_text(encoding="utf-8"))


def _normalize_text(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw or "")
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_entity_name(raw: str) -> EntityNormalizationResult:
    aliases = _load_aliases()
    norm_raw = _normalize_text(raw)
    for canonical, payload in aliases.items():
        candidates = [canonical, *payload.get("aliases", []), *payload.get("predecessors", []), *payload.get("subsidiaries", [])]
        for candidate in candidates:
            if _normalize_text(candidate) == norm_raw:
                return EntityNormalizationResult(
                    raw_input=raw,
                    canonical=canonical,
                    matched_alias=candidate,
                    aliases=list(payload.get("aliases", [])),
                    predecessors=list(payload.get("predecessors", [])),
                    subsidiaries=list(payload.get("subsidiaries", [])),
                )
    return EntityNormalizationResult(
        raw_input=raw,
        canonical=raw.strip(),
        matched_alias=raw.strip(),
        aliases=[],
        predecessors=[],
        subsidiaries=[],
    )


def normalize_inventor_name(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw or "")
    text = re.sub(r"\s+", " ", text).strip()
    parts = [part for part in re.split(r"[\s,]+", text) if part]
    if len(parts) >= 2 and "," in text:
        surname = parts[0]
        given = " ".join(parts[1:])
        return f"{given} {surname}".strip()
    return text


def normalize_model_number(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", unicodedata.normalize("NFKC", raw or "")).upper()
