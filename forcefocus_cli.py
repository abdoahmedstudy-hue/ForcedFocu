#!/usr/bin/env python3
"""
ForcedFocus CLI — Premium Command-line Interface.
Modernized with 'rich' for human-friendly dashboards and 'ai-native-cli' for agent safety.
"""

import os
import sys
import subprocess
import json
import socket
import hashlib
import getpass
import argparse
from pathlib import Path
from typing import Any, Dict

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RICH UI INTEGRATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich import box

# Custom theme for ForcedFocus
FF_THEME = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "success": "bold green",
        "highlight": "bold magenta",
        "dim": "grey50",
        "mode.blacklist": "bold red",
        "mode.whitelist": "bold green",
    }
)

console = Console(theme=FF_THEME)

SOCK_PATH = "/var/run/forcefocus.sock"
KS_HASH_FILE = Path("/etc/forcefocus/ks_hash")
CONFIG_DIR = Path("/etc/forcefocus")


class OutputHandler:
    """Handles switching between JSON (agent) and Rich (human) output."""

    def __init__(self, use_human: bool = False, use_agent: bool = False):
        # Explicit flags take precedence
        if use_human:
            self.is_human = True
        elif use_agent:
            self.is_human = False
        else:
            # Default to human if it's a TTY
            self.is_human = sys.stdout.isatty()

        self.is_agent = not self.is_human

    def print_data(self, data: Dict[str, Any], title: str = "ForcedFocus Response"):
        """Print data in the current mode."""
        if self.is_agent:
            print(json.dumps(data, indent=2))
        else:
            self._print_rich(data, title)

    def print_error(self, message: str, code: str = "ERROR", suggestion: str = None):
        """Print error in a structured way."""
        error_data = {
            "error": True,
            "code": code,
            "message": message,
            "suggestion": suggestion,
        }
        if self.is_agent:
            print(json.dumps(error_data, indent=2), file=sys.stderr)
        else:
            console.print(f"[error]✗ {message}[/error]")
            if suggestion:
                console.print(f"[dim]  Suggestion: {suggestion}[/dim]")
        sys.exit(1 if code != "USAGE_ERROR" else 2)

    def _print_rich(self, data: Dict[str, Any], title: str):
        """Internal helper for beautiful rich output."""
        status = data.get("status", "ok")
        msg = data.get("message", "")

        if status == "ok":
            console.print(
                Panel(
                    f"[success]✓[/success] {msg}",
                    title=title,
                    border_style="success",
                    expand=False,
                )
            )
        elif status == "pending":
            console.print(
                Panel(
                    f"[warning]⏱[/warning] {msg}",
                    title=title,
                    border_style="warning",
                    expand=False,
                )
            )
        elif status == "error":
            console.print(
                Panel(
                    f"[error]✗[/error] {msg}",
                    title=title,
                    border_style="error",
                    expand=False,
                )
            )
        else:
            console.print(Panel(f"{msg}", title=title, expand=False))


# Global output handler (initialized in main)
out = OutputHandler()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SOCKET COMMUNICATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def send_command(cmd: dict) -> dict:
    """Send a JSON command to the daemon over the Unix socket."""
    if not os.path.exists(SOCK_PATH):
        out.print_error(
            "Daemon is not running (socket not found).",
            code="DAEMON_NOT_FOUND",
            suggestion="Start it with: sudo launchctl load /Library/LaunchDaemons/com.forcefocus.daemon.plist",
        )

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect(SOCK_PATH)
        sock.sendall(json.dumps(cmd).encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)

        chunks = []
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            except socket.timeout:
                break
        sock.close()

        raw = b"".join(chunks).decode("utf-8")
        if not raw:
            out.print_error("Daemon sent an empty response.", code="EMPTY_RESPONSE")

        return json.loads(raw)
    except ConnectionRefusedError:
        out.print_error(
            "Connection refused. Is the daemon running?", code="CONNECTION_REFUSED"
        )
    except socket.timeout:
        out.print_error("Daemon did not respond in time.", code="TIMEOUT")
    except Exception as exc:
        out.print_error(f"Communication error: {exc}", code="SOCKET_ERROR")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COMMANDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def cmd_start(args):
    """Start a time-bound blocking session."""
    mode = args.mode
    session_type = args.session_type

    if session_type == "pomodoro":
        duration = (args.focus + args.break_time) * args.cycles
    else:
        duration = args.duration

    if duration <= 0:
        out.print_error(
            "Duration must be a positive number of minutes.", code="INVALID_DURATION"
        )

    payload = {
        "action": "start",
        "duration_minutes": duration,
        "mode": mode,
        "session_type": session_type,
        "focus_minutes": args.focus,
        "break_minutes": args.break_time,
        "cycles": args.cycles,
    }

    if args.schedule_in:
        payload["schedule_in_minutes"] = args.schedule_in
    elif args.schedule_at:
        payload["schedule_at_time"] = args.schedule_at

    if args.groups:
        payload["groups"] = args.groups

    if out.is_human:
        with console.status(
            f"[info]Requesting {mode} session ({session_type})...[/info]"
        ):
            resp = send_command(payload)
    else:
        resp = send_command(payload)

    out.print_data(resp, title="Start Session")


