"""Tests for local web candidate parsing and tier display logic."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import rws_web  # noqa: E402


class TestRwsWebCandidateParsing(unittest.TestCase):
    def test_candidate_tier_marks_npl_lead_as_lead(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "NPL_example_RWS_format.txt"
            path.write_text(
                "Self-rank: 1/3\n"
                "In-scope confidence: med\n"
                "Notes:\n"
                "  - NPL lead only\n",
                encoding="utf-8",
            )
            tier = rws_web._candidate_tier(path, path.read_text(encoding="utf-8"), 1, "med", False)
            self.assertEqual(tier, "LEAD")

    def test_candidate_tier_marks_hold_file_as_hold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "HOLD_US1234567_RWS_format.txt"
            path.write_text("Self-rank: 1/3\nIn-scope confidence: med\n", encoding="utf-8")
            tier = rws_web._candidate_tier(path, path.read_text(encoding="utf-8"), 1, "med", False)
            self.assertEqual(tier, "HOLD")

    def test_study_ui_copy_for_patent_uses_ready_rules(self) -> None:
        ui = rws_web._study_ui_copy({"patent": "US1234567"})
        self.assertEqual(ui["hunt_label"], "Run Deep Hunt")
        self.assertIn("rank >= 2", ui["how_it_works_html"])
        self.assertIn("PROOF", ui["how_it_works_html"])

    def test_study_ui_copy_for_hymn_uses_lead_language(self) -> None:
        ui = rws_web._study_ui_copy({"patent": None})
        self.assertEqual(ui["hunt_label"], "Search Hymn Translations")
        self.assertIn("LEADS", ui["how_it_works_html"])
        self.assertIn("archive.org", ui["sources_html"])


if __name__ == "__main__":
    unittest.main()
