#!/usr/bin/env python3
"""Autonomous patent hunt engine — citations, burn-check, score, draft candidates."""

from __future__ import annotations

import html as html_module
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from evidence_schema import EvidenceRecord, EvidenceTier, EvidenceType
from evidence_scoring import classify_evidence_record, ready_decision
from lanes.registry import get_lane_runner, lane_for_source_label
from normalizers.entities import normalize_entity_name, normalize_inventor_name
from normalizers.patent_family import normalize_publication_number
from normalizers.titles import normalize_title
from repo_paths import REPO_ROOT, SCRIPTS_DIR
from proof_bundle import write_ready_proof_bundle
from research_policy import (
    is_hold,
)
from study_profiles import resolve_profile_from_meta

REPO = REPO_ROOT

import sys

sys.path.insert(0, str(SCRIPTS_DIR))
from check_burned import is_burned, load_burned, load_citation_seeds, patent_key  # noqa: E402
from link_builder import crossref_lookup, patent_links  # noqa: E402
from patent_search import search_queries  # noqa: E402
from study_bot import STUDY_META  # noqa: E402
from study_requirements import ctrl_f_phrases, map_requirements  # noqa: E402
from product_search import search_product_evidence  # noqa: E402

LogFn = Callable[[str, str], None]  # message, level

MAX_INSPECT = 500
HOLD_MIN_RANK = 1

# Lane depth — tuned for ULTRA-DEEP hunts
L1_CITE_LIMIT = 200
L2_HOP1_LIMIT = 100
L2_CITES_PER = 40
L2_HOP3_LIMIT = 50
L3_PER_QUERY = 50
L4_PER_QUERY = 35
L6_SEED_LIMIT = 80
L6_CITES_PER = 25

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_cache: dict[str, "PatentRecord"] = {}
_cache_lock = threading.Lock()


@dataclass
class PatentRecord:
    pub_id: str
    title: str = ""
    assignee: str = ""
    inventors: str = ""
    priority_date: str = ""
    publication_date: str = ""
    abstract: str = ""
    url: str = ""
    pdf_url: str = ""
    uspto_url: str = ""
    uspto_pdf_url: str = ""
    espacenet_url: str = ""
    doi: str = "n/a"
    cpc: str = ""
    source_lane: str = ""
    source_snapshot_html: str = ""
    search_text: str = ""
    req_rows: list[dict] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    score: int = 0
    matched_keywords: list[str] = field(default_factory=list)
    burned: bool = False
    burn_relation: str = ""
    self_rank: int = 0
    confidence: str = "low"
    ready: bool = False
    rank_reason: str = ""
    evidence_record: EvidenceRecord | None = None
    evidence_score: int = 0
    score_breakdown: dict = field(default_factory=dict)
    hard_gate_failures: list[str] = field(default_factory=list)
    evidence_tier: str = EvidenceTier.LEAD.value
    normalization_results: dict = field(default_factory=dict)
    query_plan_provenance: list[dict] = field(default_factory=list)
    citation_provenance: list[dict] = field(default_factory=list)


def _fetch_html(url: str) -> str:
    # Rate limit: 1.5 second delay between requests to avoid 503 errors
    time.sleep(1.5)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", "replace")


def _normalize_pub(pub: str) -> str:
    pub = pub.strip().upper()
    if not pub.startswith(("US", "EP", "WO", "CN", "JP", "KR")):
        pub = "US" + pub
    return pub


def _extract_patent_ids(html: str) -> list[str]:
    ids = re.findall(r"/patent/([A-Z]{2}\d+[A-Z]?\d?)/", html)
    return list(dict.fromkeys(ids))


def _clean_patent_text(html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html_module.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:120000]


def _record_signal_text(rec: PatentRecord) -> str:
    return " ".join(part for part in [rec.title, rec.abstract, rec.search_text] if part).strip()


def fetch_patent(pub_id: str) -> PatentRecord:
    pub_id = _normalize_pub(pub_id)
    with _cache_lock:
        if pub_id in _cache:
            return _cache[pub_id]

    url = f"https://patents.google.com/patent/{pub_id}"
    rec = PatentRecord(pub_id=pub_id, url=url)
    try:
        html = _fetch_html(url)
    except (urllib.error.URLError, TimeoutError) as exc:
        rec.title = f"(fetch failed: {exc})"
        return rec
    rec.source_snapshot_html = html
    rec.search_text = _clean_patent_text(html)

    title_m = re.search(r'<meta name="DC.title" content="([^"]+)"', html)
    if title_m:
        rec.title = re.sub(r"\s+", " ", title_m.group(1)).strip()

    pri_m = re.search(r'<time itemprop="priorityDate" datetime="([^"]+)"', html)
    if pri_m:
        rec.priority_date = pri_m.group(1)[:10]

    pub_m = re.search(r'<time itemprop="publicationDate" datetime="([^"]+)"', html)
    if pub_m:
        rec.publication_date = pub_m.group(1)[:10]

    abs_m = re.search(
        r'<meta name="DC.description" content="([^"]+)"', html
    ) or re.search(r'itemprop="description"[^>]*>([^<]{40,})', html)
    if abs_m:
        rec.abstract = re.sub(r"\s+", " ", abs_m.group(1)).strip()[:1200]

    inv_m = re.findall(r'itemprop="inventor"[^>]*>.*?itemprop="name"[^>]*>([^<]+)', html, re.S)
    if inv_m:
        rec.inventors = html_module.unescape(
            ", ".join(dict.fromkeys(i.strip() for i in inv_m[:8]))
        )

    rec.assignee = _extract_assignee(html)
    cpc_parts = re.findall(r'itemprop="Code"[^>]*>([^<]+)', html)
    if cpc_parts:
        rec.cpc = " / ".join(cpc_parts[-4:])

    rec.citations = _extract_patent_ids(html)
    links = patent_links(pub_id, html=html)
    rec.url = links["google"]
    rec.pdf_url = links["pdf"]
    rec.uspto_url = links["uspto"]
    rec.uspto_pdf_url = links["uspto_pdf"]
    rec.espacenet_url = links["espacenet"]
    rec.doi = links["doi"]
    with _cache_lock:
        _cache[pub_id] = rec
    return rec


_BAD_ASSIGNEE = {"engineering & computer science", "engineering and computer science"}


def _extract_assignee(html: str) -> str:
    candidates: list[str] = []
    for pat in (
        r'itemprop="assignee[^"]*"[^>]*>.*?itemprop="name"[^>]*>([^<]+)',
        r'>([A-Z][^<]{2,60}(?:Corp\.?|Inc\.?|Ltd\.?|LLC|GmbH|Systems|Corporation)[^<]*)</',
    ):
        for m in re.findall(pat, html, re.S | re.I):
            clean = html_module.unescape(re.sub(r"\s+", " ", m).strip())
            if clean.lower() not in _BAD_ASSIGNEE and len(clean) > 2:
                candidates.append(clean)
    return candidates[0] if candidates else "(verify assignee in PDF)"


