#!/usr/bin/env python3
"""Onboard a new RWS study without hand-editing any script.

Two ways to use it:

CLI (point it at a folder — e.g. one of Angela's raw RWS portal exports):
  python scripts/add_study.py <study_id> "<path to source folder>"

The source folder is scanned for the first *.csv (known-citations list —
its presence marks this a patent/invalidity study) and all *.txt files
(concatenated as the raw study brief).

Or call add_study() directly — this is what the web app's two-box
"Add Study" form (Known Citations box + Everything Else box) calls too,
so the CLI and the web UI share one real implementation, not two.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from repo_paths import REPO_ROOT, SCRIPTS_DIR

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO = REPO_ROOT
sys.path.insert(0, str(SCRIPTS_DIR))

from study_bot import BLOCKED_SENTINEL, load_state, save_state  # noqa: E402
from brief_signals import augment_meta_from_brief, extract_requirements_from_brief_text  # noqa: E402

_DATE_FORMATS = ("%d %B %Y", "%B %d, %Y", "%B %d %Y", "%Y-%m-%d")
_PATENT_TOKEN = re.compile(r"\b([A-Z]{2}\d[\dA-Z]{4,})\b")
_INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*]')


class AddStudyError(Exception):
    pass


def _slugify(text: str) -> str:
    text = re.sub(r"\s+", "_", text.strip())
    text = _INVALID_FOLDER_CHARS.sub("", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "Study"


def _find_label_value(text: str, *labels: str) -> str | None:
    """Find a label on its own line, return the next non-empty line after it."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip().lower()
        if any(stripped == label.lower() or stripped.startswith(label.lower()) for label in labels):
            for nxt in lines[i + 1 :]:
                nxt = nxt.strip()
                if nxt:
                    return nxt
    return None


def _extract_patent(text: str) -> str | None:
    value = _find_label_value(text, "Study Patents", "Study Patent")
    if value:
        m = _PATENT_TOKEN.search(value.upper())
        if m:
            return m.group(1)
    m = _PATENT_TOKEN.search(text.upper())
    return m.group(1) if m else None


def _parse_date(raw: str) -> str | None:
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    m = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
    return m.group(1) if m else None


def _extract_critical_date(text: str) -> str | None:
    value = _find_label_value(text, "Latest Date for Responses")
    return _parse_date(value) if value else None


def _extract_expiration_date(text: str) -> str | None:
    value = _find_label_value(text, "Expiration Date")
    return _parse_date(value) if value else None


def _extract_title(text: str, study_id: str) -> str:
    value = _find_label_value(text, "Study ID")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        if line == study_id or (value and line == value):
            continue
        if line.lower() in (
            "category", "research type", "expiration date", "rewards available",
            "study patents", "description", "leads", "research requirements",
        ):
            continue
        if 4 <= len(line) <= 120:
            return line
    return f"Study {study_id}"


