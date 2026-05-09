import unittest
from unittest.mock import patch
import os

# Import the daemon class
with patch("os.geteuid", return_value=0):
    from forcefocus_daemon import ForcedFocusDaemon


class TestDaemonNaming(unittest.TestCase):
    def setUp(self):
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

    def test_init_naming(self):
        # Assert that the new name exists and the old name does not
        self.assertTrue(
            hasattr(self.daemon, "active_domains"),
            "active_domains attribute should exist",
        )
        self.assertFalse(
            hasattr(self.daemon, "blocked_domains"),
            "blocked_domains attribute should not exist",
        )


if __name__ == "__main__":
    unittest.main()
