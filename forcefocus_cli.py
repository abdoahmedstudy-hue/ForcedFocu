#!/usr/bin/env python3
"""
Backward-compatible shim for ForcedFocus CLI. All logic lives in cli/ package.
"""

from pathlib import Path
import os
import sys
import subprocess
import getpass
import json
import socket
import hashlib

from cli.client import send_command, SOCK_PATH
from cli.output import OutputHandler, console, FF_THEME, out
from cli.main import build_parser, main, print_rich_help

# Import command functions for backwards compatibility in tests
from cli.commands.start import cmd_start
from cli.commands.stop import cmd_stop
from cli.commands.status import cmd_status
from cli.commands.groups import cmd_groups
from cli.commands.perma_block import cmd_perma_block
from cli.commands.schedule import cmd_schedule
from cli.commands.set_key import cmd_set_key
from cli.commands.web import cmd_web
from cli.commands.templates import cmd_templates

# Preserve constants for backwards compatibility
KS_HASH_FILE = Path("/etc/forcefocus/ks_hash")
CONFIG_DIR = Path("/etc/forcefocus")

if __name__ == "__main__":
    main()
