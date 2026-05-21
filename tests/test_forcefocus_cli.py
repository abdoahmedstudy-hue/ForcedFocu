import unittest
import argparse
import sys
from unittest.mock import patch, MagicMock

# Create a more robust mock package for 'rich'
import types

rich_mock = types.ModuleType("rich")
sys.modules["rich"] = rich_mock

for sub_module in [
    "console",
    "panel",
    "table",
    "text",
    "box",
    "prompt",
    "layout",
    "live",
    "spinner",
    "progress",
    "theme",
]:
    sys.modules[f"rich.{sub_module}"] = MagicMock()

import forcefocus_cli


class TestForceFocusCLIParser(unittest.TestCase):
    def setUp(self):
        self.parser = forcefocus_cli.build_parser()

    def test_build_parser_returns_argument_parser(self):
        """Verify that build_parser returns an ArgumentParser instance."""
        self.assertIsInstance(self.parser, argparse.ArgumentParser)

    def test_global_flags(self):
        """Test global flags."""
        args = self.parser.parse_args(["--human", "--agent", "--brief"])
        self.assertTrue(args.human)
        self.assertTrue(args.agent)
        self.assertTrue(args.brief)

        args_empty = self.parser.parse_args([])
        self.assertFalse(args_empty.human)
        self.assertFalse(args_empty.agent)
        self.assertFalse(args_empty.brief)

    def test_start_subcommand(self):
        """Test 'start' subcommand arguments."""
        args = self.parser.parse_args(
            ["start", "--duration", "60", "--mode", "whitelist"]
        )
        self.assertEqual(args.command, "start")
        self.assertEqual(args.duration, 60)
        self.assertEqual(args.mode, "whitelist")
        self.assertEqual(args.func, forcefocus_cli.cmd_start)

        # Test defaults
        args_default = self.parser.parse_args(["start"])
        self.assertEqual(args_default.duration, 120)
        self.assertEqual(args_default.mode, "blacklist")
        self.assertEqual(args_default.session_type, "standard")

    def test_stop_subcommand(self):
        """Test 'stop' subcommand arguments."""
        args = self.parser.parse_args(["stop", "--key", "mysecret"])
        self.assertEqual(args.command, "stop")
        self.assertEqual(args.key, "mysecret")
        self.assertEqual(args.func, forcefocus_cli.cmd_stop)

    def test_status_subcommand(self):
        """Test 'status' subcommand arguments."""
        args = self.parser.parse_args(["status"])
        self.assertEqual(args.command, "status")
        self.assertEqual(args.func, forcefocus_cli.cmd_status)

    def test_set_key_subcommand(self):
        """Test 'set-key' subcommand arguments."""
        args = self.parser.parse_args(["set-key"])
        self.assertEqual(args.command, "set-key")
        self.assertEqual(args.func, forcefocus_cli.cmd_set_key)

    def test_web_subcommand(self):
        """Test 'web' subcommand arguments."""
        args = self.parser.parse_args(["web", "stop"])
        self.assertEqual(args.command, "web")
        self.assertEqual(args.action, "stop")
        self.assertEqual(args.func, forcefocus_cli.cmd_web)

        # Test default action
        args_default = self.parser.parse_args(["web"])
        self.assertEqual(args_default.action, "start")

    def test_groups_subcommand(self):
        """Test 'groups' subcommand arguments."""
        args = self.parser.parse_args(
            ["groups", "add", "mygroup", "domain.com", "domain.org"]
        )
        self.assertEqual(args.command, "groups")
        self.assertEqual(args.action, "add")
        self.assertEqual(args.name, "mygroup")
        self.assertEqual(args.domains, ["domain.com", "domain.org"])
        self.assertEqual(args.func, forcefocus_cli.cmd_groups)

    def test_perma_block_subcommand(self):
        """Test 'perma-block' subcommand and its sub-subcommands."""
        # 1. perma-block list with --human
        args = self.parser.parse_args(["perma-block", "list", "--human"])
        self.assertEqual(args.command, "perma-block")
        self.assertEqual(args.action, "list")
        self.assertTrue(args.human)
        self.assertFalse(args.agent)
        self.assertEqual(args.func, forcefocus_cli.cmd_perma_block)

        # 2. perma-block add multiple domains
        args = self.parser.parse_args(["perma-block", "add", "google.com", "facebook.com"])
        self.assertEqual(args.command, "perma-block")
        self.assertEqual(args.action, "add")
        self.assertEqual(args.domains, ["google.com", "facebook.com"])

        # 3. perma-block unblock with --key and --agent
        args = self.parser.parse_args(["perma-block", "unblock", "google.com", "-k", "secret", "--agent"])
        self.assertEqual(args.command, "perma-block")
        self.assertEqual(args.action, "unblock")
        self.assertEqual(args.domain, "google.com")
        self.assertEqual(args.key, "secret")
        self.assertTrue(args.agent)

        # 4. perma-block cancel
        args = self.parser.parse_args(["perma-block", "cancel", "google.com"])
        self.assertEqual(args.command, "perma-block")
        self.assertEqual(args.action, "cancel")
        self.assertEqual(args.domain, "google.com")


