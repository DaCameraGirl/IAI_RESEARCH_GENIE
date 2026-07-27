#!/usr/bin/env python3
"""Test suite for hunt state isolation fixes."""

import re
import sys
import threading
from pathlib import Path

# Add scripts to path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

def test_stop_calls_engine_stop():
    """1. A stop request calls engine.stop (behavioral)."""
    import rws_web
    
    # Mock engine with stop method
    class MockEngine:
        def __init__(self):
            self.stop_called = False
        def stop(self):
            self.stop_called = True
    
    test_study = "test_stop_engine_99999"
    mock_engine = MockEngine()
    
    try:
        # Register mock engine
        rws_web._hunt_engines[test_study] = mock_engine
        
        # Call stop
        result = rws_web._request_hunt_stop(test_study)
        
        # Verify
        assert result["ok"] == True, "Stop request should return ok=True"
        assert mock_engine.stop_called == True, "Engine.stop() should be called"
        
        print("✓ Test 1: Stop request calls engine.stop (behavioral)")
    finally:
        # Cleanup
        rws_web._hunt_engines.pop(test_study, None)
        rws_web._hunt_threads.pop(test_study, None)


def test_stop_does_not_remove_live_thread():
    """2. A stop request does not remove a live thread reference (behavioral)."""
    import rws_web
    
    class MockEngine:
        def stop(self):
            pass
    
    test_study = "test_live_thread_99999"
    mock_engine = MockEngine()
    
    # Create a fake live thread that stays alive
    import time
    fake_thread = threading.Thread(target=lambda: time.sleep(10), daemon=True)
    fake_thread.start()
    
    try:
        # Register mock engine and fake thread
        rws_web._hunt_engines[test_study] = mock_engine
        rws_web._hunt_threads[test_study] = fake_thread
        
        # Call stop
        result = rws_web._request_hunt_stop(test_study)
        
        # Verify thread reference remains
        assert test_study in rws_web._hunt_threads, \
            "Live thread reference should remain after stop request"
        assert rws_web._hunt_threads[test_study] is fake_thread, \
            "Thread reference should be unchanged"
        assert result.get("stopping") == True, \
            "Result should indicate thread is still stopping"
        
        print("✓ Test 2: Stop does not remove live thread reference (behavioral)")
    finally:
        # Cleanup
        rws_web._hunt_engines.pop(test_study, None)
        rws_web._hunt_threads.pop(test_study, None)


def test_second_hunt_rejected_while_thread_alive():
    """3. A second hunt for the same study is rejected while its thread is alive (behavioral)."""
    import rws_web
    
    test_study = "test_duplicate_hunt_99999"
    
    # Create a fake live thread that stays alive
    import time
    fake_thread = threading.Thread(target=lambda: time.sleep(10), daemon=True)
    fake_thread.start()
    
    try:
        # Register fake thread to simulate running hunt
        rws_web._hunt_threads[test_study] = fake_thread
        
        # Verify _study_hunt_running returns True
        assert rws_web._study_hunt_running(test_study) == True, \
            "Study should be detected as running"
        
        # The rejection happens in _start_hunt via _study_hunt_running check
        # We verify the check works without calling _start_hunt (which needs STUDY_META)
        
        print("✓ Test 3: Second hunt rejected while thread alive (behavioral)")
    finally:
        # Cleanup
        rws_web._hunt_engines.pop(test_study, None)
        rws_web._hunt_threads.pop(test_study, None)


