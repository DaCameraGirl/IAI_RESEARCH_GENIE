#!/usr/bin/env python3
"""
One-at-a-time study bot runner for RWS_RESEARCHER.

Usage:
  python scripts/study_bot.py              # show current study + agent orders
  python scripts/study_bot.py status       # queue overview
  python scripts/study_bot.py advance      # finish current, move to next
  python scripts/study_bot.py goto 25974     # jump to a study (resets it active)
  python scripts/study_bot.py round-done     # increment hunt round on current study
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from repo_paths import REPO_ROOT
from brief_signals import augment_meta_from_brief

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO = REPO_ROOT
STATE_PATH = REPO / "bot_state.json"

# Written into STUDY_BRIEF.md by add_study.py when it couldn't confidently
# extract a patent number / critical date — marks the study BLOCKED until
# someone reviews and fills in the brief.
BLOCKED_SENTINEL = "NEEDS_BRIEF_REVIEW"

STUDY_META_FILENAME = "STUDY_META.json"

_META_DEFAULTS = {
    "title": "",
    "patent": "N/A (copyright research)",
    "critical_date": "N/A",
    "focus": "",
    "type": "patent",
    "language": None,
    "language_code": None,
    "keywords": [],
    "requirements": [],
    "priority_req_ids": [],
    "synonym_queries": [],
    "cpc_queries": [],
    "npl_queries": [],
    "assignees": [],
}


def load_state() -> dict:
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def current_id(state: dict) -> str:
    return state["current_study"]


def study_folder(study_id: str, state: dict | None = None) -> Path:
    state = state or load_state()
    folder_name = state["studies"][study_id]["folder"]
    return REPO / folder_name


def _build_study_meta(study_id: str) -> dict:
    state = load_state()
    if study_id not in state.get("studies", {}):
        raise KeyError(study_id)
    folder_name = state["studies"][study_id]["folder"]
    folder = REPO / folder_name
    meta_path = folder / STUDY_META_FILENAME
    data = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    meta = dict(_META_DEFAULTS)
    meta.update(data)
    meta["folder"] = folder_name
    meta = augment_meta_from_brief(meta, folder / "STUDY_BRIEF.md")
    meta["priority_req_ids"] = tuple(meta["priority_req_ids"])
    if not meta["title"]:
        meta["title"] = study_id
    return meta


class _StudyMetaRegistry(Mapping):
    """Lazily builds per-study metadata from <folder>/STUDY_META.json.

    Behaves like the plain dict this used to be (indexing, .get(), iteration)
    so every existing call site (STUDY_META[sid], STUDY_META.get(sid, ...),
    STUDY_META.items()) keeps working without changes.
    """

    def __getitem__(self, study_id: str) -> dict:
        try:
            return _build_study_meta(study_id)
        except KeyError:
            raise KeyError(study_id) from None

    def __iter__(self):
        return iter(load_state().get("studies", {}))

    def __len__(self) -> int:
        return len(load_state().get("studies", {}))


STUDY_META = _StudyMetaRegistry()


def is_blocked(study_id: str) -> bool:
    state = load_state()
    if study_id not in state.get("studies", {}):
        return True
    folder = study_folder(study_id, state)
    brief = folder / "STUDY_BRIEF.md"
    if not brief.exists():
        return True
    return BLOCKED_SENTINEL in brief.read_text(encoding="utf-8")


def agent_orders(study_id: str) -> str:
    meta = STUDY_META[study_id]
    folder = REPO / meta["folder"]
    is_patent_study = (folder / "known_art").exists()

    if is_patent_study:
        steps = f"""1. Read: {folder / 'STUDY_BRIEF.md'}