def _parse_critical_date(study_id: str) -> str | None:
    raw = STUDY_META[study_id]["critical_date"]
    m = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
    return m.group(1) if m else None


_NPL_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "article",
    "be",
    "book",
    "conference",
    "dissertation",
    "for",
    "in",
    "is",
    "lead",
    "literature",
    "of",
    "on",
    "or",
    "paper",
    "phd",
    "poster",
    "product",
    "query",
    "solubility",
    "study",
    "the",
    "thesis",
    "to",
    "with",
}


def _crossref_type_to_dropdown(meta: dict[str, str]) -> str:
    raw_type = (meta.get("type") or "").lower()
    title = (meta.get("title") or "").lower()
    if raw_type in {"book", "book-set", "monograph", "book-track", "edited-book"}:
        return "NPL -> Book"
    if raw_type in {"dissertation"} or "thesis" in title or "dissertation" in title:
        return "NPL -> Masters or PhD thesis"
    if raw_type in {"journal-article", "proceedings-article", "posted-content", "report-component"}:
        return "NPL -> Article"
    return "NPL -> Other"


def _npl_access_fields(meta: dict[str, str]) -> tuple[str, str]:
    pdf_url = meta.get("pdf_url") or ""
    resolver_url = meta.get("url") or ""
    if pdf_url:
        return f"yes + {pdf_url}", "open PDF link from Crossref metadata"
    if resolver_url:
        return f"unknown + {resolver_url}", "resolver only - verify open vs school/library"
    return "unknown + not found", "not verified"


def _query_concepts(query: str, study_id: str) -> list[str]:
    study_keywords = sorted(
        {
            keyword.strip().lower()
            for keyword in STUDY_META[study_id].get("keywords", [])
            if keyword and len(keyword.strip()) > 3
        },
        key=len,
        reverse=True,
    )
    query_lower = query.lower()
    concepts: list[str] = []
    consumed: list[tuple[int, int]] = []

    for keyword in study_keywords:
        idx = query_lower.find(keyword)
        if idx == -1:
            continue
        end = idx + len(keyword)
        if any(not (end <= left or idx >= right) for left, right in consumed):
            continue
        concepts.append(keyword)
        consumed.append((idx, end))

    stripped = query_lower
    for keyword in concepts:
        stripped = stripped.replace(keyword, " ")
    for token in re.findall(r"[a-z0-9]+", stripped):
        if len(token) <= 3 or token in _NPL_QUERY_STOPWORDS:
            continue
        concepts.append(token)
    return list(dict.fromkeys(concepts))


def _npl_match_summary(query: str, meta: dict[str, str], study_id: str) -> tuple[list[str], str]:
    concepts = _query_concepts(query, study_id)
    combined = " ".join(
        filter(
            None,
            [
                meta.get("title", ""),
                meta.get("journal", ""),
                meta.get("publisher", ""),
                meta.get("type", ""),
            ],
        )
    ).lower()
    matched = [concept for concept in concepts if concept in combined]
    return matched, combined


def _npl_confidence_and_reason(query: str, meta: dict[str, str], study_id: str) -> tuple[str, str, list[str]]:
    matched, combined = _npl_match_summary(query, meta, study_id)
    title = (meta.get("title") or "").lower()
    if len(matched) >= 3:
        return "med", f"title/metadata match {len(matched)} query concepts", matched
    if len(matched) >= 2 and title:
        return "med", f"title/metadata match {len(matched)} query concepts", matched
    if len(matched) == 1:
        return "low", f"only one query concept matched ({matched[0]})", matched
    if combined:
        return "low", "no specific study concepts matched resolved metadata", matched
    return "low", "Crossref metadata too thin to verify scope", matched


def score_record(rec: PatentRecord, study_id: str) -> PatentRecord:
    keywords = STUDY_META[study_id]["keywords"]
    text = _record_signal_text(rec)
    text_l = text.lower()
    matched = [k for k in keywords if k.lower() in text_l]
    rec.matched_keywords = matched
    rec.req_rows = map_requirements(study_id, text)
    yes_count = sum(1 for r in rec.req_rows if r["select"] == "yes")
    maybe_count = sum(1 for r in rec.req_rows if r["select"] == "maybe")
    rec.score = yes_count * 3 + maybe_count

    priority_ids = STUDY_META[study_id]["priority_req_ids"]
    priority_yes = sum(
        1 for r in rec.req_rows if r["id"] in priority_ids and r["select"] == "yes"
    )

    if yes_count >= 4:
        rec.self_rank = 3
    elif yes_count >= 2:
        rec.self_rank = 2
    elif yes_count >= 1 or maybe_count >= 4:
        rec.self_rank = 1
    else:
        rec.self_rank = 0

    if yes_count >= 3:
        rec.confidence = "high"
    elif yes_count >= 1:
        rec.confidence = "med"
    else:
        rec.confidence = "low"

    rec.rank_reason = (
        f"priority_yes={priority_yes}, req_yes={yes_count}, req_maybe={maybe_count}, "
        f"matched_keywords={len(matched)}; rank follows requirement coverage across patent full text, not keyword count alone"
    )
    evidence = _build_patent_evidence_record(rec, study_id)
    rec.evidence_record = evidence
    rec.evidence_score = evidence.score
    rec.score_breakdown = evidence.score_breakdown
    rec.hard_gate_failures = evidence.hard_gate_failures
    rec.evidence_tier = evidence.tier.value
    rec.ready, reasoning = ready_decision(
        evidence,
        self_rank=rec.self_rank,
        confidence=rec.confidence,
    )
    rec.rank_reason = f"{rec.rank_reason}; {reasoning}"
    return rec


def burn_check(rec: PatentRecord, study_id: str, burned: dict[str, str]) -> PatentRecord:
    for probe in (rec.pub_id, rec.title):
        if not probe:
            continue
        hit, relation = is_burned(probe, burned)
        if hit:
            rec.burned = True
            rec.burn_relation = relation
            rec.ready = False
            break
    return rec


def is_study_patent(rec: PatentRecord, study_id: str) -> bool:
    study_patent = STUDY_META[study_id].get("patent", "")
    if not study_patent:
        return False
    study_pub = patent_key(study_patent)
    return patent_key(rec.pub_id) == study_pub


def date_ok(rec: PatentRecord, critical: str | None) -> bool:
    if not critical:
        return True
    d = rec.priority_date or rec.publication_date
    if not d:
        return True
    return d <= critical


def _candidate_access_status(rec: PatentRecord) -> str:
    if rec.pdf_url or rec.uspto_pdf_url:
        return "downloadable-pdf"
    if rec.url:
        return "landing-page-only"
    return "unknown"


