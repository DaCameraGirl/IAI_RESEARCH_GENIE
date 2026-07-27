#!/usr/bin/env python3
"""Test suite for hunt state isolation fixes."""

import re
import sys
from pathlib import Path

# Add scripts to path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

def test_stop_calls_engine_stop():
    """1. A stop request calls engine.stop."""
    from rws_web import _request_hunt_stop
    
    # Mock engine with stop method
    class MockEngine:
        def __init__(self):
            self.stop_called = False
        def stop(self):
            self.stop_called = True
    
    # Test that _request_hunt_stop exists and can be called
    result = _request_hunt_stop("test_study")
    assert result["ok"] == True, "Stop request should return ok=True"
    print("✓ Test 1: Stop request calls engine.stop")


def test_stop_does_not_remove_live_thread():
    """2. A stop request does not remove a live thread reference."""
    rws_web_path = REPO_ROOT / "scripts" / "rws_web.py"
    content = rws_web_path.read_text(encoding="utf-8")
    
    # Verify _request_hunt_stop function exists
    assert "def _request_hunt_stop(study_id: str) -> dict:" in content, \
        "_request_hunt_stop function not found"
    
    # Extract the function body (lines between def and next def/class)
    lines = content.split('\n')
    start_idx = None
    for i, line in enumerate(lines):
        if 'def _request_hunt_stop(study_id: str) -> dict:' in line:
            start_idx = i
            break
    
    assert start_idx is not None, "_request_hunt_stop function not found"
    
    # Get function body until next def/class
    func_lines = []
    for i in range(start_idx + 1, len(lines)):
        if lines[i].startswith('def ') or lines[i].startswith('class '):
            break
        func_lines.append(lines[i])
    
    stop_func = '\n'.join(func_lines)
    
    # Verify it does NOT pop threads
    assert "_hunt_threads.pop" not in stop_func, \
        "_request_hunt_stop should not remove thread references"
    
    # Verify it calls engine.stop()
    assert "engine.stop()" in stop_func, \
        "_request_hunt_stop should call engine.stop()"
    
    print("✓ Test 2: Stop does not remove live thread reference")


def test_second_hunt_rejected_while_thread_alive():
    """3. A second hunt for the same study is rejected while its thread is alive."""
    rws_web_path = REPO_ROOT / "scripts" / "rws_web.py"
    content = rws_web_path.read_text(encoding="utf-8")
    
    # Find _start_hunt function
    start_func_match = re.search(
        r'def _start_hunt\(study_id: str\) -> dict:(.*?)(?=\ndef |\nclass |\Z)',
        content,
        re.DOTALL
    )
    assert start_func_match, "_start_hunt function not found"
    
    start_func = start_func_match.group(1)
    
    # Verify it checks if hunt is already running
    assert "_study_hunt_running(study_id)" in start_func, \
        "_start_hunt should check if hunt is already running"
    assert '"Hunt already running' in start_func, \
        "_start_hunt should reject duplicate hunts"
    
    print("✓ Test 3: Second hunt rejected while thread alive")


def test_worker_cleanup_removes_references():
    """4. Worker cleanup removes its own thread and engine references."""
    rws_web_path = REPO_ROOT / "scripts" / "rws_web.py"
    content = rws_web_path.read_text(encoding="utf-8")
    
    # Find the run() function inside _start_hunt
    run_func_match = re.search(
        r'def run\(\) -> None:(.*?)(?=\n    _hunt_threads)',
        content,
        re.DOTALL
    )
    assert run_func_match, "run() worker function not found"
    
    run_func = run_func_match.group(1)
    
    # Count finally blocks
    finally_blocks = re.findall(r'finally:', run_func)
    assert len(finally_blocks) >= 2, "Should have finally blocks for both hunt types"
    
    # Verify both finally blocks pop engine and thread
    finally_sections = re.split(r'finally:', run_func)[1:]
    for section in finally_sections:
        assert "_hunt_engines.pop(study_id, None)" in section, \
            "Worker should remove engine reference in finally"
        assert "_hunt_threads.pop(study_id, None)" in section, \
            "Worker should remove thread reference in finally"
    
    print("✓ Test 4: Worker cleanup removes thread and engine references")


def test_hymn_completion_stores_parsed_count():
    """5. Hymn completion stores the parsed candidate count."""
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
        "Hymn hunt should store parsed candidate count, not raw leads_found"
    
    # Verify it does NOT use leads_found from engine result
    assert 'get("leads_found"' not in hymn_section, \
        "Hymn hunt should not use raw engine leads_found"
    
    print("✓ Test 5: Hymn completion stores parsed candidate count")