def cmd_schedule(args):
    """Manage schedules (recurring)."""
    action = args.action
    if action == "list":
        resp = send_command({"action": "status"})
        if out.is_agent:
            out.print_data(resp)
            return
            
        recurring = resp.get("recurring_schedules", [])
        if not recurring:
            console.print("[dim]No recurring schedules defined.[/dim]")
            return
            
        table = Table(title="Recurring Schedules", header_style="bold magenta")
        table.add_column("ID", style="dim")
        table.add_column("Days", style="info")
        table.add_column("Time", justify="right")
        table.add_column("Duration")
        
        days_arr = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for sch in recurring:
            days_str = ", ".join([days_arr[d] for d in sch.get("days_of_week", [])])
            table.add_row(
                sch.get("id", "")[:8],
                days_str,
                str(sch.get("start_time", "")),
                f"{sch.get('duration_minutes', 0)}m"
            )
        console.print(table)
        
    elif action == "add":
        if not args.recurring:
            out.print_error("Only --recurring is supported via schedule add currently. Use 'start --in' for one-off.", code="USAGE_ERROR")
            
        days = args.days
        time_str = args.time
        dur = args.duration
        mode = args.mode
        
        if not days or not time_str:
            out.print_error("Must provide --days and --time", code="USAGE_ERROR")
            
        try:
            days_list = [int(d) for d in days.split(",")]
        except:
            out.print_error("Invalid days format. Use comma-separated ints 0-6", code="USAGE_ERROR")
            return
            
        payload = {
            "action": "add_recurring_schedule",
            "days_of_week": days_list,
            "start_time": time_str,
            "duration_minutes": dur,
            "mode": mode,
            "session_type": "standard"
        }
        
        resp = send_command(payload)
        out.print_data(resp, title="Add Recurring Schedule")
        
    elif action == "remove":
        sid = args.id
        if not sid:
            out.print_error("ID is required", code="USAGE_ERROR")
        resp = send_command({"action": "remove_recurring_schedule", "id": sid})
        out.print_data(resp, title="Remove Recurring Schedule")

def cmd_groups(args):
    """Manage domain groups."""
    action = args.action
    name = args.name

    if action == "list":
        resp = send_command({"action": "get_groups"})
        if out.is_agent:
            out.print_data(resp)
            return

        groups = resp.get("groups", {})
        if not groups:
            console.print("[dim]No domain groups defined.[/dim]")
            return

        table = Table(title="Domain Groups", header_style="bold magenta")
        table.add_column("Group Name", style="success")
        table.add_column("Domain Count", justify="right")
        table.add_column("Domains")

        for gname, domains in groups.items():
            table.add_row(
                gname,
                str(len(domains)),
                ", ".join(domains[:5]) + ("..." if len(domains) > 5 else ""),
            )

        console.print(table)

    elif action == "add":
        if not name:
            out.print_error("Group name required for 'add'.", code="USAGE_ERROR")
        if not args.domains:
            out.print_error(
                "At least one domain required for 'add'.", code="USAGE_ERROR"
            )

        resp = send_command(
            {"action": "add_group", "name": name, "domains": args.domains}
        )
        out.print_data(resp, title="Add Group")

    elif action == "remove":
        if not name:
            out.print_error("Group name required for 'remove'.", code="USAGE_ERROR")

        resp = send_command({"action": "remove_group", "name": name})
        out.print_data(resp, title="Remove Group")


