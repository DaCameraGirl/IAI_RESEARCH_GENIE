#!/usr/bin/env python3
"""Deterministic evidence quality scoring and READY hard-gate evaluation."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from evidence_schema import EvidenceRecord, EvidenceTier
from repo_paths import REPO_ROOT
from research_policy import is_ready

SCORING_PATH = REPO_ROOT / "config" / "evidence_scoring.json"


@lru_cache(maxsize=1)
def load_scoring_config() -> dict[str, Any]:
    return json.loads(SCORING_PATH.read_text(encoding="utf-8"))


def _factor(applied: bool, points: int, reason: str, supporting_field: str) -> dict[str, Any]:
    return {
        "applied": applied,
        "points": points if applied else 0,
        "reason": reason,
        "supporting_field": supporting_field,
    }


PRIMARY_TECHNICAL_TYPES = {
    "PATENT",
    "PATENT_PROSECUTION",
    "STANDARD",
    "GOVERNMENT_REPORT",
    "REGULATORY",
    "PRODUCT_MANUAL",
    "SCHOLARLY_NPL",
    "SOFTWARE_ARTIFACT",
}


def score_evidence(record: EvidenceRecord) -> EvidenceRecord:
    cfg = load_scoring_config()
    positive = cfg["positive"]
    penalties = cfg["penalties"]

    exact_requirement = bool(
        record.shortest_verbatim_highlight.strip()
        and any(row.get("select") == "yes" for row in record.requirement_mapping)
    )
    verified_precritical = bool(
        record.document_date.strip()
        and record.critical_date.strip()
        and record.date_confidence.lower() in {"verified", "high"}
        and record.document_date <= record.critical_date
    )
    primary_source = (
        record.evidence_type.value in PRIMARY_TECHNICAL_TYPES
        or record.source_reliability.lower() in {"primary", "official", "regulatory", "patent-office"}
    )
    downloadable_pdf = bool(
        record.document_url.lower().endswith(".pdf")
        or record.local_copy_path.lower().endswith(".pdf")
        or record.access_status.lower() in {"open", "downloadable-pdf", "archived-pdf"}
    )
    exact_model_or_part = bool(record.model_numbers or record.part_numbers or record.publication_number)
    independent_corroboration = len(set(record.corroboration_keys)) >= 2
    inferred_relationship = record.inference_burden.lower() in {"high", "inferred-only", "inferred"}
    uncertain_date = not verified_precritical and (
        bool(record.document_date.strip()) or record.date_confidence.lower() in {"low", "uncertain", "medium"}
    )
    known_family_duplicate = record.duplicate_status.lower() in {
        "known-family-duplicate",
        "family-duplicate",
        "confirmed-duplicate",
    }

    breakdown = {
        "exact_requirement_language": _factor(
            exact_requirement,
            positive["exact_requirement_language"],
            "Explicit requirement mapping with verbatim support" if exact_requirement else "No explicit requirement support",
            "requirement_mapping",
        ),
        "verified_precritical_date": _factor(
            verified_precritical,
            positive["verified_precritical_date"],
            "Verified document date is on or before the critical date" if verified_precritical else "Document date is not verified pre-critical",
            "document_date",
        ),
        "primary_technical_source": _factor(
            primary_source,
            positive["primary_technical_source"],
            "Primary technical or official source" if primary_source else "Source is indirect or non-technical",
            "evidence_type",
        ),
        "downloadable_original_pdf": _factor(
            downloadable_pdf,
            positive["downloadable_original_pdf"],
            "Accessible downloadable document copy" if downloadable_pdf else "No downloadable document copy",
            "document_url",
        ),
        "exact_model_or_part_number": _factor(
            exact_model_or_part,
            positive["exact_model_or_part_number"],
            "Exact model, part, or publication identifier present" if exact_model_or_part else "No exact model or part identifier",
            "model_numbers",
        ),
        "independent_corroboration": _factor(
            independent_corroboration,
            positive["independent_corroboration"],
            "Independent corroboration recorded" if independent_corroboration else "No independent corroboration",
            "corroboration_keys",
        ),
        "inferred_relationship": _factor(
            inferred_relationship,
            penalties["inferred_relationship"],
            "Relationship requires inference" if inferred_relationship else "Relationship is explicit or not inference-heavy",
            "inference_burden",
        ),
        "uncertain_date": _factor(
            uncertain_date,
            penalties["uncertain_date"],
            "Date chain is uncertain" if uncertain_date else "Date chain is sufficiently verified",
            "date_confidence",
        ),
        "known_family_duplicate": _factor(
            known_family_duplicate,
            0,
            "Known patent-family duplicate" if known_family_duplicate else "No known family duplicate",
            "duplicate_status",
        ),
    }

    record.score_breakdown = breakdown
    record.score = sum(item["points"] for item in breakdown.values())
    record.hard_gate_failures = evaluate_hard_gates(record)
    return record


def evaluate_hard_gates(record: EvidenceRecord, *, include_tier_gate: bool = True) -> list[str]:
    failures: list[str] = []
    if record.critical_date and record.document_date and record.document_date > record.critical_date:
        failures.append("post-critical date")
    if not record.document_date or record.date_confidence.lower() not in {"verified", "high"}:
        failures.append("date cannot be verified sufficiently")
    if record.duplicate_status.lower() in {"known-art", "known-art-match"}:
        failures.append("known-art match")
    if record.duplicate_status.lower() in {
        "known-family-duplicate",
        "family-duplicate",
        "confirmed-duplicate",
    }:
        failures.append("known-family duplicate")
    if not any(row.get("select") == "yes" for row in record.requirement_mapping):
        failures.append("no explicit requirement support")
    if not (record.document_url or record.local_copy_path):
        failures.append("no accessible source document")
    if not record.shortest_verbatim_highlight.strip():
        failures.append("no verbatim highlight")
    if not record.requirement_mapping:
        failures.append("no requirement mapping")
    if include_tier_gate and record.tier is not EvidenceTier.PROOF:
        failures.append("evidence tier is not PROOF")
    return failures


def ready_decision(
    record: EvidenceRecord,
    *,
    self_rank: int,
    confidence: str,
) -> tuple[bool, str]:
    record = score_evidence(record)
    eligible = is_ready(self_rank, confidence) and record.tier is EvidenceTier.PROOF and not record.hard_gate_failures
    reasons: list[str] = []
    if any(row.get("select") == "yes" for row in record.requirement_mapping):
        reasons.append("Explicit relationship language")
    if record.document_date and record.date_confidence.lower() in {"verified", "high"}:
        reasons.append("verified pre-critical date")
    if record.document_url or record.local_copy_path:
        reasons.append("accessible technical document")
    if record.duplicate_status.lower() not in {"known-family-duplicate", "family-duplicate", "confirmed-duplicate"}:
        reasons.append("no family duplicate")
    reasons.append("READY policy passed" if is_ready(self_rank, confidence) else "READY policy failed")
    if record.hard_gate_failures:
        reasons.append("hard gates failed: " + ", ".join(record.hard_gate_failures))
    return eligible, "; ".join(reasons)


def classify_evidence_record(record: EvidenceRecord) -> EvidenceRecord:
    scored = score_evidence(record)
    failures_without_tier = evaluate_hard_gates(scored, include_tier_gate=False)
    if not failures_without_tier:
        target_tier = EvidenceTier.PROOF
    elif any(
        failure in {"post-critical date", "known-art match", "known-family duplicate"}
        for failure in failures_without_tier
    ):
        target_tier = EvidenceTier.LEAD
    elif any(
        (
            scored.document_url,
            scored.local_copy_path,
            scored.document_date,
            scored.shortest_verbatim_highlight,
            scored.requirement_mapping,
        )
    ):
        target_tier = EvidenceTier.CANDIDATE
    else:
        target_tier = EvidenceTier.LEAD

    if scored.tier is target_tier and scored.hard_gate_failures == evaluate_hard_gates(scored):
        return scored

    rebuilt = EvidenceRecord.from_dict(
        {
            **scored.to_dict(),
            "tier": target_tier.value,
            "hard_gate_failures": [],
        }
    )
    return score_evidence(rebuilt)
