#!/usr/bin/env python3
"""L2 lane: patent citations, prosecution, and PTAB lead discovery."""

from __future__ import annotations

import re
from typing import Any, Iterable

from evidence_schema import EvidenceRecord, EvidenceTier, EvidenceType
from evidence_scoring import classify_evidence_record, score_evidence
from normalizers.entities import normalize_entity_name, normalize_inventor_name
from normalizers.patent_family import normalize_publication_number
from normalizers.titles import normalize_title

from .base import LaneResult

_PATENT_PATTERN = re.compile(
    r"\b(?:US|EP|WO|CN|JP|KR|DE|GB|FR|CA|AU)\s*[-/]?\d[\d,\s/-]*[A-Z]?\d*\b",
    re.I,
)
_PTAB_PATTERN = re.compile(r"\b(?:IPR|PGR|CBM)\d{4}-\d{5}\b", re.I)
_NPL_SPLIT = re.compile(r"(?:^|\n)\s*(?:NPL|Non-Patent Literature|Non Patent Literature)\s*:\s*", re.I)


def _iso_date(raw: str) -> str:
    text = (raw or "").strip()
    match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if match:
        return match.group(1)
    match = re.search(r"(\d{4}-\d{2})", text)
    if match:
        return f"{match.group(1)}-01"
    match = re.search(r"(\d{4})", text)
    if match:
        return f"{match.group(1)}-01-01"
    return ""


def _looks_like_pdf(url: str) -> bool:
    return url.lower().endswith(".pdf")


def _coerce_mapping(mapping: Any) -> list[dict[str, Any]]:
    if not mapping:
        return []
    if isinstance(mapping, list):
        return [row for row in mapping if isinstance(row, dict)]
    return []


def _coerce_list(values: Any) -> list[str]:
    if not values:
        return []
    if isinstance(values, list):
        return [str(value).strip() for value in values if str(value).strip()]
    return [str(values).strip()]


def _normalize_known_art(known_art_set: Any) -> set[str]:
    if not known_art_set:
        return set()
    if isinstance(known_art_set, dict):
        values = known_art_set.keys()
    else:
        values = known_art_set
    normalized: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        patent_norm = normalize_publication_number(text)
        if patent_norm.normalized_publication:
            normalized.add(patent_norm.normalized_publication)
        normalized.add(normalize_title(text))
    return normalized


def _parse_patent_mentions(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for match in _PATENT_PATTERN.findall(text or ""):
        norm = normalize_publication_number(match)
        if not norm.normalized_publication or norm.normalized_publication in seen:
            continue
        seen.add(norm.normalized_publication)
        out.append(norm.normalized_publication)
    return out


def _extract_npl_references(text: str) -> list[dict[str, str]]:
    raw = text or ""
    if not raw.strip():
        return []
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(r'(?:doi[:\s]+)?(10\.\d{4,9}/[^\s"<>]+)', raw, re.I):
        doi = match.group(1).rstrip(".,);")
        title = f"NPL reference {doi}"
        key = normalize_title(title)
        if key in seen:
            continue
        seen.add(key)
        refs.append({"title": title, "doi": doi, "url": f"https://doi.org/{doi}"})

    split = _NPL_SPLIT.split(raw)
    if len(split) > 1:
        for chunk in split[1:]:
            line = chunk.strip().splitlines()[0].strip(" -:*")
            if not line:
                continue
            key = normalize_title(line)
            if key in seen:
                continue
            seen.add(key)
            refs.append({"title": line, "doi": "", "url": ""})
    return refs


def _extract_forward_citations_from_html(html: str) -> list[dict[str, str]]:
    if not html:
        return []
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    patterns = [
        re.compile(
            r'data-citation-direction="forward"[^>]*data-pub="([^"]+)"[^>]*data-date="([^"]*)"(?:[^>]*data-title="([^"]*)")?',
            re.I,
        ),
        re.compile(
            r'cited by[^<]{0,200}?/patent/([A-Z]{2}\d+[A-Z]?\d*)[^<]{0,200}?(\d{4}-\d{2}-\d{2})?',
            re.I | re.S,
        ),
    ]
    for pattern in patterns:
        for match in pattern.finditer(html):
            pub = normalize_publication_number(match.group(1)).normalized_publication
            if not pub or pub in seen:
                continue
            seen.add(pub)
            title = ""
            date = ""
            if match.lastindex and match.lastindex >= 2:
                date = _iso_date(match.group(2) or "")
            if match.lastindex and match.lastindex >= 3:
                title = match.group(3) or ""
            refs.append(
                {
                    "publication_number": pub,
                    "publication_date": date,
                    "title": title,
                    "source_url": "",
                }
            )
    return refs


def _coerce_reference_items(
    values: Any,
    *,
    fallback_direction: str,
) -> list[dict[str, Any]]:
    if not values:
        return []
    items: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, dict):
            item = dict(value)
        else:
            item = {"publication_number": str(value)}
        item.setdefault("direction", fallback_direction)
        items.append(item)
    return items


