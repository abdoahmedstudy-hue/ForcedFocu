import sys
import types
from unittest.mock import patch, MagicMock

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

import unittest
import argparse
import unittest
from unittest.mock import patch, MagicMock
import argparse

import forcefocus_cli


class TestCliGroups(unittest.TestCase):
    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_groups_list_agent(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="list", name=None, domains=[])
        mock_out.is_agent = True
        mock_send_command.return_value = {"groups": {"Work": ["example.com"]}}

        forcefocus_cli.cmd_groups(args)

        mock_send_command.assert_called_once_with({"action": "get_groups"})
        mock_out.print_data.assert_called_once_with(
            {"groups": {"Work": ["example.com"]}}
        )

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    @patch("forcefocus_cli.console")
    def test_cmd_groups_list_empty(self, mock_console, mock_out, mock_send_command):
        args = argparse.Namespace(action="list", name=None, domains=[])
        mock_out.is_agent = False
        mock_send_command.return_value = {"groups": {}}

        forcefocus_cli.cmd_groups(args)

        mock_send_command.assert_called_once_with({"action": "get_groups"})
        mock_console.print.assert_called_once_with(
            "[dim]No domain groups defined.[/dim]"
        )

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    @patch("forcefocus_cli.console")
    def test_cmd_groups_list_human(self, mock_console, mock_out, mock_send_command):
        args = argparse.Namespace(action="list", name=None, domains=[])
        mock_out.is_agent = False
        mock_send_command.return_value = {"groups": {"Work": ["example.com"]}}

        forcefocus_cli.cmd_groups(args)

        mock_send_command.assert_called_once_with({"action": "get_groups"})
        self.assertTrue(mock_console.print.called)

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_groups_add(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="add", name="Work", domains=["example.com"])
        mock_send_command.return_value = {"status": "ok"}

        forcefocus_cli.cmd_groups(args)

        mock_send_command.assert_called_once_with(
            {"action": "add_group", "name": "Work", "domains": ["example.com"]}
        )
        mock_out.print_data.assert_called_once_with({"status": "ok"}, title="Add Group")

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_groups_add_missing_name(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="add", name=None, domains=["example.com"])

        def print_error(*args, **kwargs):
            raise SystemExit(1)

        mock_out.print_error.side_effect = print_error

        with self.assertRaises(SystemExit):
            forcefocus_cli.cmd_groups(args)

        mock_out.print_error.assert_called_with(
            "Group name required for 'add'.", code="USAGE_ERROR"
        )

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_groups_add_missing_domains(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="add", name="Work", domains=[])

        def print_error(*args, **kwargs):
            raise SystemExit(1)

        mock_out.print_error.side_effect = print_error

        with self.assertRaises(SystemExit):
            forcefocus_cli.cmd_groups(args)

        mock_out.print_error.assert_called_with(
            "At least one domain required for 'add'.", code="USAGE_ERROR"
        )

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_groups_remove(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="remove", name="Work", domains=[])
        mock_send_command.return_value = {"status": "ok"}

        forcefocus_cli.cmd_groups(args)

        mock_send_command.assert_called_once_with(
            {"action": "remove_group", "name": "Work"}
        )
        mock_out.print_data.assert_called_once_with(
            {"status": "ok"}, title="Remove Group"
        )

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_groups_remove_missing_name(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="remove", name=None, domains=[])

        def print_error(*args, **kwargs):
            raise SystemExit(1)

        mock_out.print_error.side_effect = print_error

        with self.assertRaises(SystemExit):
            forcefocus_cli.cmd_groups(args)

        mock_out.print_error.assert_called_with(
            "Group name required for 'remove'.", code="USAGE_ERROR"
        )


if __name__ == "__main__":
    unittest.main()
