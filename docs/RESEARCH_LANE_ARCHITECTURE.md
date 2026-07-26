# Research Lane Architecture

## Implemented framework

The repository now has a reusable lane framework for source-specific research
expansion without turning the hunt engine into one undifferentiated search.

Core pieces:

- `scripts/evidence_schema.py`
  Defines typed `EvidenceRecord` objects plus `LEAD`, `CANDIDATE`, and `PROOF`
  tiers.
- `scripts/lanes/base.py`
  Defines lane metadata and the lane-result contract.
- `scripts/lanes/registry.py`
  Registers the current lane architecture:
  `L1_PATENT_FAMILIES`,
  `L2_PATENT_CITATIONS_PROSECUTION`,
  `L3_LITIGATION_PTAB`,
  `L4_SCHOLARLY_NPL`,
  `L5_STANDARDS_GOV_REGULATORY`,
  `L6_PRODUCT_COMMERCIAL`,
  `L7_ARCHIVES_DOMAINS`,
  `L8_SOFTWARE_DATA_COMMUNITY`,
  `L9_MULTILINGUAL_CLASSIFICATION_ENTITY`.
- `scripts/study_profiles.py`
  Resolves which lanes are enabled for a study type.
- `scripts/query_matrix.py`
  Generates ranked query plans from requirement concept matrices.
- `scripts/normalizers/`
  Provides patent-family, entity, and title normalization helpers.

## Connected today

The current patent hunt pipeline is connected to the framework in a minimal,
backward-compatible way:

- existing patent hits are converted into `EvidenceRecord` objects
- lane IDs are assigned from current patent source labels
- evidence scoring and hard-gate evaluation run before READY classification
- READY proof bundles embed the evidence record and provenance metadata

This keeps current filenames and workflow behavior intact while making future
lane additions plug into a typed contract.

## Evidence tiers

- `LEAD`
  Lead-generation material. Useful, but not sufficient for submission.
- `CANDIDATE`
  Potentially useful evidence that is still missing one or more proof
  requirements.
- `PROOF`
  Auditable evidence with verified date, requirement mapping, verbatim support,
  accessible source document, and no hard-gate failures.

Only `PROOF` records may become READY, and even then only if the existing READY
rank/confidence policy also passes.

## Study profiles

Profiles prevent irrelevant lane activation.

Examples:

- `patent_invalidity`
  Enables patent-family, prosecution, litigation, NPL, product, archive, and
  multilingual/classification expansion.
- `copyright_hymn`
  Enables scholarly, archive, community, and multilingual lanes; disables
  patent-family and PTAB lanes by default.
- `medical_device`
  Prioritizes regulatory, patents, product manuals, NPL, and archives.

## Not implemented in this pass

This pass does **not** add all future source scrapers or search providers.

It implements the reusable framework that future lanes will plug into.
