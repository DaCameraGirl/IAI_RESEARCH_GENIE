"""Tests for the L2 patent citations/prosecution/PTAB lead lane."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import patent_hunter  # noqa: E402
import study_requirements  # noqa: E402
from evidence_schema import EvidenceTier, EvidenceType  # noqa: E402
from evidence_scoring import ready_decision  # noqa: E402
from lanes.registry import get_lane_runner  # noqa: E402


class TestPatentCitationsProsecutionLane(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = get_lane_runner("L2_PATENT_CITATIONS_PROSECUTION")
        self.root = SimpleNamespace(
            citations=["US 2001/0001234 A1", "US20010001234A1"],
            source_snapshot_html="",
            url="https://patents.google.com/patent/US9999999",
        )

    def _run(self, **kwargs):
        params = {
            "study_id": "T26052",
            "publication_number": "US9999999A1",
            "critical_date": "2020-01-01",
            "root_record": self.root,
        }
        params.update(kwargs)
        return self.runner.run(**params)

    def test_backward_citation_normalization_and_duplicate_collapse(self) -> None:
        result = self._run()
        patent_leads = [r for r in result.records if r.evidence_type is EvidenceType.PATENT and r.tier is EvidenceTier.LEAD]
        self.assertEqual(len(patent_leads), 1)
        self.assertEqual(patent_leads[0].publication_number, "US20010001234")

    def test_forward_citation_critical_date_filtering(self) -> None:
        result = self._run(
            forward_citations=[
                {"publication_number": "US20020000001A1", "publication_date": "2019-03-01"},
                {"publication_number": "US20230000001A1", "publication_date": "2021-03-01"},
            ]
        )
        forwards = [
            r for r in result.records
            if r.citation_graph.get("direction") == "forward" and r.evidence_type is EvidenceType.PATENT
        ]
        self.assertEqual(len(forwards), 1)
        self.assertEqual(forwards[0].publication_number, "US20020000001")

    def test_npl_reference_classifies_as_lead(self) -> None:
        result = self._run(
            npl_references=[
                {
                    "title": "OpenAlex prior art survey",
                    "url": "https://example.com/openalex.pdf",
                    "authors": ["Smith"],
                }
            ]
        )
        npl = next(r for r in result.records if r.evidence_type is EvidenceType.SCHOLARLY_NPL)
        self.assertEqual(npl.tier, EvidenceTier.LEAD)
        self.assertEqual(npl.citation_graph["direction"], "npl")

    def test_ptab_reference_classifies_as_lead_and_legal_filing_cannot_be_ready(self) -> None:
        result = self._run(
            ptab_documents=[
                {
                    "title": "IPR2020-01234 Petition",
                    "source_url": "https://example.com/ipr2020-01234",
                    "document_url": "https://example.com/ipr2020-01234.pdf",
                    "document_date": "2019-05-01",
                    "text": "IPR2020-01234 cites US20010001234A1 heavily.",
                }
            ]
        )
        filing = next(
            r for r in result.records
            if r.evidence_type is EvidenceType.LITIGATION and r.raw_title == "IPR2020-01234 Petition"
        )
        self.assertEqual(filing.tier, EvidenceTier.LEAD)
        self.assertFalse(ready_decision(filing, self_rank=3, confidence="high")[0])

    def test_known_art_and_family_duplicate_rejections(self) -> None:
        known_art = self._run(
            backward_citations=[{"publication_number": "US20010001234A1"}],
            known_art_set={"US20010001234": "citation"},
            underlying_patent_documents={
                "US20010001234": {
                    "title": "Known art patent",
                    "document_url": "https://example.com/known.pdf",
                    "document_date": "2018-01-01",
                    "date_kind": "publication_date",
                    "date_confidence": "verified",
                    "requirement_mapping": [{"id": "R1", "select": "yes"}],
                    "shortest_verbatim_highlight": "offset axis",
                }
            },
        )
        known_underlying = next(
            r for r in known_art.records
            if r.record_id.endswith("underlying:US20010001234")
        )
        self.assertIn("known-art match", known_underlying.hard_gate_failures)

        family = self._run(
            backward_citations=[{"publication_number": "US9999999A1", "family_key": "FAM-1"}],
            study_family_key="FAM-1",
            underlying_patent_documents={
                "US9999999": {
                    "title": "Family duplicate patent",
                    "document_url": "https://example.com/family.pdf",
                    "document_date": "2018-01-01",
                    "date_kind": "publication_date",
                    "date_confidence": "verified",
                    "requirement_mapping": [{"id": "R1", "select": "yes"}],
                    "shortest_verbatim_highlight": "offset axis",
                }
            },
        )
        family_underlying = next(
            r for r in family.records
            if r.record_id.endswith("underlying:US9999999")
        )
        self.assertIn("known-family duplicate", family_underlying.hard_gate_failures)

    def test_direction_metadata_and_one_hop_limit(self) -> None:
        result = self._run(
            citation_depth=5,
            backward_citations=[{"publication_number": "US20010001234A1", "relation_confidence": "high"}],
        )
        lead = next(r for r in result.records if r.evidence_type is EvidenceType.PATENT)
        self.assertEqual(lead.citation_graph["direction"], "backward")
        self.assertEqual(lead.citation_graph["source_publication"], "US9999999")
        self.assertEqual(lead.citation_graph["hop_count"], 1)
        self.assertIn("citation_depth=1", result.notes)

    def test_underlying_patent_can_be_candidate_or_proof_but_ready_still_uses_policy(self) -> None:
        candidate_result = self._run(
            backward_citations=[{"publication_number": "US20010001234A1"}],
            underlying_patent_documents={
                "US20010001234": {
                    "title": "Offset axis patent",
                    "document_url": "https://example.com/candidate.pdf",
                    "document_date": "2018-01-01",
                    "date_kind": "publication_date",
                    "date_confidence": "verified",
                }
            },
        )
        candidate = next(
            r for r in candidate_result.records
            if r.record_id.endswith("underlying:US20010001234")
        )
        self.assertEqual(candidate.tier, EvidenceTier.CANDIDATE)

        proof_result = self._run(
            backward_citations=[{"publication_number": "US20010001234A1"}],
            underlying_patent_documents={
                "US20010001234": {
                    "title": "Offset axis rechargeable patent",
                    "document_url": "https://example.com/proof.pdf",
                    "document_date": "2018-01-01",
                    "date_kind": "publication_date",
                    "date_confidence": "verified",
                    "requirement_mapping": [{"id": "R1", "select": "yes", "why": "explicit"}],
                    "shortest_verbatim_highlight": "axis displaced from container center",
                    "source_reliability": "patent-office",
                }
            },
        )
        proof = next(
            r for r in proof_result.records
            if r.record_id.endswith("underlying:US20010001234")
        )
        self.assertEqual(proof.tier, EvidenceTier.PROOF)
        self.assertFalse(ready_decision(proof, self_rank=1, confidence="high")[0])
        self.assertTrue(ready_decision(proof, self_rank=2, confidence="med")[0])


class TestPatentCitationsProsecutionIntegration(unittest.TestCase):
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

    def test_proof_bundle_includes_citation_provenance_and_pipeline_remains_compatible(self) -> None:
        rec = patent_hunter.PatentRecord(
            pub_id="US1234567",
            title="Offset axis rechargeable mixer",
            assignee="Philips Semiconductors",
            inventors="Doe, Jane",
            priority_date="2019-01-01",
            publication_date="2019-06-01",
            abstract="The blade uses an offset axis and a battery charge system.",
            url="https://patents.google.com/patent/US1234567",
            pdf_url="https://patents.google.com/patent/US1234567.pdf",
            source_lane="L2-backward",
            source_snapshot_html="<html>snapshot</html>",
            citation_provenance=[
                {
                    "direction": "backward",
                    "source_publication": "US9999999",
                    "target_publication": "US1234567",
                    "hop_count": 1,
                    "discovered_from": "US9999999",
                    "relation_confidence": "high",
                }
            ],
        )
        rec = patent_hunter.score_record(rec, self.study_id)
        engine = patent_hunter.HuntEngine(self.study_id)
        engine._write_candidate(self.folder, rec, ready=rec.ready, burned={})

        proof_path = self.folder / "candidates" / "proof_bundles" / "US1234567" / "proof_bundle.json"
        payload = json.loads(proof_path.read_text(encoding="utf-8"))
        self.assertTrue(rec.ready)
        self.assertEqual(payload["evidence_tier"], "PROOF")
        self.assertIn("citation_provenance", payload)
        self.assertEqual(payload["citation_provenance"][0]["direction"], "backward")
        self.assertIn("query_plan_provenance", payload)


if __name__ == "__main__":
    unittest.main()
