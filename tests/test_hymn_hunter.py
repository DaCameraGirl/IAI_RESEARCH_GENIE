"""Tests for scripts/hymn_hunter.py."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import hymn_hunter  # noqa: E402
import study_bot  # noqa: E402

IA_RESPONSE = {
    "response": {
        "docs": [
            {"identifier": "russian-hymnal-1911"},
            {"identifier": "sda-himny-collection"},
        ]
    }
}

GB_RESPONSE = {
    "items": [
        {
            "volumeInfo": {
                "title": "Sbornik Gimnov",
                "publishedDate": "1998-01-01",
                "infoLink": "https://books.google.com/books?id=abc123",
            }
        },
        {"volumeInfo": {"title": "No link here"}},
    ]
}


class TestSearchFunctions(unittest.TestCase):
    def test_internet_archive_parses_docs(self) -> None:
        with patch.object(hymn_hunter, "_get_json", return_value=IA_RESPONSE):
            hits = hymn_hunter.search_internet_archive("Amazing Grace", "Russian")
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0]["source"], "archive.org")
        self.assertIn("archive.org/details/russian-hymnal-1911", hits[0]["url"])

    def test_google_books_skips_items_without_link(self) -> None:
        with patch.object(hymn_hunter, "_get_json", return_value=GB_RESPONSE):
            hits = hymn_hunter.search_google_books("Amazing Grace", "Russian", "ru")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["source"], "google_books")
        self.assertIn("1998", hits[0]["title"])

    def test_network_errors_return_empty_not_raise(self) -> None:
        with patch.object(hymn_hunter, "_get_json", side_effect=TimeoutError()):
            self.assertEqual(hymn_hunter.search_internet_archive("X", "Russian"), [])
            self.assertEqual(hymn_hunter.search_google_books("X", "Russian", "ru"), [])

    def test_hymnal_sources_dedupes_across_queries(self) -> None:
        with patch.object(hymn_hunter, "_get_json", return_value=IA_RESPONSE):
            hits = hymn_hunter.search_hymnal_sources("Russian")
        # Two queries hit the same two docs — dedup should collapse to 2, not 4
        self.assertEqual(len(hits), 2)

    def test_per_hymn_query_requires_mediatype_texts(self) -> None:
        captured = {}

        def fake_get_json(url):
            captured["url"] = url
            return {"response": {"docs": []}}

        with patch.object(hymn_hunter, "_get_json", side_effect=fake_get_json):
            hymn_hunter.search_internet_archive("Amazing Grace", "Russian")
        self.assertIn("mediatype", captured["url"])

    def test_cebuano_queries_expand_language_aliases(self) -> None:
        captured = {}

        def fake_get_json(url):
            captured["url"] = url
            return {"response": {"docs": []}}

        with patch.object(hymn_hunter, "_get_json", side_effect=fake_get_json):
            hymn_hunter.search_hymnal_sources("Cebuano")
        self.assertIn("Binisaya", captured["url"])
        self.assertIn("Bisaya", captured["url"])

    def test_filter_hymn_hits_suppresses_low_signal_anthologies(self) -> None:
        hits = [
            {
                "source": "archive.org",
                "title": "Rock Pop Folk Songs et cetera. Vol. 1/3 - 2.622 Songs (pvg)",
                "url": "https://archive.org/details/noise",
            },
            {
                "source": "archive.org",
                "title": 'A New Italian hymnal of "Salmi e Cantici"',
                "url": "https://archive.org/details/italian-hymnal",
            },
        ]
        filtered = hymn_hunter.filter_hymn_hits(hits, "Italian")
        self.assertEqual(len(filtered), 1)
        self.assertIn("Italian hymnal", filtered[0]["title"])


class TestHymnHuntEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        state = {
            "mode": "one_at_a_time",
            "current_study": "26006",
            "queue": ["26006"],
            "studies": {
                "26006": {
                    "folder": "26006_Test",
                    "status": "active",
                    "rounds_completed": 0,
                    "candidates_found": 0,
                    "submissions_made": 0,
                    "lanes_complete": [],
                }
            },
        }
        (self.tmp_path / "bot_state.json").write_text(json.dumps(state), encoding="utf-8")
        folder = self.tmp_path / "26006_Test"
        folder.mkdir()
        (folder / "STUDY_META.json").write_text(
            json.dumps(
                {
                    "title": "Hymn Research - Russian",
                    "type": "copyright",
                    "patent": None,
                    "critical_date": None,
                    "focus": "test",
                    "language": "Russian",
                    "language_code": "ru",
                }
            ),
            encoding="utf-8",
        )
        (folder / "HYMN_LIST.txt").write_text("Amazing Grace\nBe Thou My Vision\n", encoding="utf-8")

        study_bot.REPO = self.tmp_path
        study_bot.STATE_PATH = self.tmp_path / "bot_state.json"
        hymn_hunter.REPO = self.tmp_path

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_run_writes_candidate_screen_and_hunt_log(self) -> None:
        logs = []
        with patch.object(hymn_hunter, "search_hymnal_sources", return_value=[
            {"source": "archive.org", "title": "Russian Hymnal Collection", "url": "https://archive.org/details/y"}
        ]), patch.object(hymn_hunter, "search_internet_archive", return_value=[
            {"source": "archive.org", "title": "Russian Hymnal", "url": "https://archive.org/details/x"}
        ]), patch.object(hymn_hunter, "search_google_books", return_value=[]), \
             patch.object(hymn_hunter, "search_hathitrust", return_value=[]), \
             patch.object(hymn_hunter, "search_worldcat", return_value=[]), \
             patch.object(hymn_hunter, "search_musicbrainz_hymn", return_value=[]), \
             patch.object(hymn_hunter, "search_discogs_hymn", return_value=[]), \
             patch("time.sleep", return_value=None):
            engine = hymn_hunter.HymnHuntEngine("26006", on_log=lambda m, l: logs.append((m, l)))
            result = engine.run()

        self.assertEqual(result["hymns_searched"], 2)
        self.assertEqual(result["leads_found"], 2)
        self.assertEqual(result["hymnal_sources"], 1)

        folder = self.tmp_path / "26006_Test"
        screen = (folder / "CANDIDATE_SCREEN.md").read_text(encoding="utf-8")
        self.assertIn("Amazing Grace", screen)
        self.assertIn("Russian Hymnal Collection", screen)
        self.assertIn("archive.org", screen)
        log = (folder / "HUNT_LOG.md").read_text(encoding="utf-8")
        self.assertIn("2/2", log)

        cand_files = list((folder / "candidates").glob("*_hymn_lead.txt"))
        self.assertEqual(len(cand_files), 3)  # 1 hymnal source + 2 per-hymn leads
        hymnal_file = next(f for f in cand_files if f.name.startswith("HYMNAL_SOURCE"))
        text = hymnal_file.read_text(encoding="utf-8")
        self.assertIn("Russian Hymnal Collection", text)
        self.assertIn("UNVERIFIED", text)
        lead_file = next(f for f in cand_files if not f.name.startswith("HYMNAL_SOURCE"))
        lead_text = lead_file.read_text(encoding="utf-8")
        self.assertIn("Hymn:", lead_text)
        messages = [m for m, _level in logs]
        self.assertTrue(any("checking archive.org" in m for m in messages))
        self.assertTrue(any("checking Google Books" in m for m in messages))

    def test_missing_hymn_list_logs_warning_no_crash(self) -> None:
        (self.tmp_path / "26006_Test" / "HYMN_LIST.txt").unlink()
        logs = []
        engine = hymn_hunter.HymnHuntEngine("26006", on_log=lambda m, l: logs.append((m, l)))
        result = engine.run()
        self.assertEqual(result["hymns_searched"], 0)
        self.assertTrue(any("No" in m and "HYMN_LIST" in m for m, l in logs))

    def test_stop_halts_early(self) -> None:
        with patch.object(hymn_hunter, "search_hymnal_sources", return_value=[]), \
             patch.object(hymn_hunter, "search_internet_archive", return_value=[]), \
             patch.object(hymn_hunter, "search_google_books", return_value=[]), \
             patch("time.sleep", return_value=None):
            engine = hymn_hunter.HymnHuntEngine("26006", on_log=lambda m, l: None)
            engine.stop()
            result = engine.run()
        self.assertEqual(result["hymns_searched"], 0)

    def test_second_run_with_no_hits_keeps_existing_library_files(self) -> None:
        folder = self.tmp_path / "26006_Test"
        cand_dir = folder / "candidates"
        cand_dir.mkdir(exist_ok=True)
        old_file = cand_dir / "Amazing_Grace_existing_hymn_lead.txt"
        old_file.write_text(
            "Type: Hymn translation lead\n"
            "Hymn: Amazing Grace\n"
            "Language: Russian\n"
            "Source: archive.org\n"
            "Title: Older Lead\n"
            "URL: https://archive.org/details/older\n"
            "Status: UNVERIFIED\n",
            encoding="utf-8",
        )

        with patch.object(hymn_hunter, "search_hymnal_sources", return_value=[]), \
             patch.object(hymn_hunter, "search_internet_archive", return_value=[]), \
             patch.object(hymn_hunter, "search_google_books", return_value=[]), \
             patch.object(hymn_hunter, "search_hathitrust", return_value=[]), \
             patch.object(hymn_hunter, "search_worldcat", return_value=[]), \
             patch.object(hymn_hunter, "search_musicbrainz_hymn", return_value=[]), \
             patch.object(hymn_hunter, "search_discogs_hymn", return_value=[]), \
             patch("time.sleep", return_value=None):
            engine = hymn_hunter.HymnHuntEngine("26006", on_log=lambda m, l: None)
            result = engine.run()

        self.assertEqual(result["leads_found"], 0)
        self.assertTrue(old_file.exists())
        screen = (folder / "CANDIDATE_SCREEN.md").read_text(encoding="utf-8")
        self.assertIn("Library lead files: 1", screen)


if __name__ == "__main__":
    unittest.main()