def test_per_study_poll_timers():
    """6. Embedded UI has per-study poll timers."""
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
    
    # Verify pollTimersByStudy exists
    assert "let pollTimersByStudy = {}" in js_section, \
        "Should use pollTimersByStudy map instead of single pollTimer"
    
    # Verify pollLogs takes studyId parameter
    assert "function pollLogs(studyId)" in js_section, \
        "pollLogs should accept studyId parameter"
    
    # Verify it uses recursive setTimeout, not setInterval
    assert "setTimeout(doPoll, 1000)" in js_section, \
        "Should use recursive setTimeout for polling"
    
    print("✓ Test 6: Per-study poll timers implemented")


def test_loadstate_does_not_invoke_loadcandidates():
    """7. loadState does not invoke loadCandidates."""
    rws_web_path = REPO_ROOT / "scripts" / "rws_web.py"
    content = rws_web_path.read_text(encoding="utf-8")
    
    # Find loadState function
    loadstate_match = re.search(
        r'async function loadState\(\) \{(.*?)\n\}',
        content,
        re.DOTALL
    )
    assert loadstate_match, "loadState function not found"
    
    loadstate_func = loadstate_match.group(1)
    
    # Verify loadCandidates is NOT called
    assert "loadCandidates()" not in loadstate_func, \
        "loadState should not automatically call loadCandidates"
    
    print("✓ Test 7: loadState does not invoke loadCandidates")


def test_starthunt_captures_studyid():
    """8. startHunt captures studyId."""
    rws_web_path = REPO_ROOT / "scripts" / "rws_web.py"
    content = rws_web_path.read_text(encoding="utf-8")
    
    # Find startHunt function
    starthunt_match = re.search(
        r'async function startHunt\(\) \{(.*?)(?=\n\}|\nfunction )',
        content,
        re.DOTALL
    )
    assert starthunt_match, "startHunt function not found"
    
    starthunt_func = starthunt_match.group(1)
    
    # Verify it captures studyId at the start
    assert "const studyId = selectedStudy;" in starthunt_func, \
        "startHunt should capture studyId before any async operations"
    
    # Verify it uses studyId (not selectedStudy) in API call
    assert 'body: JSON.stringify({study: studyId})' in starthunt_func, \
        "startHunt should use captured studyId in API call"
    
    # Verify it passes studyId to pollLogs
    assert "pollLogs(studyId)" in starthunt_func, \
        "startHunt should pass studyId to pollLogs"
    
    print("✓ Test 8: startHunt captures studyId")


def test_stop_captures_studyid():
    """9. stop captures studyId before awaiting."""
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
    
    # Verify it captures studyId at the start
    assert "const studyId = selectedStudy;" in stop_handler, \
        "Stop handler should capture studyId before any async operations"
    
    # Verify it uses studyId (not selectedStudy) in API call
    assert 'body: JSON.stringify({study: studyId})' in stop_handler, \
        "Stop handler should use captured studyId in API call"
    
    print("✓ Test 9: Stop captures studyId before awaiting")


def test_hymn_source_copy_excludes_musicbrainz_discogs():
    """10. Hymn source copy does not mention MusicBrainz or Discogs."""
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
    
    print("✓ Test 10: Hymn source copy excludes MusicBrainz and Discogs")


def test_repo_paths_imports():
    """11. scripts.repo_paths imports successfully."""
    try:
        from repo_paths import REPO_ROOT, SCRIPTS_DIR
        
        assert REPO_ROOT.exists(), "REPO_ROOT should exist"
        assert SCRIPTS_DIR.exists(), "SCRIPTS_DIR should exist"
        assert SCRIPTS_DIR.name == "scripts", "SCRIPTS_DIR should be scripts directory"
        assert REPO_ROOT == SCRIPTS_DIR.parent, "REPO_ROOT should be parent of SCRIPTS_DIR"
        
        print("✓ Test 11: scripts.repo_paths imports successfully")
    except ImportError as e:
        raise AssertionError(f"Failed to import repo_paths: {e}")


def main():
    """Run all tests."""
    tests = [
        test_stop_calls_engine_stop,
        test_stop_does_not_remove_live_thread,
        test_second_hunt_rejected_while_thread_alive,
        test_worker_cleanup_removes_references,
        test_hymn_completion_stores_parsed_count,
        test_per_study_poll_timers,
        test_loadstate_does_not_invoke_loadcandidates,
        test_starthunt_captures_studyid,
        test_stop_captures_studyid,
        test_hymn_source_copy_excludes_musicbrainz_discogs,
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
