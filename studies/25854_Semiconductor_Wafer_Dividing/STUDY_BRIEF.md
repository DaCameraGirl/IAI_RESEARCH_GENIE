# 25854 Semiconductor Wafer Dividing

Status: active
Category: Chemical Engineering, Electrical Engineering, Electronics Technology,
Engineering Physics, General Chemistry, Materials Science & Engineering,
Semiconductor Technology
Study type: Prior art search (patent + non-patent literature)
Study patent: US8728916B2
Assignee: Nichia Corp
CPC class: B23K
Lead added: 2026-06-16

## Current focus (RWS lead, week of 2026-06-16)

Focus on **Research Requirement 1.2**: a fissure (13) is created. The fissure
is created by the irradiating step (RR 1.1) and extends along the line of the
processed portions (12). Dividing the wafer (RR 1.3) is done along this
created fissure.

## Critical dates

| Field | Date |
|-------|------|
| Latest date for responses | 2010-02-04 |
| Preferred latest date | 2009-02-25 |
| Study patent priority | 2009-02-25 |
| Study patent US grant | 2014-05-20 |

Documents must be dated on or before the relevant critical date to qualify.

## Problem statement

Semiconductor element manufacture includes dividing a wafer into element chips.
Laser separation grooves can discolor re-solidified melt zones and reduce
brightness of light-emitting elements. Short-pulse-width pulsed lasers avoid
discoloration via modification regions, but cracks along dividing lines can
be hard to control when force is applied.

This study seeks prior art for a method that uses **processed portions** and a
**fissure** linking adjacent processed portions and running from those portions
to the substrate surface.

## Research requirements

To satisfy, complete **3 priority** requirements:

### 1.1 Laser irradiation — processed portions

A laser irradiation step of focusing a pulsed laser beam inside of a **sapphire
substrate** constituting a wafer, thereby forming a plurality of **isolated
processed portions** inside of the substrate along an intended dividing line
extending in a direction **parallel to a main face** of the substrate.

### 1.2 Fissure creation (CURRENT FOCUS)

Creating a **fissure** that runs from the processed portions at least to the
**main face** of the substrate and **links adjacent processed portions**
aligned along the direction parallel to the main face of the substrate.

Key mechanism (study patent): processed portions form near focal positions;
compression stress around those locations is believed to create the fissure.
Control parameters include pulsed laser means, energy, frequency, pulse width,
spot diameter/shape, depth from substrate/semiconductor layer, and spacing.

### 1.3 Wafer division

A wafer division step of dividing the wafer along the intended dividing line
after the laser irradiation step. Division may use a breaking knife or other
known method. A crack (15) may run from processed portions or fissure to the
first main face (10a) side.

## Figure anchors

- **Fig. 2 / Fig. 3 (A-A):** processed portions 12 inside substrate 10;
  semiconductor layer 14 on first main face 10a; fissure 13 from processed
  portions 12 to second main face 10b; fissure links adjacent portions along
  intended dividing line.
- **Fig. 6:** crack 15 from processed portions 12 or fissure 13 toward first
  main face 10a; wafer divided along intended dividing line.

## Substrate / wafer notes

- "Wafer" = flat base sliced from ingot, optionally with laminated layers
  (semiconductor, dielectric, insulator, conductor).
- Substrate materials: sapphire (preferred), silicon, SiC, GaAs, GaN, AlN.

## Submission rules

- Cross-check every candidate against `known_art/known_citations.csv` before
  surfacing. Patents, family members, citations, and Study NPL listed there
  are burned.
- Highlights must be verbatim Ctrl+F-able passages from the PDF.
- One short highlight per requirement; anchor on processed portions, fissure,
  sapphire substrate, pulsed laser inside substrate, linking adjacent portions,
  wafer division along dividing line.
- Skip weak topical matches (generic laser dicing without fissure linking
  adjacent internal processed portions).

## First search lanes

1. **Direct citations** in `known_art/known_citations.csv` with Relation =
   `Citation` (not yet expanded to all family members): US6184544, US6335545,
   JP2000174347, JP2001036154, JP2006140207, JP2006313943, JP2007035794,
   JP2007123302, JP2007235085, JP2008106226, WO06126438A1, WO07135707A1,
   WO08059856A1, and related US/JP pre-2009 laser-internal-modification /
   sapphire wafer dicing art.
2. **Google Patents** backward/forward citation crawl from US8728916; filter
   date <= 2009-02-25.
3. **Japanese prior art** — Nichia/sapphire LED wafer laser processing:
   JP2008-098465, JP2007-324326 (cited in study patent background).
4. **Conference / journal NPL** on laser stealth dicing, internal laser
   modification, stress-induced cracking, sapphire substrate separation.
5. **Wayback / manufacturer literature** — laser dicing equipment brochures
   (DISCO, Hamamatsu, etc.) describing internal modification + surface crack
   propagation before 2009.

## Known art location

- CSV: `known_art/known_citations.csv`
- Summary: `known_art/KNOWN_CITATIONS.md`
- Study patent PDF: download from Google Patents if needed into `known_art/`

## Folder layout

```
25854_Semiconductor_Wafer_Dividing/
  STUDY_BRIEF.md
  SUBMISSION_CHECKLIST.md
  CANDIDATE_SCREEN.md
  known_art/
  candidates/
  reference/
  submitted/
```