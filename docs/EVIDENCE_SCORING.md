# Evidence Scoring

## Purpose

Evidence scoring is deterministic and diagnostic. It helps explain why a result
is strong or weak. It does **not** replace hard gates.

Score alone cannot make a record `PROOF` or READY.

## Positive factors

- `exact_requirement_language`: `+30`
- `verified_precritical_date`: `+20`
- `primary_technical_source`: `+15`
- `downloadable_original_pdf`: `+10`
- `exact_model_or_part_number`: `+10`
- `independent_corroboration`: `+5`

## Penalties

- `inferred_relationship`: `-20`
- `uncertain_date`: `-25`
- `known_family_duplicate`: hard reject

Keyword count is recorded only as diagnostic context. It is not a major
positive factor and does not control READY promotion.

## Hard gates

A record cannot be READY if any of these apply:

- post-critical date
- date cannot be verified sufficiently
- known-art match
- known-family duplicate
- no explicit requirement support
- no accessible source document
- no verbatim highlight
- no requirement mapping
- evidence tier is not `PROOF`

The existing READY policy still applies:

- `Self-rank >= 2`
- confidence is `high` or `med`

Final READY decision:

`existing READY policy` AND `evidence tier == PROOF` AND `no hard-gate failures`

## Proof bundles

READY proof bundles now include:

- evidence record
- evidence tier
- evidence score
- score breakdown
- hard-gate failures
- query-plan provenance
- normalization results

Human review is still required before any submission step.
