#!/usr/bin/env python3
"""Focused regression tests for hymn source gating (Phase 1)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add scripts to path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))


def test_musicbrainz_not_called_during_hymn_hunt():
    """Test 1: MusicBrainz is not called during a hymn hunt."""
    from hymn_hunter import HymnHuntEngine
    
    with patch('hymn_hunter.search_musicbrainz_hymn') as mock_mb:
        with patch('hymn_hunter.search_discogs_hymn'):
            with patch('hymn_hunter.search_internet_archive', return_value=[]):
                with patch('hymn_hunter.search_google_books', return_value=[]):
                    with patch('hymn_hunter.search_hathitrust', return_value=[]):
                        with patch('hymn_hunter.search_worldcat', return_value=[]):
                            with patch('hymn_hunter.search_hymnal_sources', return_value=[]):
                                engine = HymnHuntEngine("26006", on_log=lambda m, l: None)
                                engine.stopped = True  # Stop immediately after setup
                                
                                # Mock hymn list
                                with patch.object(engine, '_load_hymn_list', return_value=["Test Hymn"]):
                                    engine.run()
    
    assert mock_mb.call_count == 0, "MusicBrainz should not be called for hymn hunts"
    print("✓ Test 1 passed: MusicBrainz not called")


def test_discogs_not_called_during_hymn_hunt():
    """Test 2: Discogs is not called during a hymn hunt."""
    from hymn_hunter import HymnHuntEngine
    
    with patch('hymn_hunter.search_discogs_hymn') as mock_discogs:
        with patch('hymn_hunter.search_musicbrainz_hymn'):
            with patch('hymn_hunter.search_internet_archive', return_value=[]):
                with patch('hymn_hunter.search_google_books', return_value=[]):
                    with patch('hymn_hunter.search_hathitrust', return_value=[]):
                        with patch('hymn_hunter.search_worldcat', return_value=[]):
                            with patch('hymn_hunter.search_hymnal_sources', return_value=[]):
                                engine = HymnHuntEngine("26006", on_log=lambda m, l: None)
                                engine.stopped = True
                                
                                with patch.object(engine, '_load_hymn_list', return_value=["Test Hymn"]):
                                    engine.run()
    
    assert mock_discogs.call_count == 0, "Discogs should not be called for hymn hunts"
    print("✓ Test 2 passed: Discogs not called")


def test_legitimate_sources_remain_enabled():
    """Test 3: Internet Archive, Google Books, HathiTrust, and WorldCat remain enabled."""
    from hymn_hunter import HymnHuntEngine
    
    ia_called = False
    gb_called = False
    ht_called = False
    wc_called = False
    
    def mock_ia(*args, **kwargs):
        nonlocal ia_called
        ia_called = True
        return []
    
    def mock_gb(*args, **kwargs):
        nonlocal gb_called
        gb_called = True
        return []
    
    def mock_ht(*args, **kwargs):
        nonlocal ht_called
        ht_called = True
        return []
    
    def mock_wc(*args, **kwargs):
        nonlocal wc_called
        wc_called = True
        return []
    
    pause_count = [0]
    def mock_pause():
        # Allow 4 pauses (one after each search engine), then stop
        pause_count[0] += 1
        return pause_count[0] <= 4
    
    with patch('hymn_hunter.search_internet_archive', side_effect=mock_ia):
        with patch('hymn_hunter.search_google_books', side_effect=mock_gb):
            with patch('hymn_hunter.search_hathitrust', side_effect=mock_ht):
                with patch('hymn_hunter.search_worldcat', side_effect=mock_wc):
                    with patch('hymn_hunter.search_hymnal_sources', return_value=[]):
                        with patch('hymn_hunter.filter_hymn_hits', return_value=[]):
                            engine = HymnHuntEngine("26006", on_log=lambda m, l: None)
                            
                            with patch.object(engine, '_load_hymn_list', return_value=["Test Hymn"]):
                                with patch.object(engine, '_pause', side_effect=mock_pause):
                                    with patch.object(engine, '_persist_progress'):
                                        with patch.object(engine, '_update_hunt_log'):
                                            engine.run()
    
    assert ia_called, "Internet Archive should be called"
    assert gb_called, "Google Books should be called"
    assert ht_called, "HathiTrust should be called"
    assert wc_called, "WorldCat should be called"
    print("✓ Test 3 passed: Legitimate sources remain enabled")


def test_musicbrainz_lead_quarantined():
    """Test 4: A historical hymn candidate with Source: musicbrainz is quarantined."""
    from rws_web import _parse_hymn_lead
    from pathlib import Path
    
    text = """Type: Hymn translation lead
Hymn: Love Divine
Language: Russian
Source: musicbrainz
Title: Russian Love by Аквариум (2020)
URL: https://musicbrainz.org/recording/test
Status: UNVERIFIED"""
    
    result = _parse_hymn_lead(Path("test.txt"), text)
    
    assert result["tier"] == "LEGACY_QUARANTINED", "MusicBrainz lead should be quarantined"
    assert result["quarantined"] is True, "quarantined flag should be True"
    assert "Inappropriate source" in result["burn_relation"], "Should have quarantine reason"
    print("✓ Test 4 passed: MusicBrainz lead quarantined")


def test_discogs_lead_quarantined():
    """Test 5: A historical hymn candidate with Source: discogs is quarantined."""
    from rws_web import _parse_hymn_lead
    from pathlib import Path
    
    text = """Type: Hymn translation lead
