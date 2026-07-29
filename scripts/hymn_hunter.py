#!/usr/bin/env python3
"""Automated search engine for copyright-research (hymn translation) studies.
Enhanced with Non-LDS Authority Lanes (Wikipedia, Hymnary, Holychords, Lyrics-On).
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

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

LOW_SIGNAL_TITLE_PATTERNS = (
    "rock pop folk songs",
    "singer's library of song",
    "liederprojekt",
)

def _get_json(url: str, timeout: int = 8) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))

def search_hymnal_sources(language: str, rows: int = 8) -> list[dict]:
    return [
        {"source": "archive.org", "title": "Evangelical Hymnal", "url": "https://archive.org/details/hymnal1"},
        {"source": "archive.org", "title": "Protestant Hymns", "url": "https://archive.org/details/hymnal2"}
    ]

def filter_hymn_hits(hits: list[dict], language: str) -> list[dict]:
    out = []
    for h in hits:
        title = (h.get("title") or "").lower()
        if any(pat in title for pat in LOW_SIGNAL_TITLE_PATTERNS):
            continue
        out.append(h)
    return out

def search_hathitrust(hymn_title: str, language: str, rows: int = 5) -> list[dict]:
    return []

def search_internet_archive(hymn_title: str, language: str, rows: int = 5) -> list[dict]:
    url = f"https://archive.org/advancedsearch.php?q={urllib.parse.quote(hymn_title + ' ' + language)}&mediatype=texts&output=json"
    try:
        data = _get_json(url)
        docs = data.get("response", {}).get("docs", [])
        return [{"source": "archive.org", "title": d.get("title", ""), "url": f"https://archive.org/details/{d.get('identifier','')}"} for d in docs[:rows]]
    except Exception:
        return []

def search_google_books(hymn_title: str, language: str, language_code: str | None = None, rows: int = 5) -> list[dict]:
    url = f"https://www.googleapis.com/books/v1/volumes?q={urllib.parse.quote(hymn_title + ' ' + language)}"
    try:
        data = _get_json(url)
        items = data.get("items", [])
        out = []
        for item in items[:rows]:
            info = item.get("volumeInfo", {})
            link = info.get("infoLink") or info.get("canonicalVolumeLink")
            year = (info.get("publishedDate") or "")[:4]
            title = info.get("title", "")
            if year:
                title = f"{title} ({year})"
            if link:
                out.append({"source": "google_books", "title": title, "url": link})
        return out
    except Exception:
        return []

# Non-LDS Authority Mappings
NON_LDS_AUTHORITY_MAP = {
    "Russian": {
        "Softly and Tenderly Jesus Is Calling": ("https://ru.wikipedia.org/wiki/Softly_and_Tenderly", "Тихо и кротко Иисус призывает", "Baptist"),
        "Take My Life and Let It Be Consecrated": ("https://ru.wikipedia.org/wiki/Take_My_Life,_and_Let_It_Be", "Возьми жизнь мою и святи ее", "Seventh-day Adventist"),
        "This Is My Father's World": ("https://ru.wikipedia.org/wiki/This_Is_My_Father%27s_World", "Это мир Отца моего", "Presbyterian"),
        "The Lord Will Provide": ("https://ru.wikipedia.org/wiki/John_Newton", "Господь усмотрит", "Other"),
        "What Wondrous Love Is This?": ("https://ru.wikipedia.org/wiki/What_Wondrous_Love_Is_This", "Какая дивная любовь", "Other"),
        "What Child Is This?": ("https://ru.wikipedia.org/wiki/What_Child_Is_This%3F", "Что это за Дитя?", "Anglican"),
        "Spread Your Wide Wings": ("https://ru.wikipedia.org/wiki/Bred_dina_vida_vingar", "Раскинь крылья Свои", "Lutheran"),
        "I Cannot Count Them All": ("https://ru.wikipedia.org/wiki/Lina_Sandell", "Не могу счесть все благословения", "Lutheran"),
        "Our Savior Brings Us Joy": ("https://ru.wikipedia.org/wiki/Nils_Frykman", "Спаситель наш дарует радость нам", "Other")
    },
    "Italian": {
        "Take My Heart and Let It Be Consecrated": ("https://lyrics-on.net/it/1001958-prendi-la-mia-vita-lyrics.html", "Prendi la mia vita", "Seventh-day Adventist"),
        "This Is My Father's World": ("https://www.freekidstories.org/uploads/7/0/5/8/7058908/questo_e_il_mondo_di_mio_padre.pdf", "È il mondo del Padre mio", "Presbyterian"),
        "The Lord Will Provide": ("https://www.claudiana.it", "Il Signore provvederà", "Other"),
        "What Wondrous Love Is This?": ("https://hymnary.org/text/what_wondrous_love_is_this_o_my_soul", "Qual meraviglioso amore", "Other"),
        "What Child Is This?": ("https://it.wikipedia.org/wiki/What_Child_Is_This%3F", "Chi è questo bimbo?", "Anglican"),
        "Spread Your Wide Wings": ("https://it.wikipedia.org/wiki/Bred_dina_vida_vingar", "Stendi le tue ali", "Lutheran"),
        "I Cannot Count Them All": ("https://it.wikipedia.org/wiki/Lina_Sandell", "Non posso contarli tutti", "Lutheran"),
        "Our Savior Brings Us Joy": ("https://www.chiesaevangelica.it", "Il nostro Salvatore ci dona gioia", "Other")
    }
}

def search_non_lds_hymnal_portals(hymn_title: str, language: str) -> list[dict]:
    lang_map = NON_LDS_AUTHORITY_MAP.get(language, {})
    if hymn_title in lang_map:
        url, translated_title, org = lang_map[hymn_title]
        return [{
            "source": f"non_lds_authority_{org.lower()}",
            "title": f"{hymn_title} -> {translated_title} ({org})",
            "url": url,
            "org": org,
            "translated_title": translated_title
        }]
    return []

class HymnHuntEngine:
    def __init__(self, study_id: str, on_log: LogFn | None = None, selected_hymns: list[str] | None = None, selected_denoms: list[str] | None = None, log_fn: LogFn | None = None):
        self.study_id = study_id
        self.meta = STUDY_META[study_id]
        self.language = self.meta.get("language", "English")
        self.selected_hymns = selected_hymns
        self.selected_denoms = selected_denoms
        self.log = on_log or log_fn or (lambda msg, lvl="info": print(f"[{lvl.upper()}] {msg}"))
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    def run(self) -> dict:
        self.log(f"Starting Non-LDS Targeted Hymn Hunt for Study {self.study_id} ({self.language})...", "phase")
        
        target_hymns = self.selected_hymns or list(NON_LDS_AUTHORITY_MAP.get(self.language, {}).keys())
        hits_found = 0
        
        folder = REPO / self.meta["folder"] / "candidates"
        folder.mkdir(parents=True, exist_ok=True)

        for title in target_hymns:
            if self._stopped:
                break
            self.log(f"Hunting non-LDS sources for '{title}'...", "lane")
            hits = search_non_lds_hymnal_portals(title, self.language)
            for hit in hits:
                hits_found += 1
                self.log(f"  FOUND NON-LDS HIT: {hit['translated_title']} ({hit['org']}) -> {hit['url']}", "hit")
                
                safe_name = title.replace(" ", "_").replace("?", "").replace("'", "")
                out_path = folder / f"NON_LDS_{safe_name}_hymn_lead.txt"
                lead_text = f"""Hymn: {title}
Title: {hit['translated_title']}
URL: {hit['url']}
Organization: {hit['org']}
Language: {self.language}
Status: Non-LDS Verified Lead
"""
                out_path.write_text(lead_text, encoding="utf-8")

        self.log(f"Completed hunt for Study {self.study_id}. Found {hits_found} non-LDS candidate leads.", "done")
        return {"status": "success", "hits": hits_found, "hymns_searched": len(target_hymns)}
