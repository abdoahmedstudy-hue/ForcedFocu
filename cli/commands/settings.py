import json
from rich.table import Table
from cli.output import out, console
from cli.client import send_command

DEFAULT_SETTINGS_TYPES = {
    "sound_start": str,
    "sound_rescue": str,
    "sound_unlock": str,
    "sound_break": str,
    "sound_end": str,
    "sound_scheduled": str,
    "sound_blocked": str,
    "intent_notification_enabled": bool,
    "intent_notification_interval": int,
}

def cmd_settings(args):
    """Manage daemon settings."""
    action = args.action

    if action == "show":
        resp = send_command({"action": "get_settings"})
        if out.is_agent:
            out.print_data(resp)
            return

        if resp.get("status") != "ok":
            out.print_error(resp.get("message", "Failed to retrieve settings."), code="SETTINGS_ERROR")

        settings = resp.get("settings", {})
        table = Table(title="⚙️ ForcedFocus Settings", header_style="bold cyan")
        table.add_column("Setting Key", style="success")
        table.add_column("Type", style="dim")
        table.add_column("Value", style="info")

        for key in sorted(settings.keys()):
            val = settings[key]
            val_type = type(val).__name__
            table.add_row(key, val_type, str(val))

        console.print(table)

    elif action == "set":
        key = args.key
        raw_val = args.value

        if not key:
            out.print_error("Setting key is required.", code="USAGE_ERROR")
        if raw_val is None:
            out.print_error("Setting value is required.", code="USAGE_ERROR")

        # Fetch current settings first to merge and avoid overwriting other keys
        resp = send_command({"action": "get_settings"})
        if resp.get("status") != "ok":
            out.print_error(resp.get("message", "Failed to retrieve current settings."), code="SETTINGS_ERROR")

        settings = resp.get("settings", {})

        # Validate setting key
        if key not in DEFAULT_SETTINGS_TYPES:
            out.print_error(
                f"Unknown setting key: '{key}'",
                code="INVALID_KEY",
                suggestion=f"Available keys: {', '.join(DEFAULT_SETTINGS_TYPES.keys())}",
            )

        expected_type = DEFAULT_SETTINGS_TYPES[key]
        validated_val = None

        if expected_type is bool:
            norm = str(raw_val).strip().lower()
            if norm in ("true", "1", "yes", "on", "y"):
                validated_val = True
            elif norm in ("false", "0", "no", "off", "n"):
                validated_val = False
            else:
                out.print_error(
                    f"Invalid boolean value '{raw_val}' for key '{key}'.",
                    code="INVALID_VALUE",
                    suggestion="Use true/false, yes/no, or 1/0.",
                )
        elif expected_type is int:
            try:
                validated_val = int(raw_val)
            except ValueError:
                out.print_error(
                    f"Invalid integer value '{raw_val}' for key '{key}'.",
                    code="INVALID_VALUE",
                )
        else:
            validated_val = str(raw_val)

        # Merge and save
        settings[key] = validated_val
        save_resp = send_command({"action": "save_settings", "settings": settings})
        out.print_data(save_resp, title="Save Settings")
