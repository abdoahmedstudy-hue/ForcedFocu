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
from cli.commands.settings import cmd_settings


class TestCliSettings(unittest.TestCase):
    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_settings_show_agent(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="show")
        mock_out.is_agent = True
        mock_send_command.return_value = {
            "status": "ok",
            "settings": {
                "intent_notification_enabled": True,
                "intent_notification_interval": 15,
                "sound_start": "bell.mp3"
            }
        }

        cmd_settings(args)

        mock_send_command.assert_called_once_with({"action": "get_settings"})
        mock_out.print_data.assert_called_once_with(mock_send_command.return_value)

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    @patch("forcefocus_cli.console")
    def test_cmd_settings_show_human(self, mock_console, mock_out, mock_send_command):
        args = argparse.Namespace(action="show")
        mock_out.is_agent = False
        mock_send_command.return_value = {
            "status": "ok",
            "settings": {
                "intent_notification_enabled": True,
                "intent_notification_interval": 15,
                "sound_start": "bell.mp3"
            }
        }

        cmd_settings(args)

        mock_send_command.assert_called_once_with({"action": "get_settings"})
        self.assertTrue(mock_console.print.called)

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_settings_set_bool(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="set", key="intent_notification_enabled", value="false")
        
        # Mock get_settings then save_settings
        mock_send_command.side_effect = [
            {
                "status": "ok",
                "settings": {
                    "intent_notification_enabled": True,
                    "intent_notification_interval": 15
                }
            },
            {
                "status": "ok",
                "message": "Settings saved"
            }
        ]

        cmd_settings(args)

        self.assertEqual(mock_send_command.call_count, 2)
        mock_send_command.assert_any_call({"action": "get_settings"})
        mock_send_command.assert_any_call({
            "action": "save_settings",
            "settings": {
                "intent_notification_enabled": False,
                "intent_notification_interval": 15
            }
        })
        mock_out.print_data.assert_called_once_with(
            {"status": "ok", "message": "Settings saved"},
            title="Save Settings"
        )

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_settings_set_int(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="set", key="intent_notification_interval", value="30")
        
        mock_send_command.side_effect = [
            {
                "status": "ok",
                "settings": {
                    "intent_notification_enabled": True,
                    "intent_notification_interval": 15
                }
            },
            {
                "status": "ok",
                "message": "Settings saved"
            }
        ]

        cmd_settings(args)

        mock_send_command.assert_any_call({
            "action": "save_settings",
            "settings": {
                "intent_notification_enabled": True,
                "intent_notification_interval": 30
            }
        })

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_settings_set_str(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="set", key="sound_start", value="custom_bell.mp3")
        
        mock_send_command.side_effect = [
            {
                "status": "ok",
                "settings": {
                    "sound_start": "bell.mp3"
                }
            },
            {
                "status": "ok",
                "message": "Settings saved"
            }
        ]

        cmd_settings(args)

        mock_send_command.assert_any_call({
            "action": "save_settings",
            "settings": {
                "sound_start": "custom_bell.mp3"
            }
        })

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_settings_set_invalid_key(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="set", key="invalid_setting_key", value="123")
        
        mock_send_command.return_value = {
            "status": "ok",
            "settings": {}
        }

        def print_error(*args, **kwargs):
            raise SystemExit(1)
        mock_out.print_error.side_effect = print_error

        with self.assertRaises(SystemExit):
            cmd_settings(args)

        mock_out.print_error.assert_called_once()
        self.assertIn("Unknown setting key", mock_out.print_error.call_args[0][0])

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_settings_set_invalid_bool(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="set", key="intent_notification_enabled", value="not-a-bool")
        
        mock_send_command.return_value = {
            "status": "ok",
            "settings": {"intent_notification_enabled": True}
        }

        def print_error(*args, **kwargs):
            raise SystemExit(1)
        mock_out.print_error.side_effect = print_error

        with self.assertRaises(SystemExit):
            cmd_settings(args)

        mock_out.print_error.assert_called_once()
        self.assertIn("Invalid boolean value", mock_out.print_error.call_args[0][0])

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out")
    def test_cmd_settings_set_invalid_int(self, mock_out, mock_send_command):
        args = argparse.Namespace(action="set", key="intent_notification_interval", value="not-an-int")
        
        mock_send_command.return_value = {
            "status": "ok",
            "settings": {"intent_notification_interval": 15}
        }

        def print_error(*args, **kwargs):
            raise SystemExit(1)
        mock_out.print_error.side_effect = print_error

        with self.assertRaises(SystemExit):
            cmd_settings(args)

        mock_out.print_error.assert_called_once()
        self.assertIn("Invalid integer value", mock_out.print_error.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
