#!/usr/bin/env python3
"""Persist auditable sidecars for surfaced READY candidates."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_if_value(path: Path, value: str) -> str:
    data = value.encode("utf-8")
    path.write_bytes(data)
    return _sha256_bytes(data)


def write_ready_proof_bundle(
    bundle_dir: Path,
    *,
    candidate_text: str,
    source_snapshot_html: str,
    metadata: dict,
) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)

    candidate_copy = bundle_dir / "candidate_submission.txt"
    candidate_hash = _write_if_value(candidate_copy, candidate_text)

    snapshot_hash = ""
    snapshot_copy = None
    if source_snapshot_html:
        snapshot_copy = bundle_dir / "source_snapshot.html"
        snapshot_hash = _write_if_value(snapshot_copy, source_snapshot_html)

    payload = {
        **metadata,
        "written_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "stable_local_copy": str(candidate_copy),
        "stable_local_copy_sha256": candidate_hash,
        "source_snapshot_path": str(snapshot_copy) if snapshot_copy else "",
        "source_snapshot_sha256": snapshot_hash,
    }
    proof_path = bundle_dir / "proof_bundle.json"
    proof_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return proof_path
