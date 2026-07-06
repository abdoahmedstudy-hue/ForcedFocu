import pytest
import json

def test_dispatch_start_command(mock_daemon, monkeypatch):
    start_called = False
    
    def mock_start(cmd):
        nonlocal start_called
        start_called = True
        return {"status": "ok"}
        
    monkeypatch.setattr(mock_daemon.session_manager, "_start_session", mock_start)
    
    raw = json.dumps({
        "action": "start",
        "duration": 60,
        "mode": "blacklist",
        "type": "standard"
    })
    response = mock_daemon.socket_api_manager.dispatch_command(raw)
    
    assert start_called is True
    assert response["status"] == "ok"

def test_dispatch_invalid_action(mock_daemon):
    raw = json.dumps({
        "action": "nonexistent_action"
    })
    response = mock_daemon.socket_api_manager.dispatch_command(raw)
    
    assert response["status"] == "error"

def test_dispatch_status_command(mock_daemon):
    raw = json.dumps({"action": "status"}).encode("utf-8")
    
    # When inactive, it returns {"status": "ok", "active": False, "state": "idle", ...}
    mock_daemon.state.session.active = False
    response = mock_daemon.socket_api_manager.dispatch_command(raw)
    assert response["status"] == "ok"
    assert response.get("active") is False
    assert response.get("state") == "idle"
