#!/usr/bin/env python3
"""Brief-driven keyword and query expansion for study metadata."""

from __future__ import annotations

import copy
import re
from pathlib import Path

_ANCHOR_TERMS = (
    "solvent",
    "solubilization",
    "solubilisation",
    "solubilizer",
    "solubiliser",
    "depigment",
    "whitening",
    "lightening",
    "brightening",
    "resorcinol",
    "sarcosinate",
    "thiamidol",
    "melanin",
    "tyrosinase",
    "alkylamidothiazole",
    "thiazolyl",
    "phenylethyl",
    "cosmetic",
    "dermatological",
    "poster",
    "conference",
    "dissertation",
    "thesis",
    "product literature",
)

_GENERIC_BAD_PHRASES = {
    "added on",
    "research requirement",
    "study patent",
    "latest date for responses",
    "questions or comments",
    "reward structure",
}

_KEYWORD_STOPWORDS = {
    "after",
    "agent",
    "agents",
    "and",
    "before",
    "broad",
    "broader",
    "could",
    "date",
    "disclosure",
    "exactly",
    "focus",
    "following",
    "good",
    "interested",
    "into",
    "lead",
    "like",
    "note",
    "please",
    "preferably",
    "particularly",
    "requirement",
    "research",
    "same",
    "seeing",
    "study",
    "thank",
    "that",
    "this",
    "would",
}

