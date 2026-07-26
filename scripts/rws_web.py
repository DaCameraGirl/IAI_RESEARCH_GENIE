#!/usr/bin/env python3
"""AIA_Research_Assistant — local web app that actually runs patent hunts."""

from __future__ import annotations

import json
import queue
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from repo_paths import REPO_ROOT, SCRIPTS_DIR
from research_policy import is_ready

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO = REPO_ROOT
sys.path.insert(0, str(SCRIPTS_DIR))

from add_study import AddStudyError, add_study  # noqa: E402
from check_burned import is_burned, load_burned, patent_key  # noqa: E402
from hymn_hunter import HymnHuntEngine  # noqa: E402
from patent_hunter import HuntEngine, regrade_stored_candidates  # noqa: E402
from study_bot import (  # noqa: E402
    STUDY_META,
    current_id,
    is_blocked,
    load_state,
    save_state,
)

# patent_hunter may not export list_candidates - that's in rws_gui. I'll define here or import from rws_gui logic

PORT = 7842
BUILD_VERSION = "v1.0 | 2026-07-11-aia-researcher"

_hunt_threads: dict[str, threading.Thread] = {}
_hunt_engines: dict[str, object] = {}
_log_queues: dict[str, queue.Queue[dict]] = {}
_hunt_results: dict[str, dict | None] = {}


def _get_log_queue(study_id: str) -> queue.Queue[dict]:
    if study_id not in _log_queues:
        _log_queues[study_id] = queue.Queue()
    return _log_queues[study_id]


def _study_hunt_running(study_id: str) -> bool:
    thread = _hunt_threads.get(study_id)
    return bool(thread and thread.is_alive())


def _active_hunt_studies() -> list[str]:
    return [sid for sid, thread in _hunt_threads.items() if thread and thread.is_alive()]


def _study_patent_key(study_id: str) -> str | None:
    """None for copyright-research studies — no study patent to dedupe against."""
    raw = STUDY_META[study_id]["patent"]
    if not raw:
        return None
    if not raw.upper().startswith(("US", "EP", "WO")):
        raw = "US" + raw
    return patent_key(raw)


def _purge_burned_candidates(study_id: str, burned: dict[str, str] | None = None) -> int:
    """Delete candidate files that match known art — never show repeats to Angela."""
    import re

    burned = burned if burned is not None else load_burned(study_id)
    study_key = _study_patent_key(study_id)
    folder = REPO / STUDY_META[study_id]["folder"] / "candidates"
    if not folder.exists():
        return 0
    removed = 0
    for path in list(folder.glob("*_RWS_format.txt")):
        stem = path.name.replace("_RWS_format.txt", "")
        if stem.startswith("HOLD_"):
            stem = stem[5:]
        probes = [stem, patent_key(stem)]
        text = path.read_text(encoding="utf-8", errors="replace")
        pub_m = re.search(r"publication:\s*(.+)", text, re.I)
        title_m = re.search(r"title:\s*(.+)", text, re.I)
        if pub_m:
            probes.append(pub_m.group(1).strip())
        if title_m:
            probes.append(title_m.group(1).strip())
        if patent_key(stem) == study_key:
            path.unlink(missing_ok=True)
            removed += 1
            continue
        for probe in probes:
            if probe and is_burned(probe, burned)[0]:
                path.unlink(missing_ok=True)
                removed += 1
                break
    return removed


def _parse_hymn_lead(path: Path, text: str) -> dict:
    import re

    def field(name: str) -> str:
        m = re.search(rf"^{name}:\s*(.+)$", text, re.I | re.M)
        return m.group(1).strip() if m else ""

    hymn = field("Hymn")
    title = field("Title")
    return {
        "file": path.name,
        "publication": hymn or title or path.stem,
        "title": f"{hymn} — {title}" if hymn else title,
        "url": field("URL"),
        "pdf_url": "",
        "doi": "not found",
        "rank": 0,
        "confidence": "low",
        "ready": False,
        "tier": "LEAD",
        "burned": False,
        "burn_relation": "",
        "text": text,
    }


def _candidate_tier(path: Path, text: str, rank: int, confidence: str, ready: bool) -> str:
    if ready:
        return "READY"
    if path.name.startswith(("NPL_", "PRODUCT_", "MUSIC_", "LEAD_")):
        return "LEAD"
    text_l = text.lower()
    if any(marker in text_l for marker in ("npl lead", "lead only", "unverified")):
        return "LEAD"
    if path.name.startswith("HOLD_") or rank > 0 or confidence in {"high", "med"}:
        return "HOLD"
    return "LEAD"


def _parse_candidates(study_id: str, burned: dict[str, str] | None = None) -> list[dict]:
    import re

    burned = burned if burned is not None else load_burned(study_id)
    _purge_burned_candidates(study_id, burned)
    folder = REPO / STUDY_META[study_id]["folder"] / "candidates"
    if not folder.exists():
        return []
    out = []
    for path in sorted(folder.glob("*_hymn_lead.txt")):
        out.append(_parse_hymn_lead(path, path.read_text(encoding="utf-8", errors="replace")))
    for path in sorted(folder.glob("*_RWS_format.txt")):
        text = path.read_text(encoding="utf-8", errors="replace")
        rank_m = re.search(r"Self-rank:\s*(\d)\s*/\s*3", text, re.I)
        conf_m = re.search(r"In-scope confidence:\s*(high|med|low)", text, re.I)
        pub_m = re.search(r"publication:\s*(.+)", text, re.I)
        title_m = re.search(r"title:\s*(.+)", text, re.I)
        url_m = re.search(r"^  URL:\s*(.+)$", text, re.I | re.M)
        pdf_m = re.search(r"^  PDF URL:\s*(.+)$", text, re.I | re.M)
        doi_m = re.search(r"^  DOI:\s*(.+)$", text, re.I | re.M)
        dl_m = re.search(r"Downloadable PDF:\s*yes\s*\+\s*(.+)", text, re.I)
        rank = int(rank_m.group(1)) if rank_m else 0
        conf = conf_m.group(1).lower() if conf_m else "low"
        url = (url_m.group(1).strip() if url_m else "") or ""
        pdf = (pdf_m.group(1).strip() if pdf_m else "") or ""
        if not pdf and dl_m:
            pdf = dl_m.group(1).strip()
        doi = (doi_m.group(1).strip() if doi_m else "") or "not found"
        publication = pub_m.group(1).strip() if pub_m else path.stem
        title = title_m.group(1).strip() if title_m else ""
        burned_hit, burn_rel = is_burned(publication, burned)
        if not burned_hit and title:
            burned_hit, burn_rel = is_burned(title, burned)
        if not burned_hit and patent_key(publication) == _study_patent_key(study_id):
            burned_hit, burn_rel = True, "Study Patent"
        if burned_hit:
            path.unlink(missing_ok=True)
            continue
        ready = is_ready(rank, conf) and not burned_hit
        tier = _candidate_tier(path, text, rank, conf, ready)
        out.append(
            {
                "file": path.name,
                "publication": publication,
                "title": title,
                "url": url,
                "pdf_url": pdf,
                "doi": doi,
                "rank": rank,
                "confidence": conf,
                "ready": ready,
                "tier": tier,
                "burned": burned_hit,
                "burn_relation": burn_rel,
                "text": text,
            }
        )
    return out


