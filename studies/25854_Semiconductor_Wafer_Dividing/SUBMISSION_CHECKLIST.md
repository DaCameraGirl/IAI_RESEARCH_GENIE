# 25854 Submission Checklist

Use this before every portal submission.

## Pre-submit gate

- [ ] Document date is on or before **2009-02-25** (preferred) or at worst
      **2010-02-04**
- [ ] Publication number / title / DOI not in `known_art/known_citations.csv`
- [ ] Free downloadable PDF confirmed (patent PDF from Google Patents / Espacenet
      counts; no paywall for NPL)
- [ ] Candidate is **not** the study patent US8728916 or a listed family member

## Requirement mapping (check all that apply)

| Req | Must show in highlight |
|-----|------------------------|
| 1.1 | Pulsed laser focused **inside** sapphire (or equivalent) substrate; **isolated processed portions** along intended dividing line parallel to main face |
| 1.2 | **Fissure** from processed portions to substrate **surface**; **links adjacent** processed portions along dividing line |
| 1.3 | **Wafer divided** along intended dividing line after irradiation |

Current RWS lead priority: **1.2 first**, then 1.1 + 1.3 support.

## Highlight quality

- [ ] Quote is verbatim in the attached PDF (Ctrl+F passes)
- [ ] One sentence per requirement, two max
- [ ] Contains a technical anchor: processed portions, fissure, sapphire,
      pulsed laser, dividing line, compression stress, multiphoton absorption,
      etc.
- [ ] Not a generic background paragraph with no RR mapping

## Portal fields

```
Novelty:        likely-new | likely-duplicate
Type:           Patent or NPL (Article / Other per portal)
Document date:  YYYY-MM-DD
Critical date:  2009-02-25 preferred
Date OK?        yes / no

Select requirements:
  1.1 — <one-line why>
  1.2 — <one-line why>
  1.3 — <one-line why>

Ctrl+F phrases:
  - "<verbatim>"
  - "<verbatim>"

Highlights:
  1.1 → "<verbatim>"
  1.2 → "<verbatim>"
  1.3 → "<verbatim>"

Do NOT select:
  <requirement> — <why weak>
```

## After submit

1. Copy final PDF to `submitted/`
2. Log entry in `CANDIDATE_SCREEN.md` with publication number, date, reqs
   selected, and portal outcome when known
3. Propose `_DASHBOARD.md` update