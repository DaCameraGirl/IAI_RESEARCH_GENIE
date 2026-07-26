"""Tests for query plan ranking."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from query_matrix import QueryConceptMatrix, ranked_query_plan


class TestQueryMatrix(unittest.TestCase):
    def test_relationship_ranks_before_broad_component(self) -> None:
        matrix = QueryConceptMatrix(
            component=["blade assembly"],
            function=["blends", "chops", "pulverizes"],
            geometry=["offset axis", "eccentric shaft"],
            measurement=["5-15%", "diameter ratio"],
            relationship=["axis displaced from container center"],
            historical_synonyms=["off-center spindle", "eccentric drive", "non-concentric", "radially displaced"],
            product_classes=["blender"],
        )
        plan = ranked_query_plan(matrix)
        relationship_idx = next(i for i, item in enumerate(plan) if item["pattern"] == "relationship_plus_product_class")
        broad_idx = next(i for i, item in enumerate(plan) if item["pattern"] == "broad_component")
        self.assertLess(relationship_idx, broad_idx)


if __name__ == "__main__":
    unittest.main()
