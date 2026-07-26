# IAI Research Bot

Specialized prior-art, NPL, product-evidence, and copyright research assistant.
RWS is the current primary workflow, but the repo is structured as a reusable
research operations system rather than an official RWS tool.


Angela's project section for **RWS IP Research NPL submission work**.
This is the canonical folder — all RWS-related agent prompts, study
working files, and outputs live here.

## What this project does

Angela contributes to RWS IP Research as an NPL (Non-Patent Literature)
hunter. She finds journal articles, datasheets, brochures, press releases,
and other dated documents that count as prior art for active RWS
CrowdSearch / CrowdSearch Plus studies, then submits them through the
RWS portal for scoring (Accepted/Declined, New/Duplicate, rank 0–3,
Acceptable/Unacceptable).

`system_prompt.md` contains the tuned agent system prompt that runs the
research workflow — drop it into Claude Code, Claude.ai Projects, a
Custom GPT, or any other LLM tool to spin up the RWS Researcher agent.

## Research framework

This repo now includes a reusable evidence framework layered under the
existing RWS workflow.

- **Evidence tiers**: every result is classified as exactly one of `LEAD`,
  `CANDIDATE`, or `PROOF`.
- **Lane architecture**: reusable lane definitions live under `scripts/lanes/`
  and are activated by study profiles from `config/study_profiles.json`.
- **Study profiles**: lane selection varies by study type instead of running
  every lane for every study.
- **Evidence scoring**: deterministic scoring lives in
  `config/evidence_scoring.json` and `scripts/evidence_scoring.py`.
- **Hard gates**: score does not override hard failures.
- **READY policy**: canonical rank/confidence gating still applies on top of
  evidence gating.

### Evidence tiers

- `LEAD`: useful for finding a better source, not submission-ready.
- `CANDIDATE`: potentially usable evidence still missing one or more proof
  requirements.
- `PROOF`: auditable evidence with a stable proof bundle and no hard-gate
  failures. Human review is still required before submission.

### Hard gates

READY requires all of the following:

- existing READY policy passes (`Self-rank >= 2`, confidence `high|med`)
- evidence tier is `PROOF`
- pre-critical date is sufficiently verified
- no known-art match
- no known-family duplicate
- explicit requirement support
- accessible source document
- verbatim highlight
- requirement mapping

### Lane framework

Currently connected:

- patent evidence conversion in `scripts/patent_hunter.py`
- lane lookup from existing patent source labels
- proof bundles enriched with evidence records, score breakdowns, hard gates,
  query provenance, and normalization results

Framework implemented for future lane expansion:

- evidence schema
- lane registry and lane-result contract
- study profiles
- patent/entity/title normalizers
- ranked query-matrix planner
- deterministic evidence scoring

This system is research assistance for human review. It does **not** perform
automatic RWS submissions, login automation, or platform scraping.

## Folder layout

```
RWS_RESEARCHER/
  system_prompt.md                       ← the agent's brain (paste into tool)
  README.md                              ← this file
  outputs/                               ← agent findings, hunt logs, candidate lists
  templates/                             ← Angela's proven RWS submission playbook + blanks
  templates/RWS_SUBMISSION_PLAYBOOK.md   ← bot reads this before every submission
  25657_IC_CHIP_CANDIDATES_READY/25657_READY_RWS_FORMAT_ONLY/  ← gold examples
  25657_Integrated_Circuit_Chips/
    known_art/                           ← PDFs RWS has provided (do NOT submit)
    candidates/                          ← PDFs we found and are evaluating
    reference/                           ← supporting docs (revision histories, etc.)
    submitted/                           ← PDFs we actually submitted
  25696_Battery_Module/
    (same subfolder structure when active)
```

## RWS Research Bot (local web app)

Double-click the desktop shortcut **RWS Research Bot** (Research Genie icon).

- Starts at http://127.0.0.1:7842
- **Run Deep Hunt** — 8 lanes, up to 300 patents, strict burn gate
- **Candidates** — READY/HOLD drafts with PDF URLs and req tables
- **Burn check** — verify a publication against `known_citations.csv`

```powershell
# First-time setup
pip install -r requirements.txt
python scripts\build_genie_icon.py
powershell -File scripts\create-desktop-bot-launcher.ps1
```

Or run: `.\RUN_BOT.ps1`

## How to use the agent

1. Open whichever tool you're spinning the agent up in (Claude Code /
   Claude.ai Project / Custom GPT / etc.).
2. Paste the entire contents of `system_prompt.md` into the system /
   custom-instructions slot.
3. Start a conversation by either:
   - Pasting a candidate document or DOI ("evaluate this for 25657")
   - Asking for a hunt ("find PN511 mentions on Wayback from 2003")
   - Pasting a new study brief ("here's the 25696 brief, ingest it")

## Active studies (as of 2026-07-07)

- **26052 — Rechargeable Blender With Offset Blades** (invalidity, $7,000,
  deadline 2026-08-04). Study patent US11229891. Critical date 2019-10-28.
  Focus: RR1.1-1.3 — blade rotational axis offset 5-15% of blade diameter
  from the container's longitudinal axis. Folder:
  `26052_Rechargeable_Blender_Offset_Blades/`.
- **25974 — Oximidol (Tyrosinase Inhibitor)** (invalidity, deadline
  2026-07-15). Study patent WO2025201324. Critical date 2024-03-26. Focus:
  RR1/RR2 exact Oximidol molecule; RR3 Oximidol (or broader
  alkylamidothiazoles per 2026-06-24 lead) combined with Isopropyl Lauroyl
  Sarcosinate, priority before 2023-08-18. Folder: `25974_Oximidol/`.
- **26005 / 26006 / 26016 — Hymn Research (Cebuano / Russian / Italian)**
  (copyright research, deadline 2026-07-28 / 2026-07-30 / 2026-07-30).
  Find existing (not machine-translated) hymn translations per
  `HymnResearch_English.zip`. Folders: `26005_Hymn_Research_Cebuano/`,
  `26006_Hymn_Research_Russian/`, `26016_Hymn_Research_Italian/`.

## Closed / historical studies

- 25867 Remote Memory Transactions, 25854 Semiconductor Wafer Dividing,
  25853 Light Emitting Device Resin Package, 25657 Integrated Circuit Chips,
  25696 Battery Module, 25803 Hymn Research - Malagasy.
- 25671 Inhalers (Final Review), 25576 Smoking System (Final Review),
  25429 Wireless Devices (Completed). Submission windows over.

## Key learnings baked into the prompt

- **Skip weak matches** — rank-0 Declines hurt more than missing
  submissions help.
- **Free downloadable PDFs only** — no paywalls. Filter through
  Unpaywall before reading.
- **Verbatim highlights only** — never paraphrase. Highlight must
  contain a specific technical anchor (part number, named device,
  measured value, named person, dated event).
- **Invalidity studies need different sources than research-paper NPL
  studies** — PubMed is useless for invalidity; Wayback Machine, FCC
  OET, USPTO PTAB, and USENET archives are the goldmines.

See `system_prompt.md` for the full ruleset.
