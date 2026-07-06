import pytest
import json
import forcefocus_daemon

def test_expand_youtube_in_blacklist(mock_daemon):
    mock_daemon.domains_manager.save_lists({"blacklist": ["youtube.com"], "whitelist": []})
    mock_daemon._atomic_write_json(forcefocus_daemon.GROUPS_FILE, {})
    
    domains = mock_daemon.domains_manager.get_blacklist_domains([])
    assert "youtube.com" in domains

def test_get_blacklist_with_groups(mock_daemon):
    mock_daemon.domains_manager.save_lists({"blacklist": ["base.com"], "whitelist": []})
    mock_daemon._atomic_write_json(forcefocus_daemon.GROUPS_FILE, {
        "work": ["work-distraction.com"]
    })
    
    domains = mock_daemon.domains_manager.get_blacklist_domains(["work"])
    assert "base.com" in domains
    assert "work-distraction.com" in domains
