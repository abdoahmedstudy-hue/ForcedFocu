import re
from pathlib import Path

DAEMON_FILE = Path("/Users/aboda/Documents/ForcedFocu/daemon/forcefocus_daemon.py")
ENFORCEMENT_FILE = Path("/Users/aboda/Documents/ForcedFocu/daemon/forcefocus/enforcement.py")

def main():
    content = DAEMON_FILE.read_text()
    
    # We will extract the following methods:
    method_names = [
        "_enforce_perma_block",
        "_build_perma_block",
        "_strip_perma_block",
        "_enforce_block",
        "_build_blacklist_block",
        "_get_network_services",
        "_get_current_dns_servers",
        "_enforce_whitelist",
        "_enforce_doh_block",
        "_set_dns_to_localhost",
        "_restore_dns",
        "_update_blocked_ips",
        "_enforce_firewall",
        "_enforce_browser_policies",
        "_kill_vpns",
        "_kill_restricted_apps",
        "_reset_system_proxies",
        "_kill_vpn_interfaces",
        "_flush_dns",
        "_clear_browser_caches",
        "_enforce_current_mode",
        "_strip_block",
    ]
    
    lines = content.split("\n")
    
    extracted_methods = []
    new_daemon_lines = []
    
    in_method = False
    current_method = []
    current_method_name = ""
    
    def get_method_name(line):
        m = re.match(r"^    (?:@staticmethod\s*\n\s*)?def (_[a-zA-Z0-9_]+)\(.*", line)
        if m:
            return m.group(1)
        # Check without args
        m2 = re.match(r"^    (?:@staticmethod\s*\n\s*)?def (_[a-zA-Z0-9_]+)\b.*", line)
        if m2:
            return m2.group(1)
        return None

    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Check if it's the start of a staticmethod
        is_static_start = line == "    @staticmethod"
        method_def_line = lines[i+1] if is_static_start and i+1 < len(lines) else line
        
        if method_def_line.startswith("    def "):
            m_name = get_method_name(method_def_line)
            if m_name in method_names:
                in_method = True
                current_method_name = m_name
                if is_static_start:
                    current_method.append(line)
                    i += 1
                    line = lines[i]
                current_method.append(line)
                i += 1
                continue
                
        if in_method:
            if line.startswith("    def ") or line.startswith("    @"):
                # End of current method
                extracted_methods.append((current_method_name, current_method))
                current_method = []
                in_method = False
                current_method_name = ""
                # Do not increment i, let it process this line again
                continue
            elif line.startswith("    # ──") or line.startswith("class ") or line == "if __name__ == \"__main__\":":
                extracted_methods.append((current_method_name, current_method))
                current_method = []
                in_method = False
                current_method_name = ""
                new_daemon_lines.append(line)
                i += 1
                continue
            else:
                current_method.append(line)
                i += 1
                continue
                
        new_daemon_lines.append(line)
        i += 1

    if in_method:
        extracted_methods.append((current_method_name, current_method))

    print(f"Extracted {len(extracted_methods)} methods:")
    for name, _ in extracted_methods:
        print(f" - {name}")
        
    if len(extracted_methods) != len(method_names):
        print(f"WARNING: Expected {len(method_names)} methods, found {len(extracted_methods)}")
        for m in method_names:
            if m not in [n for n, _ in extracted_methods]:
                print(f"Missing: {m}")

    # Build enforcement.py
    enforcement_code = [
        "from __future__ import annotations",
        "import subprocess",
        "import logging",
        "import hashlib",
        "import concurrent.futures",
        "import socket",
        "import time",
        "import threading",
        "import os",
        "import json",
        "import plistlib",
        "from pathlib import Path",
        "from datetime import datetime, timedelta",
        "",
        "from forcefocus.constants import *",
        "",
        "class EnforcementManager:",
        "    def __init__(self, daemon):",
        "        self.daemon = daemon",
        ""
    ]
    
    daemon_attrs = [
        "active_domains", "active_domains_set", "session_expiry", "perma_blocklist",
        "mode", "dns_proxy", "sni_proxy", "_net_services_cache", "_net_services_cache_time",
        "original_dns", "settings", "_ip_backlog", "_whitelisted_ip_backlog", "active", "session_type",
        "pomo_phase", "prayer_ban_active", "_hosts_stat", "hosts_hash", "enforcement_lock", "lock",
        "_ip_resolution_running"
    ]
    
    daemon_methods = [
        "_start_dns_proxy", "_start_sni_proxy", "_stop_sni_proxy", "_get_active_interface"
    ]
    
    for name, method_lines in extracted_methods:
        for line in method_lines:
            # We must fix indentation. Methods were indented with 4 spaces.
            # In EnforcementManager they will be indented with 4 spaces as well.
            new_line = line
            
            # For staticmethods, if they don't have 'self', we don't need to change self -> self.daemon
            # But most methods do.
            if "self." in new_line:
                for attr in daemon_attrs:
                    new_line = re.sub(r"self\." + attr + r"\b", r"self.daemon." + attr, new_line)
                for meth in daemon_methods:
                    new_line = re.sub(r"self\." + meth + r"\b", r"self.daemon." + meth, new_line)
            
            # _clear_browser_caches doesn't have self in def _clear_browser_caches(self):
            # actually it does.
            # _flush_dns doesn't have self
            
            enforcement_code.append(new_line)
        enforcement_code.append("")
        
    ENFORCEMENT_FILE.write_text("\n".join(enforcement_code))
    
    # Replace calls in forcefocus_daemon.py
    daemon_text = "\n".join(new_daemon_lines)
    for m in method_names:
        daemon_text = re.sub(r"self\." + m + r"\b", r"self.enforcement_manager." + m, daemon_text)
        
    DAEMON_FILE.write_text(daemon_text)
    print("Done")

if __name__ == "__main__":
    main()
