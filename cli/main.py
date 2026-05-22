from cli.proxy import sys_proxy as sys, json, Path
import argparse

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from cli.output import out, console
from cli.commands.start import cmd_start
from cli.commands.stop import cmd_stop
from cli.commands.status import cmd_status
from cli.commands.groups import cmd_groups
from cli.commands.perma_block import cmd_perma_block
from cli.commands.schedule import cmd_schedule
from cli.commands.set_key import cmd_set_key
from cli.commands.web import cmd_web
from cli.commands.domains import cmd_domains
from cli.commands.settings import cmd_settings
from cli.commands.sound import cmd_sound

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
    p_schedule.add_argument(
        "--human", "-H", action="store_true", help="Force human-friendly output"
    )
    p_schedule.add_argument(
        "--agent", "-A", action="store_true", help="Force agent-friendly output"
    )
    sub_sched = p_schedule.add_subparsers(dest="action", help="Schedule action")
    sub_sched.required = True

    p_sched_list = sub_sched.add_parser("list", help="List schedules")
    
    p_sched_add = sub_sched.add_parser("add", help="Add schedule")
    p_sched_add.add_argument("--recurring", action="store_true", help="Create recurring schedule")
    p_sched_add.add_argument("--days", help="Comma separated days (0=Mon, 6=Sun)")
    p_sched_add.add_argument("--time", help="Start time HH:MM")
    p_sched_add.add_argument("--duration", type=int, default=120, help="Duration in minutes")
    p_sched_add.add_argument("--mode", default="blacklist", help="Mode")
    p_sched_add.add_argument(
        "--type",
        dest="session_type",
        choices=["standard", "pomodoro"],
        default="standard",
        help="Session type",
    )
    p_sched_add.add_argument("--focus", type=int, default=25, help="Pomodoro focus minutes")
    p_sched_add.add_argument(
        "--break", dest="break_time", type=int, default=5, help="Pomodoro break minutes"
    )
    p_sched_add.add_argument("--cycles", type=int, default=4, help="Pomodoro cycle count")
    p_sched_add.add_argument(
        "--groups", "-g", nargs="+", help="Groups to include in the session"
    )
    
    p_sched_rm = sub_sched.add_parser("remove", help="Remove schedule")
    p_sched_rm.add_argument("id", help="Schedule ID")
    p_schedule.set_defaults(func=cmd_schedule)

    # perma-block parent parser for inheriting human and agent flags
    perma_parent = argparse.ArgumentParser(add_help=False)
    perma_parent.add_argument(
        "--human", "-H", action="store_true", help="Force human-friendly output"
    )
    perma_parent.add_argument(
        "--agent", "-A", action="store_true", help="Force agent-friendly output"
    )

    p_perma = sub.add_parser(
        "perma-block",
        parents=[perma_parent],
        help="Manage permanent blocklist (always-on, session-independent)",
    )
    sub_perma = p_perma.add_subparsers(dest="action", help="Permanent block action")
    sub_perma.required = True

    p_perma_list = sub_perma.add_parser(
        "list",
        parents=[perma_parent],
        help="List permanently blocked domains",
    )
    
    p_perma_add = sub_perma.add_parser(
        "add",
        parents=[perma_parent],
        help="Add domains to permanent blocklist",
    )
    p_perma_add.add_argument("domains", nargs="+", help="Domain(s) to add")

    p_perma_unblock = sub_perma.add_parser(
        "unblock",
        parents=[perma_parent],
        help="Request permanent unblock",
    )
    p_perma_unblock.add_argument("domain", help="Domain to unblock")
    p_perma_unblock.add_argument("--key", "-k", help="Kill-switch passphrase (for unblock)")

    p_perma_cancel = sub_perma.add_parser(
        "cancel",
        parents=[perma_parent],
        help="Cancel a pending permanent unblock",
    )
    p_perma_cancel.add_argument("domain", help="Domain to cancel")
    p_perma.set_defaults(func=cmd_perma_block)

    # domains
    p_domains = sub.add_parser("domains", help="Manage regular domain lists (blacklist/whitelist)")
    p_domains.add_argument("--human", "-H", action="store_true", help="Force human-friendly output")
    p_domains.add_argument("--agent", "-A", action="store_true", help="Force agent-friendly output")
    sub_domains = p_domains.add_subparsers(dest="action", help="Domains action")
    sub_domains.required = True

    p_dom_show = sub_domains.add_parser("show", help="Show blacklist/whitelist domains")
    
    p_dom_add = sub_domains.add_parser("add", help="Add domains to a list")
    p_dom_add.add_argument("list", choices=["blacklist", "whitelist"], help="Target list")
    p_dom_add.add_argument("domains", nargs="+", help="Domains to add")

    p_dom_rm = sub_domains.add_parser("remove", help="Remove domain from a list")
    p_dom_rm.add_argument("list", choices=["blacklist", "whitelist"], help="Target list")
    p_dom_rm.add_argument("domain", help="Domain to remove")
    p_domains.set_defaults(func=cmd_domains)

    # settings
    p_settings = sub.add_parser("settings", help="Manage settings")
    p_settings.add_argument("--human", "-H", action="store_true", help="Force human-friendly output")
    p_settings.add_argument("--agent", "-A", action="store_true", help="Force agent-friendly output")
    sub_settings = p_settings.add_subparsers(dest="action", help="Settings action")
    sub_settings.required = True

    p_set_show = sub_settings.add_parser("show", help="Show current settings")

    p_set_set = sub_settings.add_parser("set", help="Set a setting value")
    p_set_set.add_argument("key", help="Setting key")
    p_set_set.add_argument("value", help="Setting value")
    p_settings.set_defaults(func=cmd_settings)

    # sound
    p_sound = sub.add_parser("sound", help="Manage notification/session sound files")
    p_sound.add_argument("--human", "-H", action="store_true", help="Force human-friendly output")
    p_sound.add_argument("--agent", "-A", action="store_true", help="Force agent-friendly output")
    sub_sound = p_sound.add_subparsers(dest="action", help="Sound action")
    sub_sound.required = True

    p_sound_list = sub_sound.add_parser("list", help="List available sound files")

    p_sound_del = sub_sound.add_parser("delete", help="Delete a sound file")
    p_sound_del.add_argument("filename", help="Sound file name to delete")
    p_sound.set_defaults(func=cmd_sound)

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
        "schedule": "Manage recurring schedules",
        "perma-block": "Manage permanent blocklist (always-on)",
        "domains": "Manage regular domain lists (blacklist/whitelist)",
        "settings": "Manage daemon settings",
        "sound": "Manage notification/session sound files",
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
    if any(h in sys.argv for h in ["--human", "-H"]):
        out.is_human = True
        out.is_agent = False
    elif any(a in sys.argv for a in ["--agent", "-A"]):
        out.is_human = False
        out.is_agent = True
    else:
        out.is_human = sys.stdout.isatty()
        out.is_agent = not out.is_human

    try:
        # Re-parse fully now that we handled globals
        args = parser.parse_args()
        args.func(args)
    except Exception as e:
        out.print_error(str(e), code="INTERNAL_ERROR")