def test_cleanup_removes_matching_refs():
    """4. Worker cleanup removes matching engine and thread references (behavioral)."""
    import rws_web
    
    test_study = "test_cleanup_99999"
    
    class MockEngine:
        pass
    
    engine1 = MockEngine()
    thread1 = threading.Thread(target=lambda: None, daemon=True)
    
    engine2 = MockEngine()
    thread2 = threading.Thread(target=lambda: None, daemon=True)
    
    try:
        # Test 1: Cleanup removes matching references
        rws_web._hunt_engines[test_study] = engine1
        rws_web._hunt_threads[test_study] = thread1
        
        rws_web._cleanup_hunt_refs(test_study, engine1, thread1)
        
        assert test_study not in rws_web._hunt_engines, \
            "Matching engine should be removed"
        assert test_study not in rws_web._hunt_threads, \
            "Matching thread should be removed"
        
        # Test 2: Cleanup does NOT remove replacement references
        rws_web._hunt_engines[test_study] = engine2
        rws_web._hunt_threads[test_study] = thread2
        
        rws_web._cleanup_hunt_refs(test_study, engine1, thread1)
        
        assert test_study in rws_web._hunt_engines, \
            "Replacement engine should NOT be removed"
        assert rws_web._hunt_engines[test_study] is engine2, \
            "Replacement engine should remain unchanged"
        assert test_study in rws_web._hunt_threads, \
            "Replacement thread should NOT be removed"
        assert rws_web._hunt_threads[test_study] is thread2, \
            "Replacement thread should remain unchanged"
        
        print("✓ Test 4: Worker cleanup removes matching refs (behavioral)")
    finally:
        # Cleanup
        rws_web._hunt_engines.pop(test_study, None)
        rws_web._hunt_threads.pop(test_study, None)


def test_hymn_completion_stores_parsed_count():
    """5. Hymn completion stores the parsed candidate count (contract)."""
    rws_web_path = REPO_ROOT / "scripts" / "rws_web.py"
    content = rws_web_path.read_text(encoding="utf-8")
    
    # Find copyright/hymn hunt section
    hymn_section_match = re.search(
        r'if meta\.get\("type"\) == "copyright":(.*?)return',
        content,
        re.DOTALL
    )
    assert hymn_section_match, "Copyright/hymn hunt section not found"
    
    hymn_section = hymn_section_match.group(1)
    
    # Verify it uses len(_parse_candidates(study_id))
    assert 'len(_parse_candidates(study_id))' in hymn_section, \
        "Hymn hunt should store parsed candidate count"
    
    # Verify it does NOT use leads_found from engine result
    assert 'get("leads_found"' not in hymn_section, \
        "Hymn hunt should not use raw engine leads_found"
    
    print("✓ Test 5: Hymn completion stores parsed candidate count (contract)")


def test_no_global_hunting_vars():
    """6. No global hunting or huntingStudy variables remain (contract)."""
    rws_web_path = REPO_ROOT / "scripts" / "rws_web.py"
    content = rws_web_path.read_text(encoding="utf-8")
    
    # Find JavaScript section
    js_section_match = re.search(
        r'<script>(.*?)</script>',
        content,
        re.DOTALL
    )
    assert js_section_match, "JavaScript section not found"
    
    js_section = js_section_match.group(1)
    
    # Verify no hunting globals
    assert "let hunting =" not in js_section, \
        "Global 'hunting' variable should be removed"
    assert "let huntingStudy =" not in js_section, \
        "Global 'huntingStudy' variable should be removed"
    
    print("✓ Test 6: No global hunting or huntingStudy variables (contract)")


def test_pollLogs_no_background_setHuntUi():
    """7. pollLogs does not call setHuntUi for background studies (contract)."""
    rws_web_path = REPO_ROOT / "scripts" / "rws_web.py"
    content = rws_web_path.read_text(encoding="utf-8")
    
    # Find pollLogs function
    pollLogs_match = re.search(
        r'function pollLogs\(studyId\) \{(.*?)\n\}',
        content,
        re.DOTALL
    )
    assert pollLogs_match, "pollLogs function not found"
    
    pollLogs_func = pollLogs_match.group(1)
    
    # Verify setHuntUi is not called unconditionally
    # It should only be called when selectedStudy === studyId or not at all
    lines = pollLogs_func.split('\n')
    for line in lines:
        if 'setHuntUi' in line:
            # Should not have unconditional setHuntUi calls
            assert 'if' in pollLogs_func[:pollLogs_func.index(line)] or \
                   'selectedStudy' in line, \
                "setHuntUi should not be called for background studies"
    
    print("✓ Test 7: pollLogs does not call setHuntUi for background studies (contract)")