class TestForceFocusCLISetKey(unittest.TestCase):
    @patch("forcefocus_cli.os.geteuid")
    @patch("forcefocus_cli.sys.exit")
    @patch("forcefocus_cli.out.print_error")
    def test_set_key_non_root(self, mock_print_error, mock_exit, mock_geteuid):
        """Test set-key command when not run as root."""
        mock_geteuid.return_value = 1000  # non-root user
        mock_print_error.side_effect = SystemExit(1)
        with self.assertRaises(SystemExit):
            forcefocus_cli.cmd_set_key(None)

        # Verify it errors out correctly
        mock_print_error.assert_called_with(
            "Must run as root to set the kill-switch passphrase.",
            code="PERM_DENIED",
            suggestion="Use: sudo forcefocus set-key",
        )

    @patch("forcefocus_cli.os.geteuid")
    @patch("forcefocus_cli.getpass.getpass")
    @patch("forcefocus_cli.out.print_error")
    def test_set_key_empty_passphrase(
        self, mock_print_error, mock_getpass, mock_geteuid
    ):
        """Test set-key command when an empty passphrase is provided."""
        mock_geteuid.return_value = 0  # root user

        # Empty string on first prompt
        mock_getpass.side_effect = ["", ""]
        mock_print_error.side_effect = SystemExit(1)
        with self.assertRaises(SystemExit):
            forcefocus_cli.cmd_set_key(None)

        mock_print_error.assert_called_with(
            "Passphrase cannot be empty.", code="INVALID_INPUT"
        )

    @patch("forcefocus_cli.os.geteuid")
    @patch("forcefocus_cli.getpass.getpass")
    @patch("forcefocus_cli.out.print_error")
    def test_set_key_mismatched_passphrases(
        self, mock_print_error, mock_getpass, mock_geteuid
    ):
        """Test set-key command when passphrases do not match."""
        mock_geteuid.return_value = 0  # root user

        # Different strings
        mock_getpass.side_effect = ["password123", "different123"]
        mock_print_error.side_effect = SystemExit(1)
        with self.assertRaises(SystemExit):
            forcefocus_cli.cmd_set_key(None)

        mock_print_error.assert_called_with(
            "Passphrases do not match.", code="MISMATCH"
        )

    @patch("forcefocus_cli.os.geteuid")
    @patch("forcefocus_cli.getpass.getpass")
    @patch("forcefocus_cli.os.urandom")
    @patch("forcefocus_cli.json.dump")
    @patch("forcefocus_cli.os.chmod")
    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    @patch("forcefocus_cli.out.print_data")
    @patch("pathlib.Path.mkdir")
    def test_set_key_success(
        self,
        mock_mkdir,
        mock_print_data,
        mock_open,
        mock_chmod,
        mock_json_dump,
        mock_urandom,
        mock_getpass,
        mock_geteuid,
    ):
        """Test successful set-key command execution."""
        mock_geteuid.return_value = 0  # root user
        mock_getpass.side_effect = ["mypassword", "mypassword"]
        mock_urandom.return_value = b"1234567890abcdef"

        forcefocus_cli.cmd_set_key(None)

        mock_mkdir.assert_called_with(parents=True, exist_ok=True)
        mock_open.assert_called_with(forcefocus_cli.KS_HASH_FILE, "w")
        mock_json_dump.assert_called_once()
        mock_chmod.assert_called_with(forcefocus_cli.KS_HASH_FILE, 0o600)
        mock_print_data.assert_called_with(
            {"status": "ok", "message": "Passphrase set successfully."}, title="Set Key"
        )

    @patch("forcefocus_cli.os.geteuid")
    @patch("forcefocus_cli.getpass.getpass")
    @patch("forcefocus_cli.sys.exit")
    @patch("builtins.print")
    def test_set_key_keyboard_interrupt(
        self, mock_print, mock_exit, mock_getpass, mock_geteuid
    ):
        """Test set-key handles KeyboardInterrupt gracefully."""
        mock_geteuid.return_value = 0  # root user
        mock_getpass.side_effect = KeyboardInterrupt()

        forcefocus_cli.cmd_set_key(None)

        mock_print.assert_called_with("\nAborted.")
        mock_exit.assert_called_with(1)


