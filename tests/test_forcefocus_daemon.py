import unittest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path
import json
import datetime

# Import the class to be tested
from forcefocus_daemon import ForcedFocusDaemon


class TestForcedFocusDaemon(unittest.TestCase):
    def setUp(self):
        # Initialize daemon without starting its threads or hitting filesystem too much
        with patch(
            "forcefocus_daemon.ForcedFocusDaemon._load_settings", return_value={}
        ):
            with patch("forcefocus_daemon.ForcedFocusDaemon._restore_session"):
                self.daemon = ForcedFocusDaemon()

    def test_validate_domain(self):
        # Valid domains
        self.assertTrue(ForcedFocusDaemon._validate_domain("google.com"))
        self.assertTrue(ForcedFocusDaemon._validate_domain("www.google.com"))
        self.assertTrue(ForcedFocusDaemon._validate_domain("my-site.co.uk"))
        self.assertTrue(ForcedFocusDaemon._validate_domain("a.b.c.d.e.com"))

        # Invalid domains
        self.assertFalse(ForcedFocusDaemon._validate_domain("google"))  # No dot
        self.assertFalse(
            ForcedFocusDaemon._validate_domain(".google.com")
        )  # Starts with dot
        self.assertFalse(
            ForcedFocusDaemon._validate_domain("google.com-")
        )  # Ends with hyphen
        self.assertFalse(ForcedFocusDaemon._validate_domain("goo gle.com"))  # Space
        self.assertFalse(
            ForcedFocusDaemon._validate_domain("http://google.com")
        )  # Protocol
        self.assertFalse(ForcedFocusDaemon._validate_domain("google.com/path"))  # Path
        self.assertFalse(
            ForcedFocusDaemon._validate_domain("a" * 256 + ".com")
        )  # Too long

    @patch("forcefocus_daemon.ForcedFocusDaemon._save_lists")
    @patch("forcefocus_daemon.ForcedFocusDaemon._load_lists")
    def test_cmd_add_domain(self, mock_load, mock_save):
        mock_load.return_value = {"blacklist": [], "whitelist": []}
        cmd = {"list": "blacklist", "domain": "example.com"}

        result = self.daemon._cmd_add_domain(cmd)

        self.assertEqual(result["status"], "ok")
        self.assertIn("example.com", result["lists"]["blacklist"])
        mock_save.assert_called_once()

    @patch("forcefocus_daemon.ForcedFocusDaemon._save_lists")
    @patch("forcefocus_daemon.ForcedFocusDaemon._load_lists")
    def test_cmd_remove_domain(self, mock_load, mock_save):
        mock_load.return_value = {"blacklist": ["example.com"], "whitelist": []}
        cmd = {"list": "blacklist", "domain": "example.com"}

        result = self.daemon._cmd_remove_domain(cmd)

        self.assertEqual(result["status"], "ok")
        self.assertNotIn("example.com", result["lists"]["blacklist"])
        mock_save.assert_called_once()

    @patch("forcefocus_daemon.ForcedFocusDaemon._save_groups")
    @patch("forcefocus_daemon.ForcedFocusDaemon._load_groups")
    def test_cmd_add_group(self, mock_load, mock_save):
        mock_load.return_value = {}
        cmd = {"name": "Work", "domains": ["slack.com", "github.com"]}

        result = self.daemon._cmd_add_group(cmd)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["groups"]["Work"], ["slack.com", "github.com"])
        mock_save.assert_called_once()

    @patch("forcefocus_daemon.ForcedFocusDaemon._save_groups")
    @patch("forcefocus_daemon.ForcedFocusDaemon._load_groups")
    def test_cmd_remove_group(self, mock_load, mock_save):
        mock_load.return_value = {"Work": ["slack.com"]}
        cmd = {"name": "Work"}

        result = self.daemon._cmd_remove_group(cmd)

        self.assertEqual(result["status"], "ok")
        self.assertNotIn("Work", result["groups"])
        mock_save.assert_called_once()

    @patch("forcefocus_daemon.ForcedFocusDaemon._enforce_block")
    @patch("forcefocus_daemon.ForcedFocusDaemon._atomic_write_json")
    @patch("forcefocus_daemon.get_continuous_time", return_value=100.0)
    @patch(
        "forcefocus_daemon.ForcedFocusDaemon._get_blacklist_domains",
        return_value=["example.com"],
    )
    def test_start_session_blacklist(
        self, mock_bl, mock_time, mock_write, mock_enforce
    ):
        cmd = {"action": "start", "duration_minutes": 60, "mode": "blacklist"}

        result = self.daemon._start_session(cmd)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(self.daemon.active)
        self.assertEqual(self.daemon.mode, "blacklist")
        self.assertEqual(self.daemon._mono_session_end, 100.0 + 3600)
        mock_enforce.assert_called_once()
        mock_write.assert_called_once()

    @patch(
        "forcefocus_daemon.subprocess.run",
        side_effect=Exception("Test cleanup exception"),
    )
    @patch("forcefocus_daemon.logging.error")
    @patch("forcefocus_daemon.ForcedFocusDaemon._play_sound")
    @patch("forcefocus_daemon.SESSION_LOCK")
    @patch("forcefocus_daemon.ForcedFocusDaemon._send_mac_notification")
    def test_cleanup_session_error_handling(
        self, mock_notif, mock_lock, mock_sound, mock_log_error, mock_run
    ):
        self.daemon.active = True
        self.daemon.mode = "blacklist"
        self.daemon.session_expiry = datetime.datetime.now()

        self.daemon._cleanup_session()

        self.assertFalse(self.daemon.active)
        mock_log_error.assert_called_once()
        self.assertIn("cleanup_session error", mock_log_error.call_args[0][0])
        mock_lock.unlink.assert_called_once_with(missing_ok=True)
        self.assertEqual(self.daemon.session_expiry, None)
        self.assertEqual(self.daemon.mode, "blacklist")

    def test_start_session_invalid_duration_type(self):
        cmd = {"action": "start", "duration_minutes": "invalid", "mode": "blacklist"}
        result = self.daemon._start_session(cmd)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "Invalid duration.")

    def test_start_session_invalid_duration_range(self):
        # Too low
        cmd = {"action": "start", "duration_minutes": 0, "mode": "blacklist"}
        result = self.daemon._start_session(cmd)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "Duration must be 1–1440 minutes.")

        # Too high
        cmd = {"action": "start", "duration_minutes": 1441, "mode": "blacklist"}
        result = self.daemon._start_session(cmd)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "Duration must be 1–1440 minutes.")

    def test_start_session_invalid_mode(self):
        cmd = {"action": "start", "duration_minutes": 60, "mode": "greylist"}
        result = self.daemon._start_session(cmd)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "Invalid mode.")

    @patch("forcefocus_daemon.subprocess.run")
    @patch("forcefocus_daemon.ForcedFocusDaemon._flush_dns")
    @patch("forcefocus_daemon.ForcedFocusDaemon._enforce_browser_policies")
    @patch("forcefocus_daemon.ForcedFocusDaemon._enforce_firewall")
    @patch("forcefocus_daemon.ForcedFocusDaemon._strip_block", return_value="stripped")
    @patch("forcefocus_daemon.Path.read_text", return_value="original")
    @patch("forcefocus_daemon.Path.write_text")
    @patch("forcefocus_daemon.ForcedFocusDaemon._play_sound")
    def test_cleanup_session(
        self,
        mock_sound,
        mock_write,
        mock_read,
        mock_strip,
        mock_fw,
        mock_bp,
        mock_dns,
        mock_run,
    ):
        self.daemon.active = True
        self.daemon.mode = "blacklist"

        self.daemon._cleanup_session()

        self.assertFalse(self.daemon.active)
        mock_write.assert_called()
        mock_dns.assert_called_once()
        mock_fw.assert_called_with(False)
        mock_bp.assert_called_with(False)

    @patch("forcefocus_daemon.ForcedFocusDaemon._persist_session_lock")
    @patch("forcefocus_daemon.ForcedFocusDaemon._enforce_current_mode")
    @patch("forcefocus_daemon.ForcedFocusDaemon._remove_block")
    @patch("forcefocus_daemon.get_continuous_time", return_value=200.0)
    @patch("forcefocus_daemon.ForcedFocusDaemon._play_sound")
    def test_transition_pomodoro_phase(
        self, mock_sound, mock_time, mock_remove, mock_enforce, mock_persist
    ):
        self.daemon.pomo_phase = "focus"
        self.daemon.pomo_break_minutes = 5
        self.daemon.pomo_current_cycle = 1

        self.daemon._transition_pomodoro_phase()

        self.assertEqual(self.daemon.pomo_phase, "break")
        self.assertEqual(self.daemon._mono_pomo_phase_end, 200.0 + 300)
        mock_remove.assert_called_once()
        mock_persist.assert_called_once()

    @patch("forcefocus_daemon.subprocess.run")
    @patch("forcefocus_daemon.Path.read_text", return_value="original hosts")
    @patch("forcefocus_daemon.Path.write_text")
    def test_enforce_doh_block_success(
        self, mock_write_text, mock_read_text, mock_subprocess_run
    ):
        self.daemon.session_expiry = datetime.datetime.now()
        self.daemon._enforce_doh_block()

        mock_read_text.assert_called_once()
        mock_write_text.assert_called_once()
        self.assertEqual(mock_subprocess_run.call_count, 2)

        # Verify write contains DoH block comments
        written_content = mock_write_text.call_args[0][0]
        self.assertIn("# Mode: WHITELIST (DoH block)", written_content)
        self.assertIn("# DoH providers (anti-bypass)", written_content)

    @patch("forcefocus_daemon.logging.error")
    @patch("forcefocus_daemon.Path.read_text", side_effect=Exception("Read failed"))
    @patch("forcefocus_daemon.subprocess.run")
    def test_enforce_doh_block_error(
        self, mock_subprocess_run, mock_read_text, mock_logging_error
    ):
        self.daemon._enforce_doh_block()

        mock_logging_error.assert_called_once()
        self.assertIn(
            "_enforce_doh_block failed: %s", mock_logging_error.call_args[0][0]
        )

    @patch("forcefocus_daemon.ForcedFocusDaemon._atomic_write_json")
    def test_persist_session_lock_success(self, mock_atomic_write):
        self.daemon.schedules = []
        self.daemon.active = False
        self.daemon._persist_session_lock()
        mock_atomic_write.assert_called_once()
        written_data = mock_atomic_write.call_args[0][1]
        self.assertEqual(written_data, {"schedules": []})

    @patch("forcefocus_daemon.logging.error")
    @patch(
        "forcefocus_daemon.ForcedFocusDaemon._atomic_write_json",
        side_effect=Exception("Simulated write failure"),
    )
    def test_persist_session_lock_error(self, mock_atomic_write, mock_logging_error):
        self.daemon.schedules = []
        self.daemon.active = False
        self.daemon._persist_session_lock()
        mock_atomic_write.assert_called_once()
        mock_logging_error.assert_called_once()
        self.assertIn(
            "Failed to persist session.lock", mock_logging_error.call_args[0][0]
        )

    @patch("forcefocus_daemon.logging.info")
    @patch("forcefocus_daemon.SESSION_LOCK")
    def test_restore_session_no_lock(self, mock_session_lock, mock_logging_info):
        # We need to unmock _restore_session just for these tests, as it was mocked in setUp
        with patch(
            "forcefocus_daemon.ForcedFocusDaemon._load_settings", return_value={}
        ):
            daemon = ForcedFocusDaemon()
            mock_session_lock.exists.return_value = False
            daemon._restore_session()
            mock_session_lock.exists.assert_called_once()
            mock_logging_info.assert_called_with(
                "No persisted session found. Daemon idle."
            )
            mock_session_lock.read_text.assert_not_called()

    @patch("forcefocus_daemon.logging.error")
    @patch("forcefocus_daemon.SESSION_LOCK")
    def test_restore_session_corrupt_lock(self, mock_session_lock, mock_logging_error):
        with patch(
            "forcefocus_daemon.ForcedFocusDaemon._load_settings", return_value={}
        ):
            daemon = ForcedFocusDaemon()
            mock_session_lock.exists.return_value = True
            mock_session_lock.read_text.return_value = "invalid json"
            daemon._restore_session()
            mock_session_lock.exists.assert_called_once()
            mock_session_lock.read_text.assert_called_once()
            mock_session_lock.unlink.assert_called_once_with(missing_ok=True)
            self.assertTrue(mock_logging_error.called)

    @patch("forcefocus_daemon.logging.warning")
    @patch("forcefocus_daemon.subprocess.run")
    @patch("forcefocus_daemon.ForcedFocusDaemon._strip_block", return_value="stripped")
    @patch(
        "forcefocus_daemon.ForcedFocusDaemon._build_blacklist_block",
        return_value="block",
    )
    @patch("forcefocus_daemon.Path.read_text", return_value="original")
    @patch("forcefocus_daemon.Path.write_text")
    @patch("forcefocus_daemon.ForcedFocusDaemon._enforce_firewall")
    @patch("forcefocus_daemon.ForcedFocusDaemon._enforce_browser_policies")
    @patch("forcefocus_daemon.ForcedFocusDaemon._clear_browser_caches")
    @patch("forcefocus_daemon.ForcedFocusDaemon._flush_dns")
    def test_enforce_block_chflags_error(
        self,
        mock_flush,
        mock_cache,
        mock_policies,
        mock_fw,
        mock_write,
        mock_read,
        mock_build,
        mock_strip,
        mock_run,
        mock_logging_warn,
    ):
        # Setup mock for subprocess.run to simulate chflags failure
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = b"Permission denied"
        mock_run.return_value = mock_result

        self.daemon._enforce_block()

        # subprocess.run is called twice for chflags nouchg and uchg
        self.assertEqual(mock_run.call_count, 2)

        # Verify logging.warning was called twice with the appropriate messages
        self.assertEqual(mock_logging_warn.call_count, 2)

        # First warning for nouchg
        mock_logging_warn.assert_any_call(
            "chflags nouchg failed with code %d: %s", 1, "Permission denied"
        )
        # Second warning for uchg
        mock_logging_warn.assert_any_call(
            "chflags uchg failed with code %d: %s", 1, "Permission denied"
        )

        # Verify other side effects still run even if chflags fails
        mock_write.assert_called_once()
        mock_fw.assert_called_once_with(True)
        mock_policies.assert_called_once_with(True)
        mock_cache.assert_called_once()
        mock_flush.assert_called_once()

    @patch("forcefocus_daemon.logging.error")
    @patch("forcefocus_daemon.subprocess.run")
    @patch("forcefocus_daemon.Path.read_text", side_effect=Exception("Disk read error"))
    def test_enforce_block_exception(self, mock_read, mock_run, mock_logging_error):
        # subprocess.run succeeds
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        self.daemon._enforce_block()

        # Verify that the exception is caught and logged
        mock_logging_error.assert_called_once()
        self.assertIn("enforce_block failed", str(mock_logging_error.call_args))


if __name__ == "__main__":
    unittest.main()
