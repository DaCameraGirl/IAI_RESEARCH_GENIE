"""Tests for evidence scoring and READY gating."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from evidence_schema import EvidenceRecord, EvidenceTier, EvidenceType
from evidence_scoring import ready_decision, score_evidence


def _base_proof() -> EvidenceRecord:
    return EvidenceRecord(
        record_id="proof-ok",
        study_id="26052",
        tier=EvidenceTier.PROOF,
        evidence_type=EvidenceType.PATENT,
        raw_title="Blade axis offset mixer",
        normalized_title="blade axis offset mixer",
        document_url="https://example.com/doc.pdf",
        local_copy_path="C:/tmp/doc.pdf",
        document_date="2019-01-01",
        date_confidence="verified",
        critical_date="2019-10-28",
        publication_number="US1234567",
        model_numbers=["BL-100"],
        requirement_mapping=[{"id": "RR1.1", "select": "yes"}],
        shortest_verbatim_highlight="the axis is displaced from the container center",
        access_status="open",
        source_reliability="primary",
        corroboration_keys=["oem-manual", "fcc-exhibit"],
    )


class TestEvidenceScoring(unittest.TestCase):
    def test_exact_requirement_language_adds_30(self) -> None:
        rec = score_evidence(_base_proof())
        self.assertEqual(rec.score_breakdown["exact_requirement_language"]["points"], 30)

    def test_verified_precritical_date_adds_20(self) -> None:
        rec = score_evidence(_base_proof())
        self.assertEqual(rec.score_breakdown["verified_precritical_date"]["points"], 20)

    def test_primary_technical_source_adds_15(self) -> None:
        rec = score_evidence(_base_proof())
        self.assertEqual(rec.score_breakdown["primary_technical_source"]["points"], 15)

    def test_downloadable_original_pdf_adds_10(self) -> None:
        rec = score_evidence(_base_proof())
        self.assertEqual(rec.score_breakdown["downloadable_original_pdf"]["points"], 10)

    def test_exact_model_or_part_number_adds_10(self) -> None:
        rec = score_evidence(_base_proof())
        self.assertEqual(rec.score_breakdown["exact_model_or_part_number"]["points"], 10)

    def test_independent_corroboration_adds_5(self) -> None:
        rec = score_evidence(_base_proof())
        self.assertEqual(rec.score_breakdown["independent_corroboration"]["points"], 5)

    def test_inferred_relationship_subtracts_20(self) -> None:
        rec = _base_proof()
        rec.inference_burden = "inferred-only"
        scored = score_evidence(rec)
        self.assertEqual(scored.score_breakdown["inferred_relationship"]["points"], -20)

    def test_uncertain_date_subtracts_25(self) -> None:
        rec = _base_proof()
        rec.date_confidence = "uncertain"
        rec.tier = EvidenceTier.CANDIDATE
        scored = score_evidence(rec)
        self.assertEqual(scored.score_breakdown["uncertain_date"]["points"], -25)

    def test_known_family_duplicate_hard_rejects(self) -> None:
        rec = _base_proof()
        rec.tier = EvidenceTier.CANDIDATE
        rec.duplicate_status = "known-family-duplicate"
        scored = score_evidence(rec)
        self.assertIn("known-family duplicate", scored.hard_gate_failures)

    def test_keyword_count_alone_cannot_make_record_ready(self) -> None:
        rec = _base_proof()
        rec.tier = EvidenceTier.CANDIDATE
        rec.requirement_mapping = []
        rec.notes.append("matched_keywords=20")
        ready, _ = ready_decision(rec, self_rank=3, confidence="high")
        self.assertFalse(ready)

    def test_score_alone_cannot_make_record_ready(self) -> None:
        rec = _base_proof()
        rec.tier = EvidenceTier.CANDIDATE
        ready, _ = ready_decision(rec, self_rank=3, confidence="high")
        self.assertFalse(ready)

    def test_proof_plus_ready_policy_can_be_ready(self) -> None:
        ready, _ = ready_decision(_base_proof(), self_rank=2, confidence="high")
        self.assertTrue(ready)

    def test_rank1_high_confidence_proof_is_not_ready(self) -> None:
        ready, _ = ready_decision(_base_proof(), self_rank=1, confidence="high")
        self.assertFalse(ready)

    def test_rank2_low_confidence_proof_is_not_ready(self) -> None:
        ready, _ = ready_decision(_base_proof(), self_rank=2, confidence="low")
        self.assertFalse(ready)


if __name__ == "__main__":
    unittest.main()