class TestCmdStart(unittest.TestCase):
    def setUp(self):
        self.args = MagicMock()
        self.args.mode = "blacklist"
        self.args.session_type = "standard"
        self.args.duration = 60
        self.args.focus = 25
        self.args.break_time = 5
        self.args.cycles = 4
        self.args.schedule_in = None
        self.args.schedule_at = None
        self.args.groups = None

        self.patch_send = patch("forcefocus_cli.send_command")
        self.patch_error = patch("forcefocus_cli.out.print_error")
        self.patch_data = patch("forcefocus_cli.out.print_data")
        self.patch_status = patch("forcefocus_cli.console.status")

        self.mock_send = self.patch_send.start()
        self.mock_error = self.patch_error.start()
        self.mock_data = self.patch_data.start()
        self.mock_status = self.patch_status.start()

        self.mock_send.return_value = {"status": "ok", "message": "Started"}

        # Start with agent mode (is_human=False) for simpler tests
        self.original_is_human = forcefocus_cli.out.is_human
        forcefocus_cli.out.is_human = False

    def tearDown(self):
        self.patch_send.stop()
        self.patch_error.stop()
        self.patch_data.stop()
        self.patch_status.stop()
        forcefocus_cli.out.is_human = self.original_is_human

    def test_standard_session(self):
        forcefocus_cli.cmd_start(self.args)

        expected_payload = {
            "action": "start",
            "duration_minutes": 60,
            "mode": "blacklist",
            "session_type": "standard",
            "focus_minutes": 25,
            "break_minutes": 5,
            "cycles": 4,
        }

        self.mock_send.assert_called_once_with(expected_payload)
        self.mock_data.assert_called_once_with(
            {"status": "ok", "message": "Started"}, title="Start Session"
        )

    def test_pomodoro_session(self):
        self.args.session_type = "pomodoro"

        forcefocus_cli.cmd_start(self.args)

        expected_payload = {
            "action": "start",
            "duration_minutes": (25 + 5) * 4,  # 120
            "mode": "blacklist",
            "session_type": "pomodoro",
            "focus_minutes": 25,
            "break_minutes": 5,
            "cycles": 4,
        }

        self.mock_send.assert_called_once_with(expected_payload)

    def test_invalid_duration(self):
        self.args.duration = 0

        forcefocus_cli.cmd_start(self.args)

        self.mock_error.assert_called_once_with(
            "Duration must be a positive number of minutes.", code="INVALID_DURATION"
        )

    def test_schedule_in(self):
        self.args.schedule_in = 30

        forcefocus_cli.cmd_start(self.args)

        payload = self.mock_send.call_args[0][0]
        self.assertEqual(payload["schedule_in_minutes"], 30)
        self.assertNotIn("schedule_at_time", payload)

    def test_schedule_at(self):
        self.args.schedule_at = "14:30"

        forcefocus_cli.cmd_start(self.args)

        payload = self.mock_send.call_args[0][0]
        self.assertEqual(payload["schedule_at_time"], "14:30")
        self.assertNotIn("schedule_in_minutes", payload)

    def test_groups(self):
        self.args.groups = ["work", "study"]

        forcefocus_cli.cmd_start(self.args)

        payload = self.mock_send.call_args[0][0]
        self.assertEqual(payload["groups"], ["work", "study"])

    def test_human_output(self):
        forcefocus_cli.out.is_human = True

        # Setup the context manager mock manually for status
        mock_ctx = MagicMock()
        self.mock_status.return_value.__enter__.return_value = mock_ctx

        forcefocus_cli.cmd_start(self.args)

        self.mock_status.assert_called_once()
        self.mock_send.assert_called_once()


