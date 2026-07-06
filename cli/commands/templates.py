from __future__ import annotations

from rich.table import Table

from cli.output import out, console
from cli.client import send_command


def _find_template(ref: str, templates: list[dict]) -> dict | None:
    ref_lower = ref.lower()
    exact = [t for t in templates if t.get("id") == ref or t.get("name", "").lower() == ref_lower]
    if exact:
        return exact[0]
    prefixed = [t for t in templates if str(t.get("id", "")).startswith(ref)]
    return prefixed[0] if len(prefixed) == 1 else None


def _resolve_template_id(ref: str) -> str | None:
    listing = send_command({"action": "get_templates"})
    templates = listing.get("templates", [])
    match = _find_template(ref, templates)
    return match.get("id") if match else None


def cmd_templates(args):
    """Manage smart session templates."""
    if args.action == "list":
        resp = send_command({"action": "get_templates"})
        if out.is_agent:
            out.print_data(resp)
            return

        templates = resp.get("templates", [])
        if not templates:
            console.print("[dim]No session templates saved yet.[/dim]")
            return

        table = Table(title="Smart Session Templates", header_style="bold magenta")
        table.add_column("ID", style="dim")
        table.add_column("Name", style="bold")
        table.add_column("Mode")
        table.add_column("Type")
        table.add_column("Duration")
        table.add_column("Groups")
        table.add_column("Uses", justify="right")
        for template in templates:
            table.add_row(
                str(template.get("id", ""))[:8],
                template.get("name", ""),
                template.get("mode", "blacklist"),
                template.get("session_type", "standard"),
                f"{template.get('duration_minutes', 0)}m",
                ", ".join(template.get("groups", [])) or "-",
                str(template.get("use_count", 0)),
            )
        console.print(table)

    elif args.action == "add":
        duration = args.duration
        if args.session_type == "pomodoro":
            duration = (args.focus + args.break_time) * args.cycles
        payload = {
            "action": "add_template",
            "name": args.name,
            "duration_minutes": duration,
            "mode": args.mode,
            "session_type": args.session_type,
            "focus_minutes": args.focus,
            "break_minutes": args.break_time,
            "cycles": args.cycles,
            "groups": args.groups or [],
            "intent": args.intent or "",
        }
        resp = send_command(payload)
        out.print_data(resp, title="Add Template")

    elif args.action in ("start", "remove", "duplicate"):
        template_id = _resolve_template_id(args.template)
        if not template_id:
            out.print_error(
                "Template not found. Use `forcefocus templates list` to see available templates.",
                code="TEMPLATE_NOT_FOUND",
            )
            return

        if args.action == "start":
            resp = send_command({"action": "start_template", "id": template_id})
            out.print_data(resp, title="Start Template")
        elif args.action == "remove":
            resp = send_command({"action": "remove_template", "id": template_id})
            out.print_data(resp, title="Remove Template")
        else:
            payload = {"action": "duplicate_template", "id": template_id}
            if args.name:
                payload["name"] = args.name
            resp = send_command(payload)
            out.print_data(resp, title="Duplicate Template")
