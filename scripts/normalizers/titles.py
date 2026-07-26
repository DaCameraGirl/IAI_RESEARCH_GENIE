#!/usr/bin/env python3
"""Title normalization and duplicate clustering helpers."""

from __future__ import annotations

import re
import unicodedata

_MIRROR_SUFFIXES = (
    " pdf",
    " mirror",
    " mirrored copy",
    " archive copy",
    " archived copy",
)


def normalize_title(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw or "")
    text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    for suffix in _MIRROR_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text
