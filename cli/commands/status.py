from rich.panel import Panel
from rich.table import Table
from rich.console import Group
from rich import box
from cli.output import out, console
from cli.client import send_command

def cmd_status(_args):
    """Print current daemon/session state."""
    resp = send_command({"action": "status"})

    if out.is_agent:
        out.print_data(resp)
        return

    # HUMAN-FRIENDLY DASHBOARD
    active = resp.get("active", False)
    schedules = resp.get("schedules", [])

    if not active and not schedules:
        console.print(
            Panel(
                "[info]ForcedFocus is idle — no active blocking session.[/info]",
                title="[dim]System Status[/dim]",
                border_style="dim",
                expand=False,
            )
        )
        return

    # 1. ACTIVE SESSION PANEL
    if active:
        mode = resp.get("mode", "unknown")
        session_type = resp.get("session_type", "standard")
        rem_secs = resp.get("remaining_seconds", 0)
        expires = resp.get("expires_at", "unknown")
        count = resp.get("domains_count", 0)
        pending = resp.get("pending_unlock")

        # Color based on mode
        mode_style = f"mode.{mode}"

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_row(
            "[dim]Type[/dim]", f"[highlight]{session_type.capitalize()}[/highlight]"
        )

        if session_type == "pomodoro":
            phase = resp.get("pomo_phase", "?")
            cycle = resp.get("pomo_current_cycle", "?")
            total_cycles = resp.get("pomo_total_cycles", "?")
            phase_rem = resp.get("pomo_phase_remaining", 0)

            table.add_row("[dim]Cycle[/dim]", f"{cycle} / {total_cycles}")
            table.add_row("[dim]Phase[/dim]", f"[bold]{phase.upper()}[/bold]")

            # Phase Progress Bar
            phase_dur = resp.get("pomo_phase_duration", 1)
            progress = (phase_dur - phase_rem) / phase_dur
            bar = f"[success]{'━' * int(progress * 20)}[/success][dim]{'━' * (20 - int(progress * 20))}[/dim]"
            table.add_row(
                "[dim]Phase Time[/dim]",
                f"{bar} [bold]{phase_rem // 60}m {phase_rem % 60}s[/bold]",
            )

        table.add_row("[dim]Domains[/dim]", f"[bold]{count}[/bold]")
        table.add_row("[dim]Expires[/dim]", f"[dim]{expires}[/dim]")

        # Total Progress Bar
        total_dur = resp.get("duration_minutes", 1) * 60
        total_progress = max(0, min(1, (total_dur - rem_secs) / total_dur))
        total_bar = f"[{mode_style}]{'━' * int(total_progress * 30)}[/{mode_style}][dim]{'━' * (30 - int(total_progress * 30))}[/dim]"

        main_group = [
            f"\n  [{mode_style}]● ACTIVE {mode.upper()}[/{mode_style}]\n",
            table,
            f"\n  {total_bar}  [bold]{rem_secs // 60}m {rem_secs % 60}s remaining[/bold]\n",
        ]

        if pending:
            p_sec = resp.get("pending_unlock_seconds", 0)
            unlock_text = f"\n[warning]⚠ UNLOCK PENDING[/warning]\n[dim]Releases at {pending}[/dim]\n[bold]{p_sec // 60}m {p_sec % 60}s to go[/bold]"
            main_group.append(
                Panel(
                    unlock_text,
                    border_style="warning",
                    title="[warning]Emergency[/warning]",
                )
            )

        console.print(
            Panel(
                Group(*main_group),
                border_style=mode_style,
                title=f"[{mode_style}]ForcedFocus Dashboard[/{mode_style}]",
                expand=False,
            )
        )

    # 2. UPCOMING SCHEDULES
    if schedules:
        sched_table = Table(
            title="[highlight]Upcoming Schedules[/highlight]",
            box=box.ROUNDED,
            header_style="bold cyan",
        )
        sched_table.add_column("#", justify="right")
        sched_table.add_column("Mode")
        sched_table.add_column("Type")
        sched_table.add_column("Starts At")
        sched_table.add_column("Wait Time", justify="right")

        for i, sch in enumerate(schedules, 1):
            s_mode = sch.get("mode", "?").upper()
            s_type = sch.get("session_type", "standard").capitalize()
            s_time = sch.get("starts_at", "?")

            rem_secs = sch.get("starting_in_seconds", 0)
            wait_time = f"{rem_secs // 60}m {rem_secs % 60}s"

            sched_table.add_row(str(i), s_mode, s_type, s_time, wait_time)

        console.print(sched_table)
