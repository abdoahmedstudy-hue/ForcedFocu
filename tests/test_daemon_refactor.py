import unittest
from unittest.mock import MagicMock, patch
import json
import os
from pathlib import Path
from datetime import datetime, timedelta

# Mock constants before importing
with patch("os.geteuid", return_value=0):
    import forcefocus_daemon
    from forcefocus_daemon import ForcedFocusDaemon


class TestDaemonRefactor(unittest.TestCase):
    def setUp(self):
        # Mock configuration paths to use /tmp
        forcefocus_daemon.CONFIG_DIR = Path("/tmp/forcefocus")
        forcefocus_daemon.SESSION_LOCK = forcefocus_daemon.CONFIG_DIR / "session.lock"
        forcefocus_daemon.LISTS_FILE = forcefocus_daemon.CONFIG_DIR / "lists.json"
        forcefocus_daemon.GROUPS_FILE = forcefocus_daemon.CONFIG_DIR / "groups.json"
        forcefocus_daemon.API_TOKEN_FILE = forcefocus_daemon.CONFIG_DIR / "api_token"
        forcefocus_daemon.HOSTS_PATH = Path("/tmp/hosts")

        if not forcefocus_daemon.CONFIG_DIR.exists():
            forcefocus_daemon.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        with patch("os.geteuid", return_value=0), patch(
            "forcefocus_daemon.ForcedFocusDaemon._load_settings", return_value={}
        ), patch("forcefocus_daemon.ForcedFocusDaemon._ensure_config_dir"), patch(
            "forcefocus_daemon.ForcedFocusDaemon._ensure_lists_file"
        ), patch(
            "forcefocus_daemon.ForcedFocusDaemon._ensure_groups_file"
        ), patch(
            "forcefocus_daemon.ForcedFocusDaemon._generate_api_token"
        ), patch(
            "forcefocus_daemon.ForcedFocusDaemon._install_signal_handlers"
        ):
            self.daemon = ForcedFocusDaemon()

    def tearDown(self):
        if forcefocus_daemon.SESSION_LOCK.exists():
            forcefocus_daemon.SESSION_LOCK.unlink()

    def test_active_domains_init(self):
        self.assertEqual(self.daemon.active_domains, [])
        self.assertTrue(hasattr(self.daemon, "active_domains"))
        self.assertFalse(hasattr(self.daemon, "blocked_domains"))

    @patch("forcefocus_daemon.ForcedFocusDaemon._load_lists")
    @patch("forcefocus_daemon.ForcedFocusDaemon._enforce_block")
    @patch("forcefocus_daemon.ForcedFocusDaemon._atomic_write_json")
    def test_start_session_blacklist(
        self, mock_atomic_write, mock_enforce, mock_load_lists
    ):
        mock_load_lists.return_value = {"blacklist": ["example.com"], "whitelist": []}
        cmd = {"action": "start", "duration_minutes": 60, "mode": "blacklist"}

        with patch("forcefocus_daemon.get_continuous_time", return_value=100.0):
            self.daemon._start_session(cmd)

        self.assertEqual(self.daemon.mode, "blacklist")
        self.assertIn("example.com", self.daemon.active_domains)
        self.assertTrue(
            any(
                "active_domains" in call.args[1]
                for call in mock_atomic_write.call_args_list
            )
        )

    def test_restore_session_backward_compatibility(self):
        legacy_data = {
            "expiry": (datetime.now() + timedelta(minutes=60)).isoformat(),
            "mode": "blacklist",
            "duration_minutes": 60,
            "blocked_domains": ["legacy.com"],
            "session_base_domains": ["legacy.com"],
        }
        forcefocus_daemon.SESSION_LOCK.write_text(json.dumps(legacy_data))

        with patch("forcefocus_daemon.ForcedFocusDaemon._enforce_block"), patch(
            "forcefocus_daemon.get_continuous_time", return_value=100.0
        ):
            self.daemon._restore_session()

        self.assertTrue(self.daemon.active)
        self.assertEqual(self.daemon.active_domains, ["legacy.com"])

    def test_restore_session_empty_list(self):
        # Test that an empty list of active_domains is correctly restored and not fallen back
        session_data = {
            "expiry": (datetime.now() + timedelta(minutes=60)).isoformat(),
            "mode": "whitelist",
            "duration_minutes": 60,
            "active_domains": [],
            "blocked_domains": ["should_not_use.com"],
            "session_base_domains": [],
        }
        forcefocus_daemon.SESSION_LOCK.write_text(json.dumps(session_data))

        with patch("forcefocus_daemon.ForcedFocusDaemon._enforce_whitelist"), patch(
            "forcefocus_daemon.get_continuous_time", return_value=100.0
        ):
            self.daemon._restore_session()

        self.assertTrue(self.daemon.active)
        self.assertEqual(self.daemon.active_domains, [])


if __name__ == "__main__":
    unittest.main()
