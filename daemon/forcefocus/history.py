import json
import uuid
import logging
from datetime import datetime, timedelta
from forcefocus.constants import HISTORY_FILE, SETTINGS_FILE, MAX_HISTORY_ENTRIES

class HistoryManager:
    def __init__(self, daemon):
        self.daemon = daemon

    def load_history(self) -> list:
        """Load session history from disk."""
        try:
            if HISTORY_FILE.exists():
                data = json.loads(HISTORY_FILE.read_text())
                if isinstance(data, list):
                    return data
        except Exception as exc:
            logging.error("Failed to load session history: %s", exc)
        return []

    def save_history(self, entries: list):
        """Persist session history to disk with cap enforcement."""
        if len(entries) > MAX_HISTORY_ENTRIES:
            entries = entries[-MAX_HISTORY_ENTRIES:]
        self.daemon._atomic_write_json(HISTORY_FILE, entries)

    def record_session_history(self):
        """Record the current session as a history entry."""
        d = self.daemon
        if not d.state.session.session_expiry or d.state.session.total_duration_seconds <= 0:
            return

        now = datetime.now()
        started_at = d.state.session.session_expiry - timedelta(seconds=d.state.session.total_duration_seconds)
        completed_normally = d.state.session.pending_unlock_at is None

        tasks = d.state.session.intent_tasks or []
        tasks_total = len(tasks)
        tasks_completed = sum(1 for t in tasks if isinstance(t, dict) and t.get("completed"))

        duration_minutes = d.state.session.total_duration_seconds // 60
        net_focus_minutes = d.state.session.total_duration_seconds // 60
        
        session_type = d.state.session.session_type
        if session_type == "pomodoro":
            # Only record the untracked remainder
            elapsed_seconds = max(0, (now - started_at).total_seconds())
            remainder_seconds = max(0, elapsed_seconds - d.state.pomodoro.pomo_phases_tracked_seconds)
            if remainder_seconds < 60:
                return  # Skip tiny untracked remnants
            
            duration_minutes = int(remainder_seconds // 60)
            started_at = started_at + timedelta(seconds=d.state.pomodoro.pomo_phases_tracked_seconds)
            pomo_phase = d.state.pomodoro.pomo_phase
            if pomo_phase == "focus":
                net_focus_minutes = duration_minutes
            else:
                net_focus_minutes = 0
        else:
            pomo_phase = None

        entry = {
            "id": str(uuid.uuid4()),
            "started_at": started_at.isoformat(),
            "ended_at": now.isoformat(),
            "duration_minutes": duration_minutes,
            "net_focus_minutes": net_focus_minutes,
            "mode": d.state.session.mode,
            "session_type": session_type,
            "session_group_id": d.state.session.session_group_id or str(uuid.uuid4()),
            "pomo_phase": pomo_phase,
            "intent": d.state.session.intent or "",
            "tasks_total": tasks_total,
            "tasks_completed": tasks_completed,
            "completed_normally": completed_normally,
            "pomo_focus_minutes": d.state.pomodoro.pomo_focus_minutes if session_type == "pomodoro" else None,
            "pomo_break_minutes": d.state.pomodoro.pomo_break_minutes if session_type == "pomodoro" else None,
            "pomo_cycles_completed": d.state.pomodoro.pomo_current_cycle if session_type == "pomodoro" else None,
            "pomo_total_cycles": d.state.pomodoro.pomo_total_cycles if session_type == "pomodoro" else None,
            "groups": list(d.state.session.session_groups or []),
            "day_of_week": started_at.weekday(),
            "hour_started": started_at.hour,
        }

        history = self.load_history()
        history.append(entry)
        self.save_history(history)
        logging.info("Session history recorded: %s (%dm, %s, %s)",
                     entry["id"][:8], entry["duration_minutes"], entry["mode"], entry["session_type"])

    def record_pomodoro_phase(self, phase_name: str, duration_minutes: int, started_at: datetime, ended_at: datetime, completed_normally: bool):
        d = self.daemon
        entry = {
            "id": str(uuid.uuid4()),
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_minutes": duration_minutes,
            "net_focus_minutes": duration_minutes if phase_name == "focus" else 0,
            "mode": d.state.session.mode,
            "session_type": "pomodoro",
            "session_group_id": d.state.session.session_group_id or str(uuid.uuid4()),
            "pomo_phase": phase_name,
            "intent": d.state.session.intent or "",
            "tasks_total": len(d.state.session.intent_tasks or []),
            "tasks_completed": sum(1 for t in (d.state.session.intent_tasks or []) if isinstance(t, dict) and t.get("completed")),
            "completed_normally": completed_normally,
            "pomo_focus_minutes": d.state.pomodoro.pomo_focus_minutes,
            "pomo_break_minutes": d.state.pomodoro.pomo_break_minutes,
            "pomo_cycles_completed": d.state.pomodoro.pomo_current_cycle,
            "pomo_total_cycles": d.state.pomodoro.pomo_total_cycles,
            "groups": list(d.state.session.session_groups or []),
            "day_of_week": started_at.weekday(),
            "hour_started": started_at.hour,
        }
        history = self.load_history()
        history.append(entry)
        self.save_history(history)
        logging.info("Pomodoro phase recorded: %s (%dm, %s)", entry["id"][:8], duration_minutes, phase_name)

    def cmd_get_session_history(self, cmd: dict) -> dict:
        """Return session history with server-side aggregation."""
        history = self.load_history()
        range_key = cmd.get("range", "week")
        specific_date = cmd.get("date", None)
        now = datetime.now()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Determine date boundaries
        if specific_date:
            try:
                target = datetime.strptime(specific_date, "%Y-%m-%d")
                start = target.replace(hour=0, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=1)
            except ValueError:
                return {"status": "error", "message": "Invalid date format. Use YYYY-MM-DD."}
        elif range_key == "today":
            start = today
            end = now
        elif range_key == "yesterday":
            start = today - timedelta(days=1)
            end = today
        elif range_key == "week":
            start = today - timedelta(days=6)
            end = now
        elif range_key == "month":
            start = today - timedelta(days=29)
            end = now
        elif range_key == "year":
            start = today - timedelta(days=364)
            end = now
        elif range_key == "all":
            start = datetime.min
            end = now
        else:
            start = today - timedelta(days=6)
            end = now

        # Filter entries
        filtered = []
        for entry in history:
            if entry.get("session_type") == "prayer":
                continue
            try:
                entry_start = datetime.fromisoformat(entry["started_at"])
                if start <= entry_start <= end:
                    filtered.append(entry)
            except (ValueError, KeyError):
                continue

        # Aggregate
        total_sessions = len(filtered)
        total_minutes = sum(e.get("duration_minutes", 0) for e in filtered)
        net_focus_minutes_total = sum(e.get("net_focus_minutes", e.get("duration_minutes", 0)) for e in filtered)
        avg_minutes = round(total_minutes / total_sessions) if total_sessions > 0 else 0
        normally_completed = sum(1 for e in filtered if e.get("completed_normally"))
        completed_rate = round(normally_completed / total_sessions, 2) if total_sessions > 0 else 0
        tasks_completed_total = sum(e.get("tasks_completed", 0) for e in filtered)
        tasks_total_sum = sum(e.get("tasks_total", 0) for e in filtered)

        by_mode = {}
        by_type = {}
        by_hour = {}
        by_day_of_week = [0] * 7
        daily_totals = {}

        for e in filtered:
            mode = e.get("mode", "blacklist")
            by_mode[mode] = by_mode.get(mode, 0) + 1
            stype = e.get("session_type", "standard")
            by_type[stype] = by_type.get(stype, 0) + 1
            hour = str(e.get("hour_started", 0))
            by_hour[hour] = by_hour.get(hour, 0) + 1
            dow = e.get("day_of_week", 0)
            if 0 <= dow < 7:
                by_day_of_week[dow] += 1

            try:
                day_key = datetime.fromisoformat(e["started_at"]).strftime("%Y-%m-%d")
                if day_key not in daily_totals:
                    daily_totals[day_key] = {"sessions": 0, "minutes": 0}
                daily_totals[day_key]["sessions"] += 1
                daily_totals[day_key]["minutes"] += e.get("duration_minutes", 0)
            except (ValueError, KeyError):
                pass

        # Read settings for daily focus goal (needed for streak threshold)
        daily_focus_goal_hours = 0
        if SETTINGS_FILE.exists():
            try:
                settings_data = json.loads(SETTINGS_FILE.read_text())
                daily_focus_goal_hours = settings_data.get("daily_focus_goal_hours", 0)
            except Exception:
                pass
        goal_threshold_minutes = (daily_focus_goal_hours * 60) / 2

        # Streak calculation (across all history)
        daily_net_minutes = {}
        for e in history:
            try:
                day_str = datetime.fromisoformat(e["started_at"]).strftime("%Y-%m-%d")
                daily_net_minutes[day_str] = daily_net_minutes.get(day_str, 0) + e.get("net_focus_minutes", 0)
            except (ValueError, KeyError):
                pass
        
        session_days = set(day for day, net in daily_net_minutes.items() if net > 0 and net >= goal_threshold_minutes)

        current_streak = 0
        longest_streak = 0
        streak = 0
        
        yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        today_str = today.strftime("%Y-%m-%d")
        
        if today_str in session_days:
            check_date = today
        elif yesterday_str in session_days:
            check_date = today - timedelta(days=1)
        else:
            check_date = None
            
        if check_date:
            while True:
                ds = check_date.strftime("%Y-%m-%d")
                if ds in session_days:
                    streak += 1
                    check_date -= timedelta(days=1)
                else:
                    break
            current_streak = streak

        # Longest streak
        if session_days:
            sorted_days = sorted(session_days)
            streak = 1
            for i in range(1, len(sorted_days)):
                prev = datetime.strptime(sorted_days[i - 1], "%Y-%m-%d")
                curr = datetime.strptime(sorted_days[i], "%Y-%m-%d")
                if (curr - prev).days == 1:
                    streak += 1
                else:
                    longest_streak = max(longest_streak, streak)
                    streak = 1
            longest_streak = max(longest_streak, streak)
            
        # Longest Session (Across all history)
        session_durations = {}
        for e in history:
            grp = e.get("session_group_id") or e.get("id")
            session_durations[grp] = session_durations.get(grp, 0) + e.get("duration_minutes", 0)
        longest = max(session_durations.values(), default=0) if session_durations else 0

        summary = {
            "total_sessions": total_sessions,
            "total_focus_minutes": total_minutes,
            "net_focus_minutes": net_focus_minutes_total,
            "daily_focus_goal_hours": daily_focus_goal_hours,
            "avg_session_minutes": avg_minutes,
            "longest_session_minutes": longest,
            "completed_rate": completed_rate,
            "total_tasks_completed": tasks_completed_total,
            "total_tasks_total": tasks_total_sum,
            "by_mode": by_mode,
            "by_type": by_type,
            "by_day_of_week": by_day_of_week,
            "by_hour": by_hour,
            "current_streak_days": current_streak,
            "longest_streak_days": longest_streak,
            "daily_totals": daily_totals,
        }

        return {"status": "ok", "entries": filtered, "summary": summary}

    def cmd_clear_session_history(self) -> dict:
        """Delete all session history."""
        try:
            if HISTORY_FILE.exists():
                HISTORY_FILE.unlink()
            return {"status": "ok", "message": "Session history cleared."}
        except Exception as exc:
            logging.error("Failed to clear session history: %s", exc)
            return {"status": "error", "message": f"Failed to clear history: {exc}"}
