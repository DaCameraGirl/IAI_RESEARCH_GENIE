#!/usr/bin/env python3
"""Requirement mapping helpers for candidate drafting and scoring."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT))

from ai_engine.semantic_matcher import SemanticMatcher  # noqa: E402
from study_bot import STUDY_META  # noqa: E402


def _priority_for_requirement(study_id: str, req_id: str) -> int:
    priority_ids = set(str(v) for v in STUDY_META[study_id].get("priority_req_ids", []))
    return 1 if str(req_id) in priority_ids else 2


def _requirement_payloads(study_id: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for req in STUDY_META[study_id]["requirements"]:
        keywords = list(req.get("keywords", []))
        must_show = [kw for kw in keywords if len(kw) >= 8][:5]
        payloads.append(
            {
                "id": str(req["id"]),
                "text": req["name"],
                "must_show_elements": must_show,
                "keywords": keywords,
                "priority": _priority_for_requirement(study_id, str(req["id"])),
            }
        )
    return payloads


@lru_cache(maxsize=16)
def _matcher_for_study(study_id: str) -> SemanticMatcher:
    matcher = SemanticMatcher()
    matcher.load_requirements(study_id, _requirement_payloads(study_id))
    return matcher


def _semantic_matches_by_requirement(study_id: str, text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    matcher = _matcher_for_study(study_id)
    matches = matcher.match_document(
        study_id,
        text,
        document_metadata={},
        min_confidence=0.45,
    )
    return {str(match.requirement_id): match for match in matches}


def map_requirements(study_id: str, text: str) -> list[dict[str, str]]:
    """Return requirement rows with lexical + semantic scoring."""
    text_l = text.lower()
    semantic_matches = _semantic_matches_by_requirement(study_id, text)
    rows = []
    for req in STUDY_META[study_id]["requirements"]:
        req_id = str(req["id"])
        hits = [k for k in req["keywords"] if k.lower() in text_l]
        semantic = semantic_matches.get(req_id)
        semantic_conf = float(getattr(semantic, "confidence", 0.0) or 0.0)

        if len(hits) >= 2 or semantic_conf >= 0.72:
            select = "yes"
            if len(hits) >= 2:
                why = f"Matched signals: {', '.join(hits[:3])}"
            else:
                why = f"Semantic match {semantic_conf:.2f} — {semantic.reasoning}"
        elif len(hits) == 1 or semantic_conf >= 0.55:
            select = "maybe"
            if len(hits) == 1:
                why = f"Weak signal — verify in PDF: {hits[0]}"
            else:
                why = f"Semantic maybe {semantic_conf:.2f} — {semantic.reasoning}"
        else:
            select = "no"
            why = "No strong lexical/semantic signal — check claims manually"

        rows.append(
            {
                "id": req["id"],
                "name": req["name"],
                "select": select,
                "why": why,
                "hits": hits,
                "semantic_confidence": f"{semantic_conf:.2f}" if semantic else "0.00",
            }
        )
    return rows


def ctrl_f_phrases(text: str, keywords: list[str], limit: int = 6) -> list[str]:
    """Pull Ctrl+F phrases from sentences containing matched keywords."""
    phrases: list[str] = []
    sentences = re_split_sentences(text)
    for sent in sentences:
        sl = sent.lower()
        if any(k.lower() in sl for k in keywords):
            clean = " ".join(sent.split())
            if 20 <= len(clean) <= 220:
                phrases.append(clean)
        if len(phrases) >= limit:
            break
    if not phrases and text:
        phrases.append(text[:180].strip() + ("..." if len(text) > 180 else ""))
    return phrases[:limit]


def re_split_sentences(text: str) -> list[str]:
    import re

    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) > 15]