2. Read: {folder / 'known_art' / 'known_citations.csv'}
3. Read: templates/RWS_SUBMISSION_PLAYBOOK.md + templates/examples/INDEX.md
4. Run ZERO_MISS_PROTOCOL.md — all 7 lanes
5. Log: {folder / 'HUNT_LOG.md'} and {folder / 'CANDIDATE_SCREEN.md'}
6. Write READY candidates to {folder / 'candidates'}/*_RWS_format.txt
7. Burn-check: python scripts/check_burned.py {study_id} <pub>"""
    else:
        steps = f"""1. Read: {folder / 'STUDY_BRIEF.md'}
2. Read: templates/RWS_SUBMISSION_PLAYBOOK.md + templates/examples/INDEX.md
3. Log: {folder / 'CANDIDATE_SCREEN.md'}
4. Write READY candidates to {folder / 'candidates'}/*_RWS_format.txt
5. Do not submit machine/AI-translated hymns — verified existing translations only"""

    return f"""
╔══════════════════════════════════════════════════════════════╗
║  ACTIVE STUDY: {study_id} — {meta['title']:<33} ║
╚══════════════════════════════════════════════════════════════╝

WORK ONLY THIS STUDY. Do not hunt other studies until advance.

{steps}

Study patent: {meta['patent']}
Critical date: {meta['critical_date']}
RWS focus: {meta['focus']}

AGENT COMMAND: hunt {study_id} deep

When this round is done, Angela runs:
  python scripts/study_bot.py round-done
  python scripts/study_bot.py advance
""".strip()


def cmd_status(state: dict) -> None:
    cur = current_id(state)
    print("RWS Study Bot — one at a time\n")
    for sid in state["queue"]:
        meta = STUDY_META[sid]
        st = state["studies"][sid]
        marker = ">>>" if sid == cur else "   "
        blocked = is_blocked(sid)
        status = "BLOCKED" if blocked else st.get("status", "queued")
        print(f"{marker} {sid}  {meta['title']}")
        print(f"      status={status}  rounds={st.get('rounds_completed', 0)}  "
              f"candidates={st.get('candidates_found', 0)}")
        if blocked:
            print(f"      ⚠ paste RWS brief into {meta['folder']}/STUDY_BRIEF.md")
    print(f"\nCurrent: {cur}")


def cmd_start(state: dict) -> None:
    sid = current_id(state)
    if is_blocked(sid):
        print(f"Study {sid} is BLOCKED.")
        print(STUDY_META[sid]["focus"])
        print("\nFix the blocker, then: python scripts/study_bot.py advance")
        return
    state["studies"][sid]["status"] = "active"
    save_state(state)
    print(agent_orders(sid))


def cmd_round_done(state: dict) -> None:
    sid = current_id(state)
    state["studies"][sid]["rounds_completed"] = state["studies"][sid].get("rounds_completed", 0) + 1
    save_state(state)
    print(f"Recorded hunt round complete for {sid} (round {state['studies'][sid]['rounds_completed']})")


def cmd_advance(state: dict) -> None:
    queue = state["queue"]
    cur = current_id(state)
    state["studies"][cur]["status"] = "done"

    idx = queue.index(cur)
    for nxt in queue[idx + 1 :]:
        if is_blocked(nxt):
            state["current_study"] = nxt
            state["studies"][nxt]["status"] = "blocked"
            save_state(state)
            print(f"Finished {cur}. Next is {nxt} but BLOCKED — paste brief first.")
            return
        state["current_study"] = nxt
        state["studies"][nxt]["status"] = "active"
        save_state(state)
        print(f"Finished {cur}. Now active: {nxt}\n")
        print(agent_orders(nxt))
        return

    save_state(state)
    print(f"All studies in queue complete. Last finished: {cur}")


def cmd_goto(state: dict, study_id: str) -> None:
    if study_id not in STUDY_META:
        raise SystemExit(f"Unknown study {study_id}")
    for sid in state["queue"]:
        if sid != study_id and state["studies"][sid].get("status") == "active":
            state["studies"][sid]["status"] = "paused"
    state["current_study"] = study_id
    if is_blocked(study_id):
        state["studies"][study_id]["status"] = "blocked"
    else:
        state["studies"][study_id]["status"] = "active"
    save_state(state)
    cmd_start(state)


def main() -> None:
    if not STATE_PATH.exists():
        raise SystemExit("Missing bot_state.json")

    state = load_state()
    args = sys.argv[1:]

    if not args or args[0] == "start":
        cmd_start(state)
    elif args[0] == "status":
        cmd_status(state)
    elif args[0] == "advance":
        cmd_advance(state)
    elif args[0] == "round-done":
        cmd_round_done(state)
    elif args[0] == "goto" and len(args) >= 2:
        cmd_goto(state, args[1])
    else:
        print(__doc__)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
