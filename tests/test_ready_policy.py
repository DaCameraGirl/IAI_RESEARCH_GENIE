"""Tests for the shared READY/HOLD policy."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import research_policy  # noqa: E402


class TestReadyPolicy(unittest.TestCase):
    def test_config_file_matches_expected_gate(self) -> None:
        policy = json.loads(
            (REPO / "config" / "research_policy.json").read_text(encoding="utf-8")
        )
        self.assertEqual(policy["ready"]["min_rank"], 2)
        self.assertEqual(policy["ready"]["allowed_confidence"], ["high", "med"])

    def test_is_ready(self) -> None:
        self.assertTrue(research_policy.is_ready(2, "high"))
        self.assertTrue(research_policy.is_ready(3, "med"))
        self.assertFalse(research_policy.is_ready(1, "high"))
        self.assertFalse(research_policy.is_ready(2, "low"))

    def test_is_hold(self) -> None:
        self.assertTrue(research_policy.is_hold(1, "med"))
        self.assertFalse(research_policy.is_hold(2, "high"))


if __name__ == "__main__":
    unittest.main()