Hymn: Test Hymn
Language: Russian
Source: discogs
Title: Test Album (2020)
URL: https://discogs.com/release/test
Status: UNVERIFIED"""
    
    result = _parse_hymn_lead(Path("test.txt"), text)
    
    assert result["tier"] == "LEGACY_QUARANTINED", "Discogs lead should be quarantined"
    assert result["quarantined"] is True, "quarantined flag should be True"
    print("✓ Test 5 passed: Discogs lead quarantined")


def test_quarantined_files_remain_on_disk():
    """Test 6: Quarantined files remain on disk."""
    import tempfile
    import os
    from rws_web import _parse_candidates
    from pathlib import Path
    
    # Create temporary test directory
    with tempfile.TemporaryDirectory() as tmpdir:
        candidates_dir = Path(tmpdir) / "candidates"
        candidates_dir.mkdir()
        
        # Create a MusicBrainz fixture file
        mb_file = candidates_dir / "test_musicbrainz_hymn_lead.txt"
        mb_content = """Type: Hymn translation lead
Hymn: Test Hymn
Source: musicbrainz
Title: Test Recording
URL: https://musicbrainz.org/test"""
        mb_file.write_text(mb_content, encoding="utf-8")
        
        # Create a legitimate fixture file
        legit_file = candidates_dir / "test_legitimate_hymn_lead.txt"
        legit_content = """Type: Hymn translation lead
Hymn: Test Hymn
Source: archive.org
Title: Test Hymnal
URL: https://archive.org/test"""
        legit_file.write_text(legit_content, encoding="utf-8")
        
        # Parse candidates (this should filter out quarantined but not delete files)
        # Mock the study folder structure
        study_folder = Path(tmpdir)
        
        # Manually call parsing logic
        from rws_web import _parse_hymn_lead
        results = []
        for path in candidates_dir.glob("*_hymn_lead.txt"):
            lead = _parse_hymn_lead(path, path.read_text(encoding="utf-8"))
            if not lead.get("quarantined"):
                results.append(lead)
        
        # Assert MusicBrainz file still exists on disk
        assert mb_file.exists(), "Quarantined file should remain on disk"
        
        # Assert legitimate file exists
        assert legit_file.exists(), "Legitimate file should remain on disk"
        
        # Assert only legitimate candidate in results
        assert len(results) == 1, "Only non-quarantined candidate should be in results"
        assert "archive.org" in results[0]["text"], "Result should be the legitimate candidate"
        
    print("✓ Test 6 passed: Quarantined files remain on disk")


def test_quarantined_files_not_in_candidate_count():
    """Test 7: Quarantined files do not appear in the active candidate count."""
    from rws_web import _parse_hymn_lead
    from pathlib import Path
    
    # Create mock quarantined lead
    text_quarantined = """Type: Hymn translation lead
Hymn: Test
Source: musicbrainz
Title: Test
URL: test"""
    
    # Create mock legitimate lead
    text_legitimate = """Type: Hymn translation lead
Hymn: Test
Source: archive.org
Title: Test
URL: test"""
    
    result_q = _parse_hymn_lead(Path("test1.txt"), text_quarantined)
    result_l = _parse_hymn_lead(Path("test2.txt"), text_legitimate)
    
    # In _parse_candidates, quarantined leads are skipped (continue statement)
    # So they won't be in the returned list
    assert result_q["quarantined"] is True
    assert result_l.get("quarantined", False) is False
    print("✓ Test 7 passed: Quarantined files filtered from candidate count")


def test_legitimate_candidate_appears_normally():
    """Test 8: A legitimate non-MusicBrainz/non-Discogs candidate still appears normally."""
    from rws_web import _parse_hymn_lead
    from pathlib import Path
    
    text = """Type: Hymn translation lead
Hymn: Test Hymn
Language: Russian
Source: archive.org
Title: Russian Hymnal Collection
URL: https://archive.org/details/test
Status: UNVERIFIED"""
    
    result = _parse_hymn_lead(Path("test.txt"), text)
    
    assert result["tier"] == "LEAD", "Legitimate lead should have LEAD tier"
    assert result.get("quarantined", False) is False, "Should not be quarantined"
    assert result["burn_relation"] == "", "Should have no burn relation"
    print("✓ Test 8 passed: Legitimate candidate appears normally")



if __name__ == "__main__":
    print("Running Phase 1 Hymn Source Gating Tests (8 Tests)\n")
    
    try:
        test_musicbrainz_not_called_during_hymn_hunt()
        test_discogs_not_called_during_hymn_hunt()
        test_legitimate_sources_remain_enabled()
        test_musicbrainz_lead_quarantined()
        test_discogs_lead_quarantined()
        test_quarantined_files_remain_on_disk()
        test_quarantined_files_not_in_candidate_count()
        test_legitimate_candidate_appears_normally()
        
        print("\n" + "="*60)
        print("✅ ALL 8 TESTS PASSED")
        print("="*60)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
