import pytest

def test_start_session_blacklist(mock_daemon):
    # Setup domains to block by saving them so _load_lists finds them
    mock_daemon.domains_manager.save_lists({"blacklist": ["example.com", "test.com"], "whitelist": []})
    
    # Start session
    response = mock_daemon.session_manager._start_session({
        "action": "start",
        "duration_minutes": 60,
        "mode": "blacklist",
        "type": "standard",
        "intent": "Focus on work"
    })
    
    assert response["status"] == "ok"
    assert mock_daemon.state.session.active is True
    assert mock_daemon.state.session.mode == "blacklist"
    assert "example.com" in mock_daemon.session_base_domains
    assert "test.com" in mock_daemon.session_base_domains

def test_start_session_while_active_merges(mock_daemon):
    mock_daemon.state.session.active = True
    mock_daemon.state.session.mode = "blacklist"
    mock_daemon.state.session.session_type = "standard"
    from datetime import datetime, timedelta
    mock_daemon.state.session.session_expiry = datetime.now() + timedelta(minutes=10)
    
    response = mock_daemon.session_manager._start_session({
        "duration_minutes": 60,
        "mode": "blacklist",
        "type": "standard",
        "session_type": "standard"
    })
    
    # Overlapping sessions with the same mode and type merge successfully
    assert response["status"] == "ok"

def test_request_stop_delayed(mock_daemon, monkeypatch):
    mock_daemon.state.session.active = True
    mock_daemon.state.session.pending_unlock_at = None
    mock_daemon.state.session.mode = "blacklist"
    
    import forcefocus_daemon
    mock_daemon.KS_HASH_FILE = forcefocus_daemon.KS_HASH_FILE
    
    response = mock_daemon.session_manager._request_stop("")
    
    assert response["status"] == "delayed" or response["status"] == "error"

def test_cleanup_session_resets_state(mock_daemon):
    from datetime import datetime
    mock_daemon.state.session.active = True
    mock_daemon.state.session.mode = "blacklist"
    mock_daemon.state.session.session_expiry = datetime.now()
    mock_daemon.state.session.intent = "To be deleted"
    
    mock_daemon.session_manager._cleanup_session()
    
    assert mock_daemon.state.session.active is False
    assert mock_daemon.state.session.session_expiry is None
    assert mock_daemon.state.session.intent is None
