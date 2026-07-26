#!/usr/bin/env python3
"""Automated search engine for copyright-research (hymn translation) studies.

Patent studies have citation-graph APIs to crawl (patent_hunter.py). Hymn
translation studies don't have an equivalent structured graph — finding an
existing Russian/Italian/Cebuano translation of a named hymn means searching
real archives. This hits two keyless, real APIs (Internet Archive full-text
search, Google Books) per hymn and surfaces candidate sources.

It does NOT auto-verify a hit actually contains the correct translation,
the translator's name, or a usable date — that requires reading the actual
source, which is exactly what RWS's submission rules require a human/agent
to confirm anyway (real screenshots, real bibliographic details, no
guessing). This engine's job is to turn "manually search 125 hymns one at
a time" into "review N pre-queried candidate sources per hymn."
"""

from __future__ import annotations

import json
import hashlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable
from repo_paths import REPO_ROOT, SCRIPTS_DIR

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO = REPO_ROOT
sys.path.insert(0, str(SCRIPTS_DIR))
from study_bot import STUDY_META  # noqa: E402

LogFn = Callable[[str, str], None]

IA_SEARCH_URL = "https://archive.org/advancedsearch.php"
GB_SEARCH_URL = "https://www.googleapis.com/books/v1/volumes"
HATHI_SEARCH_URL = "https://catalog.hathitrust.org/api/volumes/brief/json"
WORLDCAT_SEARCH_URL = "http://www.worldcat.org/search"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_PAUSE = 0.5
REQUEST_TIMEOUT = 8
MAX_HYMNS_PER_ROUND = 125
LOW_SIGNAL_TITLE_PATTERNS = (
    "rock pop folk songs",
    "singer's library of song",
    "liederprojekt",
)
HYMNAL_SIGNAL_TERMS = (
    "hymn",
    "hymnal",
    "cantici",
    "innario",
    "laudario",
    "gesangbuch",
    "cantique",
    "himnario",
    "hinario",
    "himny",
)

LANGUAGE_QUERY_TERMS = {
    "Italian": '"Italian" OR italiano OR italiana',
    "Russian": '"Russian" OR russkii OR русский',
    "Cebuano": '"Cebuano" OR Binisaya OR Bisaya OR Sebwano OR Visayan',
}


def _get_json(url: str, timeout: int = REQUEST_TIMEOUT) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _ia_search(query: str, rows: int) -> list[dict]:
    params = {
        "q": query,
        "fl[]": ["identifier", "title"],
        "rows": str(rows),
        "page": "1",
        "output": "json",
    }
    url = IA_SEARCH_URL + "?" + urllib.parse.urlencode(params, doseq=True)
    try:
        data = _get_json(url)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return []
    out = []
    for d in data.get("response", {}).get("docs", []):
        ident = d.get("identifier")
        if not ident:
            continue
        out.append(
            {
                "source": "archive.org",
                "title": d.get("title") or ident.replace("-", " ").replace("_", " "),
                "url": f"https://archive.org/details/{ident}",
            }
        )
    return out


def search_hymnal_sources(language: str, rows: int = 8) -> list[dict]:
    """One broad search per language for actual hymnal books — this is the
    highest-signal query: restricting to mediatype:(texts) (verified live —
    excludes the radio/sermon-audio noise that dominates plain full-text
    search) and searching for the hymnal itself rather than one English
    title, which foreign-language hymnal metadata won't usually contain.
    """
    seen_urls: set[str] = set()
    out: list[dict] = []
    lang_expr = LANGUAGE_QUERY_TERMS.get(language, f'"{language}"')
    queries = (
        f'({lang_expr}) AND (hymnal OR hymnbook OR hymn book) AND mediatype:(texts)',
        f'({lang_expr}) AND (awit OR himno OR canticle OR songs) AND mediatype:(texts)',
    )
    for q in queries:
        for hit in _ia_search(q, rows):
            if hit["url"] not in seen_urls:
                seen_urls.add(hit["url"])
                out.append(hit)
    return out