import socket
import json
import os


class TestSendCommand(unittest.TestCase):
    @patch("forcefocus_cli.os.path.exists")
    @patch("forcefocus_cli.out.print_error")
    def test_daemon_not_found(self, mock_print_error, mock_exists):
        mock_exists.return_value = False
        mock_print_error.side_effect = SystemExit(1)

        with self.assertRaises(SystemExit):
            forcefocus_cli.send_command({"cmd": "status"})

        mock_print_error.assert_called_once()
        args, kwargs = mock_print_error.call_args
        self.assertEqual(kwargs.get("code"), "DAEMON_NOT_FOUND")

    @patch("forcefocus_cli.os.path.exists")
    @patch("forcefocus_cli.socket.socket")
    @patch("forcefocus_cli.out.print_error")
    def test_connection_refused(self, mock_print_error, mock_socket, mock_exists):
        mock_exists.return_value = True
        mock_sock_inst = MagicMock()
        mock_socket.return_value = mock_sock_inst
        mock_sock_inst.connect.side_effect = ConnectionRefusedError()
        mock_print_error.side_effect = SystemExit(1)

        with self.assertRaises(SystemExit):
            forcefocus_cli.send_command({"cmd": "status"})

        mock_print_error.assert_called_once()
        args, kwargs = mock_print_error.call_args
        self.assertEqual(kwargs.get("code"), "CONNECTION_REFUSED")

    @patch("forcefocus_cli.os.path.exists")
    @patch("forcefocus_cli.socket.socket")
    @patch("forcefocus_cli.out.print_error")
    def test_timeout(self, mock_print_error, mock_socket, mock_exists):
        mock_exists.return_value = True
        mock_sock_inst = MagicMock()
        mock_socket.return_value = mock_sock_inst
        mock_sock_inst.connect.side_effect = socket.timeout()
        mock_print_error.side_effect = SystemExit(1)

        with self.assertRaises(SystemExit):
            forcefocus_cli.send_command({"cmd": "status"})

        mock_print_error.assert_called_once()
        args, kwargs = mock_print_error.call_args
        self.assertEqual(kwargs.get("code"), "TIMEOUT")

    @patch("forcefocus_cli.os.path.exists")
    @patch("forcefocus_cli.socket.socket")
    @patch("forcefocus_cli.out.print_error")
    def test_socket_error(self, mock_print_error, mock_socket, mock_exists):
        mock_exists.return_value = True
        mock_sock_inst = MagicMock()
        mock_socket.return_value = mock_sock_inst
        mock_sock_inst.connect.side_effect = Exception("Some error")
        mock_print_error.side_effect = SystemExit(1)

        with self.assertRaises(SystemExit):
            forcefocus_cli.send_command({"cmd": "status"})

        mock_print_error.assert_called_once()
        args, kwargs = mock_print_error.call_args
        self.assertEqual(kwargs.get("code"), "SOCKET_ERROR")

    @patch("forcefocus_cli.os.path.exists")
    @patch("forcefocus_cli.socket.socket")
    @patch("forcefocus_cli.out.print_error")
    def test_empty_response(self, mock_print_error, mock_socket, mock_exists):
        mock_exists.return_value = True
        mock_sock_inst = MagicMock()
        mock_socket.return_value = mock_sock_inst

        mock_sock_inst.recv.side_effect = [b""]
        mock_print_error.side_effect = SystemExit(1)

        with self.assertRaises(SystemExit):
            forcefocus_cli.send_command({"cmd": "status"})

        mock_print_error.assert_called_once()
        args, kwargs = mock_print_error.call_args
        self.assertEqual(kwargs.get("code"), "EMPTY_RESPONSE")

    @patch("forcefocus_cli.os.path.exists")
    @patch("forcefocus_cli.socket.socket")
    def test_success(self, mock_socket, mock_exists):
        mock_exists.return_value = True
        mock_sock_inst = MagicMock()
        mock_socket.return_value = mock_sock_inst

        response_data = {"status": "ok", "message": "success"}
        mock_sock_inst.recv.side_effect = [
            json.dumps(response_data).encode("utf-8"),
            b"",
        ]

        result = forcefocus_cli.send_command({"cmd": "status"})

        self.assertEqual(result, response_data)
        mock_sock_inst.connect.assert_called_once_with(forcefocus_cli.SOCK_PATH)
        mock_sock_inst.sendall.assert_called_once_with(
            json.dumps({"cmd": "status"}).encode("utf-8")
        )


