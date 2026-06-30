import argparse
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

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
from cli.commands.templates import cmd_templates


class TestCliTemplates(unittest.TestCase):
    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_templates_list_agent(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="list")
        mock_out.is_agent = True
        mock_send_command.return_value = {"status": "ok", "templates": []}

        cmd_templates(args)

        mock_send_command.assert_called_once_with({"action": "get_templates"})
        mock_out.print_data.assert_called_once_with(mock_send_command.return_value)

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_templates_add(self, mock_out, mock_send_command):
        args = argparse.Namespace(
            action="add",
            name="Deep Work",
            duration=90,
            mode="blacklist",
            session_type="standard",
            focus=25,
            break_time=5,
            cycles=4,
            groups=["Work"],
            intent="Finish draft",
        )
        mock_send_command.return_value = {"status": "ok"}

        cmd_templates(args)

        mock_send_command.assert_called_once_with(
            {
                "action": "add_template",
                "name": "Deep Work",
                "duration_minutes": 90,
                "mode": "blacklist",
                "session_type": "standard",
                "focus_minutes": 25,
                "break_minutes": 5,
                "cycles": 4,
                "groups": ["Work"],
                "intent": "Finish draft",
            }
        )
        mock_out.print_data.assert_called_once_with(mock_send_command.return_value, title="Add Template")

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_templates_start_by_name(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="start", template="Deep Work")
        mock_send_command.side_effect = [
            {"status": "ok", "templates": [{"id": "abc-123", "name": "Deep Work"}]},
            {"status": "ok", "message": "started"},
        ]

        cmd_templates(args)

        self.assertEqual(mock_send_command.call_count, 2)
        mock_send_command.assert_any_call({"action": "get_templates"})
        mock_send_command.assert_any_call({"action": "start_template", "id": "abc-123"})
        mock_out.print_data.assert_called_once_with({"status": "ok", "message": "started"}, title="Start Template")


if __name__ == "__main__":
    unittest.main()