def _default_patent_fetch(publication_number: str, fetch_patent_record: Any) -> Any:
    if not fetch_patent_record:
        return None
    return fetch_patent_record(publication_number)


class PatentCitationsProsecutionLane:
    lane_id = "L2_PATENT_CITATIONS_PROSECUTION"

    def run(
        self,
        study_id: str,
        **kwargs: Any,
    ) -> LaneResult:
        publication_number = str(kwargs.get("publication_number", "")).strip()
        critical_date = _iso_date(kwargs.get("critical_date", ""))
        citation_depth = min(int(kwargs.get("citation_depth", 1) or 1), 1)
        known_art = _normalize_known_art(kwargs.get("known_art_set"))
        study_patent_norm = normalize_publication_number(publication_number, kwargs.get("study_family_key", ""))
        root_record = kwargs.get("root_record")
        fetch_patent_record = kwargs.get("fetch_patent_record")
        underlying_patent_documents = kwargs.get("underlying_patent_documents", {}) or {}

        records: list[EvidenceRecord] = []
        notes = [f"citation_depth={citation_depth}", "one-hop lane"]
        seen_leads: set[tuple[str, str]] = set()

        backward_refs = _coerce_reference_items(
            kwargs.get("backward_citations")
            or getattr(root_record, "citations", [])
            or [],
            fallback_direction="backward",
        )
        forward_refs = _coerce_reference_items(
            kwargs.get("forward_citations")
            or getattr(root_record, "forward_citations", [])
            or _extract_forward_citations_from_html(getattr(root_record, "source_snapshot_html", "")),
            fallback_direction="forward",
        )
        npl_refs = _coerce_reference_items(
            kwargs.get("npl_references")
            or _extract_npl_references(getattr(root_record, "source_snapshot_html", "")),
            fallback_direction="npl",
        )
        prosecution_docs = _coerce_reference_items(
            kwargs.get("prosecution_documents")
            or [],
            fallback_direction="prosecution",
        )
        ptab_docs = _coerce_reference_items(
            kwargs.get("ptab_documents")
            or [],
            fallback_direction="ptab",
        )

        for ref in backward_refs:
            self._append_patent_reference(
                records,
                seen_leads,
                study_id=study_id,
                study_patent_norm=study_patent_norm,
                critical_date=critical_date,
                known_art=known_art,
                ref=ref,
                direction="backward",
                discovered_from=publication_number,
                source_document_url=getattr(root_record, "url", ""),
                underlying_patent_documents=underlying_patent_documents,
                fetch_patent_record=fetch_patent_record,
            )

        for ref in forward_refs:
            ref_date = _iso_date(ref.get("publication_date", ""))
            if critical_date and ref_date and ref_date > critical_date:
                continue
            self._append_patent_reference(
                records,
                seen_leads,
                study_id=study_id,
                study_patent_norm=study_patent_norm,
                critical_date=critical_date,
                known_art=known_art,
                ref=ref,
                direction="forward",
                discovered_from=publication_number,
                source_document_url=getattr(root_record, "url", ""),
                underlying_patent_documents=underlying_patent_documents,
                fetch_patent_record=fetch_patent_record,
            )

        for ref in npl_refs:
            records.append(
                self._build_lead_record(
                    study_id=study_id,
                    evidence_type=EvidenceType.SCHOLARLY_NPL,
                    tier=EvidenceTier.LEAD,
                    raw_title=ref.get("title", ""),
                    source_url=ref.get("source_url", "") or getattr(root_record, "url", ""),
                    document_url=ref.get("url", ""),
                    critical_date=critical_date,
                    duplicate_status="known-art" if normalize_title(ref.get("title", "")) in known_art else "clear",
                    provenance={
                        "source_document": getattr(root_record, "url", ""),
                        "where_found": "study patent NPL references",
                        "relationship_type": "npl reference listing",
                    },
                    citation_graph={
                        "direction": "npl",
                        "source_publication": study_patent_norm.normalized_publication,
                        "target_publication": "",
                        "hop_count": citation_depth,
                        "discovered_from": publication_number,
                        "relation_confidence": "high",
                    },
                    date_kind="citation_listing",
                    date_confidence="",
                    document_date="",
                    publisher=ref.get("publisher", ""),
                    authors=_coerce_list(ref.get("authors")),
                    notes=[f"doi={ref.get('doi', '')}".strip("=").strip()],
                )
            )

        for ref in prosecution_docs:
            records.append(
                self._build_filing_record(
                    study_id=study_id,
                    evidence_type=EvidenceType.PATENT_PROSECUTION,
                    critical_date=critical_date,
                    filing=ref,
                    direction="prosecution",
                    source_publication=study_patent_norm.normalized_publication,
                )
            )
            for pub in _parse_patent_mentions(ref.get("text", "")):
                self._append_patent_reference(
                    records,
                    seen_leads,
                    study_id=study_id,
                    study_patent_norm=study_patent_norm,
                    critical_date=critical_date,
                    known_art=known_art,
                    ref={
                        "publication_number": pub,
                        "title": "",
                        "source_url": ref.get("source_url", ""),
                        "relation_confidence": "medium",
                    },
                    direction="prosecution",
                    discovered_from=ref.get("title", "") or ref.get("source_url", ""),
                    source_document_url=ref.get("source_url", ""),
                    underlying_patent_documents=underlying_patent_documents,
                    fetch_patent_record=fetch_patent_record,
                )
            for npl_ref in _extract_npl_references(ref.get("text", "")):
                records.append(
                    self._build_lead_record(
                        study_id=study_id,
                        evidence_type=EvidenceType.SCHOLARLY_NPL,
                        tier=EvidenceTier.LEAD,
                        raw_title=npl_ref.get("title", ""),
                        source_url=ref.get("source_url", ""),
                        document_url=npl_ref.get("url", ""),
                        critical_date=critical_date,
                        duplicate_status="known-art" if normalize_title(npl_ref.get("title", "")) in known_art else "clear",
                        provenance={
                            "source_document": ref.get("source_url", ""),
                            "where_found": ref.get("title", "") or "prosecution filing",
                            "relationship_type": "prosecution referenced NPL",
                        },
                        citation_graph={
                            "direction": "prosecution",
                            "source_publication": study_patent_norm.normalized_publication,
                            "target_publication": "",
                            "hop_count": citation_depth,
                            "discovered_from": ref.get("title", "") or ref.get("source_url", ""),
                            "relation_confidence": "medium",
                        },
                        date_kind="filing_reference",
                        date_confidence="",
                        document_date="",
                        publisher=npl_ref.get("publisher", ""),
                        authors=_coerce_list(npl_ref.get("authors")),
                        notes=[f"doi={npl_ref.get('doi', '')}".strip("=").strip()],
                    )
                )

        for ref in ptab_docs:
            records.append(
                self._build_filing_record(
                    study_id=study_id,
                    evidence_type=EvidenceType.LITIGATION,
                    critical_date=critical_date,
                    filing=ref,
                    direction="ptab",
                    source_publication=study_patent_norm.normalized_publication,
                )
            )
            for pub in _parse_patent_mentions(ref.get("text", "")):
                self._append_patent_reference(
                    records,
                    seen_leads,
                    study_id=study_id,
                    study_patent_norm=study_patent_norm,
                    critical_date=critical_date,
                    known_art=known_art,
                    ref={
                        "publication_number": pub,
                        "title": "",
                        "source_url": ref.get("source_url", ""),
                        "relation_confidence": "medium",
                    },
                    direction="ptab",
                    discovered_from=ref.get("title", "") or ref.get("source_url", ""),
                    source_document_url=ref.get("source_url", ""),
                    underlying_patent_documents=underlying_patent_documents,
                    fetch_patent_record=fetch_patent_record,
                )
            for ptab_id in _PTAB_PATTERN.findall(ref.get("text", "")):
                records.append(
                    self._build_lead_record(
                        study_id=study_id,
                        evidence_type=EvidenceType.LITIGATION,
                        tier=EvidenceTier.LEAD,
                        raw_title=ptab_id.upper(),
                        source_url=ref.get("source_url", ""),
                        document_url=ref.get("document_url", ""),
                        critical_date=critical_date,
                        duplicate_status="clear",
                        provenance={
                            "source_document": ref.get("source_url", ""),
                            "where_found": ref.get("title", "") or "PTAB filing",
                            "relationship_type": "ptab identifier",
                        },
                        citation_graph={
                            "direction": "ptab",
                            "source_publication": study_patent_norm.normalized_publication,
                            "target_publication": "",
                            "hop_count": citation_depth,
                            "discovered_from": ref.get("title", "") or ref.get("source_url", ""),
                            "relation_confidence": "high",
                        },
                        date_kind="filing_reference",
                        date_confidence="",
                        document_date="",
                    )
                )

        return LaneResult(lane_id=self.lane_id, records=records, notes=notes)

    def _append_patent_reference(
        self,
        records: list[EvidenceRecord],
        seen_leads: set[tuple[str, str]],
        *,
        study_id: str,
        study_patent_norm: Any,
        critical_date: str,
        known_art: set[str],
        ref: dict[str, Any],
        direction: str,
        discovered_from: str,
        source_document_url: str,
        underlying_patent_documents: dict[str, Any],
        fetch_patent_record: Any,
    ) -> None:
        patent_norm = normalize_publication_number(
            ref.get("publication_number", "") or ref.get("target_publication", ""),
            ref.get("family_key", ""),
        )
        if not patent_norm.normalized_publication:
            return
        dedupe_key = (direction, patent_norm.family_key or patent_norm.normalized_publication)
        if dedupe_key in seen_leads:
            return
        seen_leads.add(dedupe_key)
        duplicate_status = "clear"
        if patent_norm.normalized_publication in known_art:
            duplicate_status = "known-art"
        elif (
            study_patent_norm.family_key
            and patent_norm.family_key
            and patent_norm.family_key == study_patent_norm.family_key
        ) or patent_norm.normalized_publication == study_patent_norm.normalized_publication:
            duplicate_status = "known-family-duplicate"

        lead = self._build_lead_record(
            study_id=study_id,
            evidence_type=EvidenceType.PATENT,
            tier=EvidenceTier.LEAD,
            raw_title=ref.get("title", "") or patent_norm.normalized_publication,
            source_url=ref.get("source_url", "") or source_document_url,
            document_url="",
            critical_date=critical_date,
            duplicate_status=duplicate_status,
            provenance={
                "source_document": source_document_url,
                "where_found": direction,
                "relationship_type": f"{direction} citation listing",
            },
            citation_graph={
                "direction": direction,
                "source_publication": study_patent_norm.normalized_publication,
                "target_publication": patent_norm.normalized_publication,
                "hop_count": 1,
                "discovered_from": discovered_from,
                "relation_confidence": ref.get("relation_confidence", "high"),
            },
            publication_number=patent_norm.normalized_publication,
            patent_family_key=patent_norm.family_key,
            date_kind="citation_listing",
            date_confidence="",
            document_date=_iso_date(ref.get("publication_date", "")),
            assignee=ref.get("assignee", ""),
            inventor_names=_coerce_list(ref.get("inventor_names")),
            cpc_codes=_coerce_list(ref.get("cpc_codes")),
            ipc_codes=_coerce_list(ref.get("ipc_codes")),
        )
        records.append(lead)

        underlying_seed = underlying_patent_documents.get(patent_norm.normalized_publication)
        if underlying_seed is None:
            fetched = _default_patent_fetch(patent_norm.normalized_publication, fetch_patent_record)
            if fetched is not None:
                underlying_seed = {
                    "title": getattr(fetched, "title", ""),
                    "document_url": getattr(fetched, "pdf_url", "") or getattr(fetched, "url", ""),
                    "source_url": getattr(fetched, "url", ""),
                    "document_date": getattr(fetched, "priority_date", "") or getattr(fetched, "publication_date", ""),
                    "date_kind": "priority_date" if getattr(fetched, "priority_date", "") else "publication_date",
                    "date_confidence": "verified" if (getattr(fetched, "priority_date", "") or getattr(fetched, "publication_date", "")) else "",
                    "assignee": getattr(fetched, "assignee", ""),
                    "inventor_names": _coerce_list(getattr(fetched, "inventors", "")),
                    "shortest_verbatim_highlight": "",
                    "requirement_mapping": [],
                    "source_reliability": "patent-office",
                    "publication_number": patent_norm.normalized_publication,
                    "patent_family_key": patent_norm.family_key,
                }
        if underlying_seed:
            records.append(
                self._build_underlying_patent_record(
                    study_id=study_id,
                    study_patent_norm=study_patent_norm,
                    critical_date=critical_date,
                    known_art=known_art,
                    publication_number=patent_norm.normalized_publication,
                    family_key=patent_norm.family_key,
                    direction=direction,
                    discovered_from=discovered_from,
                    source_document_url=source_document_url,
                    seed=underlying_seed,
                )
            )

    def _build_lead_record(
        self,
        *,
        study_id: str,
        evidence_type: EvidenceType,
        tier: EvidenceTier,
        raw_title: str,
        source_url: str,
        document_url: str,
        critical_date: str,
        duplicate_status: str,
        provenance: dict[str, Any],
        citation_graph: dict[str, Any],
        date_kind: str,
        date_confidence: str,
        document_date: str,
        publication_number: str = "",
        patent_family_key: str = "",
        assignee: str = "",
        inventor_names: list[str] | None = None,
        cpc_codes: list[str] | None = None,
        ipc_codes: list[str] | None = None,
        publisher: str = "",
        authors: list[str] | None = None,
        notes: list[str] | None = None,
    ) -> EvidenceRecord:
        entity_norm = normalize_entity_name(assignee)
        record = EvidenceRecord(
            record_id=f"{study_id}:{self.lane_id}:{citation_graph.get('direction', 'lead')}:{publication_number or normalize_title(raw_title)}",
            study_id=study_id,
            lane_id=self.lane_id,
            tier=tier,
            evidence_type=evidence_type,
            raw_title=raw_title,
            normalized_title=normalize_title(raw_title),
            source_url=source_url,
            document_url=document_url,
            document_date=document_date,
            date_kind=date_kind,
            date_confidence=date_confidence,
            critical_date=critical_date,
            publisher=publisher,
            authors=authors or [],
            assignee=assignee,
            inventor_names=[normalize_inventor_name(name) for name in (inventor_names or []) if name],
            publication_number=publication_number,
            patent_family_key=patent_family_key,
            entity_key=entity_norm.canonical,
            cpc_codes=cpc_codes or [],
            ipc_codes=ipc_codes or [],
            access_status="downloadable-pdf" if _looks_like_pdf(document_url) else ("open" if document_url else "listing-only"),
            source_reliability="official" if evidence_type in {EvidenceType.PATENT_PROSECUTION, EvidenceType.LITIGATION} else "patent-office",
            duplicate_status=duplicate_status,
            duplicate_relation=duplicate_status if duplicate_status != "clear" else "",
            inference_burden="listing-only",
            metadata_uncertainty="lead-only",
            provenance=provenance,
            citation_graph=citation_graph,
            notes=notes or [],
        )
        return score_evidence(record)

    def _build_underlying_patent_record(
        self,
        *,
        study_id: str,
        study_patent_norm: Any,
        critical_date: str,
        known_art: set[str],
        publication_number: str,
        family_key: str,
        direction: str,
        discovered_from: str,
        source_document_url: str,
        seed: dict[str, Any],
    ) -> EvidenceRecord:
        duplicate_status = "clear"
        if publication_number in known_art:
            duplicate_status = "known-art"
        elif (study_patent_norm.family_key and family_key and study_patent_norm.family_key == family_key) or publication_number == study_patent_norm.normalized_publication:
            duplicate_status = "known-family-duplicate"
        assignee = seed.get("assignee", "")
        entity_norm = normalize_entity_name(assignee)
        record = EvidenceRecord(
            record_id=f"{study_id}:{self.lane_id}:underlying:{publication_number}",
            study_id=study_id,
            lane_id=self.lane_id,
            tier=EvidenceTier.CANDIDATE,
            evidence_type=EvidenceType.PATENT,
            raw_title=seed.get("title", "") or publication_number,
            normalized_title=normalize_title(seed.get("title", "") or publication_number),
            source_url=seed.get("source_url", "") or source_document_url,
            document_url=seed.get("document_url", ""),
            local_copy_path=seed.get("local_copy_path", ""),
            source_snapshot_path=seed.get("source_snapshot_path", ""),
            document_date=_iso_date(seed.get("document_date", "")),
            date_kind=seed.get("date_kind", ""),
            date_confidence=seed.get("date_confidence", ""),
            critical_date=critical_date,
            publisher=seed.get("publisher", ""),
            authors=_coerce_list(seed.get("authors")),
            assignee=assignee,
            inventor_names=[normalize_inventor_name(name) for name in _coerce_list(seed.get("inventor_names"))],
            publication_number=publication_number,
            patent_family_key=family_key,
            entity_key=entity_norm.canonical,
            part_numbers=[publication_number],
            cpc_codes=_coerce_list(seed.get("cpc_codes")),
            ipc_codes=_coerce_list(seed.get("ipc_codes")),
            requirement_mapping=_coerce_mapping(seed.get("requirement_mapping")),
            shortest_verbatim_highlight=seed.get("shortest_verbatim_highlight", ""),
            page_number=seed.get("page_number"),
            timestamp_or_location=seed.get("timestamp_or_location", ""),
            access_status=seed.get("access_status", "downloadable-pdf" if _looks_like_pdf(seed.get("document_url", "")) else ("open" if seed.get("document_url", "") else "unknown")),
            source_reliability=seed.get("source_reliability", "patent-office"),
            duplicate_status=duplicate_status,
            duplicate_relation=duplicate_status if duplicate_status != "clear" else "",
            inference_burden=seed.get("inference_burden", "direct"),
            metadata_uncertainty=seed.get("metadata_uncertainty", ""),
            corroboration_keys=_coerce_list(seed.get("corroboration_keys")),
            provenance={
                "source_document": source_document_url,
                "where_found": direction,
                "relationship_type": "underlying retrieved patent document",
            },
            citation_graph={
                "direction": direction,
                "source_publication": study_patent_norm.normalized_publication,
                "target_publication": publication_number,
                "hop_count": 1,
                "discovered_from": discovered_from,
                "relation_confidence": seed.get("relation_confidence", "high"),
            },
            notes=_coerce_list(seed.get("notes")),
        )
        return classify_evidence_record(record)

    def _build_filing_record(
        self,
        *,
        study_id: str,
        evidence_type: EvidenceType,
        critical_date: str,
        filing: dict[str, Any],
        direction: str,
        source_publication: str,
    ) -> EvidenceRecord:
        return self._build_lead_record(
            study_id=study_id,
            evidence_type=evidence_type,
            tier=EvidenceTier.LEAD,
            raw_title=filing.get("title", "") or direction.upper(),
            source_url=filing.get("source_url", ""),
            document_url=filing.get("document_url", ""),
            critical_date=critical_date,
            duplicate_status="clear",
            provenance={
                "source_document": filing.get("source_url", ""),
                "where_found": direction,
                "relationship_type": f"{direction} filing",
            },
            citation_graph={
                "direction": direction,
                "source_publication": source_publication,
                "target_publication": "",
                "hop_count": 1,
                "discovered_from": filing.get("title", "") or filing.get("source_url", ""),
                "relation_confidence": filing.get("relation_confidence", "high"),
            },
            date_kind="filing_date",
            date_confidence="high" if _iso_date(filing.get("document_date", "")) else "",
            document_date=_iso_date(filing.get("document_date", "")),
            notes=[filing.get("document_category", "")] if filing.get("document_category") else [],
        )


def get_patent_citations_prosecution_lane() -> PatentCitationsProsecutionLane:
    return PatentCitationsProsecutionLane()
