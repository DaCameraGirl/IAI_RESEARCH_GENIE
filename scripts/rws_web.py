#!/usr/bin/env python3
"""AIA_Research_Assistant — local web app with interactive target checkboxes, non-LDS strategy lanes, and strict study isolation."""

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

PORT = 7842
BUILD_VERSION = "v2.0 | Interactive Target Controls & Non-LDS Strategy Engine"

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
    raw = STUDY_META[study_id]["patent"]
    if not raw:
        return None
    if not raw.upper().startswith(("US", "EP", "WO")):
        raw = "US" + raw
    return patent_key(raw)

def _purge_burned_candidates(study_id: str, burned: dict[str, str] | None = None) -> int:
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
    org = field("Organization")
    status = field("Status")
    is_ready_lead = "Non-LDS" in text or "Verified" in text or "READY" in path.name or "Non-LDS Verified" in status
    return {
        "file": path.name,
        "publication": hymn or title or path.stem,
        "title": f"{hymn} — {title} ({org})" if org else (f"{hymn} — {title}" if hymn else title),
        "url": field("URL"),
        "pdf_url": "",
        "doi": "not found",
        "rank": 2 if is_ready_lead else 0,
        "confidence": "high" if is_ready_lead else "low",
        "ready": is_ready_lead,
        "tier": "READY" if is_ready_lead else "LEAD",
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
    seen_files = set()
    for path in sorted(folder.glob("*_hymn_lead.txt")):
        seen_files.add(path.name)
        out.append(_parse_hymn_lead(path, path.read_text(encoding="utf-8", errors="replace")))
    for path in sorted(list(folder.glob("*.txt")) + list(folder.glob("*.md"))):
        if path.name in seen_files:
            continue
        seen_files.add(path.name)
        text = path.read_text(encoding="utf-8", errors="replace")
        rank_m = re.search(r"(?:Self-rank|Self rank|Rank):\s*(\d)", text, re.I)
        conf_m = re.search(r"(?:In-scope confidence|Confidence):\s*(high|med|low)", text, re.I)
        pub_m = re.search(r"(?:publication|publisher|source):\s*(.+)", text, re.I)
        title_m = re.search(r"(?:title):\s*(.+)", text, re.I)
        url_m = re.search(r"^\s*(?:URL|Link):\s*(.+)$", text, re.I | re.M)
        pdf_m = re.search(r"^\s*(?:PDF URL|PDF):\s*(.+)$", text, re.I | re.M)
        doi_m = re.search(r"^\s*(?:DOI):\s*(.+)$", text, re.I | re.M)
        dl_m = re.search(r"Downloadable PDF:\s*yes\s*\+\s*(.+)", text, re.I)
        rank = int(rank_m.group(1)) if rank_m else 1
        conf = conf_m.group(1).lower() if conf_m else ("high" if "READY" in path.name else "med")
        url = (url_m.group(1).strip() if url_m else "") or ""
        pdf = (pdf_m.group(1).strip() if pdf_m else "") or ""
        if not pdf and dl_m:
            pdf = dl_m.group(1).strip()
        doi = (doi_m.group(1).strip() if doi_m else "") or "not found"
        publication = pub_m.group(1).strip() if pub_m else path.stem
        title = title_m.group(1).strip() if title_m else path.stem.replace('_', ' ')
        burned_hit, burn_rel = is_burned(publication, burned)
        if not burned_hit and title:
            burned_hit, burn_rel = is_burned(title, burned)
        if not burned_hit and patent_key(publication) == _study_patent_key(study_id):
            burned_hit, burn_rel = True, "Study Patent"
        if burned_hit:
            path.unlink(missing_ok=True)
            continue
        ready = (is_ready(rank, conf) or "READY" in path.name) and not burned_hit
        tier = "READY" if ready else ("HOLD" if "HOLD" in path.name else _candidate_tier(path, text, rank, conf, ready))
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

def _study_ui_copy(meta: dict) -> dict[str, str]:
    crit_date = meta.get("critical_date", "")
    patent = meta.get("patent", "")
    focus = meta.get("focus", "")
    if meta.get("type") == "copyright_hymn" or not patent:
        lang = meta.get("language", "target language")
        meta_line = f"Copyright research | <strong>{lang} translations</strong> | Expiration {crit_date}"
        focus_line = "Target: Find non-LDS existing translations from Baptist, Lutheran, Adventist, and Protestant hymnals. Avoid Mormon hymnal duplicates."
        hunt_label = "Search Hymn Translations"
        how_html = "Search hymn translations for LEADS across non-LDS archives like archive.org."
        sources_html = "Open access: archive.org, google books, wikipedia."
    else:
        meta_line = f"Study patent <strong>{patent}</strong> | Critical date <strong>{crit_date}</strong>"
        focus_line = f"Focus: {focus}"
        hunt_label = "Run Deep Hunt"
        how_html = "Deep Hunt runs connected patent lanes and checks rank >= 2 and PROOF evidence."
        sources_html = "Open access: Google Patents, Unpaywall."
    return {
        "meta_copy": meta_line,
        "focus_copy": focus_line,
        "hunt_label": hunt_label,
        "how_it_works_html": how_html,
        "sources_html": sources_html,
    }

def _run_hunt_async(study_id: str, selected_hymns: list[str] | None = None, selected_denoms: list[str] | None = None) -> None:
    q = _get_log_queue(study_id)

    def log_fn(msg: str, level: str = "info") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        q.put({"t": ts, "msg": msg, "level": level, "study": study_id})

    meta = STUDY_META[study_id]
    log_fn(f"Deep Hunt initiated for {study_id} ({meta['title']})", "phase")

    try:
        if meta.get("type") == "copyright_hymn":
            engine = HymnHuntEngine(study_id, selected_hymns=selected_hymns, selected_denoms=selected_denoms, log_fn=log_fn)
            _hunt_engines[study_id] = engine
            res = engine.run()
        else:
            engine = HuntEngine(study_id, log_fn=log_fn)
            _hunt_engines[study_id] = engine
            res = engine.run()
        _hunt_results[study_id] = res
    except Exception as e:
        log_fn(f"Hunt failed with error: {e}", "error")
        _hunt_results[study_id] = {"status": "error", "error": str(e)}
    finally:
        _hunt_engines.pop(study_id, None)

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
.hero h2 { font-family: 'Cormorant Garamond', serif; font-size: 1.8rem; margin: 4px 0 8px; }
.meta { font-size: 0.85rem; color: var(--muted); }
.focus { font-size: 0.82rem; color: #a0aec0; margin-top: 8px; line-height: 1.5; }

.actions { display: flex; gap: 12px; margin-top: 20px; flex-wrap: wrap; }
.btn {
  padding: 11px 22px; border-radius: 999px; font-size: 0.85rem; font-weight: 600;
  cursor: pointer; border: none; font-family: inherit; transition: all 0.2s;
}
.btn-hunt {
  background: linear-gradient(135deg, var(--gold), #b48328); color: var(--ink);
  box-shadow: 0 4px 20px rgba(212,168,83,0.3);
}
.btn-hunt:hover { transform: translateY(-1px); box-shadow: 0 6px 26px rgba(212,168,83,0.45); }
.btn-ghost {
  background: rgba(255,255,255,0.05); color: var(--cream);
  border: 1px solid rgba(255,255,255,0.1);
}
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
.log-line.hit { color: var(--green); }
.log-line.done { color: var(--gold); font-weight: 600; }
.log-line.error { color: var(--red); }

.candidates { display: flex; flex-direction: column; gap: 10px; max-height: 400px; overflow-y: auto; }
.cand {
  padding: 14px 16px; border-radius: 12px; cursor: pointer;
  background: rgba(0,0,0,0.22); border: 1px solid rgba(255,255,255,0.05);
  transition: all 0.2s ease;
}
.cand.is-ready { border-left: 4px solid var(--green); background: rgba(94, 207, 138, 0.05); }
.cand-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.cand .pub { font-weight: 600; font-size: 0.9rem; }
.cand .ttl { color: var(--muted); font-size: 0.8rem; margin-top: 4px; }
.cand-links { margin-top: 8px; }
.cand-links a { color: var(--gold); text-decoration: none; margin-right: 10px; font-size: 0.8rem; font-weight: 500; }
.status-badge {
  font-size: 0.72rem; font-weight: 600; padding: 3px 10px; border-radius: 999px;
  display: inline-flex; align-items: center; gap: 4px; flex-shrink: 0;
}
.status-badge.green { background: rgba(94, 207, 138, 0.2); color: var(--green); border: 1px solid rgba(94, 207, 138, 0.4); }
.status-badge.lead { background: rgba(255, 255, 255, 0.05); color: var(--muted); border: 1px solid rgba(255, 255, 255, 0.1); }

/* Strategy & Checkbox Controls Panel */
.controls-panel {
  margin-top: 18px; padding: 16px; border-radius: 12px;
  background: rgba(0,0,0,0.25); border: 1px solid rgba(212,168,83,0.25);
}
.controls-panel h4 { font-family: 'Cormorant Garamond', serif; color: var(--gold); font-size: 1.05rem; margin-bottom: 10px; }
.controls-grid { display: flex; flex-wrap: wrap; gap: 16px; }
.control-col { flex: 1; min-width: 200px; }
.control-col label { display: block; font-size: 0.78rem; margin-bottom: 4px; color: var(--cream); cursor: pointer; }

footer { margin-top: 28px; text-align: center; color: #4a5568; font-size: 0.75rem; }
</style>
</head>
<body>
<div class="bg"></div>
<div class="shell">
  <header>
    <div class="brand">
      <div class="brand-row">
        <img src="/assets/genie-mascot.jpg" class="genie-avatar" id="genieAvatar" alt="AIA Mascot"/>
        <div>
          <h1>AIA_Research_Assistant <span style="font-size:0.4em;color:var(--gold);font-weight:500">v2.0</span></h1>
          <p>Interactive Target Selection & Non-LDS Strategy Engine</p>
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
          <button class="btn btn-stop" id="stopBtn" style="display:none">Stop</button>
        </div>

        <!-- Interactive Checkbox & Strategy Selection Panel -->
        <div class="controls-panel">
          <h4>🎯 Target & Strategy Selection Controls (Isolated by Study)</h4>
          <div class="controls-grid">
            <div class="control-col">
              <span style="font-size:0.75rem; color:var(--gold); font-weight:600; display:block; margin-bottom:6px;">Target Songs / Leads:</span>
              <div id="songCheckboxes" style="max-height:100px; overflow-y:auto; font-size:0.78rem;">
                <label><input type="checkbox" class="chk-song" value="Softly and Tenderly Jesus Is Calling" checked> Softly and Tenderly</label>
                <label><input type="checkbox" class="chk-song" value="Take My Life and Let It Be Consecrated" checked> Take My Life</label>
                <label><input type="checkbox" class="chk-song" value="This Is My Father's World" checked> This Is My Father's World</label>
                <label><input type="checkbox" class="chk-song" value="What Child Is This?" checked> What Child Is This?</label>
                <label><input type="checkbox" class="chk-song" value="Our Savior Brings Us Joy" checked> Our Savior Brings Us Joy</label>
              </div>
            </div>

            <div class="control-col">
              <span style="font-size:0.75rem; color:var(--gold); font-weight:600; display:block; margin-bottom:6px;">Denominational Strategy:</span>
              <div style="font-size:0.78rem;">
                <label><input type="checkbox" id="chk_non_lds" checked> Non-LDS Only (Rec)</label>
                <label><input type="checkbox" id="chk_baptist" checked> Baptist</label>
                <label><input type="checkbox" id="chk_adventist" checked> Adventist</label>
                <label><input type="checkbox" id="chk_lutheran" checked> Lutheran</label>
                <label><input type="checkbox" id="chk_presbyterian" checked> Presbyterian</label>
              </div>
            </div>

            <div class="control-col">
              <span style="font-size:0.75rem; color:var(--gold); font-weight:600; display:block; margin-bottom:6px;">Search Strategy Lanes:</span>
              <div style="font-size:0.78rem;">
                <label><input type="checkbox" id="chk_wiki" checked> Wikipedia Authority Lane</label>
                <label><input type="checkbox" id="chk_portals" checked> Hymnary / Holychords Lane</label>
                <label><input type="checkbox" id="chk_offset" checked> Blender Offset Ratio (5%-15%)</label>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="tabs">
          <button class="tab active" data-tab="console">Live hunt</button>
          <button class="tab" data-tab="candidates">Candidates</button>
        </div>
        <div class="panel active" id="panel-console">
          <div class="console" id="console"><div class="empty" id="consoleEmpty">Select targets above and click 'Run Deep Hunt'.</div></div>
        </div>
        <div class="panel" id="panel-candidates">
          <div class="candidates" id="candList"></div>
        </div>
      </div>
    </div>

    <div class="side">
      <div class="card">
        <h3>Study Select</h3>
        <div id="queue"></div>
      </div>
    </div>
  </div>
  <footer>AIA_Research_Assistant · local · port """ + str(PORT) + """ · """ + BUILD_VERSION + """</footer>
</div>

<script>
const $ = id => document.getElementById(id);
let selectedStudy = "26006";
let state = null;

async function api(path, opts) {
  const r = await fetch(path, opts);
  return r.json();
}

async function loadState() {
  state = await api('/api/state');
  if (state && state.current_study && (!selectedStudy || !state.studies[selectedStudy])) {
    selectedStudy = state.current_study;
  }
  renderPills();
}

function renderPills() {
  const pillsEl = $('pills');
  pillsEl.innerHTML = '';
  if (!state || !state.queue) return;
  state.queue.forEach(sid => {
    const meta = state.studies[sid] || {};
    const btn = document.createElement('button');
    btn.className = 'pill ' + (sid === selectedStudy ? 'active' : '');
    btn.dataset.id = sid;
    const shortTitle = meta.title ? meta.title.split(' ')[0] : sid;
    btn.textContent = `${sid} · ${shortTitle}`;
    btn.onclick = () => {
      selectedStudy = sid;
      renderPills();
      loadCandidates();
    };
    pillsEl.appendChild(btn);
  });
  renderHero();
  renderQueue();
}

function renderHero() {
  const meta = (state && state.studies && state.studies[selectedStudy]) || { title: 'Study ' + selectedStudy, meta_copy: '', focus: '' };
  $('studyId').textContent = 'Study ' + selectedStudy;
  $('studyTitle').textContent = meta.title || 'Study ' + selectedStudy;
  $('studyMeta').innerHTML = meta.meta_copy || '';
  $('studyFocus').textContent = meta.focus || '';
}

function renderQueue() {
  const qEl = $('queue');
  qEl.innerHTML = '';
  if (!state || !state.queue) return;
  state.queue.forEach(sid => {
    const meta = state.studies[sid] || {};
    const d = document.createElement('div');
    d.className = 'queue-item ' + (sid === selectedStudy ? 'current' : '');
    d.innerHTML = `<div class="qid"><strong>${sid}</strong> - ${meta.title || ''}</div>`;
    d.onclick = () => {
      selectedStudy = sid;
      renderPills();
      loadCandidates();
    };
    qEl.appendChild(d);
  });
}

async function loadCandidates() {
  const data = await api('/api/candidates?study=' + selectedStudy);
  const el = $('candList');
  el.innerHTML = '';
  if (!data.candidates || data.candidates.length === 0) {
    el.innerHTML = '<div class="empty">No candidates yet. Click Run Deep Hunt.</div>';
    return;
  }
  data.candidates.forEach(c => {
    const div = document.createElement('div');
    div.className = 'cand ' + (c.ready ? 'is-ready' : '');
    const badge = c.ready 
      ? '<span class="status-badge green">🟢 READY</span>' 
      : '<span class="status-badge lead">⚪ LEAD</span>';
    div.innerHTML = `
      <div class="cand-head">
        <div class="pub">${c.publication}</div>
        ${badge}
      </div>
      <div class="ttl">${c.title}</div>
      <div class="cand-links"><a href="${c.url}" target="_blank" rel="noopener">Open Link</a></div>
    `;
    el.appendChild(div);
  });
}

$('huntBtn').onclick = async () => {
  $('huntBtn').disabled = true;
  $('huntBtn').textContent = 'Hunting...';
  
  const selectedHymns = Array.from(document.querySelectorAll('.chk-song:checked')).map(cb => cb.value);
  await api('/api/hunt', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({study: selectedStudy, selected_hymns: selectedHymns})
  });
  
  pollLogs();
};

function pollLogs() {
  setInterval(async () => {
    const data = await api('/api/hunt/logs?study=' + selectedStudy);
    const consoleEl = $('console');
    consoleEl.innerHTML = '';
    data.logs.forEach(l => {
      const d = document.createElement('div');
      d.className = 'log-line ' + (l.level || '');
      d.textContent = `[${l.t}] ${l.msg}`;
      consoleEl.appendChild(d);
    });
    if (!data.running) {
      $('huntBtn').disabled = false;
      $('huntBtn').textContent = 'Run Deep Hunt';
      loadCandidates();
    }
  }, 1000);
}

document.querySelectorAll('.tab').forEach(t => {
  t.onclick = () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    $('panel-' + t.dataset.tab).classList.add('active');
    if (t.dataset.tab === 'candidates') loadCandidates();
  };
});

loadState().then(loadCandidates);
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
        query = parse_qs(urlparse(self.path).query)

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

        if path == "/api/state":
            state = load_state()
            sid = current_id(state)
            meta = STUDY_META[sid]
            st = state["studies"].get(sid, {})
            ui = _study_ui_copy(meta)
            
            queue_meta = {}
            for qid in state.get("queue", []):
                qmeta = STUDY_META.get(qid, {})
                q_ui = _study_ui_copy(qmeta)
                queue_meta[qid] = {
                    "title": qmeta.get("title", f"Study {qid}"),
                    "meta_copy": q_ui["meta_copy"],
                    "focus": q_ui["focus_copy"]
                }

            _json_response(self, {
                "current_study": sid,
                "queue": state.get("queue", []),
                "studies": queue_meta,
                "hunt_running": _study_hunt_running(sid)
            })
            return

        if path == "/api/candidates":
            study_id = query.get("study", ["26006"])[0]
            cands = _parse_candidates(study_id)
            _json_response(self, {"study": study_id, "candidates": cands})
            return

        if path == "/api/hunt/logs":
            study_id = query.get("study", ["26006"])[0]
            q = _get_log_queue(study_id)
            logs = []
            while not q.empty():
                logs.append(q.get_nowait())
            _json_response(self, {"study": study_id, "running": _study_hunt_running(study_id), "logs": logs})
            return

        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b"{}"

        try:
            payload = json.loads(body.decode("utf-8"))
        except ValueError:
            payload = {}

        if path == "/api/hunt":
            study_id = payload.get("study", "26006")
            selected_hymns = payload.get("selected_hymns")
            if _study_hunt_running(study_id):
                _json_response(self, {"ok": False, "error": f"Hunt already running for {study_id}"}, 400)
                return
            
            thread = threading.Thread(target=_run_hunt_async, args=(study_id, selected_hymns), daemon=True)
            _hunt_threads[study_id] = thread
            thread.start()
            _json_response(self, {"ok": True, "study": study_id})
            return

        self.send_error(404)

def _html_response(handler: BaseHTTPRequestHandler, html: str) -> None:
    data = html.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)

def _json_response(handler: BaseHTTPRequestHandler, obj: dict, code: int = 200) -> None:
    data = json.dumps(obj, indent=2).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(data)

def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), RWSHandler)
    print(f"AIA_Research_Assistant web server running at http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")

if __name__ == "__main__":
    main()
