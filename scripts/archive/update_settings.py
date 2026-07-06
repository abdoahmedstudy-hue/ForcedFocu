import os
import re

daemon_file = "/Users/aboda/Documents/ForcedFocu/daemon/forcefocus_daemon.py"
with open(daemon_file, "r") as f:
    content = f.read()

# 1. Add import
if "from forcefocus.settings import SettingsManager" not in content:
    content = content.replace(
        "from forcefocus.history import HistoryManager",
        "from forcefocus.history import HistoryManager\nfrom forcefocus.settings import SettingsManager"
    )

# 2. Add initialization
if "self.settings_manager =" not in content:
    content = content.replace(
        "self.history_manager = HistoryManager(self)",
        "self.history_manager = HistoryManager(self)\n        self.settings_manager = SettingsManager(self)"
    )

# 3. Replace methods
content = re.sub(
    r'    def _load_settings\(self\):.*?return DEFAULT_SETTINGS\.copy\(\)',
    '    def _load_settings(self):\n        return self.settings_manager.load_settings()',
    content,
    flags=re.DOTALL
)

content = re.sub(
    r'    def _save_settings\(self, new_settings\):.*?return False',
    '    def _save_settings(self, new_settings):\n        return self.settings_manager.save_settings(new_settings)',
    content,
    flags=re.DOTALL
)

content = re.sub(
    r'    def _cmd_get_settings\(self\) -> dict:\n        return \{"status": "ok", "settings": self\.settings\}',
    '    def _cmd_get_settings(self) -> dict:\n        return self.settings_manager.cmd_get_settings()',
    content,
    flags=re.DOTALL
)

content = re.sub(
    r'    def _validate_settings\(self, settings_dict: dict\) -> tuple\[bool, str, dict\]:.*?return True, "", validated',
    '    def _validate_settings(self, settings_dict: dict) -> tuple[bool, str, dict]:\n        return self.settings_manager.validate_settings(settings_dict)',
    content,
    flags=re.DOTALL
)

content = re.sub(
    r'    def _cmd_save_settings\(self, cmd: dict\) -> dict:.*?return \{"status": "error", "message": "Failed to save settings\."\}',
    '    def _cmd_save_settings(self, cmd: dict) -> dict:\n        return self.settings_manager.cmd_save_settings(cmd)',
    content,
    flags=re.DOTALL
)

with open(daemon_file, "w") as f:
    f.write(content)

print("Updated settings delegation")
