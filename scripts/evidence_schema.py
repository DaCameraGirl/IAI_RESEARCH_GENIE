#!/usr/bin/env python3
"""Typed evidence records used across research lanes and scoring."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EvidenceTier(str, Enum):
    LEAD = "LEAD"
    CANDIDATE = "CANDIDATE"
    PROOF = "PROOF"


class EvidenceType(str, Enum):
    PATENT = "PATENT"
    PATENT_PROSECUTION = "PATENT_PROSECUTION"
    LITIGATION = "LITIGATION"
    SCHOLARLY_NPL = "SCHOLARLY_NPL"
    STANDARD = "STANDARD"
    GOVERNMENT_REPORT = "GOVERNMENT_REPORT"
    REGULATORY = "REGULATORY"
    PRODUCT_MANUAL = "PRODUCT_MANUAL"
    DISTRIBUTOR = "DISTRIBUTOR"
    PROCUREMENT = "PROCUREMENT"
    CORPORATE_DISCLOSURE = "CORPORATE_DISCLOSURE"
    TRADE_SHOW = "TRADE_SHOW"
    BOOK = "BOOK"
    THESIS = "THESIS"
    SOFTWARE_ARTIFACT = "SOFTWARE_ARTIFACT"
    FORUM = "FORUM"
    VIDEO = "VIDEO"
    SCANNED_DOCUMENT = "SCANNED_DOCUMENT"
    NEWSWIRE = "NEWSWIRE"
    ARCHIVED_WEB = "ARCHIVED_WEB"
    OTHER = "OTHER"


@dataclass(slots=True)
class EvidenceRecord:
    record_id: str
    study_id: str
    lane_id: str = ""
    tier: EvidenceTier = EvidenceTier.LEAD
    evidence_type: EvidenceType = EvidenceType.OTHER
    raw_title: str = ""
    normalized_title: str = ""
    source_url: str = ""
    archived_url: str = ""
    document_url: str = ""
    local_copy_path: str = ""
    source_snapshot_path: str = ""
    retrieved_at: str = ""
    document_date: str = ""
    date_kind: str = ""
    date_confidence: str = ""
    critical_date: str = ""
    language: str = ""
    publisher: str = ""
    authors: list[str] = field(default_factory=list)
    assignee: str = ""
    inventor_names: list[str] = field(default_factory=list)
    publication_number: str = ""
    patent_family_key: str = ""
    entity_key: str = ""
    model_numbers: list[str] = field(default_factory=list)
    part_numbers: list[str] = field(default_factory=list)
    cpc_codes: list[str] = field(default_factory=list)
    ipc_codes: list[str] = field(default_factory=list)
    requirement_mapping: list[dict[str, Any]] = field(default_factory=list)
    shortest_verbatim_highlight: str = ""
    page_number: str | int | None = None
    timestamp_or_location: str = ""
    access_status: str = ""
    source_reliability: str = ""
    duplicate_status: str = ""
    duplicate_relation: str = ""
    inference_burden: str = ""
    metadata_uncertainty: str = ""
    corroboration_keys: list[str] = field(default_factory=list)
    content_sha256: str = ""
    score: int = 0
    score_breakdown: dict[str, dict[str, Any]] = field(default_factory=dict)
    hard_gate_failures: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    citation_graph: dict[str, Any] = field(default_factory=dict)
    rank_reason: str = ""
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.tier, str):
            self.tier = EvidenceTier(self.tier)
        if isinstance(self.evidence_type, str):
            self.evidence_type = EvidenceType(self.evidence_type)
        if not self.retrieved_at:
            self.retrieved_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.validate()

    def validate(self) -> None:
        if self.tier is not EvidenceTier.PROOF:
            return
        if self.hard_gate_failures:
            raise ValueError("PROOF records cannot contain hard-gate failures")
        if not (self.document_url or self.local_copy_path):
            raise ValueError("PROOF records require a document URL or stable local copy")
        if not self.requirement_mapping:
            raise ValueError("PROOF records require requirement mapping")
        if not self.shortest_verbatim_highlight.strip():
            raise ValueError("PROOF records require a verbatim highlight")
        if not self.document_date.strip():
            raise ValueError("PROOF records require a verified document date")
        if self.date_confidence.lower() not in {"verified", "high"}:
            raise ValueError("PROOF records require a verified document date")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tier"] = self.tier.value
        data["evidence_type"] = self.evidence_type.value
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceRecord":
        payload = dict(data)
        payload["tier"] = EvidenceTier(payload.get("tier", EvidenceTier.LEAD))
        payload["evidence_type"] = EvidenceType(
            payload.get("evidence_type", EvidenceType.OTHER)
        )
        return cls(**payload)

    @classmethod
    def from_json(cls, raw: str) -> "EvidenceRecord":
        return cls.from_dict(json.loads(raw))
