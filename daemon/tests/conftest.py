import os
import sys
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add the daemon directory to sys.path so we can import forcefocus_daemon
daemon_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(daemon_dir))

from forcefocus_daemon import ForcedFocusDaemon

@pytest.fixture
def tmp_config_dir(tmp_path):
    """Provides a temporary directory to act as /etc/forcefocus."""
    config_dir = tmp_path / "forcefocus"
    config_dir.mkdir()
    return config_dir

@pytest.fixture
def mock_daemon(tmp_config_dir, monkeypatch):
    """Provides a ForcedFocusDaemon instance with all system operations mocked out."""
    
    # Patch constants in daemon
    monkeypatch.setattr("forcefocus_daemon.CONFIG_DIR", tmp_config_dir)
    monkeypatch.setattr("forcefocus_daemon.SESSION_LOCK", tmp_config_dir / "session.lock")
    monkeypatch.setattr("forcefocus_daemon.KS_HASH_FILE", tmp_config_dir / "ks_hash")
    monkeypatch.setattr("forcefocus_daemon.LISTS_FILE", tmp_config_dir / "lists.json")
    monkeypatch.setattr("forcefocus_daemon.GROUPS_FILE", tmp_config_dir / "groups.json")
    monkeypatch.setattr("forcefocus_daemon.API_TOKEN_FILE", tmp_config_dir / "api_token")
    monkeypatch.setattr("forcefocus_daemon.SETTINGS_FILE", tmp_config_dir / "settings.json")
    monkeypatch.setattr("forcefocus_daemon.PERMA_BLOCK_FILE", tmp_config_dir / "perma_blocklist.json")
    monkeypatch.setattr("forcefocus_daemon.TEMPLATES_FILE", tmp_config_dir / "templates.json")
    monkeypatch.setattr("forcefocus_daemon.HISTORY_FILE", tmp_config_dir / "session_history.json")
    monkeypatch.setattr("forcefocus_daemon.PRAYER_CACHE_FILE", tmp_config_dir / "prayer_calendar.json")

    # Patch constants in extracted modules
    monkeypatch.setattr("forcefocus.history.HISTORY_FILE", tmp_config_dir / "session_history.json")
    monkeypatch.setattr("forcefocus.history.SETTINGS_FILE", tmp_config_dir / "settings.json")
    monkeypatch.setattr("forcefocus.domains.LISTS_FILE", tmp_config_dir / "lists.json")
    monkeypatch.setattr("forcefocus.domains.GROUPS_FILE", tmp_config_dir / "groups.json")
    monkeypatch.setattr("forcefocus.schedules.TEMPLATES_FILE", tmp_config_dir / "templates.json")
    monkeypatch.setattr("forcefocus.session.core.SESSION_LOCK", tmp_config_dir / "session.lock")
    monkeypatch.setattr("forcefocus.prayer.PRAYER_CACHE_FILE", tmp_config_dir / "prayer_calendar.json")
    monkeypatch.setattr("forcefocus.prayer.SETTINGS_FILE", tmp_config_dir / "settings.json")
    
    # Mock /etc/hosts
    mock_hosts = tmp_config_dir / "hosts"
    mock_hosts.write_text("127.0.0.1 localhost\n")
    monkeypatch.setattr("forcefocus_daemon.HOSTS_PATH", mock_hosts)
    
    # Mock system calls
    monkeypatch.setattr("subprocess.run", MagicMock())
    monkeypatch.setattr("subprocess.Popen", MagicMock())
    monkeypatch.setattr("os.chmod", MagicMock())
    monkeypatch.setattr("os.chown", MagicMock())
    
    # We don't want tests to actually bind to ports or loop infinitely
    monkeypatch.setattr("forcefocus.dns_proxy.LocalDNSProxy", MagicMock())
    monkeypatch.setattr("forcefocus_daemon.SniProxy", MagicMock())
    
    # Mock time
    monkeypatch.setattr("time.sleep", MagicMock())
    
    daemon = ForcedFocusDaemon()
    
    # Prevent background threads from starting
    monkeypatch.setattr(daemon.socket_api_manager, "socket_server", MagicMock())
    monkeypatch.setattr(daemon.watchdog_manager, "watchdog_loop", MagicMock())
    monkeypatch.setattr(daemon.http_api_manager, "http_server", MagicMock())
    
    return daemon