def _summarize_citations_csv(csv_text: str) -> tuple[int, dict[str, int]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    total = 0
    counts: dict[str, int] = {}
    for row in reader:
        total += 1
        rel = (row.get("Relation") or "unknown").strip()
        counts[rel] = counts.get(rel, 0) + 1
    return total, counts


def add_study(
    study_id: str,
    brief_text: str,
    citations_csv_text: str | None = None,
    title: str | None = None,
) -> dict:
    """Scaffold a new study folder, wire it into bot_state.json, return a summary.

    This is the single real implementation — both the CLI and the web app's
    Add Study form call this, so there is exactly one way a study gets
    onboarded, not a script version and a separate UI version.
    """
    state = load_state()
    if study_id in state.get("studies", {}):
        raise AddStudyError(f"Study {study_id} already exists in bot_state.json")

    is_patent = bool(citations_csv_text and citations_csv_text.strip())
    resolved_title = title or _extract_title(brief_text, study_id)
    folder_name = f"{study_id}_{_slugify(resolved_title)}"
    folder = REPO / folder_name
    if folder.exists():
        raise AddStudyError(f"Folder already exists: {folder_name}")

    patent = _extract_patent(brief_text) if is_patent else None
    critical_date = _extract_critical_date(brief_text) if is_patent else None
    expiration_date = _extract_expiration_date(brief_text)

    warnings: list[str] = []
    blocked = False
    if is_patent and not patent:
        warnings.append("Could not confidently extract a study patent number — review STUDY_BRIEF.md")
        blocked = True
    if is_patent and not critical_date:
        warnings.append("Could not confidently extract a critical date — review STUDY_BRIEF.md")
        blocked = True

    today = datetime.now().strftime("%Y-%m-%d")

    # --- folder structure ---
    (folder / "candidates").mkdir(parents=True, exist_ok=True)
    (folder / "candidates" / ".gitkeep").touch()
    (folder / "submitted").mkdir(parents=True, exist_ok=True)
    (folder / "submitted" / ".gitkeep").touch()
    if is_patent:
        (folder / "reference").mkdir(parents=True, exist_ok=True)
        (folder / "reference" / ".gitkeep").touch()
        (folder / "known_art").mkdir(parents=True, exist_ok=True)
        (folder / "known_art" / "known_citations.csv").write_text(citations_csv_text, encoding="utf-8")
        total, counts = _summarize_citations_csv(citations_csv_text)
        rel_lines = "\n".join(f"| {rel} | {n} |" for rel, n in sorted(counts.items(), key=lambda kv: -kv[1]))
        (folder / "known_art" / "KNOWN_CITATIONS.md").write_text(
            f"# {study_id} Known Citations Summary\n\n"
            f"Source file: `known_citations.csv`\n"
            f"Study patent: **{patent or 'unknown — see STUDY_BRIEF.md'}**\n\n"
            f"## Counts by relation\n\n"
            f"| Relation | Count |\n|----------|-------|\n{rel_lines}\n"
            f"| **Total rows** | **{total}** |\n\n"
            f"All rows above are burned — do not resubmit. Run every candidate through "
            f"`scripts/check_burned.py {study_id} <pub>` before surfacing.\n",
            encoding="utf-8",
        )
    else:
        (folder / "sources").mkdir(parents=True, exist_ok=True)
        (folder / "sources" / ".gitkeep").touch()

    brief_header = (
        f"# {study_id} {resolved_title}\n\n"
        f"Status: {'BLOCKED — ' + BLOCKED_SENTINEL if blocked else 'active'}\n"
        f"Type: {'Patent / invalidity' if is_patent else 'Copyright / other research'}\n"
    )
    if patent:
        brief_header += f"Study patent: {patent}\n"
    if critical_date:
        brief_header += f"Critical date: {critical_date}\n"
    if expiration_date:
        brief_header += f"Expiration date: {expiration_date}\n"
    if warnings:
        brief_header += "\n## Needs review\n\n" + "\n".join(f"- {w}" for w in warnings) + "\n"
    brief_header += "\n## Raw RWS brief (as pasted)\n\n"

    (folder / "STUDY_BRIEF.md").write_text(brief_header + brief_text.strip() + "\n", encoding="utf-8")

    (folder / "CANDIDATE_SCREEN.md").write_text(
        f"# Candidate Screen — updated {today}\n\n"
        f"Inspected: 0 · READY: 0 · HOLD: 0\n\n"
        f"## READY (Self-rank ≥2, high/med)\n\n- (none this round)\n\n"
        f"## HOLD (rank 1 — verify before surfacing)\n\n- (none)\n",
        encoding="utf-8",
    )

    if is_patent:
        (folder / "HUNT_LOG.md").write_text(
            f"# {study_id} Hunt Log\n\n"
            "Bot updates this after each hunt round. Angela can ignore unless auditing coverage.\n\n"
            "| Date | Lanes completed | Docs inspected | Candidates surfaced | Next lane |\n"
            "|------|-----------------|----------------|---------------------|-----------|\n"
            "| — | — | — | — | L1 |\n\n"
            "## Lane checklist (7 lanes)\n\n"
            "- [ ] L1 Study patent citation backward 2-hop\n"
            f"- [ ] L2 Study patent cited-by ≤ {critical_date or 'unknown'}\n"
            "- [ ] L3 Assignee/inventor sweep\n"
            "- [ ] L4 Synonym lattice\n"
            "- [ ] L5 NPL adjacent\n"
            f"- [ ] L6 PTAB/IPR exhibits {patent or ''}\n"
            "- [ ] L7 Wayback/product literature\n",
            encoding="utf-8",
        )

    extracted_requirements = extract_requirements_from_brief_text(brief_text)
    meta_json = {
        "title": resolved_title,
        "type": "patent" if is_patent else "copyright",
        "patent": patent,
        "critical_date": critical_date,
        "focus": "" if blocked else f"See STUDY_BRIEF.md — Research Requirements",
        "keywords": [],
        "requirements": extracted_requirements,
        "priority_req_ids": [req["id"] for req in extracted_requirements],
        "synonym_queries": [],
        "cpc_queries": [],
        "npl_queries": [],
        "assignees": [],
    }
    meta_json = augment_meta_from_brief(meta_json, folder / "STUDY_BRIEF.md")
    (folder / "STUDY_META.json").write_text(json.dumps(meta_json, indent=2) + "\n", encoding="utf-8")

    # --- wire into bot_state.json ---
    state["queue"].append(study_id)
    state["studies"][study_id] = {
        "folder": folder_name,
        "status": "blocked" if blocked else "queued",
        "rounds_completed": 0,
        "candidates_found": 0,
        "submissions_made": 0,
        "lanes_complete": [],
    }
    save_state(state)

    return {
        "study_id": study_id,
        "folder": folder_name,
        "type": meta_json["type"],
        "patent": patent,
        "critical_date": critical_date,
        "expiration_date": expiration_date,
        "blocked": blocked,
        "warnings": warnings,
    }


def _read_source_folder(source: Path) -> tuple[str, str | None]:
    csv_text = None
    for csv_path in sorted(source.glob("*.csv")):
        csv_text = csv_path.read_text(encoding="utf-8-sig")
        break

    txt_parts = []
    for txt_path in sorted(source.glob("*.txt")):
        txt_parts.append(txt_path.read_text(encoding="utf-8", errors="replace"))
    brief_text = "\n\n".join(txt_parts)

    if not brief_text and not csv_text:
        raise AddStudyError(f"No .txt or .csv files found in {source}")
    return brief_text, csv_text


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python scripts/add_study.py <study_id> <source_folder> [--title \"...\"]")
        raise SystemExit(1)

    study_id = sys.argv[1]
    source = Path(sys.argv[2])
    title = None
    if "--title" in sys.argv:
        title = sys.argv[sys.argv.index("--title") + 1]

    if not source.exists():
        raise SystemExit(f"Source folder not found: {source}")

    brief_text, csv_text = _read_source_folder(source)

    try:
        result = add_study(study_id, brief_text, csv_text, title=title)
    except AddStudyError as exc:
        raise SystemExit(f"Failed: {exc}") from None

    print(f"Added study {result['study_id']} -> {result['folder']} ({result['type']})")
    if result["patent"]:
        print(f"  Patent: {result['patent']}  Critical date: {result['critical_date'] or 'unknown'}")
    if result["expiration_date"]:
        print(f"  Expiration date: {result['expiration_date']}")
    if result["blocked"]:
        print("  BLOCKED — needs review:")
        for w in result["warnings"]:
            print(f"    - {w}")
    print("  Seeded metadata from the brief — review STUDY_META.json for study-specific cleanup.")
    print(f"\nRun: python scripts/study_bot.py status")


if __name__ == "__main__":
    main()