def cmd_stop(args):
    """Request a delayed unlock (20-minute delay)."""
    key = args.key
    if not key:
        if out.is_agent:
            out.print_error(
                "Kill-switch passphrase required for agent mode.", code="MISSING_KEY"
            )
        key = getpass.getpass("🔐 Kill-switch passphrase: ")

    if out.is_human:
        with console.status("[info]Sending unlock request...[/info]"):
            resp = send_command({"action": "stop", "key": key})
    else:
        resp = send_command({"action": "stop", "key": key})

    out.print_data(resp, title="Stop Session")


def cmd_status(_args):
    """Print current daemon/session state."""
    resp = send_command({"action": "status"})

    if out.is_agent:
        out.print_data(resp)
        return

    # HUMAN-FRIENDLY DASHBOARD
    active = resp.get("active", False)
    schedules = resp.get("schedules", [])

    if not active and not schedules:
        console.print(
            Panel(
                "[info]ForcedFocus is idle — no active blocking session.[/info]",
                title="[dim]System Status[/dim]",
                border_style="dim",
                expand=False,
            )
        )
        return

    # 1. ACTIVE SESSION PANEL
    if active:
        mode = resp.get("mode", "unknown")
        session_type = resp.get("session_type", "standard")
        rem_secs = resp.get("remaining_seconds", 0)
        expires = resp.get("expires_at", "unknown")
        count = resp.get("domains_count", 0)
        pending = resp.get("pending_unlock")

        # Color based on mode
        mode_style = f"mode.{mode}"

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_row(
            "[dim]Type[/dim]", f"[highlight]{session_type.capitalize()}[/highlight]"
        )

        if session_type == "pomodoro":
            phase = resp.get("pomo_phase", "?")
            cycle = resp.get("pomo_current_cycle", "?")
            total_cycles = resp.get("pomo_total_cycles", "?")
            phase_rem = resp.get("pomo_phase_remaining", 0)

            table.add_row("[dim]Cycle[/dim]", f"{cycle} / {total_cycles}")
            table.add_row("[dim]Phase[/dim]", f"[bold]{phase.upper()}[/bold]")

            # Phase Progress Bar
            phase_dur = resp.get("pomo_phase_duration", 1)
            progress = (phase_dur - phase_rem) / phase_dur
            bar = f"[success]{'━' * int(progress * 20)}[/success][dim]{'━' * (20 - int(progress * 20))}[/dim]"
            table.add_row(
                "[dim]Phase Time[/dim]",
                f"{bar} [bold]{phase_rem // 60}m {phase_rem % 60}s[/bold]",
            )

        table.add_row("[dim]Domains[/dim]", f"[bold]{count}[/bold]")
        table.add_row("[dim]Expires[/dim]", f"[dim]{expires}[/dim]")

        # Total Progress Bar
        total_dur = resp.get("duration_minutes", 1) * 60
        total_progress = max(0, min(1, (total_dur - rem_secs) / total_dur))
        total_bar = f"[{mode_style}]{'━' * int(total_progress * 30)}[/{mode_style}][dim]{'━' * (30 - int(total_progress * 30))}[/dim]"

        main_group = [
            f"\n  [{mode_style}]● ACTIVE {mode.upper()}[/{mode_style}]\n",
            table,
            f"\n  {total_bar}  [bold]{rem_secs // 60}m {rem_secs % 60}s remaining[/bold]\n",
        ]

        if pending:
            p_sec = resp.get("pending_unlock_seconds", 0)
            unlock_text = f"\n[warning]⚠ UNLOCK PENDING[/warning]\n[dim]Releases at {pending}[/dim]\n[bold]{p_sec // 60}m {p_sec % 60}s to go[/bold]"
            main_group.append(
                Panel(
                    unlock_text,
                    border_style="warning",
                    title="[warning]Emergency[/warning]",
                )
            )

        console.print(
            Panel(
                Group(*main_group),
                border_style=mode_style,
                title=f"[{mode_style}]ForcedFocus Dashboard[/{mode_style}]",
                expand=False,
            )
        )

    # 2. UPCOMING SCHEDULES
    if schedules:
        sched_table = Table(
            title="[highlight]Upcoming Schedules[/highlight]",
            box=box.ROUNDED,
            header_style="bold cyan",
        )
        sched_table.add_column("#", justify="right")
        sched_table.add_column("Mode")
        sched_table.add_column("Type")
        sched_table.add_column("Starts At")
        sched_table.add_column("Wait Time", justify="right")

        for i, sch in enumerate(schedules, 1):
            s_mode = sch.get("mode", "?").upper()
            s_type = sch.get("session_type", "standard").capitalize()
            s_time = sch.get("starts_at", "?")

            rem_secs = sch.get("starting_in_seconds", 0)
            wait_time = f"{rem_secs // 60}m {rem_secs % 60}s"

            sched_table.add_row(str(i), s_mode, s_type, s_time, wait_time)

        console.print(sched_table)


