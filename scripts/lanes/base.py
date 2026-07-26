#!/usr/bin/env python3
"""Base lane definitions and contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from evidence_schema import EvidenceTier, EvidenceType


class CostClass(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class LaneProduce(str, Enum):
    LEAD = EvidenceTier.LEAD.value
    CANDIDATE = EvidenceTier.CANDIDATE.value
    PROOF = EvidenceTier.PROOF.value


@dataclass(slots=True)
class LaneDefinition:
    id: str
    name: str
    supported_study_types: tuple[str, ...]
    evidence_types: tuple[EvidenceType, ...]
    cost_class: CostClass
    default_enabled: bool
    produces: tuple[LaneProduce, ...]
    required_inputs: tuple[str, ...]
    dedupe_strategy: str
    date_rules: str
    description: str


@dataclass(slots=True)
class LaneResult:
    lane_id: str
    records: list["EvidenceRecord"]
    notes: list[str] = field(default_factory=list)


class LaneRunner(Protocol):
    def run(self, study_id: str, **kwargs) -> LaneResult:
        ...
