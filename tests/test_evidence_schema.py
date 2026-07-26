"""Tests for evidence record typing and validation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from evidence_schema import EvidenceRecord, EvidenceTier, EvidenceType


class TestEvidenceSchema(unittest.TestCase):
    def test_json_round_trip(self) -> None:
        rec = EvidenceRecord(
            record_id="r1",
            study_id="26052",
            tier=EvidenceTier.CANDIDATE,
            evidence_type=EvidenceType.PATENT,
            raw_title="Blade Assembly",
            normalized_title="blade assembly",
        )
        clone = EvidenceRecord.from_json(rec.to_json())
        self.assertEqual(clone.record_id, "r1")
        self.assertEqual(clone.tier, EvidenceTier.CANDIDATE)
        self.assertEqual(clone.evidence_type, EvidenceType.PATENT)

    def test_lead_can_be_incomplete(self) -> None:
        rec = EvidenceRecord(record_id="lead-1", study_id="26052")
        self.assertEqual(rec.tier, EvidenceTier.LEAD)

    def test_candidate_can_be_incomplete(self) -> None:
        rec = EvidenceRecord(
            record_id="cand-1",
            study_id="26052",
            tier=EvidenceTier.CANDIDATE,
        )
        self.assertEqual(rec.tier, EvidenceTier.CANDIDATE)

    def test_proof_requires_date(self) -> None:
        with self.assertRaisesRegex(ValueError, "verified document date"):
            EvidenceRecord(
                record_id="proof-1",
                study_id="26052",
                tier=EvidenceTier.PROOF,
                evidence_type=EvidenceType.PATENT,
                document_url="https://example.com/doc.pdf",
                requirement_mapping=[{"id": "R1", "select": "yes"}],
                shortest_verbatim_highlight="axis displaced from container center",
            )

    def test_proof_requires_highlight(self) -> None:
        with self.assertRaisesRegex(ValueError, "verbatim highlight"):
            EvidenceRecord(
                record_id="proof-2",
                study_id="26052",
                tier=EvidenceTier.PROOF,
                evidence_type=EvidenceType.PATENT,
                document_url="https://example.com/doc.pdf",
                requirement_mapping=[{"id": "R1", "select": "yes"}],
                document_date="2019-01-01",
            )

    def test_proof_requires_requirement_mapping(self) -> None:
        with self.assertRaisesRegex(ValueError, "requirement mapping"):
            EvidenceRecord(
                record_id="proof-3",
                study_id="26052",
                tier=EvidenceTier.PROOF,
                evidence_type=EvidenceType.PATENT,
                document_url="https://example.com/doc.pdf",
                shortest_verbatim_highlight="axis displaced from container center",
                document_date="2019-01-01",
            )

    def test_proof_fails_with_hard_gate_failure(self) -> None:
        with self.assertRaisesRegex(ValueError, "hard-gate failures"):
            EvidenceRecord(
                record_id="proof-4",
                study_id="26052",
                tier=EvidenceTier.PROOF,
                evidence_type=EvidenceType.PATENT,
                document_url="https://example.com/doc.pdf",
                requirement_mapping=[{"id": "R1", "select": "yes"}],
                shortest_verbatim_highlight="axis displaced from container center",
                document_date="2019-01-01",
                date_confidence="verified",
                hard_gate_failures=["known-family duplicate"],
            )


if __name__ == "__main__":
    unittest.main()