def cmd_set_key(_args):
    """Set or change the kill-switch passphrase."""
    if os.geteuid() != 0:
        out.print_error(
            "Must run as root to set the kill-switch passphrase.",
            code="PERM_DENIED",
            suggestion="Use: sudo forcefocus set-key",
        )

    console.print(
        Panel(
            "This passphrase is required to unlock an active blocking session.\nIt is stored as a secure PBKDF2-HMAC-SHA256 hash.",
            title="[highlight]Set Kill-Switch Passphrase[/highlight]",
            expand=False,
        )
    )

    try:
        p1 = getpass.getpass("  New Passphrase: ")
        if not p1:
            out.print_error("Passphrase cannot be empty.", code="INVALID_INPUT")
        p2 = getpass.getpass("  Confirm Passphrase: ")
        if p1 != p2:
            out.print_error("Passphrases do not match.", code="MISMATCH")

        # PBKDF2-HMAC-SHA256 — must match daemon's _verify_passphrase()
        salt = os.urandom(16)
        iterations = 100_000  # Must match daemon (forcefocus_daemon.py L1827)
        key_hash = hashlib.pbkdf2_hmac("sha256", p1.encode(), salt, iterations)

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {"salt": salt.hex(), "hash": key_hash.hex()}
        with open(KS_HASH_FILE, "w") as f:
            json.dump(data, f)

        os.chmod(KS_HASH_FILE, 0o600)
        out.print_data(
            {"status": "ok", "message": "Passphrase set successfully."}, title="Set Key"
        )
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)


def cmd_web(args):
    """Start or stop the web interface."""
    action = args.action
    if action == "start":
        out.print_data(
            {"status": "ok", "message": "Starting web interface..."}, title="Web UI"
        )
        web_script = Path("/usr/local/bin/forcefocus_web.py")
        if not web_script.exists():
            web_script = Path(__file__).parent / "forcefocus_web.py"

        if web_script.exists():
            subprocess.run([sys.executable, str(web_script)])
        else:
            out.print_error("Web server script not found.", code="FILE_NOT_FOUND")
    elif action == "stop":
        out.print_data(
            {"status": "ok", "message": "Stopping web interface..."}, title="Web UI"
        )
        # In a real implementation, we would find and kill the process.


