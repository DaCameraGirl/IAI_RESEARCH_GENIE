"""Tests for READY proof-bundle persistence."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import proof_bundle  # noqa: E402


class TestProofBundle(unittest.TestCase):
    def test_writes_bundle_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp) / "proof"
            proof_path = proof_bundle.write_ready_proof_bundle(
                bundle_dir,
                candidate_text="candidate text",
                source_snapshot_html="<html>snapshot</html>",
                metadata={"publication": "US1234567", "reason_for_rank": "2 yes reqs"},
            )

            self.assertTrue(proof_path.exists())
            payload = json.loads(proof_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["publication"], "US1234567")
            self.assertEqual(payload["reason_for_rank"], "2 yes reqs")
            self.assertTrue(payload["stable_local_copy_sha256"])
            self.assertTrue(payload["source_snapshot_sha256"])
            self.assertTrue((bundle_dir / "candidate_submission.txt").exists())
            self.assertTrue((bundle_dir / "source_snapshot.html").exists())


if __name__ == "__main__":
    unittest.main()
