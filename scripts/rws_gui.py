#!/usr/bin/env python3
"""RWS Research Bot — pretty desktop GUI for prior-art hunt workflow."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import customtkinter as ctk
from repo_paths import REPO_ROOT, SCRIPTS_DIR
from research_policy import is_ready

REPO = REPO_ROOT
sys.path.insert(0, str(SCRIPTS_DIR))

from check_burned import is_burned, load_burned  # noqa: E402
from study_bot import (  # noqa: E402
    STUDY_META,
    agent_orders,
    current_id,
    is_blocked,
    load_state,
    save_state,
)

STUDY_COLORS = {
    "26052": ("#8B5CF6", "#6D28D9"),  # purple
    "25974": ("#3B82F6", "#1D4ED8"),  # blue
    "26005": ("#10B981", "#047857"),  # green
    "26006": ("#F59E0B", "#B45309"),  # amber
    "26016": ("#EC4899", "#BE185D"),  # pink
}

STATUS_COLORS = {
    "active": "#22C55E",
    "queued": "#64748B",
    "done": "#94A3B8",
    "blocked": "#EF4444",
    "paused": "#F59E0B",
}

BG = "#0F1117"
SURFACE = "#1A1D27"
SURFACE_ALT = "#232735"
TEXT = "#E8EAED"
TEXT_DIM = "#9CA3AF"
ACCENT = "#8B5CF6"


def burn_count(study_id: str) -> int:
    try:
        return len(load_burned(study_id))
    except Exception:
        return 0


def study_folder(study_id: str) -> Path:
    return REPO / STUDY_META[study_id]["folder"]


def read_text(path: Path, limit: int | None = None) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if limit and len(text) > limit:
        return text[:limit] + "\n\n… (truncated)"
    return text


def parse_candidate(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    rank_m = re.search(r"Self-rank:\s*(\d)\s*/\s*3", text, re.I)
    conf_m = re.search(r"In-scope confidence:\s*(high|med|low)", text, re.I)
    pub_m = re.search(r"publication:\s*(.+)", text, re.I)
    title_m = re.search(r"title:\s*(.+)", text, re.I)

    rank = int(rank_m.group(1)) if rank_m else 0
    conf = conf_m.group(1).lower() if conf_m else "low"
    ready = is_ready(rank, conf)

    return {
        "file": path.name,
        "path": path,
        "rank": rank,
        "confidence": conf,
        "ready": ready,
        "publication": (pub_m.group(1).strip() if pub_m else path.stem),
        "title": (title_m.group(1).strip() if title_m else ""),
        "text": text,
    }


def list_candidates(study_id: str) -> list[dict]:
    folder = study_folder(study_id) / "candidates"
    if not folder.exists():
        return []
    files = sorted(folder.glob("*_RWS_format.txt"))
    return [parse_candidate(p) for p in files]


def lane_progress(study_id: str) -> tuple[int, int]:
    log = study_folder(study_id) / "HUNT_LOG.md"
    if not log.exists():
        return 0, 7
    text = log.read_text(encoding="utf-8", errors="replace")
    done = len(re.findall(r"- \[x\]", text, re.I))
    return done, 7


class RWSResearchApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title("RWS Research Bot")
        self.geometry("1280x820")
        self.minsize(1000, 680)
        self.configure(fg_color=BG)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.state_data = load_state()
        self.selected_id = current_id(self.state_data)
        self._toast_after: str | None = None

        self._build_ui()
        self.refresh_all()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_sidebar()
        self._build_main()
        self._build_footer()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=72)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_propagate(False)

        title = ctk.CTkLabel(
            header,
            text="RWS Research Bot",
            font=ctk.CTkFont(family="Segoe UI", size=26, weight="bold"),
            text_color=TEXT,
        )
        title.pack(side="left", padx=28, pady=18)

        subtitle = ctk.CTkLabel(
            header,
            text="Prior-art hunt · one study at a time · 90% in-scope gate",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_DIM,
        )
        subtitle.pack(side="left", padx=(0, 20))

        refresh_btn = ctk.CTkButton(
            header,
            text="↻ Refresh",
            width=100,
            height=34,
            fg_color=SURFACE_ALT,
            hover_color="#2D3344",
            command=self.refresh_all,
        )
        refresh_btn.pack(side="right", padx=24, pady=18)

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, width=300)
        sidebar.grid(row=1, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(
            sidebar,
            text="Study queue",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(20, 8))

        self.queue_frame = ctk.CTkScrollableFrame(
            sidebar, fg_color="transparent", scrollbar_button_color=SURFACE_ALT
        )
        self.queue_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        ctk.CTkLabel(
            sidebar,
            text="Click a study to inspect.\nActive study drives hunt commands.",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_DIM,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 16))

    def _build_main(self) -> None:
        main = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        main.grid(row=1, column=1, sticky="nsew", padx=(0, 0), pady=0)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        self.hero = ctk.CTkFrame(main, fg_color=SURFACE, corner_radius=16)
        self.hero.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 12))
        self.hero.grid_columnconfigure(1, weight=1)

        self.hero_accent = ctk.CTkFrame(self.hero, width=6, corner_radius=3, fg_color=ACCENT)
        self.hero_accent.grid(row=0, column=0, rowspan=4, sticky="ns", padx=(16, 0), pady=16)

        self.study_id_label = ctk.CTkLabel(
            self.hero, text="", font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_DIM
        )
        self.study_id_label.grid(row=0, column=1, sticky="w", padx=20, pady=(16, 0))

        self.study_title_label = ctk.CTkLabel(
            self.hero, text="", font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT
        )
        self.study_title_label.grid(row=1, column=1, sticky="w", padx=20, pady=(2, 8))

        self.meta_label = ctk.CTkLabel(
            self.hero, text="", font=ctk.CTkFont(size=13), text_color=TEXT_DIM, justify="left"
        )
        self.meta_label.grid(row=2, column=1, sticky="w", padx=20, pady=(0, 8))

        self.focus_label = ctk.CTkLabel(
            self.hero,
            text="",
            font=ctk.CTkFont(size=13),
            text_color="#C4B5FD",
            wraplength=700,
            justify="left",
        )
        self.focus_label.grid(row=3, column=1, sticky="w", padx=20, pady=(0, 16))

        stats = ctk.CTkFrame(self.hero, fg_color="transparent")
        stats.grid(row=0, column=2, rowspan=4, padx=20, pady=16, sticky="ne")

        self.stat_rounds = self._stat_chip(stats, "Rounds", "0")
        self.stat_candidates = self._stat_chip(stats, "Candidates", "0")
        self.stat_burned = self._stat_chip(stats, "Burned", "0")
        self.stat_lanes = self._stat_chip(stats, "Lanes", "0/7")

        actions = ctk.CTkFrame(main, fg_color="transparent")
        actions.grid(row=0, column=0, sticky="ew", padx=24, pady=(0, 8))
        actions.grid_columnconfigure(0, weight=1)

        hunt_btns = ctk.CTkFrame(actions, fg_color="transparent")
        hunt_btns.grid(row=0, column=0, sticky="ew")
        hunt_btns.grid_columnconfigure(0, weight=1)
        
        self.hunt_btn = ctk.CTkButton(
            hunt_btns,
            text="⚡  Run Hunt Now",
            height=48,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=ACCENT,
            hover_color="#7C3AED",
            command=self.run_hunt_now,
        )
        self.hunt_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        
        self.copy_hunt_btn = ctk.CTkButton(
            hunt_btns,
            text="📋 Copy Command",
            height=48,
            font=ctk.CTkFont(size=13),
            fg_color=SURFACE_ALT,
            hover_color="#2D3344",
            command=self.copy_hunt_command,
        )
        self.copy_hunt_btn.grid(row=0, column=1, sticky="ew")

        btn_row = ctk.CTkFrame(actions, fg_color="transparent")
        btn_row.grid(row=0, column=1, sticky="e")

        for col, (label, cmd) in enumerate(
            [
                ("Round done", self.round_done),
                ("Advance", self.advance_study),
                ("Open folder", self.open_folder),
                ("Brief", self.open_brief),
            ]
        ):
            ctk.CTkButton(
                btn_row,
                text=label,
                width=110,
                height=40,
                fg_color=SURFACE_ALT,
                hover_color="#2D3344",
                command=cmd,
            ).grid(row=0, column=col, padx=4)

        self.tabs = ctk.CTkTabview(
            main,
            fg_color=SURFACE,
            segmented_button_fg_color=SURFACE_ALT,
            segmented_button_selected_color=ACCENT,
            segmented_button_unselected_color=SURFACE_ALT,
        )
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=24, pady=(4, 20))
        self.tabs.grid_columnconfigure(0, weight=1)
        self.tabs.grid_rowconfigure(0, weight=1)

        for name in ("Overview", "Hunt log", "Candidates", "Burn check"):
            self.tabs.add(name)
            tab = self.tabs.tab(name)
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)

        self.overview_box = ctk.CTkTextbox(
            self.tabs.tab("Overview"),
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=SURFACE_ALT,
            text_color=TEXT,
            wrap="word",
        )
        self.overview_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        self.hunt_log_box = ctk.CTkTextbox(
            self.tabs.tab("Hunt log"),
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=SURFACE_ALT,
            text_color=TEXT,
            wrap="word",
        )
        self.hunt_log_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        cand_tab = self.tabs.tab("Candidates")
        cand_tab.grid_columnconfigure(0, weight=1)
        cand_tab.grid_rowconfigure(1, weight=1)

        self.cand_summary = ctk.CTkLabel(
            cand_tab, text="", font=ctk.CTkFont(size=13), text_color=TEXT_DIM, anchor="w"
        )
        self.cand_summary.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 4))

        cand_split = ctk.CTkFrame(cand_tab, fg_color="transparent")
        cand_split.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
        cand_split.grid_columnconfigure(1, weight=1)
        cand_split.grid_rowconfigure(0, weight=1)

        self.cand_list = ctk.CTkScrollableFrame(
            cand_split, width=280, fg_color=SURFACE_ALT, label_text="Files"
        )
        self.cand_list.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        self.cand_detail = ctk.CTkTextbox(
            cand_split,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=SURFACE_ALT,
            text_color=TEXT,
            wrap="word",
        )
        self.cand_detail.grid(row=0, column=1, sticky="nsew")

        burn_tab = self.tabs.tab("Burn check")
        burn_tab.grid_columnconfigure(0, weight=1)

        burn_row = ctk.CTkFrame(burn_tab, fg_color="transparent")
        burn_row.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        burn_row.grid_columnconfigure(0, weight=1)

        self.burn_entry = ctk.CTkEntry(
            burn_row,
            placeholder_text="Publication number — e.g. US5613071 or US7702742B2",
            height=40,
            font=ctk.CTkFont(size=14),
            fg_color=SURFACE_ALT,
        )
        self.burn_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.burn_entry.bind("<Return>", lambda _e: self.run_burn_check())

        ctk.CTkButton(
            burn_row,
            text="Check",
            width=100,
            height=40,
            fg_color=ACCENT,
            hover_color="#7C3AED",
            command=self.run_burn_check,
        ).grid(row=0, column=1)

        self.burn_result = ctk.CTkLabel(
            burn_tab, text="", font=ctk.CTkFont(size=16, weight="bold"), anchor="w"
        )
        self.burn_result.grid(row=1, column=0, sticky="ew", padx=16, pady=4)

        self.burn_detail = ctk.CTkLabel(
            burn_tab, text="", font=ctk.CTkFont(size=13), text_color=TEXT_DIM, anchor="w"
        )
        self.burn_detail.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 12))

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=36)
        footer.grid(row=2, column=0, columnspan=2, sticky="ew")
        footer.grid_propagate(False)

        self.status_label = ctk.CTkLabel(
            footer,
            text="Ready",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_DIM,
            anchor="w",
        )
        self.status_label.pack(side="left", padx=20, pady=8)

        self.toast_label = ctk.CTkLabel(
            footer,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#86EFAC",
        )
        self.toast_label.pack(side="right", padx=20, pady=8)

    def _stat_chip(self, parent: ctk.CTkFrame, label: str, value: str) -> ctk.CTkLabel:
        frame = ctk.CTkFrame(parent, fg_color=SURFACE_ALT, corner_radius=10)
        frame.pack(side="left", padx=6)
        ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=10), text_color=TEXT_DIM).pack(
            padx=14, pady=(8, 0)
        )
        val = ctk.CTkLabel(
            frame, text=value, font=ctk.CTkFont(size=18, weight="bold"), text_color=TEXT
        )
        val.pack(padx=14, pady=(0, 8))
        return val

    def _set_textbox(self, box: ctk.CTkTextbox, content: str) -> None:
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", content)
        box.configure(state="disabled")

    def toast(self, message: str, color: str = "#86EFAC") -> None:
        self.toast_label.configure(text=message, text_color=color)
        if self._toast_after:
            self.after_cancel(self._toast_after)
        self._toast_after = self.after(4000, lambda: self.toast_label.configure(text=""))

    def refresh_all(self) -> None:
        self.state_data = load_state()
        self._render_queue()
        self._render_study(self.selected_id)
        self.status_label.configure(
            text=f"Active: {current_id(self.state_data)}  ·  {REPO}"
        )

    def _render_queue(self) -> None:
        for w in self.queue_frame.winfo_children():
            w.destroy()

        cur = current_id(self.state_data)
        for sid in self.state_data["queue"]:
            meta = STUDY_META[sid]
            st = self.state_data["studies"][sid]
            status = st.get("status", "queued")
            if is_blocked(sid):
                status = "blocked"

            accent, _ = STUDY_COLORS.get(sid, (ACCENT, ACCENT))
            is_sel = sid == self.selected_id
            is_cur = sid == cur

            card = ctk.CTkFrame(
                self.queue_frame,
                fg_color="#2A2F3D" if is_sel else SURFACE_ALT,
                corner_radius=12,
                border_width=2 if is_sel else 0,
                border_color=accent,
            )
            card.pack(fill="x", pady=6, padx=4)
            card.bind("<Button-1>", lambda _e, s=sid: self.select_study(s))

            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(10, 4))
            top.bind("<Button-1>", lambda _e, s=sid: self.select_study(s))

            id_lbl = ctk.CTkLabel(
                top,
                text=sid,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=accent,
            )
            id_lbl.pack(side="left")
            id_lbl.bind("<Button-1>", lambda _e, s=sid: self.select_study(s))

            if is_cur:
                cur_badge = ctk.CTkLabel(
                    top,
                    text="ACTIVE",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    text_color="#052E16",
                    fg_color="#86EFAC",
                    corner_radius=6,
                    width=56,
                    height=20,
                )
                cur_badge.pack(side="right")

            status_color = STATUS_COLORS.get(status, TEXT_DIM)
            ctk.CTkLabel(
                card,
                text=meta["title"],
                font=ctk.CTkFont(size=12),
                text_color=TEXT,
                anchor="w",
                wraplength=240,
                justify="left",
            ).pack(anchor="w", padx=12, pady=(0, 4))

            bottom = ctk.CTkFrame(card, fg_color="transparent")
            bottom.pack(fill="x", padx=12, pady=(0, 10))
            bottom.bind("<Button-1>", lambda _e, s=sid: self.select_study(s))

            ctk.CTkLabel(
                bottom,
                text=f"● {status.upper()}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=status_color,
            ).pack(side="left")

            ctk.CTkLabel(
                bottom,
                text=f"R{st.get('rounds_completed', 0)} · C{st.get('candidates_found', 0)}",
                font=ctk.CTkFont(size=11),
                text_color=TEXT_DIM,
            ).pack(side="right")

    def select_study(self, study_id: str) -> None:
        self.selected_id = study_id
        self._render_queue()
        self._render_study(study_id)

    def _render_study(self, study_id: str) -> None:
        meta = STUDY_META[study_id]
        st = self.state_data["studies"][study_id]
        accent, hover = STUDY_COLORS.get(study_id, (ACCENT, "#7C3AED"))
        blocked = is_blocked(study_id)

        self.hero_accent.configure(fg_color=accent)
        self.hunt_btn.configure(fg_color=accent, hover_color=hover)

        status = "BLOCKED" if blocked else st.get("status", "queued").upper()
        self.study_id_label.configure(text=f"Study {study_id}  ·  {status}")
        self.study_title_label.configure(text=meta["title"])

        self.meta_label.configure(
            text=(
                f"Patent: {meta['patent']}\n"
                f"Critical date: {meta['critical_date']}\n"
                f"Folder: {meta['folder']}"
            )
        )
        self.focus_label.configure(text=f"RWS focus: {meta['focus']}")

        burned = burn_count(study_id)
        lanes_done, lanes_total = lane_progress(study_id)
        cands = list_candidates(study_id)
        ready_count = sum(1 for c in cands if c["ready"])

        self.stat_rounds.configure(text=str(st.get("rounds_completed", 0)))
        self.stat_candidates.configure(text=str(ready_count))
        self.stat_burned.configure(text=str(burned))
        self.stat_lanes.configure(text=f"{lanes_done}/{lanes_total}")

        orders = agent_orders(study_id)
        if blocked:
            orders = (
                f"⚠ STUDY BLOCKED\n\n{meta['focus']}\n\n"
                f"Paste the RWS portal brief into:\n"
                f"{study_folder(study_id) / 'STUDY_BRIEF.md'}"
            )
        self._set_textbox(self.overview_box, orders)

        hunt_log = read_text(study_folder(study_id) / "HUNT_LOG.md", limit=12000)
        if not hunt_log:
            hunt_log = "(No hunt log yet — run a hunt round from Cursor.)"
        self._set_textbox(self.hunt_log_box, hunt_log)

        self._render_candidates(study_id, cands)

        if blocked:
            self.hunt_btn.configure(state="disabled", text="⚠  Study blocked")
        else:
            self.hunt_btn.configure(
                state="normal", text=f"⚡  Copy: hunt {study_id} deep"
            )

    def _render_candidates(self, study_id: str, cands: list[dict]) -> None:
        for w in self.cand_list.winfo_children():
            w.destroy()

        ready = [c for c in cands if c["ready"]]
        pending = [c for c in cands if not c["ready"]]

        if not cands:
            summary = "No candidate files yet. Hunt writes *_RWS_format.txt to the study candidates folder."
        else:
            summary = (
                f"{len(ready)} ready for Angela (rank ≥2, high/med confidence) · "
                f"{len(pending)} below gate · {len(cands)} total"
            )
        self.cand_summary.configure(text=summary)

        self._set_textbox(
            self.cand_detail,
            "Select a candidate file on the left to preview submission text.",
        )

        accent, _ = STUDY_COLORS.get(study_id, (ACCENT, ACCENT))

        for cand in cands:
            badge_color = "#22C55E" if cand["ready"] else "#64748B"
            badge_text = "READY" if cand["ready"] else f"R{cand['rank']}/{cand['confidence']}"

            row = ctk.CTkFrame(self.cand_list, fg_color="#2A2F3D", corner_radius=8)
            row.pack(fill="x", pady=4, padx=4)
            row.bind("<Button-1>", lambda _e, c=cand: self._show_candidate(c))

            ctk.CTkLabel(
                row,
                text=cand["publication"][:28],
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=accent,
                anchor="w",
            ).pack(anchor="w", padx=10, pady=(8, 0))
            ctk.CTkLabel(
                row,
                text=cand["title"][:40] or cand["file"],
                font=ctk.CTkFont(size=11),
                text_color=TEXT_DIM,
                anchor="w",
            ).pack(anchor="w", padx=10, pady=(0, 4))
            ctk.CTkLabel(
                row,
                text=badge_text,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="white",
                fg_color=badge_color,
                corner_radius=6,
                width=70,
                height=18,
            ).pack(anchor="w", padx=10, pady=(0, 8))

    def _show_candidate(self, cand: dict) -> None:
        header = (
            f"{'✓ READY FOR ANGELA' if cand['ready'] else 'Below gate — do not surface'}\n"
            f"Self-rank: {cand['rank']}/3  ·  Confidence: {cand['confidence']}\n"
            f"{'─' * 60}\n\n"
        )
        self._set_textbox(self.cand_detail, header + cand["text"])

    def run_hunt_now(self) -> None:
        sid = self.selected_id
        if is_blocked(sid):
            self.toast("Study is blocked — paste brief first", "#FCA5A5")
            return
        
        rounds = self.state_data["studies"][sid].get("rounds_completed", 0)
        script = REPO / "scripts" / "hunt_with_strategy.py"
        
        self.toast(f"🔍 Starting hunt round {rounds + 1} for {sid}...", "#A78BFA")
        
        # Run hunt in background
        subprocess.Popen(
            [sys.executable, str(script), sid, "--round", str(rounds + 1)],
            cwd=str(REPO),
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        
        self.toast(f"Hunt running in background — check candidates tab in a few minutes", "#86EFAC")

    def copy_hunt_command(self) -> None:
        sid = self.selected_id
        if is_blocked(sid):
            self.toast("Study is blocked — paste brief first", "#FCA5A5")
            return
        cmd = f"hunt {sid} deep"
        self.clipboard_clear()
        self.clipboard_append(cmd)
        self.toast(f"Copied «{cmd}» — paste into Cursor chat")
        self.tabs.set("Overview")

    def round_done(self) -> None:
        sid = current_id(self.state_data)
        self.state_data["studies"][sid]["rounds_completed"] = (
            self.state_data["studies"][sid].get("rounds_completed", 0) + 1
        )
        save_state(self.state_data)
        self.refresh_all()
        self.toast(f"Hunt round recorded for {sid}")

    def advance_study(self) -> None:
        from study_bot import cmd_advance

        cmd_advance(self.state_data)
        self.state_data = load_state()
        self.selected_id = current_id(self.state_data)
        self.refresh_all()
        self.toast(f"Advanced — now on {self.selected_id}")

    def open_folder(self) -> None:
        path = study_folder(self.selected_id)
        os.startfile(path)  # type: ignore[attr-defined]

    def open_brief(self) -> None:
        path = study_folder(self.selected_id) / "STUDY_BRIEF.md"
        if path.exists():
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            self.toast("STUDY_BRIEF.md not found", "#FCA5A5")

    def run_burn_check(self) -> None:
        raw = self.burn_entry.get().strip()
        if not raw:
            return
        sid = self.selected_id
        try:
            burned = load_burned(sid)
            hit, relation = is_burned(raw, burned)
            if hit:
                self.burn_result.configure(text="BURNED", text_color="#FCA5A5")
                self.burn_detail.configure(text=f"{raw} is already known ({relation})")
            else:
                self.burn_result.configure(text="CLEAR", text_color="#86EFAC")
                self.burn_detail.configure(text=f"{raw} is not in the burn list — safe to pursue")
        except Exception as exc:
            self.burn_result.configure(text="ERROR", text_color="#FCD34D")
            self.burn_detail.configure(text=str(exc))


def main() -> None:
    app = RWSResearchApp()
    app.mainloop()


if __name__ == "__main__":
    main()
