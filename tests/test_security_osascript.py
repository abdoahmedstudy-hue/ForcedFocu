import unittest
from unittest.mock import patch, MagicMock
from forcefocus_daemon import ForcedFocusDaemon

class TestSecurityOsascript(unittest.TestCase):
    def setUp(self):
        with patch("forcefocus_daemon.ForcedFocusDaemon._load_settings", return_value={}):
            with patch("forcefocus_daemon.ForcedFocusDaemon._restore_session"):
                self.daemon = ForcedFocusDaemon()

    @patch("forcefocus_daemon.subprocess.run")
    def test_osascript_argv_safety(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        # The payload that would have been dangerous if concatenated
        bad_title = ' & (do shell script "whoami") & '
        bad_message = '\\'

        self.daemon._send_mac_notification(bad_title, bad_message)

        # Check the first call to subprocess.run
        # args should be: (['osascript', '-e', script_content, message, title],)
        call_args = mock_run.call_args_list[0]
        args, _ = call_args
        cmd_list = args[0]

        # Verify the structure of the command
        self.assertEqual(cmd_list[0], "osascript")
        self.assertEqual(cmd_list[1], "-e")
        # cmd_list[2] is the script content
        # cmd_list[3] should be the message (positional arg 1)
        # cmd_list[4] should be the title (positional arg 2)

        self.assertEqual(cmd_list[3], bad_message)
        self.assertEqual(cmd_list[4], bad_title)

        # Verify the script uses argv
        script_content = cmd_list[2]
        self.assertIn("on run argv", script_content)
        self.assertIn("item 1 of argv", script_content)
        self.assertIn("item 2 of argv", script_content)

        # Ensure no accidental concatenation in the script body
        self.assertNotIn(bad_message, script_content)
        self.assertNotIn(bad_title, script_content)

if __name__ == "__main__":
    unittest.main()