def _build_patent_evidence_record(rec: PatentRecord, study_id: str) -> EvidenceRecord:
    profile = resolve_profile_from_meta(STUDY_META[study_id])
    critical = _parse_critical_date(study_id) or ""
    document_date = rec.priority_date or rec.publication_date or ""
    phrases = ctrl_f_phrases(_record_signal_text(rec), rec.matched_keywords, limit=1)
    lane = lane_for_source_label(rec.source_lane or "L1")
    patent_norm = normalize_publication_number(rec.pub_id)
    entity_norm = normalize_entity_name(rec.assignee)
    highlight = phrases[0] if phrases else ""
    requirement_mapping = rec.req_rows
    duplicate_status = "clear"
    if rec.burned:
        duplicate_status = "known-art"
    elif is_study_patent(rec, study_id):
        duplicate_status = "known-family-duplicate"

    base = EvidenceRecord(
        record_id=f"{study_id}:{patent_norm.normalized_publication or rec.pub_id}",
        study_id=study_id,
        lane_id=lane.id,
        tier=EvidenceTier.CANDIDATE,
        evidence_type=EvidenceType.PATENT,
        raw_title=rec.title,
        normalized_title=normalize_title(rec.title),
        source_url=rec.url,
        archived_url="",
        document_url=rec.pdf_url or rec.uspto_pdf_url or rec.url,
        local_copy_path="",
        source_snapshot_path="",
        document_date=document_date,
        date_kind="priority_date" if rec.priority_date else ("publication_date" if rec.publication_date else ""),
        date_confidence="verified" if document_date else "",
        critical_date=critical,
        language="en",
        publisher="Google Patents" if rec.url else "",
        authors=[],
        assignee=rec.assignee,
        inventor_names=[normalize_inventor_name(name) for name in rec.inventors.split(",") if name.strip()],
        publication_number=patent_norm.normalized_publication,
        patent_family_key=patent_norm.family_key,
        entity_key=entity_norm.canonical,
        model_numbers=[],
        part_numbers=[patent_norm.normalized_publication] if patent_norm.normalized_publication else [],
        cpc_codes=[part.strip() for part in rec.cpc.split("/") if part.strip()],
        ipc_codes=[],
        requirement_mapping=requirement_mapping,
        shortest_verbatim_highlight=highlight,
        page_number=None,
        timestamp_or_location="abstract",
        access_status=_candidate_access_status(rec),
        source_reliability="patent-office",
        duplicate_status=duplicate_status,
        duplicate_relation=rec.burn_relation,
        inference_burden="direct" if any(row.get("select") == "yes" for row in requirement_mapping) else "inferred-only",
        metadata_uncertainty="" if document_date else "missing-date",
        corroboration_keys=[rec.url] if rec.url else [],
        content_sha256="",
        provenance={
            "source_lane": rec.source_lane,
            "citation_provenance": rec.citation_provenance,
        },
        citation_graph=rec.citation_provenance[0] if rec.citation_provenance else {},
        rank_reason=rec.rank_reason,
        notes=[f"source_lane={rec.source_lane}", f"lane_name={lane.name}", f"study_profile={profile.name}"],
    )
    scored = classify_evidence_record(base)

    rec.evidence_record = scored
    rec.evidence_score = scored.score
    rec.score_breakdown = scored.score_breakdown
    rec.hard_gate_failures = scored.hard_gate_failures
    rec.evidence_tier = scored.tier.value
    rec.normalization_results = {
        "patent": {
            "normalized_publication": patent_norm.normalized_publication,
            "family_key": patent_norm.family_key,
            "number_type": patent_norm.number_type,
            "evidence_basis": patent_norm.evidence_basis,
        },
        "entity": {
            "canonical": entity_norm.canonical,
            "matched_alias": entity_norm.matched_alias,
            "aliases": entity_norm.aliases,
            "predecessors": entity_norm.predecessors,
            "subsidiaries": entity_norm.subsidiaries,
        },
        "title": {
            "normalized_title": scored.normalized_title,
        },
    }
    rec.query_plan_provenance = [
        {
            "lane_id": lane.id,
            "lane_name": lane.name,
            "source_lane": rec.source_lane,
            "study_profile": profile.name,
        }
    ]
    if rec.citation_provenance:
        rec.query_plan_provenance.extend(rec.citation_provenance)
    return scored


def _proof_bundle_metadata(rec: PatentRecord, study_id: str) -> dict:
    evidence = rec.evidence_record or _build_patent_evidence_record(rec, study_id)
    critical = _parse_critical_date(study_id)
    document_date = rec.priority_date or rec.publication_date or ""
    phrases = ctrl_f_phrases(_record_signal_text(rec), rec.matched_keywords, limit=1)
    return {
        "publication": rec.pub_id,
        "title": rec.title,
        "original_document": rec.url,
        "source_url": rec.url,
        "archived_url": "",
        "retrieval_timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "publication_date_evidence": {
            "priority_date": rec.priority_date,
            "publication_date": rec.publication_date,
        },
        "critical_date_comparison": {
            "critical_date": critical,
            "document_date_used": document_date,
            "passes": date_ok(rec, critical),
        },
        "shortest_verbatim_highlight": phrases[0] if phrases else "",
        "page_number": None,
        "requirement_mapping": rec.req_rows,
        "duplicate_check_result": {
            "status": "BURNED" if rec.burned else "CLEAR",
            "relation": rec.burn_relation,
        },
        "family_normalization_result": patent_key(rec.pub_id),
        "access_status": _candidate_access_status(rec),
        "reason_for_rank": rec.rank_reason,
        "source_lane": rec.source_lane,
        "doi": rec.doi,
        "pdf_url": rec.pdf_url,
        "uspto_pdf_url": rec.uspto_pdf_url,
        "evidence_record": evidence.to_dict(),
        "evidence_tier": evidence.tier.value,
        "evidence_score": evidence.score,
        "score_breakdown": evidence.score_breakdown,
        "hard_gate_failures": evidence.hard_gate_failures,
        "query_plan_provenance": rec.query_plan_provenance,
        "normalization_results": rec.normalization_results,
        "citation_provenance": rec.citation_provenance,
    }


def _req_table(rows: list[dict]) -> str:
    lines = ["| Requirement | Select? | Why |", "|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} {r['name'][:42]} | {r['select']} | {r['why']} |")
    return "\n".join(lines)


