from rich.table import Table
from cli.output import out, console
from cli.client import send_command

def cmd_sound(args):
    """Manage notification/session sound files."""
    action = args.action

    if action == "list":
        resp = send_command({"action": "get_sounds"})
        if out.is_agent:
            out.print_data(resp)
            return

        if resp.get("status") != "ok":
            out.print_error(
                resp.get("message", "Failed to retrieve sounds."), code="SOUND_ERROR"
            )

        sounds = resp.get("sounds", [])
        if not sounds:
            console.print("[dim]No sound files available.[/dim]")
            return

        table = Table(title="🎵 Available Sounds", header_style="bold magenta")
        table.add_column("Filename", style="info")

        for sound in sounds:
            table.add_row(sound)

        console.print(table)

    elif action == "delete":
        filename = args.filename
        if not filename:
            out.print_error("Filename is required for 'delete'.", code="USAGE_ERROR")

        resp = send_command({"action": "delete_sound", "filename": filename})
        out.print_data(resp, title="Delete Sound")
