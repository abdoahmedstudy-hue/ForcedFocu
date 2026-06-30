import unittest
from unittest.mock import patch, MagicMock
from forcefocus_daemon import ForcedFocusDaemon

class TestSecurityOsascript(unittest.TestCase):
    def setUp(self):
        with patch("forcefocus_daemon.ForcedFocusDaemon._load_settings", return_value={}):
            with patch("forcefocus_daemon.ForcedFocusDaemon._restore_session"):
                self.daemon = ForcedFocusDaemon()

    @patch("forcefocus_daemon.Path.exists", return_value=True)
    @patch("forcefocus_daemon.subprocess.Popen")
    def test_osascript_argv_safety(self, mock_popen, mock_exists):
        mock_popen.return_value = MagicMock()

        # The payload that would have been dangerous if concatenated
        bad_title = ' & (do shell script "whoami") & '
        bad_message = '\\\\'

        self.daemon._send_mac_notification(bad_title, bad_message)

        # Check that Popen was called
        self.assertTrue(mock_popen.called)

        # Get the call args of Popen
        args, kwargs = mock_popen.call_args
        cmd_list = args[0]

        # Verify the structure of the command
        self.assertTrue(cmd_list[0].endswith("ForcedFocusBar"))
        self.assertEqual(cmd_list[1], "-notify-title")
        self.assertEqual(cmd_list[2], bad_title)
        self.assertEqual(cmd_list[3], "-notify-body")
        self.assertEqual(cmd_list[4], bad_message)

        # Check that shell was not set or is False
        self.assertFalse(kwargs.get("shell", False))

if __name__ == "__main__":
    unittest.main()