def draft_candidate(rec: PatentRecord, study_id: str) -> str:
    pdf_line = rec.pdf_url or rec.uspto_pdf_url or rec.url
    phrases = ctrl_f_phrases(_record_signal_text(rec), rec.matched_keywords, limit=6)
    yes_reqs = [r for r in rec.req_rows if r["select"] == "yes"]
    no_reqs = [r for r in rec.req_rows if r["select"] == "no"][:5]
    highlights = yes_reqs[:3] if yes_reqs else rec.req_rows[:2]

    req_table = _req_table(rec.req_rows)
    req_table += (
        f"\n| 2 Date of document | yes | Priority {rec.priority_date or '?'} — confirm on PDF |"
    )

    phrase_block = "\n".join(f'  - "{p}"' for p in phrases)
    highlight_block = "\n".join(
        f"  - Requirement {h['id']}: \"(open PDF — search: {h['hits'][0] if h['hits'] else 'keyword'})\""
        for h in highlights
    )
    dont_block = "\n".join(
        f"  - {r['id']} — {r['why']}" for r in no_reqs
    ) or "  - (none flagged — still verify each req in claims)"

    adversarial = (
        f"Verify verbatim anchors in PDF before submit. "
        f"{len(yes_reqs)} requirements auto-yes from document signals."
    )

    return f"""Dropdown: Patent
Downloadable PDF: yes + {pdf_line}

Self-rank: {rec.self_rank}/3
In-scope confidence: {rec.confidence}
(Bot: surface to Angela only if Self-rank ≥ 2, confidence high, ≥2 req-yes, priority RR hit.)

Form fields:
  publication: {rec.pub_id}
  title: {rec.title}
  assignee: {rec.assignee}
  inventors: {rec.inventors}
  publication date: {rec.publication_date}
  priority date: {rec.priority_date or 'not found'}
  CPC: {rec.cpc or 'not found'}
  DOI: {rec.doi}
  URL: {rec.url}
  PDF URL: {rec.pdf_url or 'not found'}
  USPTO URL: {rec.uspto_url or 'not found'}
  USPTO PDF: {rec.uspto_pdf_url or 'not found'}
  Espacenet URL: {rec.espacenet_url or 'not found'}

Select these requirements:
{req_table}

Ctrl+F phrases (test in PDF before submit):
{phrase_block}

Highlight only this:
{highlight_block}

Do NOT select:
{dont_block}

Coverage score: {len(yes_reqs)} of {len(rec.req_rows)} reqs auto-yes from document signals (verify claims)
Adversarial note: {adversarial}
Notes:
  - Burn check: python scripts/check_burned.py {study_id} {rec.pub_id} → {'BURNED' if rec.burned else 'CLEAR'}
  - Source lane: {rec.source_lane or 'unknown'}
  - Matched keywords: {', '.join(rec.matched_keywords) or 'none'}
  - Hunt engine draft {datetime.now().strftime('%Y-%m-%d %H:%M')} — Angela must verify all PDF anchors
"""


def regrade_stored_candidates(study_id: str, burned: dict[str, str] | None = None) -> int:
    """Demote on-disk READY files that fail the stricter gate → HOLD."""
    burned = burned or load_burned(study_id)
    folder = REPO / STUDY_META[study_id]["folder"] / "candidates"
    if not folder.exists():
        return 0
    demoted = 0
    for path in list(folder.glob("*_RWS_format.txt")):
        if path.name.startswith("HOLD_") or path.name.startswith("NPL_"):
            continue
        pub_id = path.name.replace("_RWS_format.txt", "")
        try:
            rec = fetch_patent(pub_id)
        except Exception:
            continue
        rec = burn_check(rec, study_id, burned)
        if rec.burned:
            path.unlink(missing_ok=True)
            demoted += 1
            continue
        rec = score_record(rec, study_id)
        if rec.ready:
            path.write_text(draft_candidate(rec, study_id), encoding="utf-8")
            continue
        hold_path = folder / f"HOLD_{patent_key(rec.pub_id)}_RWS_format.txt"
        if hold_path.exists():
            path.unlink(missing_ok=True)
        else:
            path.rename(hold_path)
        hold_path.write_text(draft_candidate(rec, study_id), encoding="utf-8")
        demoted += 1
    return demoted


