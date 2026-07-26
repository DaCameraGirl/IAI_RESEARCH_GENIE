#!/usr/bin/env python3
"""Registry of research lanes available to the bot."""

from __future__ import annotations

from evidence_schema import EvidenceType

from .base import CostClass, LaneDefinition, LaneProduce
from .patent_citations_prosecution import get_patent_citations_prosecution_lane


_LANES: dict[str, LaneDefinition] = {
    "L1_PATENT_FAMILIES": LaneDefinition(
        id="L1_PATENT_FAMILIES",
        name="Patent offices and family normalization",
        supported_study_types=("patent_invalidity", "product_evidence", "medical_device", "chemical_compound"),
        evidence_types=(EvidenceType.PATENT,),
        cost_class=CostClass.MEDIUM,
        default_enabled=True,
        produces=(LaneProduce.CANDIDATE, LaneProduce.PROOF),
        required_inputs=("study_patent", "keywords"),
        dedupe_strategy="patent_family_key",
        date_rules="Use verified publication or priority dates from patent-office sources.",
        description="Patent offices, family members, classification-neighbor, and identity-normalized patent retrieval.",
    ),
    "L2_PATENT_CITATIONS_PROSECUTION": LaneDefinition(
        id="L2_PATENT_CITATIONS_PROSECUTION",
        name="Patent citations and prosecution",
        supported_study_types=("patent_invalidity", "medical_device", "chemical_compound"),
        evidence_types=(EvidenceType.PATENT, EvidenceType.PATENT_PROSECUTION),
        cost_class=CostClass.HIGH,
        default_enabled=True,
        produces=(LaneProduce.LEAD, LaneProduce.CANDIDATE, LaneProduce.PROOF),
        required_inputs=("study_patent", "critical_date"),
        dedupe_strategy="patent_family_key",
        date_rules="Search report and office-action dates are leads; cited documents need independent dating.",
        description="Backward/forward citations, examination history, IDS, and prosecution leads.",
    ),
    "L3_LITIGATION_PTAB": LaneDefinition(
        id="L3_LITIGATION_PTAB",
        name="Litigation, PTAB, and oppositions",
        supported_study_types=("patent_invalidity", "medical_device", "chemical_compound"),
        evidence_types=(EvidenceType.LITIGATION,),
        cost_class=CostClass.HIGH,
        default_enabled=True,
        produces=(LaneProduce.LEAD, LaneProduce.CANDIDATE),
        required_inputs=("study_patent",),
        dedupe_strategy="normalized_title",
        date_rules="Filing dates are leads only; underlying exhibits need separate verification.",
        description="PTAB petitions, invalidity filings, claim charts, and opposition materials as lead generators.",
    ),
    "L4_SCHOLARLY_NPL": LaneDefinition(
        id="L4_SCHOLARLY_NPL",
        name="Scholarly and adjacent NPL",
        supported_study_types=("patent_invalidity", "copyright_hymn", "software_artifact", "medical_device", "chemical_compound", "general_npl"),
        evidence_types=(EvidenceType.SCHOLARLY_NPL, EvidenceType.THESIS, EvidenceType.BOOK),
        cost_class=CostClass.MEDIUM,
        default_enabled=True,
        produces=(LaneProduce.LEAD, LaneProduce.CANDIDATE, LaneProduce.PROOF),
        required_inputs=("keywords",),
        dedupe_strategy="normalized_title",
        date_rules="Prefer native document dates and archived/open PDFs.",
        description="Scholarly NPL, theses, books, and citation-graph expansion.",
    ),
    "L5_STANDARDS_GOV_REGULATORY": LaneDefinition(
        id="L5_STANDARDS_GOV_REGULATORY",
        name="Standards, government, and regulatory",
        supported_study_types=("patent_invalidity", "product_evidence", "medical_device", "general_npl"),
        evidence_types=(EvidenceType.STANDARD, EvidenceType.GOVERNMENT_REPORT, EvidenceType.REGULATORY),
        cost_class=CostClass.HIGH,
        default_enabled=True,
        produces=(LaneProduce.LEAD, LaneProduce.CANDIDATE, LaneProduce.PROOF),
        required_inputs=("keywords", "critical_date"),
        dedupe_strategy="normalized_title",
        date_rules="Distinguish draft/filing/publication/amendment dates explicitly.",
        description="Standards drafts, technical reports, and regulatory/certification evidence.",
    ),
    "L6_PRODUCT_COMMERCIAL": LaneDefinition(
        id="L6_PRODUCT_COMMERCIAL",
        name="Product, manuals, distributors, and commercial evidence",
        supported_study_types=("patent_invalidity", "product_evidence", "medical_device"),
        evidence_types=(EvidenceType.PRODUCT_MANUAL, EvidenceType.DISTRIBUTOR, EvidenceType.PROCUREMENT, EvidenceType.TRADE_SHOW),
        cost_class=CostClass.MEDIUM,
        default_enabled=True,
        produces=(LaneProduce.LEAD, LaneProduce.CANDIDATE, LaneProduce.PROOF),
        required_inputs=("keywords", "assignees"),
        dedupe_strategy="model_or_part_number",
        date_rules="Commercial listings are leads unless backed by original technical documentation.",
        description="OEM manuals, support docs, distributor records, and procurement/commercial availability.",
    ),
    "L7_ARCHIVES_DOMAINS": LaneDefinition(
        id="L7_ARCHIVES_DOMAINS",
        name="Archives, domains, and historical web",
        supported_study_types=("patent_invalidity", "product_evidence", "copyright_hymn", "general_npl", "medical_device"),
        evidence_types=(EvidenceType.ARCHIVED_WEB, EvidenceType.NEWSWIRE, EvidenceType.CORPORATE_DISCLOSURE),
        cost_class=CostClass.MEDIUM,
        default_enabled=True,
        produces=(LaneProduce.LEAD, LaneProduce.CANDIDATE, LaneProduce.PROOF),
        required_inputs=("keywords", "critical_date"),
        dedupe_strategy="normalized_title",
        date_rules="Use pre-critical archive captures; archived landing pages may still be CANDIDATE, not PROOF.",
        description="Wayback/Memento-style archive discovery, domain expansion, and historical support pages.",
    ),
    "L8_SOFTWARE_DATA_COMMUNITY": LaneDefinition(
        id="L8_SOFTWARE_DATA_COMMUNITY",
        name="Software, data, and community evidence",
        supported_study_types=("software_artifact", "copyright_hymn", "general_npl"),
        evidence_types=(EvidenceType.SOFTWARE_ARTIFACT, EvidenceType.FORUM, EvidenceType.VIDEO),
        cost_class=CostClass.MEDIUM,
        default_enabled=True,
        produces=(LaneProduce.LEAD, LaneProduce.CANDIDATE, LaneProduce.PROOF),
        required_inputs=("keywords",),
        dedupe_strategy="normalized_title",
        date_rules="Prefer release artifacts and package registries over raw commit timestamps.",
        description="Software releases, data repositories, public forums, and community artifacts.",
    ),
    "L9_MULTILINGUAL_CLASSIFICATION_ENTITY": LaneDefinition(
        id="L9_MULTILINGUAL_CLASSIFICATION_ENTITY",
        name="Multilingual, classification, and identity expansion",
        supported_study_types=("patent_invalidity", "product_evidence", "copyright_hymn", "software_artifact", "medical_device", "chemical_compound", "general_npl"),
        evidence_types=(EvidenceType.OTHER,),
        cost_class=CostClass.LOW,
        default_enabled=True,
        produces=(LaneProduce.LEAD, LaneProduce.CANDIDATE),
        required_inputs=("keywords", "language"),
        dedupe_strategy="entity_key",
        date_rules="Expansion lane only; resulting documents still need independent dating.",
        description="Query expansion across languages, classifications, assignee aliases, and inventor variants.",
    ),
}


