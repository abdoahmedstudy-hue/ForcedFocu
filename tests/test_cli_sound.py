import sys
import types
from unittest.mock import patch, MagicMock
import unittest
import argparse

# Setup mock for rich module if not already done
if "rich" not in sys.modules:
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
from cli.commands.sound import cmd_sound


class TestCliSound(unittest.TestCase):
    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_sound_list_agent(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="list")
        mock_out.is_agent = True
        mock_send_command.return_value = {
            "status": "ok",
            "sounds": ["bell.mp3", "chime.mp3"]
        }

        cmd_sound(args)

        mock_send_command.assert_called_once_with({"action": "get_sounds"})
        mock_out.print_data.assert_called_once_with(mock_send_command.return_value)

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    @patch("forcefocus_cli.console")
    def test_cmd_sound_list_human(self, mock_console, mock_out, mock_send_command):
        args = argparse.Namespace(action="list")
        mock_out.is_agent = False
        mock_send_command.return_value = {
            "status": "ok",
            "sounds": ["bell.mp3", "chime.mp3"]
        }

        cmd_sound(args)

        mock_send_command.assert_called_once_with({"action": "get_sounds"})
        self.assertTrue(mock_console.print.called)

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    @patch("forcefocus_cli.console")
    def test_cmd_sound_list_empty(self, mock_console, mock_out, mock_send_command):
        args = argparse.Namespace(action="list")
        mock_out.is_agent = False
        mock_send_command.return_value = {
            "status": "ok",
            "sounds": []
        }

        cmd_sound(args)

        mock_send_command.assert_called_once_with({"action": "get_sounds"})
        mock_console.print.assert_called_once_with("[dim]No sound files available.[/dim]")

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_sound_delete(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="delete", filename="bell.mp3")
        mock_send_command.return_value = {"status": "ok", "message": "Sound deleted"}

        cmd_sound(args)

        mock_send_command.assert_called_once_with({
            "action": "delete_sound",
            "filename": "bell.mp3"
        })
        mock_out.print_data.assert_called_once_with(
            mock_send_command.return_value,
            title="Delete Sound"
        )

    @patch("forcefocus_cli.out")
    def test_cmd_sound_delete_missing_filename(self, mock_out):
        args = argparse.Namespace(action="delete", filename=None)

        def print_error(*args, **kwargs):
            raise SystemExit(1)
        mock_out.print_error.side_effect = print_error

        with self.assertRaises(SystemExit):
            cmd_sound(args)

        mock_out.print_error.assert_called_once_with(
            "Filename is required for 'delete'.", code="USAGE_ERROR"
        )


if __name__ == "__main__":
    unittest.main()
