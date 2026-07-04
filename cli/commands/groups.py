from rich.table import Table
from cli.output import out, console
from cli.client import send_command

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
