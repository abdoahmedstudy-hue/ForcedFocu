from cli.output import out, console
from cli.client import send_command

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
