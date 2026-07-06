import ast
import os
import shutil

os.makedirs("daemon/forcefocus/enforcement", exist_ok=True)

with open("daemon/forcefocus/enforcement.py", "r") as f:
    source = f.read()

tree = ast.parse(source)

# We want to extract methods by name
def extract_methods(method_names, mixin_name, imports):
    methods_src = ""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "EnforcementManager":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name in method_names:
                    # extract exact source using node line numbers
                    # get source segment
                    method_code = ast.get_source_segment(source, item)
                    methods_src += "    " + method_code.replace("\n", "\n    ") + "\n\n"
                    
    with open(f"daemon/forcefocus/enforcement/{mixin_name.lower().replace('mixin', '')}.py", "w") as f:
        f.write(imports + "\n\nclass " + mixin_name + ":\n" + methods_src)

dns_methods = [
    "_enforce_perma_block", "_build_perma_block", "_strip_perma_block",
    "_enforce_block", "_build_blacklist_block", "_get_network_services",
    "_get_current_dns_servers", "_enforce_whitelist", "_enforce_doh_block",
    "_set_dns_to_localhost", "_restore_dns", "_strip_block", "_flush_dns"
]

firewall_methods = [
    "_update_blocked_ips", "_enforce_firewall"
]

system_methods = [
    "_clear_browser_caches", "_enforce_browser_policies", "_kill_vpns",
    "_kill_restricted_apps", "_reset_system_proxies", "_kill_vpn_interfaces"
]

common_imports = """import os
import subprocess
import logging
import threading
import json
import time
import socket
import tempfile
import plistlib
import ssl
from pathlib import Path
from datetime import datetime
from forcefocus.constants import *"""

extract_methods(dns_methods, "DNSMixin", common_imports)
extract_methods(firewall_methods, "FirewallMixin", common_imports)
extract_methods(system_methods, "SystemMixin", common_imports)

# Generate __init__.py
core_methods = ["__init__", "_enforce_current_mode"]
init_src = f"{common_imports}\n\nfrom .dns import DNSMixin\nfrom .firewall import FirewallMixin\nfrom .system import SystemMixin\n\nclass EnforcementManager(DNSMixin, FirewallMixin, SystemMixin):\n"
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "EnforcementManager":
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name in core_methods:
                method_code = ast.get_source_segment(source, item)
                init_src += "    " + method_code.replace("\n", "\n    ") + "\n\n"

with open("daemon/forcefocus/enforcement/__init__.py", "w") as f:
    f.write(init_src)

print("Split enforcement complete.")
