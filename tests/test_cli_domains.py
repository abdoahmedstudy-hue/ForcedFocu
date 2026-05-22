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
from cli.commands.domains import cmd_domains


class TestCliDomains(unittest.TestCase):
    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_domains_show_agent(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="show")
        mock_out.is_agent = True
        mock_send_command.return_value = {
            "status": "ok",
            "lists": {
                "blacklist": ["bad.com"],
                "whitelist": ["good.com"]
            }
        }

        cmd_domains(args)

        mock_send_command.assert_called_once_with({"action": "get_lists"})
        mock_out.print_data.assert_called_once_with(mock_send_command.return_value)

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    @patch("forcefocus_cli.console")
    def test_cmd_domains_show_human(self, mock_console, mock_out, mock_send_command):
        args = argparse.Namespace(action="show")
        mock_out.is_agent = False
        mock_send_command.return_value = {
            "status": "ok",
            "lists": {
                "blacklist": ["bad.com", "worse.org"],
                "whitelist": ["good.com"]
            }
        }

        cmd_domains(args)

        mock_send_command.assert_called_once_with({"action": "get_lists"})
        self.assertTrue(mock_console.print.called)

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_domains_add_single(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="add", list="blacklist", domains=["blockme.com"])
        mock_send_command.return_value = {"status": "ok", "message": "Domain added"}

        cmd_domains(args)

        mock_send_command.assert_called_once_with({
            "action": "add_domain",
            "list": "blacklist",
            "domain": "blockme.com"
        })
        mock_out.print_data.assert_called_once_with(
            mock_send_command.return_value,
            title="Add Domain(s) to Blacklist"
        )

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_domains_add_multiple(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="add", list="whitelist", domains=["allow1.com", "allow2.com"])
        mock_send_command.return_value = {"status": "ok", "message": "Domains added"}

        cmd_domains(args)

        mock_send_command.assert_called_once_with({
            "action": "add_domains",
            "list": "whitelist",
            "domains": ["allow1.com", "allow2.com"]
        })
        mock_out.print_data.assert_called_once_with(
            mock_send_command.return_value,
            title="Add Domain(s) to Whitelist"
        )

    @patch("forcefocus_cli.out")
    def test_cmd_domains_add_invalid_list(self, mock_out):
        args = argparse.Namespace(action="add", list="invalid_list", domains=["test.com"])

        def print_error(*args, **kwargs):
            raise SystemExit(1)
        mock_out.print_error.side_effect = print_error

        with self.assertRaises(SystemExit):
            cmd_domains(args)

        mock_out.print_error.assert_any_call(
            "List must be 'blacklist' or 'whitelist'.", code="USAGE_ERROR"
        )

    @patch("forcefocus_cli.out")
    def test_cmd_domains_add_missing_domains(self, mock_out):
        args = argparse.Namespace(action="add", list="blacklist", domains=[])

        def print_error(*args, **kwargs):
            raise SystemExit(1)
        mock_out.print_error.side_effect = print_error

        with self.assertRaises(SystemExit):
            cmd_domains(args)

        mock_out.print_error.assert_any_call(
            "At least one domain must be provided.", code="USAGE_ERROR"
        )

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_domains_remove(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="remove", list="blacklist", domain="removeme.com")
        mock_send_command.return_value = {"status": "ok", "message": "Domain removed"}

        cmd_domains(args)

        mock_send_command.assert_called_once_with({
            "action": "remove_domain",
            "list": "blacklist",
            "domain": "removeme.com"
        })
        mock_out.print_data.assert_called_once_with(
            mock_send_command.return_value,
            title="Remove Domain from Blacklist"
        )


if __name__ == "__main__":
    unittest.main()