_RELATION_PATTERNS = (
    re.compile(
        r"(?i)(?P<a>[A-Za-z0-9'()/,\-\s]{4,90}?)\s+with\s+(?P<b>[A-Za-z0-9'()/,\-\s]{4,120}?)(?:[.;\n]|,\s*(?:preferably|before|for|and)\b)"
    ),
    re.compile(
        r"(?i)explicit disclosure that\s+(?P<a>[A-Za-z0-9'()/,\-\s]{4,90}?)\s+is a good\s+"
        r"(?P<role>solvent|solubilizer|solubiliser)\s+for\s+(?P<b>[A-Za-z0-9'()/,\-\s]{4,120}?)(?:[.;\n]|$)"
    ),
    re.compile(
        r"(?i)ingredients?\s+(?:promoting|favoring|favouring)\s+(?:the\s+)?solubili[sz]ation\s+of\s+"
        r"(?P<b>[A-Za-z0-9'()/,\-\s]{4,120}?)(?:[.;\n]|$)"
    ),
)


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        clean = re.sub(r"\s+", " ", item).strip(" \"'.,;:-")
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _split_paragraphs(text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", text)
    return [re.sub(r"\s+", " ", block).strip() for block in blocks if block.strip()]


def _split_sentences(text: str) -> list[str]:
    raw = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [re.sub(r"\s+", " ", part).strip() for part in raw if len(part.strip()) >= 12]


def _clean_fragment(text: str) -> str:
    text = re.sub(r"(?i)^added on \d{1,2} [a-z]+ \d{4}\s*", "", text).strip()
    text = re.sub(r"(?i)^please note that\s*", "", text).strip()
    text = re.sub(r"(?i)^please focus your efforts on finding\s*", "", text).strip()
    text = re.sub(r"(?i)^we are also interested in seeing\s*", "", text).strip()
    text = re.sub(r"(?i)^we are particularly interested in\s*", "", text).strip()
    text = re.sub(r"(?i)^a combination of\s*", "", text).strip()
    text = re.sub(r"(?i)^combination of\s*", "", text).strip()
    text = re.sub(r"(?i)\s*\(preferably before[^)]*\)", "", text).strip()
    text = re.sub(r"(?i)\s+for research requirement \d+\b.*$", "", text).strip()
    text = re.sub(r"(?i)\s+as long as the solvent is exactly the same.*$", "", text).strip()
    text = re.sub(r"\s+", " ", text).strip(" ,.;:-")
    return text


def _extract_quoted_phrases(text: str) -> list[str]:
    phrases = re.findall(r'"([^"\n]{4,120})"', text)
    phrases += re.findall(r"\*\*([^*\n]{4,120})\*\*", text)
    return _dedupe(phrases)


def _extract_anchor_phrases(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9'()/\-]+", text)
    phrases: list[str] = []
    for size in range(2, 7):
        for idx in range(0, max(0, len(words) - size + 1)):
            phrase = " ".join(words[idx : idx + size]).strip()
            lower = phrase.lower()
            if any(bad in lower for bad in _GENERIC_BAD_PHRASES):
                continue
            if any(anchor in lower for anchor in _ANCHOR_TERMS):
                phrases.append(phrase)
    return _dedupe(phrases)


def _extract_relations(text: str) -> list[dict[str, str]]:
    relations: list[dict[str, str]] = []
    for sentence in _split_sentences(text):
        for pattern in _RELATION_PATTERNS:
            for match in pattern.finditer(sentence):
                a = _clean_fragment(match.groupdict().get("a", ""))
                b = _clean_fragment(match.groupdict().get("b", ""))
                role = (match.groupdict().get("role") or "").lower()
                if len(a) > 90 or len(b) > 120:
                    continue
                if not a and not b:
                    continue
                relations.append({"a": a, "b": b, "role": role})
    return relations


def _extract_assignees(text: str) -> list[str]:
    hits = []
    for raw in re.findall(r"(?i)products?\s+from\s+([A-Z][A-Za-z0-9&.\- ]{2,60})", text):
        hits.append(_clean_fragment(re.split(r"[.,;]", raw)[0]))
    return _dedupe(hits)


def _build_keyword_pool(text: str) -> list[str]:
    phrases = _extract_quoted_phrases(text)
    phrases += _extract_anchor_phrases(text)
    for relation in _extract_relations(text):
        if relation["a"]:
            phrases.append(relation["a"])
        if relation["b"]:
            phrases.append(relation["b"])
    for token in re.findall(r"[A-Za-z][A-Za-z0-9'()/\-]{3,}", text):
        lower = token.lower()
        if lower in _KEYWORD_STOPWORDS:
            continue
        if any(anchor in lower for anchor in _ANCHOR_TERMS):
            phrases.append(lower)
    return _dedupe(phrases)


def _build_query_expansions(text: str) -> tuple[list[str], list[str]]:
    synonym_queries: list[str] = []
    npl_queries: list[str] = []
    relations = _extract_relations(text)
    wants_npl = bool(re.search(r"(?i)\b(dissertations?|conference abstracts?|posters?|product literature)\b", text))
    npl_terms = [term for term in ("dissertation", "conference abstract", "poster", "product literature") if term in text.lower()]

    for relation in relations:
        a = relation["a"]
        b = relation["b"]
        role = relation["role"]
        if a and b:
            synonym_queries.append(f"\"{a}\" \"{b}\"")
            synonym_queries.append(f"\"{a}\" solvent \"{b}\"")
            synonym_queries.append(f"\"{a}\" solubilization \"{b}\"")
        elif b:
            synonym_queries.append(f"solubilization \"{b}\"")
        if wants_npl:
            bases = [query for query in synonym_queries[-3:] if query]
            for base in bases:
                for doc_type in npl_terms or ["conference abstract", "poster", "dissertation"]:
                    npl_queries.append(f"{base} {doc_type}")

    if re.search(r"(?i)\bproducts?\s+from\b", text):
        for assignee in _extract_assignees(text):
            for phrase in _build_keyword_pool(text)[:6]:
                if len(phrase.split()) <= 6:
                    synonym_queries.append(f"\"{assignee}\" {phrase}")
                    if wants_npl:
                        npl_queries.append(f"\"{assignee}\" {phrase} product literature")

    return _dedupe(synonym_queries), _dedupe(npl_queries)


def extract_requirements_from_brief_text(brief_text: str) -> list[dict]:
    """Extract numbered requirements from a raw study brief."""
    requirements: list[dict] = []

    section_match = re.search(
        r"(?is)research requirements(.+?)(?:reward structure|questions or comments|study guidelines|\Z)",
        brief_text,
    )
    section = section_match.group(1) if section_match else brief_text
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if re.fullmatch(r"\d+", line):
            req_id = line
            idx += 1
            body_parts: list[str] = []
            while idx < len(lines) and not re.fullmatch(r"\d+", lines[idx]):
                if re.match(r"(?i)^(latest date|relevant patent dates|us patent date|publication date|ep date|other patent authorities)$", lines[idx]):
                    idx += 1
                    continue
                body_parts.append(lines[idx])
                idx += 1
            body = re.sub(r"\s+", " ", " ".join(body_parts)).strip()
            if len(body) >= 6:
                requirements.append(
                    {
                        "id": req_id,
                        "name": body,
                        "keywords": _build_keyword_pool(body),
                    }
                )
            continue
        idx += 1

    if requirements:
        return requirements

    for match in re.finditer(r"(?im)^\s*[-*]\s*\*\*RR(\d+)\*\*\s*[—-]\s*(.+)$", brief_text):
        req_id = match.group(1)
        body = re.sub(r"\s+", " ", match.group(2)).strip()
        requirements.append(
            {
                "id": req_id,
                "name": body,
                "keywords": _build_keyword_pool(body),
            }
        )
    return requirements


def augment_meta_from_brief(meta: dict, brief_path: Path) -> dict:
    """Return study metadata augmented from the raw brief text."""
    if not brief_path.exists():
        return meta

    brief_text = brief_path.read_text(encoding="utf-8", errors="replace")
    augmented = copy.deepcopy(meta)

    if not augmented.get("requirements"):
        augmented["requirements"] = extract_requirements_from_brief_text(brief_text)
    if not augmented.get("priority_req_ids") and augmented.get("requirements"):
        augmented["priority_req_ids"] = [req["id"] for req in augmented["requirements"]]

    study_keywords = list(augmented.get("keywords", []))
    study_keywords.extend(_build_keyword_pool(brief_text))
    augmented["keywords"] = _dedupe(study_keywords)

    synonym_queries = list(augmented.get("synonym_queries", []))
    npl_queries = list(augmented.get("npl_queries", []))
    extra_synonyms, extra_npl = _build_query_expansions(brief_text)
    synonym_queries.extend(extra_synonyms)
    npl_queries.extend(extra_npl)
    augmented["synonym_queries"] = _dedupe(synonym_queries)
    augmented["npl_queries"] = _dedupe(npl_queries)

    assignees = list(augmented.get("assignees", []))
    assignees.extend(_extract_assignees(brief_text))
    augmented["assignees"] = _dedupe(assignees)

    extracted_requirement_map = {
        str(req["id"]): req for req in extract_requirements_from_brief_text(brief_text)
    }
    reqs = []
    for req in augmented.get("requirements", []):
        req_copy = copy.deepcopy(req)
        extracted = extracted_requirement_map.get(str(req_copy.get("id", "")))
        if extracted:
            req_keywords = list(req_copy.get("keywords", []))
            req_keywords.extend(extracted.get("keywords", []))
            req_copy["keywords"] = _dedupe(req_keywords)
        reqs.append(req_copy)
    augmented["requirements"] = reqs
    return augmented