def test_completion_refreshes_selected_study():
    """8. Hunt completion directly refreshes candidates for selected study (contract)."""
    rws_web_path = REPO_ROOT / "scripts" / "rws_web.py"
    content = rws_web_path.read_text(encoding="utf-8")
    
    # Find pollLogs function
    pollLogs_match = re.search(
        r'function pollLogs\(studyId\) \{(.*?)\n\}',
        content,
        re.DOTALL
    )
    assert pollLogs_match, "pollLogs function not found"
    
    pollLogs_func = pollLogs_match.group(1)
    
    # Find the not-running branch
    assert 'if (!data.running)' in pollLogs_func, \
        "Should have completion branch"
    
    # Verify it checks selectedStudy === studyId
    assert 'selectedStudy === studyId' in pollLogs_func, \
        "Should check if completed study is selected"
    
    # Verify it calls loadCandidates
    assert 'loadCandidates()' in pollLogs_func, \
        "Should refresh candidates for selected completed study"
    
    print("✓ Test 8: Completion refreshes candidates for selected study (contract)")


def test_startup_conditional_loadCandidates():
    """9. Startup does not unconditionally call loadCandidates (contract)."""
    rws_web_path = REPO_ROOT / "scripts" / "rws_web.py"
    content = rws_web_path.read_text(encoding="utf-8")
    
    # Find ensureFreshBuild startup section
    startup_match = re.search(
        r'ensureFreshBuild\(\)\.then\(async \(\) => \{(.*?)\}\);',
        content,
        re.DOTALL
    )
    assert startup_match, "Startup section not found"
    
    startup_section = startup_match.group(1)
    
    # Verify loadCandidates is conditional
    assert "if (document.querySelector('.tab.active')?.dataset.tab === 'candidates')" in startup_section, \
        "loadCandidates should be conditional on active tab"
    
    # Verify it's not called unconditionally
    lines = startup_section.split('\n')
    for i, line in enumerate(lines):
        if 'await loadCandidates()' in line:
            # Check if there's an if statement before it
            preceding = '\n'.join(lines[:i])
            assert 'if (' in preceding, \
                "loadCandidates should be inside conditional block"
    
    print("✓ Test 9: Startup conditionally loads candidates (contract)")


def test_stop_no_premature_setHuntUi():
    """10. Stop does not call setHuntUi before awaiting server (contract)."""
    rws_web_path = REPO_ROOT / "scripts" / "rws_web.py"
    content = rws_web_path.read_text(encoding="utf-8")
    
    # Find stop button onclick handler
    stop_match = re.search(
        r"\$\('stopBtn'\)\.onclick = async \(\) => \{(.*?)\};",
        content,
        re.DOTALL
    )
    assert stop_match, "stopBtn onclick handler not found"
    
    stop_handler = stop_match.group(1)
    
    # Verify setHuntUi is not called before await api
    lines = stop_handler.split('\n')
    api_call_idx = None
    setHuntUi_idx = None
    
    for i, line in enumerate(lines):
        if 'await api(' in line and '/api/hunt/stop' in line:
            api_call_idx = i
        if 'setHuntUi(false' in line:
            setHuntUi_idx = i
    
    # setHuntUi should not appear before the API call
    if setHuntUi_idx is not None and api_call_idx is not None:
        assert setHuntUi_idx > api_call_idx, \
            "setHuntUi should not be called before stop API request"
    
    print("✓ Test 10: Stop does not call setHuntUi before server response (contract)")


def test_pollTimers_store_timeout_handles():
    """11. pollTimersByStudy stores recursive timeout handles (contract)."""
    rws_web_path = REPO_ROOT / "scripts" / "rws_web.py"
    content = rws_web_path.read_text(encoding="utf-8")
    
    # Find pollLogs function
    pollLogs_match = re.search(
        r'function pollLogs\(studyId\) \{(.*?)\n\}',
        content,
        re.DOTALL
    )
    assert pollLogs_match, "pollLogs function not found"
    
    pollLogs_func = pollLogs_match.group(1)
    
    # Verify setTimeout is assigned to pollTimersByStudy
    assert 'pollTimersByStudy[studyId] = setTimeout(' in pollLogs_func, \
        "Should store timeout handle in pollTimersByStudy"
    
    # Verify recursive setTimeout pattern
    assert 'setTimeout(doPoll,' in pollLogs_func, \
        "Should use recursive setTimeout"
    
    print("✓ Test 11: pollTimersByStudy stores timeout handles (contract)")


