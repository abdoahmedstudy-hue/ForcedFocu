from rich.table import Table
from rich.panel import Panel
from cli.output import out, console
from cli.client import send_command

def cmd_domains(args):
    """Manage regular domain lists (blacklist/whitelist)."""
    action = args.action

    if action == "show":
        resp = send_command({"action": "get_lists"})
        if out.is_agent:
            out.print_data(resp)
            return

        lists = resp.get("lists", {})
        blacklist = lists.get("blacklist", [])
        whitelist = lists.get("whitelist", [])

        # Display blacklist and whitelist in beautiful side-by-side or stacked tables
        bl_table = Table(title="🚫 Blacklisted Domains", header_style="bold red")
        bl_table.add_column("Domain", style="bold")
        for domain in sorted(blacklist):
            bl_table.add_row(domain)

        wl_table = Table(title="✅ Whitelisted Domains", header_style="bold green")
        wl_table.add_column("Domain", style="bold")
        for domain in sorted(whitelist):
            wl_table.add_row(domain)

        console.print(bl_table)
        console.print()
        console.print(wl_table)

    elif action == "add":
        list_name = args.list
        domains = args.domains

        if not list_name or list_name not in ("blacklist", "whitelist"):
            out.print_error("List must be 'blacklist' or 'whitelist'.", code="USAGE_ERROR")

        if not domains:
            out.print_error("At least one domain must be provided.", code="USAGE_ERROR")

        if len(domains) == 1:
            payload = {
                "action": "add_domain",
                "list": list_name,
                "domain": domains[0]
            }
        else:
            payload = {
                "action": "add_domains",
                "list": list_name,
                "domains": domains
            }

        resp = send_command(payload)
        out.print_data(resp, title=f"Add Domain(s) to {list_name.capitalize()}")

    elif action == "remove":
        list_name = args.list
        domain = args.domain

        if not list_name or list_name not in ("blacklist", "whitelist"):
            out.print_error("List must be 'blacklist' or 'whitelist'.", code="USAGE_ERROR")

        if not domain:
            out.print_error("Domain must be provided.", code="USAGE_ERROR")

        payload = {
            "action": "remove_domain",
            "list": list_name,
            "domain": domain
        }

        resp = send_command(payload)
        out.print_data(resp, title=f"Remove Domain from {list_name.capitalize()}")
