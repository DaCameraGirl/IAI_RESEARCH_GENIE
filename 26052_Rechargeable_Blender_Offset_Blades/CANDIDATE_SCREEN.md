# Candidate Screen - updated 2026-07-22 16:05

Inspected: manual patent review pass
READY this run: 0
HOLD this run: 4
UI library still shows 2 LEAD because the app only surfaced the old NPL files; use this screen and the hold memo for human review.

## READY (Self-rank >=2, high/med)

- (none)

## HOLD (rank 1 - verify before surfacing)

- `US20050207270A1 / US7217028B2` - Off-axis goblet for food mixer
  Why it matters: explicit non-collinear / offset relationship between the container longitudinal axis and the mixing-axis, plus usable vortex / turbulence rationale.
  Main gap: no explicit 5%-15% offset-to-blade-diameter ratio; not a handheld portable blender.
  URL: https://patents.google.com/patent/US20050207270

- `US20070297281A1 / US7766540B2` - Kitchen blender
  Why it matters: explicit statement that the tool shaft is offset from the pitcher central vertical axis, with vortex / improved blending rationale.
  Main gap: no explicit numeric ratio; top-driven architecture.
  URL: https://patents.google.com/patent/US20070297281A1/en

- `CA2450764A1` - Container for a blender
  Why it matters: displaced blade assembly and strong anti-air-pocket / better-mixing rationale.
  Main gap: no explicit 5%-15% blade-diameter ratio and not clearly handheld.
  URL: https://patents.google.com/patent/CA2450764A1/en

- `CN206565828U / CN206565826U` family
  Why it matters: pre-critical household food-processor art with explicit eccentric distance `L2` from cutter axis to cup-body axis and explicit swirling / crushing rationale.
  Main gap: not handheld portable blender and no explicit conversion of `L2` to blade-diameter percentage.
  URLs:
  - https://patents.google.com/patent/CN206565828U/en
  - https://patents.google.com/patent/CN206565826U/en

## Do Not Surface

- `NPL_blender_offset_blade_vortex_mixing_produ_RWS_format`
  False positive for `26052`. Industrial granular / helical ribbon blender paper, not handheld domestic upright blender prior art.

- `NPL_food_processor_eccentric_rotor_design_ma_RWS_format`
  False positive for `26052`. Crossref mismatch to `Nutrition Today`; not a blender offset-axis reference.

## Review Note

- Best current manual review file: `candidates/HOLD_2026-07-22_best_offset_refs.md`
- No reference in this pass cleanly satisfies `RR1.1 + RR1.2 + RR1.3`
- Do not submit the two NPL leads in their current form