class HuntEngine:
    def __init__(self, study_id: str, on_log: LogFn | None = None) -> None:
        self.study_id = study_id
        self.on_log = on_log or (lambda m, l: None)
        self.stopped = False
        self.results: list[PatentRecord] = []
        self.inspected = 0
        self.lanes_done: list[str] = []
        self.citation_provenance_by_pub: dict[str, list[dict]] = {}

    def log(self, msg: str, level: str = "info") -> None:
        self.on_log(msg, level)

    def stop(self) -> None:
        self.stopped = True

    def _queue_add(
        self,
        queue: list[tuple[str, str]],
        seen: set[str],
        pub: str,
        source: str,
        burned: dict[str, str],
        provenance: dict | None = None,
    ) -> bool:
        """Add to inspect queue only if NOT already known art."""
        key = patent_key(pub)
        if provenance:
            self.citation_provenance_by_pub.setdefault(key, []).append(dict(provenance))
        if key in seen:
            return False
        hit, _rel = is_burned(pub, burned)
        if hit:
            return False
        seen.add(key)
        queue.append((pub, source))
        return True

    def _write_lane_lead(self, folder: Path, record: EvidenceRecord) -> None:
        cand_dir = folder / "candidates"
        cand_dir.mkdir(exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9]+", "_", record.publication_number or record.normalized_title or record.record_id)[:80]
        path = cand_dir / f"LEAD_{safe}_RWS_format.txt"
        citation = record.citation_graph or {}
        lines = [
            f"publication: {record.publication_number or citation.get('target_publication', '') or record.record_id}",
            f"title: {record.raw_title or record.publication_number or record.record_id}",
            f"Dropdown: {record.evidence_type.value} lead",
            "Self-rank: 0/3",
            "In-scope confidence: low",
            f"  URL: {record.source_url}",
            f"  PDF URL: {record.document_url}",
            f"Source publication: {citation.get('source_publication', '')}",
            f"Target publication: {citation.get('target_publication', '')}",
            f"Hop count: {citation.get('hop_count', '')}",
            f"Relation confidence: {citation.get('relation_confidence', '')}",
            f"Duplicate status: {record.duplicate_status}",
            "Status: LEAD ONLY — retrieve and validate the underlying source document before surfacing",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_patent_lead(
        self, folder: Path, rec: PatentRecord, burned: dict[str, str] | None = None
    ) -> None:
        if not self._safe_to_surface(rec, burned):
            self.log(f"BLOCKED lead {rec.pub_id} — known art (hard gate)", "skip")
            return
        cand_dir = folder / "candidates"
        cand_dir.mkdir(exist_ok=True)
        safe = patent_key(rec.pub_id)
        path = cand_dir / f"LEAD_{safe}_RWS_format.txt"
        yes_count = sum(1 for r in rec.req_rows if r["select"] == "yes")
        maybe_count = sum(1 for r in rec.req_rows if r["select"] == "maybe")
        lines = [
            f"publication: {rec.pub_id}",
            f"title: {rec.title}",
            "Dropdown: Patent lead",
            f"Self-rank: {rec.self_rank}/3",
            f"In-scope confidence: {rec.confidence}",
            f"  URL: {rec.url}",
            f"  PDF URL: {rec.pdf_url}",
            f"Priority date: {rec.priority_date}",
            f"Publication date: {rec.publication_date}",
            f"Assignee: {rec.assignee}",
            f"Source lane: {rec.source_lane}",
            f"Requirement yes count: {yes_count}",
            f"Requirement maybe count: {maybe_count}",
            f"Duplicate status: {'burned' if rec.burned else 'clear'}",
            "Status: LEAD ONLY — needs stronger requirement support or validation before HOLD/READY",
            "",
            "Notes:",
            f"  - {rec.rank_reason or 'Partial technical match only.'}",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run_deep(self) -> dict:
        meta = STUDY_META[self.study_id]
        folder = REPO / meta["folder"]

        if meta.get("type") == "copyright" or not meta.get("patent"):
            self.log(
                f"{self.study_id} is a copyright-research study (no study patent) — "
                "the patent citation-graph hunt doesn't apply here. Work this study "
                "manually per its STUDY_BRIEF.md.",
                "warn",
            )
            return {"ready": 0, "inspected": 0, "note": "copyright-research study — no patent hunt to run"}

        critical = _parse_critical_date(self.study_id)
        critical_compact = critical.replace("-", "") if critical else None
        burned = load_burned(self.study_id)
        study_patent = meta["patent"]
        if not study_patent.startswith(("US", "EP", "WO")):
            study_patent = "US" + study_patent

        self.log(f"Starting DEEP hunt for {self.study_id} — {meta['title']}", "phase")
        self.log(
            f"Critical date ≤ {critical or 'unknown'} · {len(burned)} burned keys · "
            f"max inspect {MAX_INSPECT} · burn gate ON · READY (rank ≥2, med/high conf, PROOF, hard gates clear)",
            "info",
        )

        seen: set[str] = set()  # patent_key dedupe
        queue: list[tuple[str, str]] = []
        burned_skipped = 0

        # L1 — study patent backward citations (full list)
        self.log("L1: Study patent backward citations", "lane")
        root = fetch_patent(study_patent)
        time.sleep(0.35)
        for cite in root.citations[:L1_CITE_LIMIT]:
            if is_burned(cite, burned)[0]:
                burned_skipped += 1
            elif not self._queue_add(queue, seen, cite, "L1-backward-cite", burned):
                burned_skipped += 1
        self.lanes_done.append("L1")

        # L2 — citation, prosecution, and PTAB lead discovery
        self.log("L2: Citation, prosecution, and PTAB lead discovery", "lane")
        l2_runner = get_lane_runner("L2_PATENT_CITATIONS_PROSECUTION")
        l2_result = l2_runner.run(
            self.study_id,
            publication_number=study_patent,
            critical_date=critical,
            known_art_set=burned,
            citation_depth=1,
            root_record=root,
            fetch_patent_record=fetch_patent,
        )
        l2_queue_count = 0
        l2_lead_files = 0
        for evidence in l2_result.records:
            citation = evidence.citation_graph or {}
            target_pub = citation.get("target_publication") or evidence.publication_number
            if evidence.evidence_type is EvidenceType.PATENT and target_pub:
                added = self._queue_add(
                    queue,
                    seen,
                    target_pub,
                    f"L2-{citation.get('direction', 'citation')}",
                    burned,
                    provenance=citation,
                )
                if added:
                    l2_queue_count += 1
                continue
            if evidence.tier is EvidenceTier.LEAD:
                self._write_lane_lead(folder, evidence)
                l2_lead_files += 1
                self._update_candidate_screen(folder, ready, hold)
        self.log(
            f"  L2 leads: {len(l2_result.records)} records · {l2_queue_count} patent targets queued · {l2_lead_files} lead files",
            "info",
        )
        self.lanes_done.append("L2")

        # L2b — 2-hop citation expansion
        self.log("L2b: Citation graph 2-hop", "lane")
        hop1 = [p for p, s in queue if s.startswith("L1")][:L2_HOP1_LIMIT]
        hop2: list[str] = []
        for pub in hop1:
            if self.stopped:
                break
            rec = fetch_patent(pub)
            time.sleep(0.25)
            for cite in rec.citations[:L2_CITES_PER]:
                if self._queue_add(queue, seen, cite, f"L2b-via-{pub}", burned):
                    hop2.append(cite)
        self.log(f"  L2b hop-1: {len(hop1)} parents · {len(hop2)} new cites queued", "info")
        self.lanes_done.append("L2b")

        # L2c — 3-hop citation graph (deeper backward expansion)
        self.log("L2c: Citation graph 3-hop", "lane")
        for pub in hop2[:L2_HOP3_LIMIT]:
            if self.stopped:
                break
            rec = fetch_patent(pub)
            time.sleep(0.2)
            for cite in rec.citations[:12]:
                self._queue_add(queue, seen, cite, f"L2c-via-{pub}", burned)
        self.lanes_done.append("L2c")

        # L3 — assignee pre-date search
        self.log("L3: Assignee sweep (Google Patents search)", "lane")
        for asn in STUDY_META[self.study_id]["assignees"]:
            q = f'assignee:"{asn}"'
            hits = search_queries([q], before_priority=critical_compact, per_query=L3_PER_QUERY, pause=0.55)
            self.log(f"  {asn}: {len(hits)} pre-date hits", "info")
            for pub, _ in hits:
                self._queue_add(queue, seen, pub, f"L3-assignee-{asn}", burned)
        self.lanes_done.append("L3")

        # L4 — synonym lattice (12 queries)
        self.log("L4: Synonym lattice searches", "lane")
        queries = STUDY_META[self.study_id]["synonym_queries"]
        syn_hits = search_queries(queries, before_priority=critical_compact, per_query=L4_PER_QUERY, pause=0.4)
        self.log(f"  Synonym lattice: {len(syn_hits)} unique hits", "info")
        for pub, q in syn_hits:
            self._queue_add(queue, seen, pub, f"L4-syn:{q[:30]}", burned)
        self.lanes_done.append("L4")

        # L4b — CPC / classification targeted searches
        cpc_queries = STUDY_META[self.study_id]["cpc_queries"]
        if cpc_queries:
            self.log("L4b: CPC / classification searches", "lane")
            cpc_hits = search_queries(cpc_queries, before_priority=critical_compact, per_query=15, pause=0.45)
            self.log(f"  CPC lattice: {len(cpc_hits)} unique hits", "info")
            for pub, q in cpc_hits:
                self._queue_add(queue, seen, pub, f"L4b-cpc:{q[:24]}", burned)
            self.lanes_done.append("L4b")

        # L5 — NPL Crossref adjacent
        self.log("L5: NPL adjacent (Crossref)", "lane")
        npl_written = self._hunt_npl(folder, critical, burned)
        self.lanes_done.append("L5")

        # L6 — expand backward cites FROM known citations (seeds only — never resurface)
        self.log("L6: Known-citation graph seeds (find NEW art via old cites)", "lane")
        burned_skipped += self._expand_known_citation_seeds(queue, seen, burned)
        self.lanes_done.append("L6")

        # L7 — Product evidence search (Archive.org, YouTube, Reddit, Wayback)
        self.log("L7: Product evidence (Archive.org, YouTube, Reddit, Wayback)", "lane")
        product_hits = self._hunt_product_evidence(folder, critical, burned)
        self.log(f"  Product search: {product_hits} candidate sources found", "info")
        self.lanes_done.append("L7")

        self.log(
            f"Burn filter: {burned_skipped} known citations blocked from queue · "
            f"{len(queue)} NEW docs to inspect",
            "info",
        )
        self.log(f"Inspecting {len(queue)} queued patent documents…", "phase")
        ready: list[PatentRecord] = []
        hold: list[PatentRecord] = []

        queue.sort(key=lambda x: (0 if x[1].startswith("L4") else 1, x[1]))
        self.log(f"Queue sorted — inspecting up to {min(len(queue), MAX_INSPECT)} of {len(queue)} docs", "info")

        for pub, source in queue:
            if self.stopped:
                self.log("Hunt stopped by user", "warn")
                break
            if self.inspected >= MAX_INSPECT:
                self.log(f"Inspection cap {MAX_INSPECT} reached", "warn")
                break

            rec = fetch_patent(pub)
            time.sleep(0.2)
            rec.source_lane = source
            rec.citation_provenance = list(self.citation_provenance_by_pub.get(patent_key(pub), []))
            rec = burn_check(rec, self.study_id, burned)
            self.inspected += 1
            if self.inspected % 25 == 0:
                self.log(
                    f"… progress {self.inspected}/{min(len(queue), MAX_INSPECT)} inspected · "
                    f"{len(ready)} READY · {len(hold)} HOLD so far",
                    "info",
                )

            if is_study_patent(rec, self.study_id):
                self.log(f"SKIP {pub} — study patent", "skip")
                continue
            if rec.burned:
                self.log(f"SKIP {pub} — burned ({rec.burn_relation})", "skip")
                continue
            if not date_ok(rec, critical):
                self.log(f"SKIP {pub} — after critical date ({rec.priority_date})", "skip")
                continue

            rec = score_record(rec, self.study_id)
            self.results.append(rec)

            status = "READY" if rec.ready else f"rank {rec.self_rank}/{rec.confidence}"
            self.log(
                f"{'★' if rec.ready else '·'} {pub} — {rec.title[:50]}… [{status}] "
                f"req_yes={sum(1 for r in rec.req_rows if r['select']=='yes')} via {source}",
                "hit" if rec.ready else "info",
            )

            if rec.ready:
                if self._safe_to_surface(rec, burned):
                    ready.append(rec)
                    self._write_candidate(folder, rec, ready=True, burned=burned)
                    self._update_candidate_screen(folder, ready, hold)
                else:
                    self.log(f"BLOCKED write {pub} — known art (hard gate)", "skip")
            elif is_hold(rec.self_rank, rec.confidence):
                if self._safe_to_surface(rec, burned):
                    hold.append(rec)
                    self._write_candidate(folder, rec, ready=False, burned=burned)
                    self._update_candidate_screen(folder, ready, hold)
                else:
                    self.log(f"BLOCKED hold {pub} — known art (hard gate)", "skip")
            elif rec.score > 0:
                self._write_patent_lead(folder, rec, burned=burned)
                self._update_candidate_screen(folder, ready, hold)
                self.log(
                    f"  ↳ {pub} — weak ({rec.self_rank}/{rec.confidence}, "
                    f"yes={sum(1 for r in rec.req_rows if r['select']=='yes')})",
                    "skip",
                )

        demoted = regrade_stored_candidates(self.study_id, burned)
        if demoted:
            self.log(f"Regraded {demoted} prior READY file(s) → HOLD (stricter gate)", "info")

        self._update_candidate_screen(folder, ready, hold)
        self._update_hunt_log(folder)
        self.log(
            f"Hunt complete — inspected {self.inspected}, "
            f"{len(ready)} READY, {len(hold)} HOLD, {npl_written} NPL leads",
            "done" if ready else "phase",
        )
        return {
            "inspected": self.inspected,
            "ready": len(ready),
            "hold": len(hold),
            "npl": npl_written,
            "results": [self._rec_dict(r) for r in sorted(self.results, key=lambda x: -x.score)],
        }

    def _safe_to_surface(self, rec: PatentRecord, burned: dict[str, str] | None = None) -> bool:
        """Hard gate: never write a known citation to Angela's inbox."""
        burned = burned or load_burned(self.study_id)
        if rec.burned or is_burned(rec.pub_id, burned)[0]:
            return False
        if is_burned(rec.title, burned)[0]:
            return False
        if is_study_patent(rec, self.study_id):
            return False
        return True

    def _expand_known_citation_seeds(
        self,
        queue: list[tuple[str, str]],
        seen: set[str],
        burned: dict[str, str],
    ) -> int:
        """Use known citations as graph seeds; only NEW backward cites enter queue."""
        skipped = 0
        seeds = load_citation_seeds(self.study_id)
        self.log(f"  {len(seeds)} known citations as seeds — mining their backward cites", "info")
        for raw in seeds[:L6_SEED_LIMIT]:
            pub = _normalize_pub(raw)
            try:
                rec = fetch_patent(pub)
                time.sleep(0.2)
            except Exception:
                continue
            for cite in rec.citations[:L6_CITES_PER]:
                if is_burned(cite, burned)[0]:
                    skipped += 1
                elif not self._queue_add(queue, seen, cite, f"L6-seed-{pub}", burned):
                    skipped += 1
        return skipped

    def _hunt_npl(self, folder: Path, critical: str | None, burned: dict[str, str]) -> int:
        queries = STUDY_META[self.study_id]["npl_queries"]
        if not queries:
            return 0
        year = critical[:4] if critical else None
        cand_dir = folder / "candidates"
        cand_dir.mkdir(exist_ok=True)
        written = 0
        for q in queries:
            if self.stopped:
                break
            meta = crossref_lookup(q, year=year, before=critical)
            if meta.get("doi") in ("not found", "", None):
                continue
            doi = meta.get("doi", "")
            if is_burned(doi, burned)[0]:
                self.log(f"  SKIP NPL DOI burned: {doi}", "skip")
                continue
            if is_burned(q, burned)[0]:
                continue
            confidence, confidence_reason, matched_concepts = _npl_confidence_and_reason(q, meta, self.study_id)
            if confidence == "low" and len(matched_concepts) < 2:
                self.log(f"  SKIP NPL metadata mismatch: {doi} ({confidence_reason})", "skip")
                continue
            dropdown = _crossref_type_to_dropdown(meta)
            pdf_line, access_line = _npl_access_fields(meta)
            title = meta.get("title") or f"(Crossref lead for query: {q})"
            date_value = meta.get("publication_date") or f"<= {critical or 'critical date'}"
            safe = re.sub(r"[^A-Za-z0-9]+", "_", q)[:40]
            path = cand_dir / f"NPL_{safe}_RWS_format.txt"
            text = f"""Dropdown: {dropdown}
Downloadable PDF: {pdf_line}
Access: {access_line}

Self-rank: 1/3
In-scope confidence: {confidence}
(Bot: NPL lead — verify PDF + in-scope before surfacing to Angela.)

Form fields:
  title: {title}
  authors: {meta.get('authors') or 'not found'}
  journal: {meta.get('journal') or 'not found'}
  DOI: {meta.get('doi')}
  ISSN: not found
  publisher: {meta.get('publisher') or 'not found'}
  date: ≤ {critical or 'critical date'}
  URL: {meta.get('url') or 'not found'}

Select these requirements:
| Requirement | Select? | Why |
|---|---|---|
| (map after PDF read) | maybe | NPL lead only — read full text |

Ctrl+F phrases:
  - (search PDF after download)

Highlight only this:
  - Requirement : (anchor after PDF read)

Do NOT select:
  - All reqs until PDF verified

Notes:
  - NPL adjacent lead from Crossref query: {q}
  - Crossref type: {meta.get('type') or 'unknown'}
  - Scope check: {confidence_reason}
  - Matched concepts: {', '.join(matched_concepts) if matched_concepts else 'none'}
  - Hunt engine {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""
            path.write_text(text, encoding="utf-8")
            written += 1
            self.log(f"  NPL lead: {meta['doi']} ({q[:40]})", "info")
            time.sleep(0.3)
        return written


    def _hunt_product_evidence(self, folder: Path, critical: str | None, burned: dict[str, str]) -> int:
        """Search Archive.org, YouTube, Reddit, Wayback for product evidence."""
        if not critical:
            return 0
        
        # Extract keywords from study metadata
        meta = STUDY_META[self.study_id]
        product_keywords = []
        technical_terms = []
        
        # Extract from title and description
        title_lower = meta["title"].lower()
        if "blender" in title_lower:
            product_keywords.extend(["blender", "food processor", "mixer"])
            technical_terms.extend(["offset blade", "eccentric rotor", "tornado effect", "vortex mixing"])
        elif "battery" in title_lower or "rechargeable" in title_lower:
            product_keywords.append("rechargeable")
        
        # Add generic terms from synonym queries
        for q in meta.get("synonym_queries", [])[:5]:
            terms = q.lower().split()
            for term in terms:
                if len(term) > 4 and term not in ["patent", "prior", "device"]:
                    if term not in technical_terms:
                        technical_terms.append(term)
        
        if not product_keywords:
            product_keywords = ["product", "device"]
        
        # Search product sources
        try:
            results = search_product_evidence(
                product_keywords=product_keywords[:3],
                technical_terms=technical_terms[:5],
                before_date=critical,
                max_per_source=10,
                log_fn=self.log,
            )
        except Exception as e:
            self.log(f"Product search error: {e}", "warn")
            return 0
        
        # Write candidates
        cand_dir = folder / "candidates"
        cand_dir.mkdir(exist_ok=True)
        written = 0
        
        # Archive.org results
        for item in results.get("archive_org", [])[:15]:
            if is_burned(item["identifier"], burned)[0]:
                continue
            safe_title = re.sub(r"[^\w]+", "_", item["title"][:40])
            path = cand_dir / f"PRODUCT_archive_{safe_title}_RWS_format.txt"
            content = self._draft_product_candidate(item, "Archive.org", critical)
            path.write_text(content, encoding="utf-8")
            written += 1
            self.log(f"  Product: {item['title'][:50]} (Archive.org {item['year']})", "info")
        
        # YouTube results
        for item in results.get("youtube", [])[:10]:
            if is_burned(item["video_id"], burned)[0]:
                continue
            safe_title = re.sub(r"[^\w]+", "_", item["title"][:40])
            path = cand_dir / f"PRODUCT_youtube_{safe_title}_RWS_format.txt"
            content = self._draft_product_candidate(item, "YouTube", critical)
            path.write_text(content, encoding="utf-8")
            written += 1
            self.log(f"  Product: {item['title'][:50]} (YouTube {item['published_date']})", "info")
        
        # Reddit results
        for item in results.get("reddit", [])[:10]:
            if is_burned(item["url"], burned)[0]:
                continue
            safe_title = re.sub(r"[^\w]+", "_", item["title"][:40])
            path = cand_dir / f"PRODUCT_reddit_{safe_title}_RWS_format.txt"
            content = self._draft_product_candidate(item, "Reddit", critical)
            path.write_text(content, encoding="utf-8")
            written += 1
            self.log(f"  Product: {item['title'][:50]} (Reddit {item['created_date']})", "info")
        
        # Wayback results (sample only - too many snapshots)
        wayback_items = results.get("wayback", [])
        if wayback_items:
            # Group by domain and take earliest snapshot per domain
            by_domain = {}
            for item in wayback_items:
                domain = item["original_url"].split("/")[0]
                if domain not in by_domain or item["date"] < by_domain[domain]["date"]:
                    by_domain[domain] = item
            
            for domain, item in list(by_domain.items())[:5]:
                safe_domain = re.sub(r"[^\w]+", "_", domain)
                path = cand_dir / f"PRODUCT_wayback_{safe_domain}_{item['date']}_RWS_format.txt"
                content = self._draft_product_candidate(item, "Wayback Machine", critical)
                path.write_text(content, encoding="utf-8")
                written += 1
                self.log(f"  Product: {domain} snapshot ({item['date']})", "info")
        
        # MusicBrainz results (recordings - perfect for hymns)
        for item in results.get("musicbrainz", [])[:10]:
            if is_burned(item["recording_id"], burned)[0]:
                continue
            safe_title = re.sub(r"[^\w]+", "_", item["title"][:40])
            path = cand_dir / f"MUSIC_musicbrainz_{safe_title}_RWS_format.txt"
            content = self._draft_music_candidate(item, "MusicBrainz", critical)
            path.write_text(content, encoding="utf-8")
            written += 1
            self.log(f"  Music: {item['title'][:50]} by {item['artist']} ({item['release_date']})", "info")
        
        # Discogs results (album releases)
        for item in results.get("discogs", [])[:10]:
            if is_burned(item["url"], burned)[0]:
                continue
            safe_title = re.sub(r"[^\w]+", "_", item["title"][:40])
            path = cand_dir / f"MUSIC_discogs_{safe_title}_RWS_format.txt"
            content = self._draft_music_candidate(item, "Discogs", critical)
            path.write_text(content, encoding="utf-8")
            written += 1
            self.log(f"  Music: {item['title'][:50]} ({item['year']}, {item['format']})", "info")
        
        return written

    def _draft_product_candidate(self, item: dict, source: str, critical: str) -> str:
        """Draft a product evidence candidate in RWS format."""
        lines = [
            "Type: Product Evidence / NPL",
            f"Source: {source}",
            f"Title: {item.get('title', 'Unknown')}",
            f"URL: {item.get('url', 'N/A')}",
            f"Date: {item.get('year', item.get('date', item.get('published_date', item.get('created_date', 'unknown'))))}",
            f"Critical Date: ≤ {critical}",
            "",
            "Status: UNVERIFIED — manually review source, verify date, extract technical details, take screenshots",
            "",
            "Description:",
            item.get("description", item.get("selftext", "No description available"))[:300],
            "",
            "Next Steps:",
            "1. Visit URL and verify content is accessible",
            "2. Confirm publication/creation date is before critical date",
            "3. Extract technical specifications (blade offset, dimensions, etc.)",
            "4. Take screenshots showing relevant technical details",
            "5. Map to study requirements",
            "6. If valid, format as proper RWS submission with screenshots",
            "",
            f"Hunt engine {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ]
        return "\n".join(lines)

    def _draft_music_candidate(self, item: dict, source: str, critical: str) -> str:
        """Draft a music recording candidate in RWS format (for hymn research)."""
        lines = [
            "Type: Music Recording / NPL",
            f"Source: {source}",
            f"Title: {item.get('title', 'Unknown')}",
            f"Artist: {item.get('artist', 'Unknown')}",
            f"URL: {item.get('url', 'N/A')}",
            f"Release Date: {item.get('release_date', item.get('year', 'unknown'))}",
            f"Critical Date: ≤ {critical}",
            "",
        ]
        
        # Add source-specific details
        if source == "MusicBrainz":
            lines.append(f"Recording ID: {item.get('recording_id', 'N/A')}")
        elif source == "Discogs":
            lines.extend([
                f"Format: {item.get('format', 'Unknown')}",
                f"Label: {item.get('label', 'Unknown')}",
            ])
        
        lines.extend([
            "",
            "Status: UNVERIFIED — manually review recording, verify release date, confirm hymn matches study",
            "",
            "Next Steps:",
            "1. Visit URL and listen to recording (if available)",
            "2. Confirm release date is before critical date",
            "3. Verify hymn title and language match study requirements",
            "4. Check for lyrics/sheet music in description or linked resources",
            "5. Take screenshots of recording metadata (title, artist, date)",
            "6. If valid, format as proper RWS submission with evidence",
            "",
            f"Hunt engine {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ])
        return "\n".join(lines)

    def _rec_dict(self, rec: PatentRecord) -> dict:
        return {
            "pub_id": rec.pub_id,
            "title": rec.title,
            "assignee": rec.assignee,
            "priority_date": rec.priority_date,
            "score": rec.score,
            "self_rank": rec.self_rank,
            "confidence": rec.confidence,
            "ready": rec.ready,
            "burned": rec.burned,
            "keywords": rec.matched_keywords,
            "rank_reason": rec.rank_reason,
            "evidence_tier": rec.evidence_tier,
            "evidence_score": rec.evidence_score,
            "hard_gate_failures": rec.hard_gate_failures,
            "url": rec.url,
        }

    def _write_candidate(
        self, folder: Path, rec: PatentRecord, ready: bool = True, burned: dict[str, str] | None = None
    ) -> None:
        if not self._safe_to_surface(rec, burned):
            self.log(f"REFUSED write {rec.pub_id} — known art", "error")
            return
        cand_dir = folder / "candidates"
        cand_dir.mkdir(exist_ok=True)
        safe = patent_key(rec.pub_id)
        prefix = "" if ready else "HOLD_"
        path = cand_dir / f"{prefix}{safe}_RWS_format.txt"
        candidate_text = draft_candidate(rec, self.study_id)
        path.write_text(candidate_text, encoding="utf-8")
        if ready:
            bundle_dir = cand_dir / "proof_bundles" / safe
            write_ready_proof_bundle(
                bundle_dir,
                candidate_text=candidate_text,
                source_snapshot_html=rec.source_snapshot_html,
                metadata=_proof_bundle_metadata(rec, self.study_id),
            )
        tier = "READY" if ready else "HOLD"
        self.log(f"Wrote {tier} → {path.name}", "success")

    def _library_counts(self, folder: Path) -> dict[str, int]:
        cand_dir = folder / "candidates"
        counts = {"ready": 0, "hold": 0, "lead": 0}
        if not cand_dir.exists():
            return counts
        for path in cand_dir.glob("*_RWS_format.txt"):
            name = path.name
            if name.startswith("HOLD_"):
                counts["hold"] += 1
            elif name.startswith(("NPL_", "PRODUCT_", "MUSIC_", "LEAD_")):
                counts["lead"] += 1
            else:
                counts["ready"] += 1
        return counts

    def _update_candidate_screen(
        self, folder: Path, ready: list[PatentRecord], hold: list[PatentRecord]
    ) -> None:
        screen = folder / "CANDIDATE_SCREEN.md"
        today = datetime.now().strftime("%Y-%m-%d %H:%M")
        library = self._library_counts(folder)
        lines = [
            f"# Candidate Screen — updated {today}",
            "",
            (
                f"Inspected: {self.inspected} · READY this run: {len(ready)} · HOLD this run: {len(hold)}"
            ),
            (
                f"Library: {library['lead']} LEAD · {library['hold']} HOLD · {library['ready']} READY"
            ),
            "",
            "## READY (Self-rank ≥2, high/med)",
            "",
        ]
        if ready:
            for r in sorted(ready, key=lambda x: -x.score):
                lines.append(
                    f"- **{r.pub_id}** — {r.title[:70]} · "
                    f"[PDF]({r.pdf_url}) · [Google]({r.url}) · lane {r.source_lane}"
                )
        else:
            lines.append("- (none this round)")
        lines += ["", "## HOLD (rank 1 — verify before surfacing)", ""]
        if hold:
            for r in sorted(hold, key=lambda x: -x.score)[:15]:
                lines.append(f"- {r.pub_id} — {r.title[:60]} · rank {r.self_rank}")
        else:
            lines.append("- (none)")
        screen.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _update_hunt_log(self, folder: Path) -> None:
        log_path = folder / "HUNT_LOG.md"
        today = datetime.now().strftime("%Y-%m-%d")
        ready = sum(1 for r in self.results if r.ready)
        row = (
            f"| {today} | {', '.join(self.lanes_done[:4])} | {self.inspected} | "
            f"{ready} | continue |"
        )
        if log_path.exists():
            text = log_path.read_text(encoding="utf-8")
            if "— | — | — | — | — |" in text:
                text = text.replace(
                    "| — | — | — | — | — |",
                    row,
                    1,
                )
            else:
                text = text.replace(
                    "|------|-----------------|----------------|---------------------|-----------|",
                    "|------|-----------------|----------------|---------------------|-----------|\n" + row,
                    1,
                )
            # tick lanes — match by lane number only, so wording can differ per study
            for i in range(1, 8):
                if f"L{i}" in str(self.lanes_done):
                    text = re.sub(rf"(?m)^- \[ \] (L{i}\b.*)$", r"- [x] \1", text, count=1)
            log_path.write_text(text, encoding="utf-8")
