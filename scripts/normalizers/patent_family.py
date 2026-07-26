#!/usr/bin/env python3
"""Patent publication and family normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class PatentNormalizationResult:
    raw_input: str
    normalized_publication: str
    family_key: str
    number_type: str
    evidence_basis: str


def _strip_pub(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()


def normalize_publication_number(raw: str, family_hint: str = "") -> PatentNormalizationResult:
    clean = _strip_pub(raw)
    if not clean:
        return PatentNormalizationResult(raw_input=raw, normalized_publication="", family_key="", number_type="unknown", evidence_basis="missing")

    country = clean[:2] if len(clean) > 2 and clean[:2].isalpha() else ""
    body = clean[2:] if country else clean
    kind_match = re.match(r"^(.*?)([A-Z]\d*|B\d*|A\d*)$", body)
    base = body
    number_type = "publication"
    if kind_match and any(ch.isdigit() for ch in kind_match.group(1)):
        base = kind_match.group(1)
        suffix = kind_match.group(2)
        if suffix.startswith("B"):
            number_type = "grant"
        elif suffix.startswith("A"):
            number_type = "publication"
    normalized = f"{country}{base}" if country else base
    family_key = _strip_pub(family_hint) or normalized
    basis = "family_hint" if family_hint else "normalized_publication"
    return PatentNormalizationResult(
        raw_input=raw,
        normalized_publication=normalized,
        family_key=family_key,
        number_type=number_type,
        evidence_basis=basis,
    )
