import re
from pathlib import Path

DAEMON_FILE = Path("/Users/aboda/Documents/ForcedFocu/daemon/forcefocus_daemon.py")
SESSION_FILE = Path("/Users/aboda/Documents/ForcedFocu/daemon/forcefocus/session.py")

def main():
    content = DAEMON_FILE.read_text()
    
    method_names = [
        "_start_session",
        "_request_stop",
        "_cancel_stop",
        "_remove_block",
        "_transition_pomodoro_phase",
        "_cleanup_session",
    ]
    
    lines = content.split("\n")
    
    extracted_methods = []
    new_daemon_lines = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        m = re.match(r"^    def (_[a-zA-Z0-9_]+)\b", line)
        if m and m.group(1) in method_names:
            method_name = m.group(1)
            method_lines = [line]
            i += 1
            while i < len(lines):
                next_line = lines[i]
                if next_line.strip() != "":
                    if not next_line.startswith(" " * 5) and not next_line.startswith("\t"):
                        if next_line.startswith("    def ") or next_line.startswith("    @") or next_line.startswith("class "):
                            break
                method_lines.append(next_line)
                i += 1
            extracted_methods.append((method_name, method_lines))
            continue
            
        new_daemon_lines.append(line)
        i += 1

    print(f"Extracted {len(extracted_methods)} methods:")
    for name, _ in extracted_methods:
        print(f" - {name}")
        
    if len(extracted_methods) != len(method_names):
        print(f"WARNING: Expected {len(method_names)} methods, found {len(extracted_methods)}")

    # Build session.py
    session_code = [
        "from __future__ import annotations",
        "import subprocess",
        "import logging",
        "import time",
        "import threading",
        "import uuid",
        "from pathlib import Path",
        "from datetime import datetime, timedelta",
        "",
        "from forcefocus.constants import *",
        "from forcefocus.utils import get_continuous_time",
        "",
        "class SessionManager:",
        "    def __init__(self, daemon):",
        "        self.daemon = daemon",
        ""
    ]
    
    daemon_attrs = [
        "active", "mode", "intent", "session_expiry", "session_group_id", "total_duration_seconds",
        "pending_unlock_at", "_mono_session_end", "_mono_unlock_end", "_mono_last_intent_notif",
        "session_type", "pomo_focus_minutes", "pomo_break_minutes", "pomo_total_cycles",
        "pomo_current_cycle", "pomo_phase", "pomo_phase_expiry", "_mono_pomo_phase_end",
        "settings", "schedules", "recurring_schedules", "remaining_seconds", "pending_unlock_seconds",
        "pomo_phase_remaining", "session_groups", "original_dns", "enforcement_manager",
        "session_base_domains", "active_domains", "active_domains_set", "whitelist_count",
        "whitelist_expanded_count", "intent_tasks", "hosts_hash", "dns_proxy", "sni_proxy",
        "perma_blocklist", "pomo_phases_tracked_seconds", "enforcement_lock", "_hosts_stat",
        "_ip_backlog", "_whitelisted_ip_backlog", "whitelist_resolved", "_reenforce_flag",
        "_passphrase_attempts", "history_manager"
    ]
    
    daemon_methods = [
        "broadcast_state_changed", "_persist_session_lock", "_play_sound", "_send_mac_notification",
        "_atomic_write_json", "_load_lists", "_load_groups", "_expand_whitelist_domains",
        "_get_blacklist_domains", "_record_pomodoro_phase", "_record_session_history"
    ]
    
    for name, method_lines in extracted_methods:
        for line in method_lines:
            new_line = line
            
            if "self." in new_line:
                for attr in daemon_attrs:
                    new_line = re.sub(r"self\." + attr + r"\b", r"self.daemon." + attr, new_line)
                for meth in daemon_methods:
                    new_line = re.sub(r"self\." + meth + r"\b", r"self.daemon." + meth, new_line)
                    
            # Method itself might need self. to self.daemon. if it recursively calls something?
            # E.g. self._cleanup_session -> self.daemon.session_manager._cleanup_session
            # But wait, inside session_manager, it can just call self._cleanup_session!
            # So if it's one of the extracted methods, do NOT replace self. with self.daemon.
            
            session_code.append(new_line)
        session_code.append("")
        
    SESSION_FILE.write_text("\n".join(session_code))
    
    # Replace calls in forcefocus_daemon.py
    daemon_text = "\n".join(new_daemon_lines)
    for m in method_names:
        daemon_text = re.sub(r"self\." + m + r"\b", r"self.session_manager." + m, daemon_text)
        
    DAEMON_FILE.write_text(daemon_text)
    print("Done")

if __name__ == "__main__":
    main()