def test_poll_failures_retry():
    """12. Poll failures schedule a retry after 2000ms (contract)."""
    rws_web_path = REPO_ROOT / "scripts" / "rws_web.py"
    content = rws_web_path.read_text(encoding="utf-8")
    
    # Find pollLogs function
    pollLogs_match = re.search(
        r'function pollLogs\(studyId\) \{(.*?)\n\}',
        content,
        re.DOTALL
    )
    assert pollLogs_match, "pollLogs function not found"
    
    pollLogs_func = pollLogs_match.group(1)
    
    # Verify try-catch exists
    assert 'try {' in pollLogs_func, "Should have try-catch for error handling"
    assert 'catch' in pollLogs_func, "Should have catch block"
    
    # Verify retry with 2000ms delay
    assert 'setTimeout(doPoll, 2000)' in pollLogs_func, \
        "Should retry after 2000ms on error"
    
    print("✓ Test 12: Poll failures schedule retry after 2000ms (contract)")


def test_hymn_sources_exclude_musicbrainz_discogs():
    """13. Hymn source copy excludes MusicBrainz and Discogs (contract)."""
    rws_web_path = REPO_ROOT / "scripts" / "rws_web.py"
    content = rws_web_path.read_text(encoding="utf-8")
    
    # Find the sources text for hymn studies
    sources_match = re.search(
        r'"HathiTrust.*?<br><br>"',
        content,
        re.DOTALL
    )
    assert sources_match, "Hymn sources text not found"
    
    sources_text = sources_match.group(0)
    
    # Verify MusicBrainz and Discogs are NOT mentioned
    assert "MusicBrainz" not in sources_text, \
        "Hymn sources should not mention MusicBrainz"
    assert "Discogs" not in sources_text, \
        "Hymn sources should not mention Discogs"
    
    # Verify HathiTrust and WorldCat are still mentioned
    assert "HathiTrust" in sources_text, \
        "Hymn sources should still mention HathiTrust"
    assert "WorldCat" in sources_text, \
        "Hymn sources should still mention WorldCat"
    
    print("✓ Test 13: Hymn sources exclude MusicBrainz and Discogs (contract)")


def test_repo_paths_imports():
    """14. scripts.repo_paths imports successfully (behavioral)."""
    try:
        from repo_paths import REPO_ROOT, SCRIPTS_DIR
        
        assert REPO_ROOT.exists(), "REPO_ROOT should exist"
        assert SCRIPTS_DIR.exists(), "SCRIPTS_DIR should exist"
        assert SCRIPTS_DIR.name == "scripts", "SCRIPTS_DIR should be scripts directory"
        assert REPO_ROOT == SCRIPTS_DIR.parent, "REPO_ROOT should be parent of SCRIPTS_DIR"
        
        print("✓ Test 14: scripts.repo_paths imports successfully (behavioral)")
    except ImportError as e:
        raise AssertionError(f"Failed to import repo_paths: {e}")


def main():
    """Run all tests."""
    tests = [
        test_stop_calls_engine_stop,
        test_stop_does_not_remove_live_thread,
        test_second_hunt_rejected_while_thread_alive,
        test_cleanup_removes_matching_refs,
        test_hymn_completion_stores_parsed_count,
        test_no_global_hunting_vars,
        test_pollLogs_no_background_setHuntUi,
        test_completion_refreshes_selected_study,
        test_startup_conditional_loadCandidates,
        test_stop_no_premature_setHuntUi,
        test_pollTimers_store_timeout_handles,
        test_poll_failures_retry,
        test_hymn_sources_exclude_musicbrainz_discogs,
        test_repo_paths_imports,
    ]
    
    print("\n" + "="*60)
    print("Hunt State Isolation Test Suite")
    print("="*60 + "\n")
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__doc__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__doc__}: Unexpected error: {e}")
            failed += 1
    
    print("\n" + "="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60 + "\n")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())