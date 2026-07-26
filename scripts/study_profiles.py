#!/usr/bin/env python3
"""Study profile resolution for lane activation and hard-gate preferences."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from repo_paths import REPO_ROOT

PROFILES_PATH = REPO_ROOT / "config" / "study_profiles.json"


@dataclass(slots=True)
class StudyProfile:
    name: str
    enabled_lanes: tuple[str, ...]
    disabled_lanes: tuple[str, ...]
    lane_priority: tuple[str, ...]
    maximum_cost_class: str
    preferred_evidence_types: tuple[str, ...]
    required_hard_gates: tuple[str, ...]
    language_expansion_enabled: bool
    archive_search_enabled: bool
    regulatory_search_enabled: bool
    patent_family_normalization_enabled: bool


@lru_cache(maxsize=1)
def load_profiles() -> dict[str, dict[str, Any]]:
    return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))


def get_profile(name: str) -> StudyProfile:
    raw = load_profiles()[name]
    return StudyProfile(
        name=name,
        enabled_lanes=tuple(raw["enabled_lanes"]),
        disabled_lanes=tuple(raw["disabled_lanes"]),
        lane_priority=tuple(raw["lane_priority"]),
        maximum_cost_class=raw["maximum_cost_class"],
        preferred_evidence_types=tuple(raw["preferred_evidence_types"]),
        required_hard_gates=tuple(raw["required_hard_gates"]),
        language_expansion_enabled=bool(raw["language_expansion_enabled"]),
        archive_search_enabled=bool(raw["archive_search_enabled"]),
        regulatory_search_enabled=bool(raw["regulatory_search_enabled"]),
        patent_family_normalization_enabled=bool(raw["patent_family_normalization_enabled"]),
    )


def resolve_profile_from_meta(meta: dict[str, Any]) -> StudyProfile:
    title = f"{meta.get('title', '')} {meta.get('focus', '')}".lower()
    study_type = str(meta.get("type", "")).lower()
    if study_type == "copyright" and "hymn" in title:
        return get_profile("copyright_hymn")
    if "medical" in title or "fda" in title or "510(k)" in title:
        return get_profile("medical_device")
    if "oximidol" in title or "compound" in title or "tyrosinase" in title:
        return get_profile("chemical_compound")
    if "software" in title or "package" in title or "release" in title:
        return get_profile("software_artifact")
    if "product" in title or "manual" in title or "catalog" in title:
        return get_profile("product_evidence")
    if study_type == "patent":
        return get_profile("patent_invalidity")
    return get_profile("general_npl")
