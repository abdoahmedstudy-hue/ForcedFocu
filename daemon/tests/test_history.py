import pytest
from datetime import datetime, timedelta
import forcefocus_daemon
import json

def test_record_session_history(mock_daemon):
    # Set up session state
    mock_daemon.state.session.active = True
    mock_daemon.state.session.mode = "blacklist"
    mock_daemon.state.session.session_type = "standard"
    mock_daemon.state.session.intent = "Testing"
    mock_daemon.state.session.total_duration_seconds = 3600
    mock_daemon._mono_session_end = 0.0 # Will be completed
    mock_daemon.state.session.session_expiry = datetime.now()
    
    mock_daemon.history_manager.record_session_history()
    
    history_file = forcefocus_daemon.HISTORY_FILE
    assert history_file.exists()
    
    data = json.loads(history_file.read_text())
    assert len(data) == 1
    assert data[0]["intent"] == "Testing"
    assert data[0]["duration_minutes"] == 60
