import unittest
from unittest.mock import MagicMock, patch
import json
import os
import shutil
from pathlib import Path

# Mock constants/imports
with patch("os.geteuid", return_value=0):
    import forcefocus_daemon
    from forcefocus_daemon import ForcedFocusDaemon


class TestDaemonSocketSettings(unittest.TestCase):
    def setUp(self):
        # Override paths to use a temporary sandbox directory
        self.sandbox_dir = Path("/tmp/forcefocus_socket_test")
        if self.sandbox_dir.exists():
            shutil.rmtree(self.sandbox_dir)
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)

        forcefocus_daemon.CONFIG_DIR = self.sandbox_dir / "config"
        forcefocus_daemon.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        forcefocus_daemon.SETTINGS_FILE = forcefocus_daemon.CONFIG_DIR / "settings.json"
        
        forcefocus_daemon.WEB_DIR = self.sandbox_dir / "web"
        self.sounds_dir = forcefocus_daemon.WEB_DIR / "sounds"
        self.sounds_dir.mkdir(parents=True, exist_ok=True)

        forcefocus_daemon.SESSION_LOCK = forcefocus_daemon.CONFIG_DIR / "session.lock"
        forcefocus_daemon.LISTS_FILE = forcefocus_daemon.CONFIG_DIR / "lists.json"
        forcefocus_daemon.GROUPS_FILE = forcefocus_daemon.CONFIG_DIR / "groups.json"
        forcefocus_daemon.API_TOKEN_FILE = forcefocus_daemon.CONFIG_DIR / "api_token"
        forcefocus_daemon.HOSTS_PATH = self.sandbox_dir / "hosts"

        # Instantiate daemon with mocked setup methods
        with patch("os.geteuid", return_value=0), patch(
            "forcefocus_daemon.ForcedFocusDaemon._ensure_config_dir"
        ), patch(
            "forcefocus_daemon.ForcedFocusDaemon._ensure_lists_file"
        ), patch(
            "forcefocus_daemon.ForcedFocusDaemon._ensure_groups_file"
        ), patch(
            "forcefocus_daemon.ForcedFocusDaemon._generate_api_token"
        ), patch(
            "forcefocus_daemon.ForcedFocusDaemon._install_signal_handlers"
        ):
            self.daemon = ForcedFocusDaemon()

    def tearDown(self):
        if self.sandbox_dir.exists():
            shutil.rmtree(self.sandbox_dir)

    def test_get_settings(self):
        self.daemon.settings = {
            "sound_start": "bell.mp3",
            "intent_notification_enabled": True
        }
        cmd = {"action": "get_settings"}
        resp = self.daemon._dispatch_command(json.dumps(cmd))
        self.assertEqual(resp["status"], "ok")
        self.assertEqual(resp["settings"], self.daemon.settings)

    def test_save_settings_success(self):
        cmd = {
            "action": "save_settings",
            "settings": {
                "sound_start": "chime.mp3",
                "intent_notification_enabled": False
            }
        }
        resp = self.daemon._dispatch_command(json.dumps(cmd))
        self.assertEqual(resp["status"], "ok")
        self.assertEqual(self.daemon.settings["sound_start"], "chime.mp3")
        self.assertFalse(self.daemon.settings["intent_notification_enabled"])

        # Check if saved to disk
        self.assertTrue(forcefocus_daemon.SETTINGS_FILE.exists())
        saved_data = json.loads(forcefocus_daemon.SETTINGS_FILE.read_text())
        self.assertEqual(saved_data["sound_start"], "chime.mp3")

    def test_save_settings_empty(self):
        cmd = {
            "action": "save_settings",
            "settings": {}
        }
        resp = self.daemon._dispatch_command(json.dumps(cmd))
        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["message"], "No settings provided.")

    def test_get_sounds(self):
        # Create dummy mp3 files
        (self.sounds_dir / "bell.mp3").touch()
        (self.sounds_dir / "chime.mp3").touch()
        (self.sounds_dir / "ignore.wav").touch()

        cmd = {"action": "get_sounds"}
        resp = self.daemon._dispatch_command(json.dumps(cmd))
        self.assertEqual(resp["status"], "ok")
        self.assertEqual(resp["sounds"], ["bell.mp3", "chime.mp3"])

    def test_delete_sound_success(self):
        sound_file = self.sounds_dir / "bell.mp3"
        sound_file.touch()
        self.assertTrue(sound_file.exists())

        cmd = {
            "action": "delete_sound",
            "filename": "bell.mp3"
        }
        resp = self.daemon._dispatch_command(json.dumps(cmd))
        self.assertEqual(resp["status"], "ok")
        self.assertIn("deleted", resp["message"])
        self.assertFalse(sound_file.exists())

    def test_delete_sound_missing_filename(self):
        cmd = {
            "action": "delete_sound",
            "filename": ""
        }
        resp = self.daemon._dispatch_command(json.dumps(cmd))
        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["message"], "No filename provided.")

    def test_delete_sound_not_found(self):
        cmd = {
            "action": "delete_sound",
            "filename": "nonexistent.mp3"
        }
        resp = self.daemon._dispatch_command(json.dumps(cmd))
        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["message"], "File not found.")

    def test_delete_sound_path_traversal(self):
        # Even if traversal resolves, sanitization cleans non-alphanumeric/._- and relative_to enforces WEB_DIR/sounds scope
        cmd = {
            "action": "delete_sound",
            "filename": "../../../etc/passwd"
        }
        # The sanitized filename will be "etcpasswd" (dots/slashes stripped/cleaned)
        # and relative_to check will raise ValueError or look for "etcpasswd" in the sounds dir, which won't exist.
        resp = self.daemon._dispatch_command(json.dumps(cmd))
        self.assertEqual(resp["status"], "error")
        self.assertEqual(resp["message"], "File not found.")


if __name__ == "__main__":
    unittest.main()
