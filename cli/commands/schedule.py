from rich.table import Table
from cli.output import out, console
from cli.client import send_command

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
        table.add_column("Mode")
        table.add_column("Type")
        table.add_column("Details")
        table.add_column("Groups")
        
        days_arr = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for sch in recurring:
            days_str = ", ".join([days_arr[d] for d in sch.get("days_of_week", [])])
            
            mode_str = sch.get("mode", "blacklist")
            session_type = sch.get("session_type", "standard")
            
            details_str = "-"
            if session_type == "pomodoro":
                focus = sch.get("focus_minutes", 25)
                brk = sch.get("break_minutes", 5)
                cycles = sch.get("cycles", 4)
                details_str = f"focus:{focus}m, break:{brk}m, cycles:{cycles}"
                
            groups = sch.get("groups", [])
            groups_str = ", ".join(groups) if groups else "-"
            
            table.add_row(
                sch.get("id", "")[:8],
                days_str,
                str(sch.get("start_time", "")),
                f"{sch.get('duration_minutes', 0)}m",
                mode_str,
                session_type,
                details_str,
                groups_str
            )
        console.print(table)
        
    elif action == "add":
        if not args.recurring:
            out.print_error("Only --recurring is supported via schedule add currently. Use 'start --in' for one-off.", code="USAGE_ERROR")
            
        days = args.days
        time_str = args.time
        dur = args.duration
        mode = args.mode
        session_type = args.session_type
        
        if not days or not time_str:
            out.print_error("Must provide --days and --time", code="USAGE_ERROR")
            
        try:
            days_list = [int(d) for d in days.split(",")]
        except:
            out.print_error("Invalid days format. Use comma-separated ints 0-6", code="USAGE_ERROR")
            return
            
        if session_type == "pomodoro":
            dur = (args.focus + args.break_time) * args.cycles
            
        if dur <= 0:
            out.print_error("Duration must be a positive number of minutes.", code="INVALID_DURATION")
            return
            
        payload = {
            "action": "add_recurring_schedule",
            "days_of_week": days_list,
            "start_time": time_str,
            "duration_minutes": dur,
            "mode": mode,
            "session_type": session_type,
            "groups": args.groups or []
        }
        
        if session_type == "pomodoro":
            payload["focus_minutes"] = args.focus
            payload["break_minutes"] = args.break_time
            payload["cycles"] = args.cycles
        
        resp = send_command(payload)
        out.print_data(resp, title="Add Recurring Schedule")
        
    elif action == "remove":
        sid = args.id
        if not sid:
            out.print_error("ID is required", code="USAGE_ERROR")
        resp = send_command({"action": "remove_recurring_schedule", "id": sid})
        out.print_data(resp, title="Remove Recurring Schedule")
