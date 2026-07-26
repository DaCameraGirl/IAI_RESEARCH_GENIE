"""Integration tests for patent evidence records and proof bundles."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import patent_hunter  # noqa: E402
import study_requirements  # noqa: E402


class TestPatentPipelineEvidence(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.study_id = "T26052"
        self.folder_name = "T26052_Blender"
        self.folder = self.tmp_path / self.folder_name
        (self.folder / "candidates").mkdir(parents=True)

        self.meta = {
            "title": "Blender offset blade study",
            "folder": self.folder_name,
            "patent": "US9999999",
            "critical_date": "2019-10-28",
            "focus": "offset axis requirements",
            "type": "patent",
            "keywords": ["offset", "axis", "battery", "charge"],
            "requirements": [
                {"id": "RR1.1", "name": "Offset axis", "keywords": ["offset", "axis"]},
                {"id": "RR1.2", "name": "Battery charge", "keywords": ["battery", "charge"]},
            ],
            "priority_req_ids": ("RR1.1",),
            "assignees": [],
            "synonym_queries": [],
            "cpc_queries": [],
            "npl_queries": [],
        }

        self.orig_repo = patent_hunter.REPO
        self.orig_patent_meta = patent_hunter.STUDY_META
        self.orig_req_meta = study_requirements.STUDY_META
        self.orig_is_burned = patent_hunter.is_burned
        self.orig_load_burned = patent_hunter.load_burned

        patent_hunter.REPO = self.tmp_path
        patent_hunter.STUDY_META = {self.study_id: self.meta}
        study_requirements.STUDY_META = {self.study_id: self.meta}
        patent_hunter.is_burned = lambda _probe, _burned: (False, "")
        patent_hunter.load_burned = lambda _study_id: {}

    def tearDown(self) -> None:
        patent_hunter.REPO = self.orig_repo
        patent_hunter.STUDY_META = self.orig_patent_meta
        study_requirements.STUDY_META = self.orig_req_meta
        patent_hunter.is_burned = self.orig_is_burned
        patent_hunter.load_burned = self.orig_load_burned
        self.tmp.cleanup()

    def _record(self, *, title: str, abstract: str) -> patent_hunter.PatentRecord:
        return patent_hunter.PatentRecord(
            pub_id="US1234567",
            title=title,
            assignee="Philips Semiconductors",
            inventors="Doe, Jane",
            priority_date="2019-01-01",
            publication_date="2019-06-01",
            abstract=abstract,
            url="https://patents.google.com/patent/US1234567",
            pdf_url="https://patents.google.com/patent/US1234567.pdf",
            source_lane="L1-backward-cite",
            source_snapshot_html="<html>snapshot</html>",
        )

    def test_existing_patent_pipeline_writes_ready_proof_bundle(self) -> None:
        rec = self._record(
            title="Offset axis rechargeable mixer",
            abstract="The blade uses an offset axis and a battery charge system.",
        )
        rec = patent_hunter.score_record(rec, self.study_id)
        engine = patent_hunter.HuntEngine(self.study_id)
        engine._write_candidate(self.folder, rec, ready=rec.ready, burned={})

        candidate_path = self.folder / "candidates" / "US1234567_RWS_format.txt"
        proof_path = self.folder / "candidates" / "proof_bundles" / "US1234567" / "proof_bundle.json"
        self.assertTrue(rec.ready)
        self.assertTrue(candidate_path.exists())
        self.assertTrue(proof_path.exists())

        payload = json.loads(proof_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["evidence_tier"], "PROOF")
        self.assertIn("evidence_record", payload)
        self.assertIn("score_breakdown", payload)
        self.assertIn("normalization_results", payload)
        self.assertIn("query_plan_provenance", payload)

    def test_existing_hold_flow_still_works(self) -> None:
        rec = self._record(
            title="Offset axis mixer",
            abstract="The blade uses an offset axis for mixing.",
        )
        rec = patent_hunter.score_record(rec, self.study_id)
        engine = patent_hunter.HuntEngine(self.study_id)
        engine._write_candidate(self.folder, rec, ready=False, burned={})

        hold_path = self.folder / "candidates" / "HOLD_US1234567_RWS_format.txt"
        proof_dir = self.folder / "candidates" / "proof_bundles" / "US1234567"
        self.assertFalse(rec.ready)
        self.assertTrue(hold_path.exists())
        self.assertFalse(proof_dir.exists())

    def test_weak_patent_hit_persists_as_lead_record(self) -> None:
        rec = self._record(
            title="Axis mixer",
            abstract="A mixer uses an axis arrangement for blending.",
        )
        rec = patent_hunter.score_record(rec, self.study_id)
        engine = patent_hunter.HuntEngine(self.study_id)
        engine._write_patent_lead(self.folder, rec, burned={})

        lead_path = self.folder / "candidates" / "LEAD_US1234567_RWS_format.txt"
        self.assertGreater(rec.score, 0)
        self.assertFalse(rec.ready)
        self.assertTrue(lead_path.exists())
        text = lead_path.read_text(encoding="utf-8")
        self.assertIn("Dropdown: Patent lead", text)
        self.assertIn("Status: LEAD ONLY", text)

    def test_candidate_screen_reports_library_leads(self) -> None:
        rec = self._record(
            title="Axis mixer",
            abstract="A mixer uses an axis arrangement for blending.",
        )
        rec = patent_hunter.score_record(rec, self.study_id)
        engine = patent_hunter.HuntEngine(self.study_id)
        engine._write_patent_lead(self.folder, rec, burned={})
        engine._update_candidate_screen(self.folder, ready=[], hold=[])

        screen = (self.folder / "CANDIDATE_SCREEN.md").read_text(encoding="utf-8")
        self.assertIn("Library: 1 LEAD", screen)
        self.assertIn("READY this run: 0", screen)


if __name__ == "__main__":
    unittest.main()
