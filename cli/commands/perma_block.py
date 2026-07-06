from cli.proxy import getpass
from rich.table import Table
from rich.panel import Panel
from rich import box
from cli.output import out, console
from cli.client import send_command

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
                    title="[error]🔒 Permanent Blocklist[/error]",
                    border_style="dim",
                    expand=False,
                )
            )
            return

        table = Table(
            title="🔒 Permanent Blocklist",
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
                    "[warning]⏳ PENDING UNBLOCK[/warning]",
                    f"[warning]{m}m {s:02d}s[/warning]",
                )
            else:
                table.add_row(domain, "[error]🔒 LOCKED[/error]", "[dim]—[/dim]")

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
        out.print_data(resp, title="🔒 Permanent Block")

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
            key = getpass.getpass("🔓 Kill-switch passphrase: ")

        if out.is_human:
            with console.status("[info]Verifying passphrase...[/info]"):
                resp = send_command(
                    {"action": "request_perma_unblock", "domain": domain, "key": key}
                )
        else:
            resp = send_command(
                {"action": "request_perma_unblock", "domain": domain, "key": key}
            )

        out.print_data(resp, title="🔒 Permanent Unblock")

    elif action == "cancel":
        domain = args.domain
        if not domain:
            out.print_error("Domain is required for 'cancel'.", code="USAGE_ERROR")

        resp = send_command({"action": "cancel_perma_unblock", "domain": domain})
        out.print_data(resp, title="🔒 Cancel Unblock")
