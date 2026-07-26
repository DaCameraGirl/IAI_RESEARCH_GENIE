"""Regression tests for patent READY gating."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import patent_hunter  # noqa: E402
import study_requirements  # noqa: E402


class TestPatentReadyGate(unittest.TestCase):
    def setUp(self) -> None:
        self.study_id = "TREADY"
        self.meta = {
            "title": "Blender offset study",
            "patent": "US9999999",
            "keywords": ["offset", "axis", "battery", "charge"],
            "requirements": [
                {"id": "R1", "name": "Offset axis", "keywords": ["offset", "axis"]},
                {"id": "R2", "name": "Battery charge", "keywords": ["battery", "charge"]},
            ],
            "priority_req_ids": ["R1"],
            "critical_date": "2020-01-01",
        }
        self._orig_patent_meta = patent_hunter.STUDY_META
        self._orig_requirements_meta = study_requirements.STUDY_META
        patent_hunter.STUDY_META = {self.study_id: self.meta}
        study_requirements.STUDY_META = {self.study_id: self.meta}

    def tearDown(self) -> None:
        patent_hunter.STUDY_META = self._orig_patent_meta
        study_requirements.STUDY_META = self._orig_requirements_meta

    def test_rank_one_is_not_ready(self) -> None:
        rec = patent_hunter.PatentRecord(
            pub_id="US1234567",
            title="Offset axis mixer",
            priority_date="2019-01-01",
            publication_date="2019-06-01",
            url="https://patents.google.com/patent/US1234567",
            pdf_url="https://patents.google.com/patent/US1234567.pdf",
            abstract="The blade uses an offset axis for mixing.",
        )
        scored = patent_hunter.score_record(rec, self.study_id)
        self.assertEqual(scored.self_rank, 1)
        self.assertEqual(scored.confidence, "med")
        self.assertFalse(scored.ready)

    def test_rank_two_is_ready(self) -> None:
        rec = patent_hunter.PatentRecord(
            pub_id="US2345678",
            title="Offset axis rechargeable mixer",
            priority_date="2019-01-01",
            publication_date="2019-06-01",
            url="https://patents.google.com/patent/US2345678",
            pdf_url="https://patents.google.com/patent/US2345678.pdf",
            abstract="The blade uses an offset axis and a battery charge system.",
        )
        scored = patent_hunter.score_record(rec, self.study_id)
        self.assertEqual(scored.self_rank, 2)
        self.assertEqual(scored.confidence, "med")
        self.assertTrue(scored.ready)


if __name__ == "__main__":
    unittest.main()