def cmd_perma_block(args):
    """Manage the permanent blocklist — always-on, session-independent domain blocking."""
    action = args.action

    if action == "list":
        resp = send_command({"action": "get_perma_blocklist"})
        if out.is_agent:
            out.print_data(resp)
            return

        domains = resp.get("domains", [])
        pending = resp.get("pending_unlocks", {})

        if not domains:
            console.print(
                Panel(
                    "[dim]No permanently blocked domains.[/dim]",
                    title="[error]\U0001f512 Permanent Blocklist[/error]",
                    border_style="dim",
                    expand=False,
                )
            )
            return

        table = Table(
            title="\U0001f512 Permanent Blocklist",
            header_style="bold red",
            box=box.ROUNDED,
        )
        table.add_column("Domain", style="bold")
        table.add_column("Status", justify="center")
        table.add_column("Timer", justify="right")

        for domain in domains:
            if domain in pending:
                rem = pending[domain].get("remaining_seconds", 0)
                m, s = divmod(rem, 60)
                table.add_row(
                    domain,
                    "[warning]\u23F3 PENDING UNBLOCK[/warning]",
                    f"[warning]{m}m {s:02d}s[/warning]",
                )
            else:
                table.add_row(domain, "[error]\U0001f512 LOCKED[/error]", "[dim]—[/dim]")

        console.print(table)
        console.print(
            f"\n[dim]  {len(domains)} domain(s) permanently blocked, "
            f"{len(pending)} pending unblock(s).[/dim]\n"
        )

    elif action == "add":
        domains = args.domains
        if not domains:
            out.print_error(
                "At least one domain is required.", code="USAGE_ERROR"
            )

        resp = send_command({"action": "add_perma_block", "domains": domains})
        out.print_data(resp, title="\U0001f512 Permanent Block")

    elif action == "unblock":
        domain = args.domain
        if not domain:
            out.print_error("Domain is required for 'unblock'.", code="USAGE_ERROR")

        key = args.key
        if not key:
            if out.is_agent:
                out.print_error(
                    "Kill-switch passphrase required for agent mode.",
                    code="MISSING_KEY",
                )
            key = getpass.getpass("\U0001f510 Kill-switch passphrase: ")

        if out.is_human:
            with console.status("[info]Verifying passphrase...[/info]"):
                resp = send_command(
                    {"action": "request_perma_unblock", "domain": domain, "key": key}
                )
        else:
            resp = send_command(
                {"action": "request_perma_unblock", "domain": domain, "key": key}
            )

        out.print_data(resp, title="\U0001f512 Permanent Unblock")

    elif action == "cancel":
        domain = args.domain
        if not domain:
            out.print_error("Domain is required for 'cancel'.", code="USAGE_ERROR")

        resp = send_command({"action": "cancel_perma_unblock", "domain": domain})
        out.print_data(resp, title="\U0001f512 Cancel Unblock")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ARGUMENT PARSER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def build_parser():
    # Base parser with global flags
    parser = argparse.ArgumentParser(
        prog="forcefocus",
        description="ForcedFocus — Premium Productivity Kill-Switch",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Use 'forcefocus <command> --help' for details on specific commands.",
    )

    # Global Flags
    parser.add_argument(
        "--human",
        "-H",
        action="store_true",
        help="Force human-friendly output (styled panels/tables)",
    )
    parser.add_argument(
        "--agent",
        "-A",
        action="store_true",
        help="Force agent-friendly output (structured JSON)",
    )
    parser.add_argument(
        "--brief",
        action="store_true",
        help="Output a brief one-paragraph summary of the tool",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version="ForcedFocus CLI v2.0.0 (Rich Edition)",
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # start
    p_start = sub.add_parser("start", help="Start a blocking session")
    p_start.add_argument(
        "--human", "-H", action="store_true", help="Force human-friendly output"
    )
    p_start.add_argument(
        "--agent", "-A", action="store_true", help="Force agent-friendly output"
    )
    p_start.add_argument(
        "--duration",
        "-d",
        type=int,
        default=120,
        metavar="MIN",
        help="Duration in minutes (default: 120)",
    )
    p_start.add_argument(
        "--mode",
        "-m",
        choices=["blacklist", "whitelist"],
        default="blacklist",
        help="Blocking mode",
    )
    p_start.add_argument(
        "--type",
        dest="session_type",
        choices=["standard", "pomodoro"],
        default="standard",
        help="Session type",
    )
    p_start.add_argument("--focus", type=int, default=25, help="Pomodoro focus minutes")
    p_start.add_argument(
        "--break", dest="break_time", type=int, default=5, help="Pomodoro break minutes"
    )
    p_start.add_argument("--cycles", type=int, default=4, help="Pomodoro cycle count")
    p_start.add_argument(
        "--in",
        dest="schedule_in",
        type=int,
        metavar="MIN",
        help="Schedule session in N minutes",
    )
    p_start.add_argument(
        "--at",
        dest="schedule_at",
        metavar="TIME",
        help="Schedule session at HH:MM time",
    )
    p_start.add_argument(
        "--groups", "-g", nargs="+", help="Groups to include in the session"
    )
    p_start.set_defaults(func=cmd_start)

    # stop
    p_stop = sub.add_parser("stop", help="Request delayed unlock (20-min delay)")
    p_stop.add_argument(
        "--human", "-H", action="store_true", help="Force human-friendly output"
    )
    p_stop.add_argument(
        "--agent", "-A", action="store_true", help="Force agent-friendly output"
    )
    p_stop.add_argument("--key", "-k", help="Kill-switch passphrase")
    p_stop.set_defaults(func=cmd_stop)

    # status
    p_status = sub.add_parser("status", help="Show current session state")
    p_status.add_argument(
        "--human", "-H", action="store_true", help="Force human-friendly output"
    )
    p_status.add_argument(
        "--agent", "-A", action="store_true", help="Force agent-friendly output"
    )
    p_status.set_defaults(func=cmd_status)

    # set-key
    p_setkey = sub.add_parser("set-key", help="Set/change kill-switch passphrase")
    p_setkey.add_argument(
        "--human", "-H", action="store_true", help="Force human-friendly output"
    )
    p_setkey.add_argument(
        "--agent", "-A", action="store_true", help="Force agent-friendly output"
    )
    p_setkey.set_defaults(func=cmd_set_key)

    # web
    p_web = sub.add_parser("web", help="Manage web interface")
    p_web.add_argument(
        "--human", "-H", action="store_true", help="Force human-friendly output"
    )
    p_web.add_argument(
        "--agent", "-A", action="store_true", help="Force agent-friendly output"
    )
    p_web.add_argument(
        "action",
        choices=["start", "stop"],
        default="start",
        nargs="?",
        help="Action to perform",
    )
    p_web.set_defaults(func=cmd_web)

    # groups
    p_groups = sub.add_parser("groups", help="Manage domain groups")
    p_groups.add_argument(
        "--human", "-H", action="store_true", help="Force human-friendly output"
    )
    p_groups.add_argument(
        "--agent", "-A", action="store_true", help="Force agent-friendly output"
    )
    p_groups.add_argument(
        "action", choices=["list", "add", "remove"], help="Group action"
    )
    p_groups.add_argument("name", nargs="?", help="Group name")
    p_groups.add_argument("domains", nargs="*", help="Domains for 'add'")
    p_groups.set_defaults(func=cmd_groups)

    # schedule
    p_schedule = sub.add_parser("schedule", help="Manage schedules")
    p_schedule.add_argument("--human", "-H", action="store_true", help="Force human-friendly output")
    p_schedule.add_argument("--agent", "-A", action="store_true", help="Force agent-friendly output")
    
    sub_sched = p_schedule.add_subparsers(dest="action", help="Schedule action")
    
    p_sched_list = sub_sched.add_parser("list", help="List schedules")
    
    p_sched_add = sub_sched.add_parser("add", help="Add schedule")
    p_sched_add.add_argument("--recurring", action="store_true", help="Create recurring schedule")
    p_sched_add.add_argument("--days", help="Comma separated days (0=Mon, 6=Sun)")
    p_sched_add.add_argument("--time", help="Start time HH:MM")
    p_sched_add.add_argument("--duration", type=int, default=120, help="Duration in minutes")
    p_sched_add.add_argument("--mode", default="blacklist", help="Mode")
    
    p_sched_rm = sub_sched.add_parser("remove", help="Remove schedule")
    p_sched_rm.add_argument("id", help="Schedule ID")
    
    p_schedule.set_defaults(func=cmd_schedule)

    # perma-block
    p_perma = sub.add_parser(
        "perma-block", help="Manage permanent blocklist (always-on, session-independent)"
    )
    p_perma.add_argument(
        "--human", "-H", action="store_true", help="Force human-friendly output"
    )
    p_perma.add_argument(
        "--agent", "-A", action="store_true", help="Force agent-friendly output"
    )
    p_perma.add_argument(
        "action",
        choices=["list", "add", "unblock", "cancel"],
        help="Permanent block action",
    )
    p_perma.add_argument(
        "domain", nargs="?", help="Domain for 'unblock' or 'cancel'"
    )
    p_perma.add_argument(
        "domains", nargs="*", help="Domain(s) for 'add'"
    )
    p_perma.add_argument("--key", "-k", help="Kill-switch passphrase (for unblock)")
    p_perma.set_defaults(func=cmd_perma_block)

    return parser


def print_rich_help(parser):
    """Print a beautiful rich-themed help screen."""
    # Header
    console.print(
        Panel(
            Text.assemble(
                ("ForcedFocus", "highlight"),
                " — Premium Productivity Kill-Switch\n",
                ("High-integrity website blocking for deep work", "dim"),
            ),
            box=box.DOUBLE_EDGE,
            padding=(1, 2),
        )
    )

    # Usage
    usage_text = Text.assemble(
        ("Usage: ", "bold"),
        (parser.prog, "success"),
        (" [options] ", "bold magenta"),
        ("<command> ", "success"),
        ("[args]", "bold cyan"),
    )
    console.print(usage_text)
    console.print()

    # Commands Table
    table = Table(box=box.SIMPLE, header_style="bold magenta", expand=False)
    table.add_column("Command", style="success")
    table.add_column("Description")

    # Manually extract subcommand help (since we know them)
    commands = {
        "start": "Start a time-bound blocking session",
        "stop": "Request a delayed unlock (20-min delay)",
        "status": "Show current session dashboard",
        "set-key": "Set/change the kill-switch passphrase",
        "web": "Manage the web interface",
        "groups": "Manage domain groups",
        "perma-block": "Manage permanent blocklist (always-on)",
    }
    for cmd, desc in commands.items():
        table.add_row(cmd, desc)

    console.print(
        Panel(
            table,
            title="[bold]Available Commands[/bold]",
            border_style="highlight",
            expand=False,
        )
    )

    # Options Table
    opt_table = Table(box=box.SIMPLE, header_style="bold cyan", expand=False)
    opt_table.add_column("Option", style="info")
    opt_table.add_column("Description")
    opt_table.add_row("--human, -H", "Force styled human-friendly output")
    opt_table.add_row("--agent, -A", "Force structured agent JSON output")
    opt_table.add_row("--brief", "Output a one-paragraph tool summary")
    opt_table.add_row("--version, -v", "Show program version")
    opt_table.add_row("--help, -h", "Show this help message")

    console.print(
        Panel(
            opt_table,
            title="[bold]Global Options[/bold]",
            border_style="info",
            expand=False,
        )
    )

    console.print(
        f"\n[dim]Use '{parser.prog} <command> --help' for details on specific commands.[/dim]\n"
    )


def main():
    parser = build_parser()

    # Check for help flags manually to override default behavior
    if any(h in sys.argv for h in ["-h", "--help"]) and sys.stdout.isatty():
        if "--agent" not in sys.argv and "-A" not in sys.argv:
            print_rich_help(parser)
            sys.exit(0)

    args, unknown = parser.parse_known_args()

    # Handle --brief
    if args.brief:
        brief_text = "ForcedFocus is a high-integrity productivity system that enforces deep work by blocking distracting domains at the system level. It features a daemon-backed kill-switch mechanism, support for pomodoro cycles, and scheduled sessions, all managed via a secure Unix socket interface."
        if args.agent or (not args.human and not sys.stdout.isatty()):
            print(json.dumps({"brief": brief_text}))
        else:
            console.print(
                Panel(
                    brief_text,
                    title="[highlight]ForcedFocus Brief[/highlight]",
                    expand=False,
                )
            )
        return

    if not args.command:
        if sys.stdout.isatty() and not args.agent:
            print_rich_help(parser)
        else:
            parser.print_help()
        sys.exit(0)

    # Initialize global output handler with explicit flags
    global out
    out = OutputHandler(use_human=args.human, use_agent=args.agent)

    try:
        # Re-parse fully now that we handled globals
        args = parser.parse_args()
        args.func(args)
    except Exception as e:
        out.print_error(str(e), code="INTERNAL_ERROR")


if __name__ == "__main__":
    main()