def list_lanes() -> list[LaneDefinition]:
    return list(_LANES.values())


def get_lane_definition(lane_id: str) -> LaneDefinition:
    return _LANES[lane_id]


def get_lane_runner(lane_id: str):
    if lane_id == "L2_PATENT_CITATIONS_PROSECUTION":
        return get_patent_citations_prosecution_lane()
    raise KeyError(f"No runner registered for lane {lane_id}")


def lane_for_source_label(source_lane: str) -> LaneDefinition:
    prefix = (source_lane or "").upper()
    if prefix.startswith("L1"):
        return _LANES["L1_PATENT_FAMILIES"]
    if prefix.startswith("L2"):
        return _LANES["L2_PATENT_CITATIONS_PROSECUTION"]
    if prefix.startswith("L3"):
        return _LANES["L3_LITIGATION_PTAB"]
    if prefix.startswith("L4"):
        return _LANES["L4_SCHOLARLY_NPL"]
    if prefix.startswith("L5"):
        return _LANES["L5_STANDARDS_GOV_REGULATORY"]
    if prefix.startswith("L6"):
        return _LANES["L6_PRODUCT_COMMERCIAL"]
    if prefix.startswith("L7"):
        return _LANES["L7_ARCHIVES_DOMAINS"]
    if prefix.startswith("L8"):
        return _LANES["L8_SOFTWARE_DATA_COMMUNITY"]
    return _LANES["L9_MULTILINGUAL_CLASSIFICATION_ENTITY"]
