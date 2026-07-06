import os

daemon_file = "/Users/aboda/Documents/ForcedFocu/daemon/forcefocus_daemon.py"
with open(daemon_file, "r") as f:
    content = f.read()

# 1. Add import
import_stmt = "from forcefocus.history import HistoryManager\n"
if "from forcefocus.history" not in content:
    content = content.replace("from forcefocus.constants import *", f"from forcefocus.constants import *\n{import_stmt}")

# 2. Add history manager initialization in __init__
if "self.history_manager =" not in content:
    content = content.replace(
        "self.lock = threading.RLock()",
        "self.lock = threading.RLock()\n        self.history_manager = HistoryManager(self)"
    )

# 3. Replace methods
old_load = """    def _load_history(self) -> list:
        \"\"\"Load session history from disk.\"\"\"
        try:
            if HISTORY_FILE.exists():
                data = json.loads(HISTORY_FILE.read_text())
                if isinstance(data, list):
                    return data
        except Exception as exc:
            logging.error("Failed to load session history: %s", exc)
        return []"""
new_load = """    def _load_history(self) -> list:
        return self.history_manager.load_history()"""

old_save = """    def _save_history(self, entries: list):
        \"\"\"Persist session history to disk with cap enforcement.\"\"\"
        if len(entries) > MAX_HISTORY_ENTRIES:
            entries = entries[-MAX_HISTORY_ENTRIES:]
        self._atomic_write_json(HISTORY_FILE, entries)"""
new_save = """    def _save_history(self, entries: list):
        self.history_manager.save_history(entries)"""

# I'll just find where they are defined and replace with regex/slices to be safe against minor text changes
import re

content = re.sub(r'    def _load_history\(self\) -> list:.*?        return \[\]', new_load, content, flags=re.DOTALL)
content = re.sub(r'    def _save_history\(self, entries: list\):.*?self\._atomic_write_json\(HISTORY_FILE, entries\)', new_save, content, flags=re.DOTALL)
content = re.sub(r'    def _record_session_history\(self\):.*?entry\["session_type"\]\)', '    def _record_session_history(self):\n        self.history_manager.record_session_history()', content, flags=re.DOTALL)
content = re.sub(r'    def _record_pomodoro_phase\(self, phase_name: str, duration_minutes: int, started_at: datetime, ended_at: datetime, completed_normally: bool\):.*?phase_name\)', '    def _record_pomodoro_phase(self, phase_name: str, duration_minutes: int, started_at: datetime, ended_at: datetime, completed_normally: bool):\n        self.history_manager.record_pomodoro_phase(phase_name, duration_minutes, started_at, ended_at, completed_normally)', content, flags=re.DOTALL)
content = re.sub(r'    def _cmd_get_session_history\(self, cmd: dict\) -> dict:.*?return \{"status": "ok", "entries": filtered, "summary": summary\}', '    def _cmd_get_session_history(self, cmd: dict) -> dict:\n        return self.history_manager.cmd_get_session_history(cmd)', content, flags=re.DOTALL)
content = re.sub(r'    def _cmd_clear_session_history\(self\) -> dict:.*?return \{"status": "error", "message": f"Failed to clear history: \{exc\}"\}', '    def _cmd_clear_session_history(self) -> dict:\n        return self.history_manager.cmd_clear_session_history()', content, flags=re.DOTALL)

with open(daemon_file, "w") as f:
    f.write(content)

print("Updated daemon")