class TestForceFocusCLICmdWeb(unittest.TestCase):
    def setUp(self):
        self.args = MagicMock()

    @patch("forcefocus_cli.out")
    @patch("forcefocus_cli.Path")
    @patch("forcefocus_cli.subprocess.run")
    def test_cmd_web_start_default_path(self, mock_run, mock_path_class, mock_out):
        self.args.action = "start"

        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path_class.return_value = mock_path_instance

        forcefocus_cli.cmd_web(self.args)

        mock_out.print_data.assert_called_once_with(
            {"status": "ok", "message": "Starting web interface..."}, title="Web UI"
        )
        mock_run.assert_called_once_with([sys.executable, str(mock_path_instance)])
        mock_out.print_error.assert_not_called()

    @patch("forcefocus_cli.out")
    @patch("forcefocus_cli.Path")
    @patch("forcefocus_cli.subprocess.run")
    def test_cmd_web_start_fallback_path(self, mock_run, mock_path_class, mock_out):
        self.args.action = "start"

        mock_default_path = MagicMock()
        mock_default_path.exists.return_value = False

        mock_fallback_path = MagicMock()
        mock_fallback_path.exists.return_value = True

        mock_parent = MagicMock()
        mock_parent.__truediv__.return_value = mock_fallback_path

        mock_file_path = MagicMock()
        mock_file_path.parent = mock_parent

        def path_side_effect(*args, **kwargs):
            if args and args[0] == "/usr/local/bin/forcefocus_web.py":
                return mock_default_path
            return mock_file_path

        mock_path_class.side_effect = path_side_effect

        forcefocus_cli.cmd_web(self.args)

        mock_out.print_data.assert_called_once_with(
            {"status": "ok", "message": "Starting web interface..."}, title="Web UI"
        )
        mock_run.assert_called_once_with([sys.executable, str(mock_fallback_path)])
        mock_out.print_error.assert_not_called()

    @patch("forcefocus_cli.out")
    @patch("forcefocus_cli.Path")
    @patch("forcefocus_cli.subprocess.run")
    def test_cmd_web_start_not_found(self, mock_run, mock_path_class, mock_out):
        self.args.action = "start"

        mock_default_path = MagicMock()
        mock_default_path.exists.return_value = False

        mock_fallback_path = MagicMock()
        mock_fallback_path.exists.return_value = False

        mock_parent = MagicMock()
        mock_parent.__truediv__.return_value = mock_fallback_path

        mock_file_path = MagicMock()
        mock_file_path.parent = mock_parent

        def path_side_effect(*args, **kwargs):
            if args and args[0] == "/usr/local/bin/forcefocus_web.py":
                return mock_default_path
            return mock_file_path

        mock_path_class.side_effect = path_side_effect

        forcefocus_cli.cmd_web(self.args)

        mock_out.print_data.assert_called_once_with(
            {"status": "ok", "message": "Starting web interface..."}, title="Web UI"
        )
        mock_run.assert_not_called()
        mock_out.print_error.assert_called_once_with(
            "Web server script not found.", code="FILE_NOT_FOUND"
        )

    @patch("forcefocus_cli.out")
    @patch("forcefocus_cli.subprocess.run")
    def test_cmd_web_stop(self, mock_run, mock_out):
        self.args.action = "stop"

        forcefocus_cli.cmd_web(self.args)

        mock_out.print_data.assert_called_once_with(
            {"status": "ok", "message": "Stopping web interface..."}, title="Web UI"
        )
        mock_run.assert_not_called()
        mock_out.print_error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
