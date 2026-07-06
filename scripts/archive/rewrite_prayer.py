import re
from pathlib import Path

DAEMON_FILE = Path("/Users/aboda/Documents/ForcedFocu/daemon/forcefocus_daemon.py")
PRAYER_FILE = Path("/Users/aboda/Documents/ForcedFocu/daemon/forcefocus/prayer.py")

def main():
    content = DAEMON_FILE.read_text()
    
    method_names = [
        "_cmd_get_prayer",
        "_cmd_skip_prayer",
        "_fetch_prayer_calendar",
        "_get_prayer_times_for_date",
        "_evaluate_prayer_block",
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

    # Build prayer.py
    prayer_code = [
        "from __future__ import annotations",
        "import json",
        "import time",
        "import urllib.request",
        "import urllib.error",
        "from datetime import datetime, timedelta",
        "from pathlib import Path",
        "",
        "from forcefocus.constants import *",
        "from forcefocus.utils import get_continuous_time",
        "",
        "class PrayerManager:",
        "    def __init__(self, daemon):",
        "        self.daemon = daemon",
        ""
    ]
    
    daemon_attrs = [
        "settings", "skipped_prayers"
    ]
    
    daemon_methods = [
        "_atomic_write_json"
    ]
    
    for name, method_lines in extracted_methods:
        for line in method_lines:
            new_line = line
            
            if "self." in new_line:
                for attr in daemon_attrs:
                    new_line = re.sub(r"self\." + attr + r"\b", r"self.daemon." + attr, new_line)
                for meth in daemon_methods:
                    new_line = re.sub(r"self\." + meth + r"\b", r"self.daemon." + meth, new_line)
                    
            prayer_code.append(new_line)
        prayer_code.append("")
        
    PRAYER_FILE.write_text("\n".join(prayer_code))
    
    # Replace calls in forcefocus_daemon.py
    daemon_text = "\n".join(new_daemon_lines)
    for m in method_names:
        daemon_text = re.sub(r"self\." + m + r"\b", r"self.prayer_manager." + m, daemon_text)
        
    DAEMON_FILE.write_text(daemon_text)
    print("Done")

if __name__ == "__main__":
    main()
