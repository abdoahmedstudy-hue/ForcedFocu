from cli.proxy import getpass
from cli.output import out, console
from cli.client import send_command

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