def search_internet_archive(hymn_title: str, language: str, rows: int = 5) -> list[dict]:
    """Per-hymn search — lower yield than search_hymnal_sources() since a
    foreign hymnal's own metadata rarely contains the English title, but
    occasionally surfaces a direct hit (verified live against real hymn
    titles). mediatype:(texts) is required — without it, results are
    dominated by radio broadcast / sermon audio transcripts that merely
    co-mention the title and the language name.
    """
    # Add language-specific keywords to filter out English sources
    lang_keywords = {
        "Italian": "inno OR innario OR canto",
        "Russian": "гимн OR песня",
        "Cebuano": "awit OR himno",
        "Spanish": "himno OR himnario OR canto",
        "Portuguese": "hino OR hinário",
        "French": "hymne OR cantique",
        "German": "Lied OR Gesangbuch",
        "Chinese": "赞美诗 OR 圣诗",
        "Japanese": "賛美歌",
        "Korean": "찬송가",
        "Hindi": "भजन OR स्तुति",
        "Tamil": "பாடல் OR துதி",
        "Telugu": "కీర్తన OR స్తుతి",
        "Bengali": "গান OR স্তুতি",
        "Marathi": "भजन OR स्तुति",
        "Tagalog": "awit OR himno",
        "Vietnamese": "bài hát OR thánh ca",
        "Thai": "เพลง OR สวด",
        "Indonesian": "lagu OR himne",
        "Malay": "lagu OR himne",
        "Swahili": "wimbo OR sifa",
        "Arabic": "ترنيمة OR تسبيح",
        "Hebrew": "שיר OR תהילה",
        "Polish": "pieśń OR hymn",
        "Ukrainian": "пісня OR гімн",
        "Dutch": "lied OR hymne",
        "Swedish": "sång OR psalm",
        "Norwegian": "sang OR salme",
        "Danish": "sang OR salme",
        "Finnish": "laulu OR virsi"
    }
    extra = lang_keywords.get(language, "")
    lang_expr = LANGUAGE_QUERY_TERMS.get(language, f'"{language}"')
    if extra:
        query = f'"{hymn_title}" AND ({lang_expr}) AND ({extra}) AND mediatype:(texts)'
    else:
        query = f'"{hymn_title}" AND ({lang_expr}) AND mediatype:(texts)'
    return _ia_search(query, rows)


def search_google_books(hymn_title: str, language: str, language_code: str | None, rows: int = 5) -> list[dict]:
    """Real, keyless (free-tier) search against the Google Books API."""
    # Add language-specific keywords to improve relevance
    lang_keywords = {
        "Italian": "inno OR innario",
        "Russian": "гимн",
        "Cebuano": "awit OR himno",
        "Spanish": "himno OR himnario",
        "Portuguese": "hino OR hinário",
        "French": "hymne OR cantique",
        "German": "Lied OR Gesangbuch",
        "Chinese": "赞美诗 OR 圣诗",
        "Japanese": "賛美歌",
        "Korean": "찬송가",
        "Hindi": "भजन OR स्तुति",
        "Tamil": "பாடல் OR துதி",
        "Telugu": "కీర్తన OR స్తుతి",
        "Bengali": "গান OR স্তুতি",
        "Marathi": "भजन OR स्तुति",
        "Tagalog": "awit OR himno",
        "Vietnamese": "bài hát OR thánh ca",
        "Thai": "เพลง OR สวด",
        "Indonesian": "lagu OR himne",
        "Malay": "lagu OR himne",
        "Swahili": "wimbo OR sifa",
        "Arabic": "ترنيمة OR تسبيح",
        "Hebrew": "שיר OR תהילה",
        "Polish": "pieśń OR hymn",
        "Ukrainian": "пісня OR гімн",
        "Dutch": "lied OR hymne",
        "Swedish": "sång OR psalm",
        "Norwegian": "sang OR salme",
        "Danish": "sang OR salme",
        "Finnish": "laulu OR virsi"
    }
    extra = lang_keywords.get(language, "hymnal")
    lang_expr = LANGUAGE_QUERY_TERMS.get(language, f'"{language}"')
    query = f'"{hymn_title}" {lang_expr} {extra}'
    params = {"q": query, "maxResults": str(rows)}
    if language_code:
        params["langRestrict"] = language_code
    url = GB_SEARCH_URL + "?" + urllib.parse.urlencode(params)
    try:
        data = _get_json(url)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return []
    out = []
    for item in data.get("items", []) or []:
        info = item.get("volumeInfo", {})
        title = info.get("title", "")
        link = info.get("infoLink") or info.get("canonicalVolumeLink") or ""
        if not title or not link:
            continue
        year = (info.get("publishedDate") or "")[:4]
        out.append(
            {
                "source": "google_books",
                "title": f"{title} ({year})" if year else title,
                "url": link,
            }
        )
    return out


