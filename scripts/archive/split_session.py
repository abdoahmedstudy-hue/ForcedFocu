import ast
import os

os.makedirs("daemon/forcefocus/session", exist_ok=True)

with open("daemon/forcefocus/session.py", "r") as f:
    source = f.read()

tree = ast.parse(source)

def extract_methods(method_names, mixin_name, imports):
    methods_src = ""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "SessionManager":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name in method_names:
                    method_code = ast.get_source_segment(source, item)
                    methods_src += "    " + method_code.replace("\n", "\n    ") + "\n\n"
                    
    with open(f"daemon/forcefocus/session/{mixin_name.lower().replace('mixin', '')}.py", "w") as f:
        f.write(imports + "\n\nclass " + mixin_name + ":\n" + methods_src)

core_methods = [
    "_start_session", "_request_stop", "_cancel_stop",
    "_remove_block", "_cleanup_session", "cmd_get_status"
]
pomodoro_methods = ["_transition_pomodoro_phase"]
intent_methods = ["cmd_set_intent"]

common_imports = """import logging
import threading
import uuid
import time
import json
from pathlib import Path
from datetime import datetime, timedelta
from forcefocus.constants import *
from forcefocus.utils import get_continuous_time
from forcefocus.events import Event"""

extract_methods(core_methods, "CoreMixin", common_imports)
extract_methods(pomodoro_methods, "PomodoroMixin", common_imports)
extract_methods(intent_methods, "IntentMixin", common_imports)

# Generate __init__.py
init_methods = ["__init__"]
init_src = f"{common_imports}\n\nfrom .core import CoreMixin\nfrom .pomodoro import PomodoroMixin\nfrom .intent import IntentMixin\n\nclass SessionManager(CoreMixin, PomodoroMixin, IntentMixin):\n"
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "SessionManager":
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name in init_methods:
                method_code = ast.get_source_segment(source, item)
                init_src += "    " + method_code.replace("\n", "\n    ") + "\n\n"

with open("daemon/forcefocus/session/__init__.py", "w") as f:
    f.write(init_src)

print("Split session complete.")
