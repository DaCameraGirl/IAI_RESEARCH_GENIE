"""Tests for normalization helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from normalizers.entities import normalize_entity_name
from normalizers.patent_family import normalize_publication_number
from normalizers.titles import normalize_title


class TestNormalizers(unittest.TestCase):
    def test_patent_number_normalization(self) -> None:
        result = normalize_publication_number("US 7,702,742 B2")
        self.assertEqual(result.normalized_publication, "US7702742")
        self.assertEqual(result.number_type, "grant")

    def test_title_normalization(self) -> None:
        self.assertEqual(
            normalize_title("Blade Assembly — Archive Copy"),
            "blade assembly - archive copy".replace(" archive copy", ""),
        )

    def test_entity_alias_normalization(self) -> None:
        result = normalize_entity_name("Philips Semiconductors")
        self.assertEqual(result.canonical, "NXP Semiconductors")


if __name__ == "__main__":
    unittest.main()
