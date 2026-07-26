"""Tests for study profile activation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from study_profiles import get_profile, resolve_profile_from_meta


class TestStudyProfiles(unittest.TestCase):
    def test_patent_invalidity_profile_activates_family_normalization(self) -> None:
        profile = get_profile("patent_invalidity")
        self.assertTrue(profile.patent_family_normalization_enabled)
        self.assertIn("L1_PATENT_FAMILIES", profile.enabled_lanes)

    def test_copyright_hymn_profile_does_not_activate_patent_family_lane(self) -> None:
        profile = get_profile("copyright_hymn")
        self.assertNotIn("L1_PATENT_FAMILIES", profile.enabled_lanes)
        self.assertFalse(profile.patent_family_normalization_enabled)

    def test_resolve_hymn_profile(self) -> None:
        profile = resolve_profile_from_meta({"type": "copyright", "title": "Hymn Research - Italian", "focus": ""})
        self.assertEqual(profile.name, "copyright_hymn")


if __name__ == "__main__":
    unittest.main()