def _burn_count(study_id: str) -> int:
    try:
        return len(load_burned(study_id))
    except Exception:
        return 0


def _study_ui_copy(meta: dict) -> dict[str, str]:
    if meta.get("patent"):
        return {
            "hunt_label": "Run Deep Hunt",
            "console_empty": "Run a patent hunt to populate leads, HOLD records, and READY proof candidates.",
            "empty_candidates": "No research records yet - run a patent hunt.",
            "sources_html": (
                '<strong style="color:var(--cream)">Open access:</strong> Google Patents, '
                "Unpaywall, PubMed, arXiv, DOAJ, RFCs.<br><br>"
                '<strong style="color:var(--cream)">School login OK:</strong> Elsevier, '
                "ScienceDirect, Journal of Pharmaceutical Sciences - keep those tagged "
                '<code style="color:var(--gold)">Access: school</code> for manual PDF pull-through.'
            ),
            "how_it_works_html": (
                '<strong style="color:var(--gold)">Deep Hunt</strong> runs the connected patent '
                "lanes, burn-checks against known art, and separates <strong>LEAD</strong>, "
                "<strong>HOLD</strong>, and <strong>READY</strong> evidence. READY still requires "
                "<strong>rank >= 2</strong>, <strong>confidence high or med</strong>, "
                "<strong>PROOF</strong> evidence, and no hard-gate failures. Human review is still "
                "required before submission."
            ),
        }
    return {
        "hunt_label": "Search Hymn Translations",
        "console_empty": "Run a hymn search to collect leads worth opening and verifying.",
        "empty_candidates": "No leads yet - run a hymn search.",
        "sources_html": (
            '<strong style="color:var(--cream)">Open access:</strong> archive.org, Google Books, '
            "HathiTrust, WorldCat, MusicBrainz, Discogs.<br><br>"
            '<strong style="color:var(--cream)">Human step:</strong> open the actual source, '
            "confirm the target-language text, date, and translator, then capture a real screenshot "
            "before treating anything as submittable."
        ),
        "how_it_works_html": (
            '<strong style="color:var(--gold)">Hymn search</strong> prioritizes hymnals and other '
            "language-specific source books first, then checks per-hymn catalog and archive hits. "
            "Most results are <strong>LEADS</strong>, not proof. A green light appears only after "
            "you verify the real source and promote it into submission-ready evidence."
        ),
    }


def _no_cache_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Access-Control-Allow-Origin", "*")


def _json_response(handler: BaseHTTPRequestHandler, data: dict, status: int = 200) -> None:
    body = json.dumps(data).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    _no_cache_headers(handler)
    handler.end_headers()
    handler.wfile.write(body)


def _html_response(handler: BaseHTTPRequestHandler, html: str) -> None:
    body = html.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    _no_cache_headers(handler)
    handler.end_headers()
    handler.wfile.write(body)


def _start_hunt(study_id: str) -> dict:
    if _study_hunt_running(study_id):
        return {"ok": False, "error": "Hunt already running for this study"}

    _hunt_results[study_id] = None
    log_queue = _get_log_queue(study_id)
    while not log_queue.empty():
        try:
            log_queue.get_nowait()
        except queue.Empty:
            break

    def on_log(msg: str, level: str) -> None:
        log_queue.put(
            {"t": datetime.now().strftime("%H:%M:%S"), "msg": msg, "level": level, "study": study_id}
        )

    def run() -> None:
        meta = STUDY_META[study_id]
        if meta.get("type") == "copyright":
            engine = HymnHuntEngine(study_id, on_log=on_log)
            _hunt_engines[study_id] = engine
            try:
                _hunt_results[study_id] = engine.run()
                state = load_state()
                if study_id in state["studies"]:
                    state["studies"][study_id]["candidates_found"] = _hunt_results[study_id].get("leads_found", 0)
                    state["studies"][study_id]["rounds_completed"] = state["studies"][study_id].get("rounds_completed", 0) + 1
                save_state(state)
            except Exception as exc:
                on_log(f"Hunt error: {exc}", "error")
            finally:
                _hunt_engines.pop(study_id, None)
            return

        engine = HuntEngine(study_id, on_log=on_log)
        _hunt_engines[study_id] = engine
        try:
            _hunt_results[study_id] = engine.run_deep()
            state = load_state()
            if study_id in state["studies"]:
                state["studies"][study_id]["candidates_found"] = len(_parse_candidates(study_id))
                state["studies"][study_id]["rounds_completed"] = state["studies"][study_id].get("rounds_completed", 0) + 1
            save_state(state)
        except Exception as exc:
            on_log(f"Hunt error: {exc}", "error")
            _hunt_results[study_id] = {"error": str(exc)}
        finally:
            _hunt_engines.pop(study_id, None)

    _hunt_threads[study_id] = threading.Thread(target=run, daemon=True)
    _hunt_threads[study_id].start()
    return {"ok": True, "study_id": study_id}


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>AIA_Research_Assistant</title>
<link rel="icon" href="/assets/genie-mascot.jpg" type="image/jpeg"/>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,700;1,500&family=Outfit:wght@300;400;500;600&display=swap" rel="stylesheet"/>
<style>
:root {
  --ink: #070b14;
  --deep: #0e1525;
  --panel: rgba(18, 26, 42, 0.82);
  --glass: rgba(255, 252, 245, 0.04);
  --cream: #f4efe6;
  --muted: #8b95a8;
  --gold: #d4a853;
  --gold-dim: #a67c2e;
  --green: #5ecf8a;
  --red: #f07178;
  --purple: #a78bfa;
  --blue: #60a5fa;
  --emerald: #34d399;
  --radius: 18px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; }