def search_hathitrust(hymn_title: str, language: str, rows: int = 5) -> list[dict]:
    """Search HathiTrust Digital Library catalog."""
    lang_keywords = {
        "Italian": "inno innario",
        "Russian": "гимн",
        "Cebuano": "awit himno",
        "Spanish": "himno himnario",
        "Portuguese": "hino hinário",
        "French": "hymne cantique",
        "German": "Lied Gesangbuch",
        "Chinese": "赞美诗",
        "Japanese": "賛美歌",
        "Korean": "찬송가",
        "Hindi": "भजन स्तुति",
        "Tamil": "பாடல் துதி",
        "Telugu": "కీర్తన స్తుతి",
        "Bengali": "গান স্তুতি",
        "Marathi": "भजन स्तुति",
        "Tagalog": "awit himno",
        "Vietnamese": "bài hát thánh ca",
        "Thai": "เพลง สวด",
        "Indonesian": "lagu himne",
        "Malay": "lagu himne",
        "Swahili": "wimbo sifa",
        "Arabic": "ترنيمة تسبيح",
        "Hebrew": "שיר תהילה",
        "Polish": "pieśń hymn",
        "Ukrainian": "пісня гімн",
        "Dutch": "lied hymne",
        "Swedish": "sång psalm",
        "Norwegian": "sang salme",
        "Danish": "sang salme",
        "Finnish": "laulu virsi"
    }
    extra = lang_keywords.get(language, "hymnal")
    lang_expr = LANGUAGE_QUERY_TERMS.get(language, f'"{language}"')
    query = f'"{hymn_title}" {lang_expr} {extra}'
    
    # HathiTrust catalog search (web scraping fallback since API requires auth)
    search_url = f"https://catalog.hathitrust.org/Search/Home?lookfor={urllib.parse.quote(query)}&type=all"
    
    try:
        req = urllib.request.Request(search_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        
        # Simple extraction - look for result links
        import re
        results = []
        matches = re.findall(r'<a[^>]+href="(/Record/\d+)"[^>]*>([^<]+)</a>', html)
        for path, title in matches[:rows]:
            results.append({
                "source": "hathitrust",
                "title": title.strip(),
                "url": f"https://catalog.hathitrust.org{path}"
            })
        return results
    except (urllib.error.URLError, TimeoutError, ValueError):
        return []


def search_worldcat(hymn_title: str, language: str, rows: int = 3) -> list[dict]:
    """Search WorldCat library catalog."""
    lang_keywords = {
        "Italian": "inno",
        "Russian": "гимн",
        "Cebuano": "awit",
        "Spanish": "himno",
        "Portuguese": "hino",
        "French": "hymne",
        "German": "Lied",
        "Chinese": "赞美诗",
        "Japanese": "賛美歌",
        "Korean": "찬송가",
        "Hindi": "भजन",
        "Tamil": "பாடல்",
        "Telugu": "కీర్తన",
        "Bengali": "গান",
        "Marathi": "भजन",
        "Tagalog": "awit",
        "Vietnamese": "bài hát",
        "Thai": "เพลง",
        "Indonesian": "lagu",
        "Malay": "lagu",
        "Swahili": "wimbo",
        "Arabic": "ترنيمة",
        "Hebrew": "שיר",
        "Polish": "pieśń",
        "Ukrainian": "пісня",
        "Dutch": "lied",
        "Swedish": "sång",
        "Norwegian": "sang",
        "Danish": "sang",
        "Finnish": "laulu"
    }
    extra = lang_keywords.get(language, "hymnal")
    lang_expr = LANGUAGE_QUERY_TERMS.get(language, f'"{language}"')
    query = f'"{hymn_title}" {lang_expr} {extra}'
    
    search_url = f"https://www.worldcat.org/search?q={urllib.parse.quote(query)}&qt=results_page"
    
    try:
        req = urllib.request.Request(search_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        
        # Simple extraction
        import re
        results = []
        matches = re.findall(r'<a[^>]+href="(https://www\.worldcat\.org/title/[^"]+)"[^>]*>([^<]+)</a>', html)
        for url, title in matches[:rows]:
            if "title" in url:
                results.append({
                    "source": "worldcat",
                    "title": title.strip(),
                    "url": url
                })
        return results
    except (urllib.error.URLError, TimeoutError, ValueError):
        return []




def search_musicbrainz_hymn(hymn_title: str, language: str, rows: int = 5) -> list[dict]:
    """Search MusicBrainz for hymn recordings (no API key needed)."""
    import os
    sys.path.insert(0, str(REPO / "scripts"))
    from product_search import search_musicbrainz
    
    # Build query with hymn title and language
    query = f"{hymn_title} {language}"
    
    try:
        results = search_musicbrainz(query, before_date=None, max_results=rows)
        # Convert to hymn_hunter format
        out = []
        for r in results:
            out.append({
                "source": "musicbrainz",
                "title": f"{r['title']} by {r['artist']} ({r['release_date']})",
                "url": r["url"],
                "artist": r["artist"],
                "release_date": r["release_date"],
            })
        return out
    except Exception as e:
        print(f"MusicBrainz search error: {e}")
        return []


def search_discogs_hymn(hymn_title: str, language: str, rows: int = 5) -> list[dict]:
    """Search Discogs for hymn album releases (requires DISCOGS_API_KEY)."""
    import os
    sys.path.insert(0, str(REPO / "scripts"))
    from product_search import search_discogs
    
    # Build query with hymn title and language keywords
    lang_keywords = {
        "Italian": "innario",
        "Russian": "гимн",
        "Cebuano": "himno",
        "Spanish": "himnario",
        "Portuguese": "hinário",
        "French": "cantique",
        "German": "Gesangbuch",
    }
    extra = lang_keywords.get(language, "hymnal")
    query = f"{hymn_title} {extra}"
    
    try:
        results = search_discogs(query, before_year=None, max_results=rows)
        # Convert to hymn_hunter format
        out = []
        for r in results:
            out.append({
                "source": "discogs",
                "title": f"{r['title']} ({r['year']}, {r['format']})",
                "url": r["url"],
                "artist": r["artist"],
                "year": r["year"],
                "format": r["format"],
            })
        return out
    except Exception as e:
        print(f"Discogs search error: {e}")
        return []


def _language_signal_terms(language: str) -> tuple[str, ...]:
    terms = {
        "Italian": ("italian", "italiano", "italiana", "salmi", "cantici", "inno", "innario"),
        "Russian": ("russian", "russian empire", "russ", "гимн", "песн", "himny"),
        "Cebuano": ("cebuano", "binisaya", "bisaya", "awit", "himno"),
    }
    return terms.get(language, (language.lower(),))


def filter_hymn_hits(hits: list[dict], language: str) -> list[dict]:
    """Suppress obvious generic anthology noise and prioritize language/hymnal signals."""
    signal_terms = _language_signal_terms(language)
    filtered: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        title = str(hit.get("title", ""))
        url = str(hit.get("url", ""))
        source = str(hit.get("source", ""))
        key = (title.strip().lower(), url.strip().lower())
        if key in seen:
            continue
        seen.add(key)

        title_l = title.lower()
        source_l = source.lower()
        has_signal = any(term in title_l for term in signal_terms) or any(term in title_l for term in HYMNAL_SIGNAL_TERMS)
        low_signal = any(term in title_l for term in LOW_SIGNAL_TITLE_PATTERNS)
        if low_signal and not has_signal:
            continue
        if source_l in {"musicbrainz", "discogs"} and not has_signal:
            continue
        filtered.append(hit)
    return filtered


def _slug(text: str, limit: int = 60) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in text)
    return "_".join(keep.split())[:limit] or "item"


def _stable_lead_filename(prefix: str, *parts: str) -> str:
    joined = " | ".join((part or "").strip() for part in parts)
    digest = hashlib.sha1(joined.encode("utf-8", errors="replace")).hexdigest()[:10]
    slug = _slug("_".join(part for part in parts if part), limit=70)
    return f"{prefix}_{slug}_{digest}_hymn_lead.txt"


class HymnHuntEngine:
    def __init__(self, study_id: str, on_log: LogFn | None = None) -> None:
        self.study_id = study_id
        self.on_log = on_log or (lambda m, l: None)
        self.stopped = False
        self.hymns_searched = 0
        self.leads_found = 0

    def log(self, msg: str, level: str = "info") -> None:
        self.on_log(msg, level)

    def stop(self) -> None:
        self.stopped = True

    def _pause(self, seconds: float = REQUEST_PAUSE) -> bool:
        """Sleep in short slices so stop requests land quickly."""
        remaining = max(seconds, 0.0)
        while remaining > 0:
            if self.stopped:
                return False
            step = min(0.05, remaining)
            time.sleep(step)
            remaining -= step
        return not self.stopped

    def _run_source_search(
        self,
        hymn: str,
        label: str,
        fn: Callable[..., list[dict]],
        *args,
    ) -> tuple[list[dict], bool]:
        if self.stopped:
            return [], False
        self.log(f"  {hymn}: checking {label}", "info")
        hits = fn(*args)
        if not self._pause():
            self.log("Hunt stopped by user", "warn")
            return hits, False
        return hits, True

    def _load_hymn_list(self, folder: Path) -> list[str]:
        path = folder / "HYMN_LIST.txt"
        if not path.exists():
            return []
        return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def _persist_progress(
        self,
        folder: Path,
        language: str,
        hymnal_sources: list[dict],
        leads: list[dict],
    ) -> None:
        """Persist the current library state during the run so the UI updates live."""
        self._write_candidate_files(folder, language, hymnal_sources, leads)
        self._write_candidate_screen(folder, hymnal_sources, leads)

    def run(self) -> dict:
        meta = STUDY_META[self.study_id]
        folder = REPO / meta["folder"]
        language = meta.get("language") or meta["title"]
        language_code = meta.get("language_code")

        hymns = self._load_hymn_list(folder)
        if not hymns:
            self.log(
                f"No {folder / 'HYMN_LIST.txt'} found — nothing to search. "
                "Add the hymn list from the RWS brief's zip file to this folder.",
                "warn",
            )
            return {"hymns_searched": 0, "leads_found": 0}

        self.log(f"Starting hymn search for {self.study_id} — {meta['title']}", "phase")

        self.log(f"Lane 1: searching for {language} hymnal sources (highest-signal query)", "lane")
        hymnal_sources = search_hymnal_sources(language)
        self.log(f"  Found {len(hymnal_sources)} candidate hymnal source(s)", "info")
        self._persist_progress(folder, language, hymnal_sources, [])
        if not self._pause():
            self.log("Hunt stopped by user", "warn")
            return {"hymns_searched": 0, "leads_found": 0, "hymnal_sources": len(hymnal_sources)}

        self.log(f"Lane 2: searching each of {len(hymns)} hymns individually (6 sources)", "lane")
        leads: list[dict] = []
        for hymn in hymns[:MAX_HYMNS_PER_ROUND]:
            if self.stopped:
                self.log("Hunt stopped by user", "warn")
                break
            self.log(f"  {hymn}: checking archive.org", "info")
            hits = search_internet_archive(hymn, language)
            if not self._pause():
                self.log("Hunt stopped by user", "warn")
                break
            self.log(f"  {hymn}: checking Google Books", "info")
            hits += search_google_books(hymn, language, language_code)
            if not self._pause():
                self.log("Hunt stopped by user", "warn")
                break
            self.log(f"  {hymn}: checking HathiTrust", "info")
            hits += search_hathitrust(hymn, language)
            if not self._pause():
                self.log("Hunt stopped by user", "warn")
                break
            self.log(f"  {hymn}: checking WorldCat", "info")
            hits += search_worldcat(hymn, language)
            if not self._pause():
                self.log("Hunt stopped by user", "warn")
                break
            self.log(f"  {hymn}: checking MusicBrainz", "info")
            hits += search_musicbrainz_hymn(hymn, language)
            if not self._pause():
                self.log("Hunt stopped by user", "warn")
                break
            self.log(f"  {hymn}: checking Discogs", "info")
            hits += search_discogs_hymn(hymn, language)
            if not self._pause():
                self.log("Hunt stopped by user", "warn")
                break
            hits = filter_hymn_hits(hits, language)
            self.hymns_searched += 1
            if hits:
                leads.append({"hymn": hymn, "hits": hits})
                self.leads_found += len(hits)
                self.log(f"  {hymn}: {len(hits)} candidate source(s)", "info")
                self._persist_progress(folder, language, hymnal_sources, leads)
            elif self.hymns_searched == 1 or self.hymns_searched % 10 == 0:
                self._write_candidate_screen(folder, hymnal_sources, leads)
            if self.hymns_searched % 10 == 0:
                self.log(f"Searched {self.hymns_searched}/{len(hymns)} hymns…", "info")

        self._persist_progress(folder, language, hymnal_sources, leads)
        self._update_hunt_log(folder, len(hymns))

        self.log(
            f"Done — {len(hymnal_sources)} hymnal source(s) + {self.leads_found} per-hymn "
            f"candidate(s) across {len(leads)}/{self.hymns_searched} hymns searched. "
            "Every lead needs manual verification before submission — translator, date, and "
            "copyright info can't be auto-confirmed, and RWS requires real screenshots anyway.",
            "phase",
        )
        return {
            "hymns_searched": self.hymns_searched,
            "leads_found": self.leads_found,
            "hymnal_sources": len(hymnal_sources),
        }

    def _write_candidate_screen(self, folder: Path, hymnal_sources: list[dict], leads: list[dict]) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        library_count = len(list((folder / "candidates").glob("*_hymn_lead.txt")))
        lines = [
            f"# Candidate Screen — updated {today}",
            "",
            f"Inspected: {self.hymns_searched} · Hymns with leads: {len(leads)} · "
            f"Total per-hymn candidates: {self.leads_found} · Hymnal sources: {len(hymnal_sources)} · "
            f"Library lead files: {library_count}",
            "",
            "## Candidate hymnal sources (search WITHIN these for the full hymn list — "
            "highest-value lead type, verified to beat per-hymn search)",
            "",
        ]
        if hymnal_sources:
            for hit in hymnal_sources:
                lines.append(f"- [{hit['source']}] {hit['title']} — {hit['url']}")
        else:
            lines.append("- (none found — try broadening the language name or check manually)")
        lines += [
            "",
            "## Per-hymn leads found this round (unverified — read source before submitting)",
            "",
        ]
        if leads:
            for lead in leads:
                lines.append(f"### {lead['hymn']}")
                for hit in lead["hits"]:
                    lines.append(f"- [{hit['source']}] {hit['title']} — {hit['url']}")
                lines.append("")
        else:
            lines.append("- (none this round)")
            lines.append("")
        lines += ["## HOLD (rank 1 — verify before surfacing)", "", "- (none)"]
        (folder / "CANDIDATE_SCREEN.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_candidate_files(
        self, folder: Path, language: str, hymnal_sources: list[dict], leads: list[dict]
    ) -> None:
        """Write one file per lead into candidates/ so the web app's Candidates
        tab (which reads candidates/*.txt) actually shows hymn leads — writing
        only to CANDIDATE_SCREEN.md left that tab empty for these studies.
        """
        cand_dir = folder / "candidates"
        cand_dir.mkdir(parents=True, exist_ok=True)

        for hit in hymnal_sources:
            fname = _stable_lead_filename(
                "HYMNAL_SOURCE",
                language,
                str(hit.get("source", "")),
                str(hit.get("title", "")),
                str(hit.get("url", "")),
            )
            (cand_dir / fname).write_text(
                "Type: Candidate hymnal source (search within for the full hymn list)\n"
                f"Language: {language}\n"
                f"Source: {hit['source']}\n"
                f"Title: {hit['title']}\n"
                f"URL: {hit['url']}\n"
                "Status: UNVERIFIED — open and search within before submitting anything from it\n",
                encoding="utf-8",
            )

        for lead in leads:
            for hit in lead["hits"]:
                fname = _stable_lead_filename(
                    _slug(lead["hymn"], limit=32),
                    lead["hymn"],
                    language,
                    str(hit.get("source", "")),
                    str(hit.get("title", "")),
                    str(hit.get("url", "")),
                )
                (cand_dir / fname).write_text(
                    "Type: Hymn translation lead\n"
                    f"Hymn: {lead['hymn']}\n"
                    f"Language: {language}\n"
                    f"Source: {hit['source']}\n"
                    f"Title: {hit['title']}\n"
                    f"URL: {hit['url']}\n"
                    "Status: UNVERIFIED — read the source and confirm translator/date/copyright "
                    "before submitting; RWS requires a real screenshot attachment\n",
                    encoding="utf-8",
                )

    def _update_hunt_log(self, folder: Path, total_hymns: int) -> None:
        log_path = folder / "HUNT_LOG.md"
        today = datetime.now().strftime("%Y-%m-%d")
        row = f"| {today} | {self.hymns_searched}/{total_hymns} | {self.leads_found} | archive.org + Google Books + HathiTrust + WorldCat |"
        header = (
            f"# {self.study_id} Hunt Log\n\n"
            "Bot updates this after each hunt round. Angela can ignore unless auditing coverage.\n\n"
            "| Date | Hymns searched | Candidate sources found | Engines |\n"
            "|------|-----------------|--------------------------|---------|\n"
        )
        if log_path.exists():
            text = log_path.read_text(encoding="utf-8")
            if "| Date | Hymns searched |" in text:
                text = text.rstrip() + "\n" + row + "\n"
            else:
                text = header + row + "\n"
        else:
            text = header + row + "\n"
        log_path.write_text(text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/hymn_hunter.py <study_id>")
        raise SystemExit(1)
    engine = HymnHuntEngine(sys.argv[1], on_log=lambda m, l: print(f"[{l}] {m}"))
    engine.run()


if __name__ == "__main__":
    main()