body {
  font-family: 'Outfit', system-ui, sans-serif;
  color: var(--cream);
  background: var(--ink);
  overflow-x: hidden;
}
.bg {
  position: fixed; inset: 0; z-index: 0;
  background:
    radial-gradient(ellipse 80% 60% at 15% 10%, rgba(167,139,250,0.14), transparent 55%),
    radial-gradient(ellipse 70% 50% at 85% 80%, rgba(212,168,83,0.10), transparent 50%),
    linear-gradient(165deg, #070b14 0%, #0c1220 45%, #080d18 100%);
}
.bg::after {
  content: ''; position: absolute; inset: 0; opacity: 0.35;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.04'/%3E%3C/svg%3E");
  pointer-events: none;
}
.shell { position: relative; z-index: 1; max-width: 1380px; margin: 0 auto; padding: 28px 32px 40px; min-height: 100vh; }

header {
  display: flex; align-items: flex-end; justify-content: space-between;
  margin-bottom: 32px; padding-bottom: 24px;
  border-bottom: 1px solid rgba(212,168,83,0.18);
}
.brand-row { display: flex; align-items: center; gap: 18px; }
.genie-avatar {
  width: 76px; height: 76px; border-radius: 50%;
  border: 2px solid var(--gold);
  box-shadow: 0 0 28px rgba(212,168,83,0.35);
  object-fit: cover; flex-shrink: 0;
}
.genie-avatar.hunting { animation: genie-glow 1.6s ease-in-out infinite; }
@keyframes genie-glow {
  0%, 100% { box-shadow: 0 0 28px rgba(167,139,250,0.35); }
  50% { box-shadow: 0 0 42px rgba(212,168,83,0.65); }
}
.brand h1 {
  font-family: 'Cormorant Garamond', Georgia, serif;
  font-size: clamp(2.2rem, 4vw, 3.2rem);
  font-weight: 700; letter-spacing: -0.02em;
  background: linear-gradient(135deg, var(--cream) 20%, var(--gold) 100%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.brand p { color: var(--muted); font-size: 0.95rem; margin-top: 6px; font-weight: 300; }

.study-pills { display: flex; gap: 10px; flex-wrap: wrap; }
.pill {
  padding: 10px 18px; border-radius: 999px; cursor: pointer;
  border: 1px solid rgba(255,255,255,0.08);
  background: var(--glass); font-size: 0.82rem; font-weight: 500;
  transition: all 0.25s ease; color: var(--muted);
}
.pill:hover { border-color: rgba(212,168,83,0.35); color: var(--cream); }
.pill.active { color: var(--ink); border-color: transparent; }
.pill[data-id="26052"].active { background: linear-gradient(135deg, #a78bfa, #7c3aed); }
.pill[data-id="25974"].active { background: linear-gradient(135deg, #60a5fa, #2563eb); }
.pill[data-id="26005"].active { background: linear-gradient(135deg, #34d399, #059669); }
.pill[data-id="26006"].active { background: linear-gradient(135deg, #fbbf24, #b45309); }
.pill[data-id="26016"].active { background: linear-gradient(135deg, #f472b6, #be185d); }

.grid { display: grid; grid-template-columns: 1fr 380px; gap: 22px; }
@media (max-width: 1100px) { .grid { grid-template-columns: 1fr; } }

.card {
  background: var(--panel);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: var(--radius);
  padding: 24px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.35);
}

.hero { margin-bottom: 22px; }
.hero-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.study-id { font-size: 0.75rem; letter-spacing: 0.14em; text-transform: uppercase; color: var(--gold); font-weight: 600; }
.hero h2 {
  font-family: 'Cormorant Garamond', serif;
  font-size: 1.85rem; font-weight: 700; margin: 8px 0 12px; line-height: 1.15;
}
.meta { color: var(--muted); font-size: 0.88rem; line-height: 1.65; }
.focus {
  margin-top: 14px; padding: 14px 16px; border-radius: 12px;
  background: rgba(167,139,250,0.08); border-left: 3px solid var(--purple);
  font-size: 0.9rem; line-height: 1.55; color: #d8d0f0;
}

.stats { display: flex; gap: 12px; flex-wrap: wrap; }
.stat {
  min-width: 88px; text-align: center; padding: 12px 14px;
  border-radius: 14px; background: rgba(0,0,0,0.25);
  border: 1px solid rgba(255,255,255,0.05);
}
.stat .n { font-size: 1.6rem; font-weight: 600; color: var(--cream); }
.stat .l { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted); margin-top: 2px; }

.actions { display: flex; gap: 12px; margin: 22px 0; flex-wrap: wrap; }
.btn {
  padding: 14px 28px; border: none; border-radius: 12px;
  font-family: inherit; font-size: 0.95rem; font-weight: 600;
  cursor: pointer; transition: transform 0.15s, box-shadow 0.2s;
}
.btn:active { transform: scale(0.97); }
.btn-hunt {
  background: linear-gradient(135deg, var(--gold) 0%, var(--gold-dim) 100%);
  color: var(--ink); box-shadow: 0 8px 32px rgba(212,168,83,0.28);
  flex: 1; min-width: 200px;
}
.btn-hunt:hover { box-shadow: 0 12px 40px rgba(212,168,83,0.4); }
.btn-hunt.running { 
  animation: pulse-green 1.2s ease infinite; 
  background: linear-gradient(135deg, #34d399 0%, #059669 100%);
  box-shadow: 0 8px 32px rgba(52,211,153,0.4);
}
@keyframes pulse-green { 
  0%,100%{ box-shadow: 0 8px 32px rgba(52,211,153,0.4); transform: scale(1); } 
  50%{ box-shadow: 0 12px 48px rgba(52,211,153,0.7); transform: scale(1.02); } 
}
.btn-round-done {
  background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%);
  color: var(--ink); box-shadow: 0 8px 32px rgba(251,191,36,0.3);
}
.btn-round-done.blink { animation: blink-gold 0.8s ease infinite; }
@keyframes blink-gold {
  0%,100%{ opacity: 1; box-shadow: 0 8px 32px rgba(251,191,36,0.3); }
  50%{ opacity: 0.6; box-shadow: 0 12px 48px rgba(251,191,36,0.6); }
}
.btn-ghost {
  background: rgba(255,255,255,0.05); color: var(--cream);
  border: 1px solid rgba(255,255,255,0.1);
}
.btn-ghost:hover { background: rgba(255,255,255,0.09); }
.btn-stop { background: rgba(240,113,120,0.15); color: var(--red); border: 1px solid rgba(240,113,120,0.3); }

.tabs { display: flex; gap: 6px; margin-bottom: 16px; }
.tab {
  padding: 8px 16px; border-radius: 8px; font-size: 0.82rem;
  cursor: pointer; color: var(--muted); background: transparent; border: none;
  font-family: inherit;
}
.tab.active { background: rgba(255,255,255,0.07); color: var(--cream); }

.panel { display: none; }
.panel.active { display: block; }

.console {
  height: 340px; overflow-y: auto; font-family: 'Consolas', 'Courier New', monospace;
  font-size: 0.78rem; line-height: 1.55; padding: 16px;
  background: rgba(0,0,0,0.4); border-radius: 12px;
  border: 1px solid rgba(255,255,255,0.04);
}
.log-line { padding: 2px 0; }
.log-line .t { color: #555f72; margin-right: 8px; }
.log-line.phase { color: var(--gold); font-weight: 600; }
.log-line.lane { color: var(--purple); }
.log-line.hit { color: var(--green); }
.log-line.success { color: var(--green); font-weight: 600; }
.log-line.skip { color: #666; }
.log-line.done { color: var(--gold); font-size: 0.85rem; font-weight: 600; }
.log-line.error { color: var(--red); }
.log-line.warn { color: #f0c674; }

.candidates { display: flex; flex-direction: column; gap: 10px; max-height: 400px; overflow-y: auto; }
.cand {
  padding: 14px 16px; border-radius: 12px; cursor: pointer;
  background: rgba(0,0,0,0.22); border: 1px solid rgba(255,255,255,0.05);
  transition: border-color 0.2s;
}
.cand:hover, .cand.sel { border-color: rgba(212,168,83,0.4); }
.cand-head { display: flex; align-items: center; gap: 10px; }
.cand-signal {
  width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;
  background: var(--muted);
  box-shadow: 0 0 8px rgba(139,149,168,0.45);
}
.cand-signal.ready {
  background: var(--green);
  box-shadow: 0 0 10px rgba(94,207,138,0.7);
  animation: cand-pulse 1s ease-in-out infinite;
}
.cand-signal.lead {
  background: var(--blue);
  box-shadow: 0 0 8px rgba(96,165,250,0.55);
}
.cand-signal.hold {
  background: var(--gold);
  box-shadow: 0 0 8px rgba(212,168,83,0.55);
}
.cand-signal.burned {
  background: var(--red);
  box-shadow: 0 0 10px rgba(240,113,120,0.7);
  animation: none;
}
@keyframes cand-pulse {
  0%, 100% { opacity: 0.55; transform: scale(0.95); }
  50% { opacity: 1; transform: scale(1.15); }
}
.cand .pub { font-weight: 600; font-size: 0.9rem; }
.cand .ttl { color: var(--muted); font-size: 0.8rem; margin-top: 4px; }
.badge {
  display: inline-block; margin-top: 8px; padding: 3px 10px;
  border-radius: 6px; font-size: 0.68rem; font-weight: 700; letter-spacing: 0.06em;
}
.badge.ready { background: rgba(94,207,138,0.2); color: var(--green); }
.badge.hold { background: rgba(139,149,168,0.2); color: var(--muted); }
.badge.burned { background: rgba(248,113,113,0.2); color: var(--red); }
.cand-links { margin-top: 6px; font-size: 0.72rem; }
.cand-links a { color: var(--gold); text-decoration: none; margin-right: 10px; }
.cand-links a:hover { text-decoration: underline; }

.preview {
  margin-top: 14px; padding: 16px; border-radius: 12px;
  background: rgba(0,0,0,0.3); font-family: Consolas, monospace;
  font-size: 0.75rem; line-height: 1.5; white-space: pre-wrap;
  max-height: 280px; overflow-y: auto; color: #c5cad6;
}

.burn-row { display: flex; gap: 10px; margin-top: 12px; }
.burn-row input {
  flex: 1; padding: 12px 16px; border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.1); background: rgba(0,0,0,0.3);
  color: var(--cream); font-family: inherit; font-size: 0.95rem;
}
.burn-row input:focus { outline: none; border-color: rgba(212,168,83,0.5); }
.burn-result { margin-top: 14px; font-size: 1.4rem; font-weight: 700; }
.burn-result.clear { color: var(--green); }
.burn-result.burned { color: var(--red); }

.add-study-form { display: flex; flex-direction: column; gap: 8px; }
.add-study-form input, .add-study-form textarea {
  width: 100%; padding: 10px 12px; border-radius: 8px; box-sizing: border-box;
  border: 1px solid rgba(255,255,255,0.1); background: rgba(0,0,0,0.3);
  color: var(--cream); font-family: inherit; font-size: 0.85rem; resize: vertical;
}
.add-study-form input:focus, .add-study-form textarea:focus {
  outline: none; border-color: rgba(212,168,83,0.5);
}
.add-study-form label { font-size: 0.76rem; color: var(--muted); margin-top: 4px; }
#addStudyResult.ok { color: var(--green); }
#addStudyResult.err { color: var(--red); }

.side .card { margin-bottom: 18px; }
.side h3 {
  font-family: 'Cormorant Garamond', serif;
  font-size: 1.15rem; margin-bottom: 14px; color: var(--gold);
}
.queue-item {
  padding: 12px 14px; border-radius: 10px; margin-bottom: 8px;
  background: rgba(0,0,0,0.2); border: 1px solid transparent;
  cursor: pointer; transition: all 0.2s;
}
.queue-item:hover { border-color: rgba(255,255,255,0.08); }
.queue-item.current { border-color: rgba(212,168,83,0.35); }
.queue-item .qid { font-weight: 600; font-size: 0.85rem; }
.queue-item .qtitle { color: var(--muted); font-size: 0.78rem; margin-top: 3px; }
.status-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; }
.status-dot.active { background: var(--green); box-shadow: 0 0 8px var(--green); }
.status-dot.blocked { background: var(--red); }
.status-dot.queued { background: var(--muted); }

.empty { color: var(--muted); font-style: italic; font-size: 0.88rem; padding: 20px 0; text-align: center; }

footer {
  margin-top: 28px; text-align: center; color: #4a5568;
  font-size: 0.75rem;
}
</style>
</head>
<body>
<div class="bg"></div>
<div class="shell">
  <header>
    <div class="brand">
      <div class="brand-row">
        <img src="/assets/genie-mascot.jpg" class="genie-avatar" id="genieAvatar" alt="AIA Research Assistant mascot"/>
        <div>
          <h1>AIA_Research_Assistant <span style="font-size:0.4em;color:var(--gold);font-weight:500;letter-spacing:0.05em">v1.0</span></h1>
          <p>Local evidence hunter | burn-checks | drafts reviewable leads</p>
        </div>
      </div>
    </div>
    <div class="study-pills" id="pills"></div>
  </header>

  <div class="grid">
    <div class="main">
      <div class="card hero">
        <div class="hero-top">
          <div>
            <div class="study-id" id="studyId">Study —</div>
            <h2 id="studyTitle">Loading…</h2>
            <div class="meta" id="studyMeta"></div>
            <div class="focus" id="studyFocus"></div>
          </div>
          <div class="stats" id="stats"></div>
        </div>
        <div class="actions">
          <button class="btn btn-hunt" id="huntBtn">Run Deep Hunt</button>
          <button class="btn btn-round-done" id="roundBtn" style="display:none">✓ Round Done</button>
          <button class="btn btn-stop" id="stopBtn" style="display:none">Stop</button>
        </div>
      </div>

      <div class="card">
        <div class="tabs">
          <button class="tab active" data-tab="console">Live hunt</button>
          <button class="tab" data-tab="candidates">Candidates</button>
          <button class="tab" data-tab="burn">Burn check</button>
        </div>
        <div class="panel active" id="panel-console">
          <div class="console" id="console"><div class="empty" id="consoleEmpty">Run a patent hunt to populate leads, HOLD records, and READY proof candidates.</div></div>
        </div>
        <div class="panel" id="panel-candidates">
          <div class="candidates" id="candList"></div>
          <div class="preview" id="candPreview" style="display:none"></div>
        </div>
        <div class="panel" id="panel-burn">
          <p style="color:var(--muted);font-size:0.88rem">Check a publication against the study burn list before pursuing.</p>
          <div class="burn-row">
            <input id="burnInput" placeholder="US5613071 or US7702742B2"/>
            <button class="btn btn-ghost" id="burnBtn">Check</button>
          </div>
          <div class="burn-result" id="burnResult"></div>
        </div>
      </div>
    </div>

    <div class="side">
      <div class="card">
        <h3>Queue</h3>
        <div id="queue"></div>
      </div>
      <div class="card">
        <h3>Add Study</h3>
        <div class="add-study-form">
          <input id="newStudyId" placeholder="Study ID (e.g. 26100)"/>
          <input id="newStudyTitle" placeholder="Title (optional — auto-detected if blank)"/>
          <label>Known Citations (CSV) — leave blank for copyright/non-patent studies</label>
          <textarea id="newStudyCsv" rows="3" placeholder="Citation/Document Number,Type,Relation&#10;&quot;US1234567&quot;,&quot;Patent&quot;,&quot;Study Patent&quot;"></textarea>
          <label>Everything else — paste the raw RWS study page / brief</label>
          <textarea id="newStudyBrief" rows="7" placeholder="Paste the whole study brief text here"></textarea>
          <button class="btn btn-ghost" id="addStudyBtn" style="width:100%">Add Study</button>
          <div id="addStudyResult"></div>
        </div>
      </div>
      <div class="card">
        <h3>Sources</h3>
        <p style="color:var(--muted);font-size:0.82rem;line-height:1.6" id="sourcesCopy">
          <strong style="color:var(--cream)">Open access:</strong> Google Patents, Unpaywall, PubMed, arXiv, DOAJ, RFCs.<br><br>
          <strong style="color:var(--cream)">School login OK:</strong> Elsevier, ScienceDirect, Journal of Pharmaceutical Sciences -
          keep those tagged <code style="color:var(--gold)">Access: school</code> for manual PDF pull-through.
        </p>
      </div>
      <div class="card">
        <h3>How it works</h3>
          <p style="color:var(--muted);font-size:0.82rem;line-height:1.6" id="howItWorksCopy">
          <strong style="color:var(--gold)">Deep Hunt</strong> runs the connected patent lanes, burn-checks against known art, and separates <strong>LEAD</strong>, <strong>HOLD</strong>, and <strong>READY</strong> evidence. READY still requires <strong>rank >= 2</strong>, <strong>confidence high or med</strong>, <strong>PROOF</strong> evidence, and no hard-gate failures. Human review is still required before submission.
        </p>
      </div>
    </div>
  </div>
  <footer>AIA_Research_Assistant · local · port """ + str(PORT) + """ · <span id="buildVer">""" + BUILD_VERSION + """</span></footer>
</div>
<script>
let state = null;
let selectedStudy = null;
let pollTimer = null;
let hunting = false;
let huntingStudy = null;
let huntLogsByStudy = {};
const PAGE_VERSION = """ + '"' + BUILD_VERSION + '"' + """;

async function api(path, opts={}) {
  const r = await fetch(path, {cache: 'no-store', ...opts});
  return r.json();
}

async function ensureFreshBuild() {
  const v = await api('/api/version');
  if (v.version && v.version !== PAGE_VERSION) {
    location.replace(location.pathname + '?v=' + encodeURIComponent(v.version));
  }
}

function $(id) { return document.getElementById(id); }

function currentMeta() {
  return state?.studies?.[selectedStudy] || null;
}

function renderConsole() {
  const c = $('console');
  const entries = huntLogsByStudy[selectedStudy] || [];
  if (!entries.length) {
    const meta = currentMeta();
    const msg = meta?.hunt_running
      ? `Live hunt running for study ${selectedStudy}...`
      : (currentMeta()?.console_empty || 'No live hunt output yet.');
    c.innerHTML = `<div class="empty">${msg}</div>`;
    return;
  }
  c.innerHTML = '';
  entries.forEach(entry => appendLog(entry, c));
  c.scrollTop = c.scrollHeight;
}

function setHuntUi(running, studyId=null) {
  hunting = running;
  huntingStudy = running ? studyId : null;
  if (running && studyId === selectedStudy) {
    $('genieAvatar').classList.add('hunting');
    $('huntBtn').classList.add('running');
    $('huntBtn').textContent = 'Hunting...';
    $('stopBtn').style.display = 'inline-block';
    $('stopBtn').disabled = false;
    $('stopBtn').textContent = 'Stop';
    return;
  }
  $('genieAvatar').classList.remove('hunting');
  $('huntBtn').classList.remove('running');
  $('stopBtn').style.display = 'none';
  $('stopBtn').disabled = false;
  $('stopBtn').textContent = 'Stop';
}

function renderState(data) {
  state = data;
  selectedStudy = selectedStudy || data.current;
  const meta = data.studies[selectedStudy];

  $('studyId').textContent = `Study ${selectedStudy} · ${meta.status.toUpperCase()}`;
  $('studyTitle').textContent = meta.title;
  const patentTxt = meta.patent || 'N/A (copyright research)';
  const criticalTxt = meta.critical_date || 'N/A';
  $('studyMeta').innerHTML = `Patent <strong>${patentTxt}</strong><br>Critical date ${criticalTxt}<br>${meta.burned} burned · folder ${meta.folder}`;
  $('studyFocus').textContent = meta.focus;
  $('sourcesCopy').innerHTML = meta.sources_html;
  $('howItWorksCopy').innerHTML = meta.how_it_works_html;
  renderConsole();

  if (meta.patent) {
    $('stats').innerHTML = `
      <div class="stat"><div class="n">${meta.rounds}</div><div class="l">Rounds</div></div>
      <div class="stat"><div class="n">${meta.lead_candidates}</div><div class="l">Leads</div></div>
      <div class="stat"><div class="n">${meta.ready_candidates}</div><div class="l">Ready</div></div>
      <div class="stat"><div class="n">${meta.burned}</div><div class="l">Burned</div></div>
    `;
  } else {
    $('stats').innerHTML = `
      <div class="stat"><div class="n">${meta.rounds}</div><div class="l">Rounds</div></div>
      <div class="stat"><div class="n">${meta.candidates_total}</div><div class="l">Leads</div></div>
      <div class="stat"><div class="n">${meta.burned}</div><div class="l">Burned</div></div>
    `;
  }

  const pills = $('pills');
  pills.innerHTML = '';
  data.queue.forEach(id => {
    const p = document.createElement('button');
    p.className = 'pill' + (id === selectedStudy ? ' active' : '');
    p.dataset.id = id;
    p.textContent = id;
    p.onclick = () => { selectedStudy = id; renderState(state); loadCandidates(); };
    pills.appendChild(p);
  });

  const q = $('queue');
  q.innerHTML = '';
  data.queue.forEach(id => {
    const s = data.studies[id];
    const div = document.createElement('div');
    div.className = 'queue-item' + (id === data.current ? ' current' : '');
    const dotClass = s.blocked ? 'blocked' : (s.status === 'active' ? 'active' : 'queued');
    div.innerHTML = `<div class="qid"><span class="status-dot ${dotClass}"></span>${id}</div><div class="qtitle">${s.title}</div>`;
    div.onclick = () => { selectedStudy = id; renderState(state); loadCandidates(); };
    q.appendChild(div);
  });

  const huntBtn = $('huntBtn');
  if (meta.blocked) {
    huntBtn.disabled = true;
    huntBtn.textContent = 'Study blocked - paste brief';
  } else if (!meta.hunt_running) {
    huntBtn.disabled = false;
    huntBtn.textContent = `⚡ ${meta.hunt_label}`;
    huntBtn.classList.remove('running');
  }
  setHuntUi(Boolean(meta.hunt_running), selectedStudy);
  if (!meta.hunt_running) {
    huntBtn.disabled = !!meta.blocked;
    if (!meta.blocked) huntBtn.textContent = `⚡ ${meta.hunt_label}`;
  }
}

function appendLog(entry, c=$('console')) {
  const d = document.createElement('div');
  d.className = 'log-line ' + (entry.level || 'info');
  d.innerHTML = `<span class="t">${entry.t}</span>${entry.msg}`;
  c.appendChild(d);
}

async function loadState() {
  const data = await api('/api/state');
  renderState(data);
  if (document.querySelector('.tab.active')?.dataset.tab === 'candidates') loadCandidates();
}

async function loadCandidates() {
  await ensureFreshBuild();
  const data = await api('/api/candidates?study=' + selectedStudy);
  const list = $('candList');
  const prev = $('candPreview');
  // Client-side burn gate — never show known art even from stale files
  const clear = [];
  for (const c of data.candidates) {
    const burn = await api('/api/burn-check', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({study:selectedStudy, pub:c.publication})});
    if (burn.clear) clear.push(c);
  }
  data.candidates = clear;
  if (!data.candidates.length) {
    list.innerHTML = `<div class="empty">${currentMeta()?.empty_candidates || 'No research records yet.'}</div>`;
    prev.style.display = 'none';
    return;
  }
  list.innerHTML = '';
  data.candidates.forEach((c, i) => {
    const div = document.createElement('div');
    div.className = 'cand' + (i === 0 ? ' sel' : '');
    const links = [];
    if (c.url && c.url.startsWith('http')) links.push(`<a href="${c.url}" target="_blank">Google</a>`);
    if (c.pdf_url && c.pdf_url.startsWith('http')) links.push(`<a href="${c.pdf_url}" target="_blank">PDF</a>`);
    if (c.text && c.text.includes('USPTO PDF:')) { const m = c.text.match(/USPTO PDF: (https?\\S+)/); if (m) links.push(`<a href="${m[1]}" target="_blank">USPTO</a>`); }
    if (c.text && c.text.includes('Espacenet URL:')) { const m = c.text.match(/Espacenet URL: (https?\\S+)/); if (m) links.push(`<a href="${m[1]}" target="_blank">Espacenet</a>`); }
    if (c.doi && c.doi !== 'n/a' && c.doi !== 'not found') links.push(`<a href="https://doi.org/${c.doi}" target="_blank">DOI</a>`);
    const linkHtml = links.length ? `<div class="cand-links">${links.join('')}</div>` : '';
    const badgeCls = c.burned ? 'burned' : (c.ready ? 'ready' : (c.tier === 'LEAD' ? 'hold' : 'hold'));
    const badgeTxt = c.burned ? 'BURNED' : (c.ready ? 'READY' : (c.tier === 'LEAD' ? 'LEAD' : ('R' + c.rank + '/' + c.confidence)));
    const signalCls = c.burned ? 'cand-signal burned' : (c.ready ? 'cand-signal ready' : (c.tier === 'LEAD' ? 'cand-signal lead' : 'cand-signal hold'));
    div.innerHTML = `<div class="cand-head"><span class="${signalCls}"></span><div class="pub">${c.publication}</div></div><div class="ttl">${c.title || c.file}</div>
      <span class="badge ${badgeCls}">${badgeTxt}</span>${linkHtml}`;
    div.onclick = () => {
      document.querySelectorAll('.cand').forEach(x => x.classList.remove('sel'));
      div.classList.add('sel');
      prev.style.display = 'block';
      prev.textContent = c.text;
    };
    list.appendChild(div);
  });
  prev.style.display = 'block';
  prev.textContent = data.candidates[0].text;
}

async function startHunt() {
  setHuntUi(true, selectedStudy);
  huntLogsByStudy[selectedStudy] = [];
  renderConsole();
  document.querySelector('[data-tab="console"]').click();
  const started = await api('/api/hunt/start', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({study: selectedStudy}) });
  if (!started.ok) {
    setHuntUi(false, null);
    huntLogsByStudy[selectedStudy] = huntLogsByStudy[selectedStudy] || [];
    huntLogsByStudy[selectedStudy].push({t: new Date().toLocaleTimeString('en-US', {hour12:false}), msg: started.error || 'Hunt failed to start', level: 'error'});
    renderConsole();
    loadState();
    return;
  }
  pollLogs();
}

function pollLogs() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const data = await api('/api/hunt/logs?study=' + selectedStudy);
    data.logs.forEach(e => {
      const sid = e.study || selectedStudy;
      huntLogsByStudy[sid] = huntLogsByStudy[sid] || [];
      huntLogsByStudy[sid].push(e);
    });
    await loadState();
    renderConsole();
    setHuntUi(Boolean(data.running), selectedStudy);
    if (!data.running && hunting && huntingStudy === selectedStudy) {
      setHuntUi(false, null);
      $('roundBtn').style.display = 'inline-block';
      $('roundBtn').classList.add('blink');
      loadState();
      loadCandidates();
    }
  }, 600);
}

$('huntBtn').onclick = startHunt;
$('stopBtn').onclick = async () => {
  $('stopBtn').disabled = true;
  $('stopBtn').textContent = 'Stopping...';
  await api('/api/hunt/stop', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({study: selectedStudy})});
  huntLogsByStudy[selectedStudy] = huntLogsByStudy[selectedStudy] || [];
  huntLogsByStudy[selectedStudy].push({t: new Date().toLocaleTimeString('en-US', {hour12:false}), msg: 'Stop requested', level: 'warn'});
  renderConsole();
};
$('roundBtn').onclick = () => { 
  $('roundBtn').style.display = 'none'; 
  $('roundBtn').classList.remove('blink'); 
};

$('addStudyBtn').onclick = async () => {
  const study_id = $('newStudyId').value.trim();
  const title = $('newStudyTitle').value.trim();
  const citations_csv = $('newStudyCsv').value;
  const brief_text = $('newStudyBrief').value;
  const result = $('addStudyResult');
  result.className = '';
  if (!study_id || !brief_text.trim()) {
    result.className = 'err';
    result.textContent = 'Study ID and the brief box are both required.';
    return;
  }
  $('addStudyBtn').disabled = true;
  $('addStudyBtn').textContent = 'Adding...';
  const data = await api('/api/add-study', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({study_id, title, citations_csv, brief_text}),
  });
  $('addStudyBtn').disabled = false;
  $('addStudyBtn').textContent = 'Add Study';
  if (data.ok) {
    result.className = 'ok';
    result.textContent = `Added ${data.study_id} -> ${data.folder} (${data.type})`
      + (data.blocked ? ' - BLOCKED, needs review: ' + data.warnings.join('; ') : '');
    $('newStudyId').value = '';
    $('newStudyTitle').value = '';
    $('newStudyCsv').value = '';
    $('newStudyBrief').value = '';
    loadState();
  } else {
    result.className = 'err';
    result.textContent = data.error || 'Failed to add study.';
  }
};
$('burnBtn').onclick = async () => {
  const pub = $('burnInput').value.trim();
  if (!pub) return;
  const data = await api('/api/burn-check', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({study:selectedStudy, pub})});
  const el = $('burnResult');
  el.className = 'burn-result ' + (data.clear ? 'clear' : 'burned');
  el.textContent = data.clear ? 'CLEAR' : 'BURNED';
};

document.querySelectorAll('.tab').forEach(t => {
  t.onclick = () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    $('panel-' + t.dataset.tab).classList.add('active');
    if (t.dataset.tab === 'candidates') loadCandidates();
  };
});

ensureFreshBuild().then(async () => {
  await loadState();
  await loadCandidates();
  if (state?.hunt_running) pollLogs();
});
</script>
</body>
</html>"""


class RWSHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        pass

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path

        if path in ("/", "/index.html"):
            _html_response(self, INDEX_HTML)
            return

        if path.startswith("/assets/"):
            asset = REPO / path.lstrip("/")
            if asset.is_file():
                ext = asset.suffix.lower()
                mime = {
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".png": "image/png",
                    ".webp": "image/webp",
                    ".svg": "image/svg+xml",
                }.get(ext, "application/octet-stream")
                data = asset.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_error(404)
            return

        if path == "/api/version":
            _json_response(
                self,
                {"version": BUILD_VERSION, "burn_gate": True, "port": PORT},
            )
            return

        if path == "/api/state":
            state = load_state()
            cur = current_id(state)
            active_hunts = _active_hunt_studies()
            studies = {}
            for sid in state["queue"]:
                meta = STUDY_META[sid]
                ui = _study_ui_copy(meta)
                st = state["studies"][sid]
                blocked = is_blocked(sid)
                cands = _parse_candidates(sid)
                ready = sum(1 for c in cands if c["ready"])
                leads = sum(1 for c in cands if c.get("tier") == "LEAD")
                hold = sum(1 for c in cands if c.get("tier") == "HOLD")
                studies[sid] = {
                    "title": meta["title"],
                    "patent": meta["patent"],
                    "type": meta.get("type", ""),
                    "critical_date": meta["critical_date"],
                    "focus": meta["focus"],
                    "folder": meta["folder"],
                    "status": "blocked" if blocked else st.get("status", "queued"),
                    "blocked": blocked,
                    "rounds": st.get("rounds_completed", 0),
                    "candidates": st.get("candidates_found", 0),
                    "candidates_total": len(cands),
                    "lead_candidates": leads,
                    "hold_candidates": hold,
                    "ready_candidates": ready,
                    "burned": _burn_count(sid),
                    "hunt_running": sid in active_hunts,
                    **ui,
                }
            _json_response(
                self,
                {
                    "current": cur,
                    "queue": state["queue"],
                    "studies": studies,
                    "hunt_running": bool(active_hunts),
                    "active_hunts": active_hunts,
                    "version": BUILD_VERSION,
                },
            )
            return

        if path == "/api/candidates":
            qs = parse_qs(urlparse(self.path).query)
            sid = (qs.get("study") or [current_id(load_state())])[0]
            _json_response(self, {"candidates": _parse_candidates(sid)})
            return

        if path == "/api/hunt/logs":
            qs = parse_qs(urlparse(self.path).query)
            sid = (qs.get("study") or [current_id(load_state())])[0]
            log_queue = _get_log_queue(sid)
            logs = []
            while True:
                try:
                    logs.append(log_queue.get_nowait())
                except queue.Empty:
                    break
            running = _study_hunt_running(sid)
            _json_response(
                self,
                {"logs": logs, "running": running, "result": _hunt_results.get(sid), "study": sid},
            )
            return

        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}

        if path == "/api/hunt/start":
            sid = data.get("study") or current_id(load_state())
            if is_blocked(sid):
                _json_response(self, {"ok": False, "error": "Study blocked"}, 400)
                return
            _json_response(self, _start_hunt(sid))
            return

        if path == "/api/hunt/stop":
            sid = data.get("study") or current_id(load_state())
            engine = _hunt_engines.get(sid)
            if engine:
                engine.stop()
            _json_response(self, {"ok": True})
            return

        if path == "/api/burn-check":
            sid = data.get("study") or current_id(load_state())
            pub = data.get("pub", "")
            burned = load_burned(sid)
            hit, relation = is_burned(pub, burned)
            _json_response(self, {"clear": not hit, "relation": relation})
            return

        if path == "/api/purge-candidates":
            sid = data.get("study") or current_id(load_state())
            removed = _purge_burned_candidates(sid)
            ready = len(_parse_candidates(sid))
            state = load_state()
            if sid in state.get("studies", {}):
                state["studies"][sid]["candidates_found"] = ready
                save_state(state)
            _json_response(self, {"ok": True, "removed": removed, "ready": ready})
            return

        if path == "/api/add-study":
            study_id = (data.get("study_id") or "").strip()
            brief_text = data.get("brief_text") or ""
            citations_csv = data.get("citations_csv") or None
            title = (data.get("title") or "").strip() or None
            if not study_id or not brief_text.strip():
                _json_response(self, {"ok": False, "error": "study_id and brief_text are required"}, 400)
                return
            try:
                result = add_study(study_id, brief_text, citations_csv, title=title)
            except AddStudyError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, 400)
                return
            _json_response(self, {"ok": True, **result})
            return

        self.send_error(404)


def _startup_purge() -> None:
    state = load_state()
    for sid in state.get("queue", ()):
        try:
            n = _purge_burned_candidates(sid)
            if n:
                print(f"  Purged {n} known-art candidate file(s) for study {sid}")
            d = regrade_stored_candidates(sid)
            if d:
                print(f"  Regraded {d} weak READY → HOLD for study {sid}")
            if sid in state.get("studies", {}):
                ready = sum(1 for c in _parse_candidates(sid) if c["ready"])
                state["studies"][sid]["candidates_found"] = ready
        except Exception as exc:
            print(f"  Purge skip {sid}: {exc}")
    save_state(state)


def main() -> None:
    _startup_purge()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), RWSHandler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"\n  AIA_Research_Assistant → {url}\n")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
