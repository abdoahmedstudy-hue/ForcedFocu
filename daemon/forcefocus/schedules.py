from __future__ import annotations
import json
import uuid
import re
import logging
from datetime import datetime, timedelta
from forcefocus.constants import TEMPLATES_FILE

class SchedulesManager:
    def __init__(self, daemon):
        self.daemon = daemon

    def load_templates(self) -> list[dict]:
        try:
            if not TEMPLATES_FILE.exists():
                return []
            data = json.loads(TEMPLATES_FILE.read_text())
            templates = data.get("templates", [])
            if isinstance(templates, list):
                return [t for t in templates if isinstance(t, dict)]
        except Exception as exc:
            logging.error("Failed to load templates: %s", exc)
        return []

    def save_templates(self, templates: list[dict]):
        self.daemon._atomic_write_json(TEMPLATES_FILE, {"templates": templates}, indent=2)
        self.daemon.notifications_manager.broadcast_state_changed()

    @staticmethod
    def _coerce_int(value, default=None):
        try:
            if value is None:
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    def normalize_template(self, raw: dict, existing: dict | None = None) -> tuple[bool, str, dict]:
        if not isinstance(raw, dict):
            return False, "Template must be an object.", {}

        now = datetime.now().isoformat()
        template = dict(existing or {})
        name = str(raw.get("name", template.get("name", ""))).strip()
        if not name:
            return False, "Template name is required.", {}
        if len(name) > 80:
            return False, "Template name must be 80 characters or fewer.", {}

        mode = raw.get("mode", template.get("mode", "blacklist"))
        session_type = raw.get("session_type", template.get("session_type", "standard"))
        if session_type == "rescue":
            mode = "whitelist"
        if mode not in ("blacklist", "whitelist", "ban"):
            return False, "Invalid mode.", {}
        if session_type not in ("standard", "pomodoro", "rescue"):
            return False, "Invalid session type.", {}

        duration = self._coerce_int(
            raw.get("duration_minutes", raw.get("duration", template.get("duration_minutes", 120)))
        )
        if duration is None or duration < 1 or duration > 1440:
            return False, "Duration must be 1–1440 minutes.", {}

        focus = self._coerce_int(raw.get("focus_minutes", template.get("focus_minutes", 25)), 25)
        break_minutes = self._coerce_int(raw.get("break_minutes", template.get("break_minutes", 5)), 5)
        cycles = self._coerce_int(raw.get("cycles", template.get("cycles", 4)), 4)
        if session_type == "pomodoro":
            if focus < 1 or focus > 240:
                return False, "Focus minutes must be 1–240.", {}
            if break_minutes < 1 or break_minutes > 60:
                return False, "Break minutes must be 1–60.", {}
            if cycles < 1 or cycles > 50:
                return False, "Cycles must be 1–50.", {}
            duration = (focus + break_minutes) * cycles
            if duration > 1440:
                return False, "Pomodoro template duration must be 1440 minutes or less.", {}

        groups_raw = raw.get("groups", template.get("groups", []))
        if not isinstance(groups_raw, list):
            return False, "Groups must be a list.", {}
        groups = []
        known_groups = self.daemon.domains_manager.load_groups()
        for group in groups_raw:
            group_name = str(group).strip()
            if group_name and group_name in known_groups and group_name not in groups:
                groups.append(group_name)

        intent = str(raw.get("intent", template.get("intent", ""))).strip()
        if len(intent) > 500:
            return False, "Intent must be 500 characters or fewer.", {}

        tasks_raw = raw.get("intent_tasks", template.get("intent_tasks", []))
        tasks = []
        if isinstance(tasks_raw, list):
            for task in tasks_raw[:50]:
                if isinstance(task, dict):
                    text = str(task.get("text", "")).strip()
                    completed = bool(task.get("completed", False))
                else:
                    text = str(task).strip()
                    completed = False
                if text:
                    tasks.append({"text": text[:300], "completed": completed})
        else:
            return False, "Intent tasks must be a list.", {}

        template.update(
            {
                "id": template.get("id") or str(uuid.uuid4()),
                "name": name,
                "mode": mode,
                "duration_minutes": duration,
                "session_type": session_type,
                "focus_minutes": focus,
                "break_minutes": break_minutes,
                "cycles": cycles,
                "groups": groups,
                "intent": intent,
                "intent_tasks": tasks,
                "created_at": template.get("created_at") or now,
                "updated_at": now,
                "last_used_at": template.get("last_used_at"),
                "use_count": int(template.get("use_count", 0) or 0),
            }
        )
        return True, "", template

    def template_start_payload(self, template: dict) -> dict:
        payload = {
            "action": "start",
            "duration_minutes": template.get("duration_minutes", 120),
            "mode": template.get("mode", "blacklist"),
            "session_type": template.get("session_type", "standard"),
            "groups": template.get("groups", []),
            "intent": template.get("intent", ""),
            "intent_tasks": template.get("intent_tasks", []),
        }
        if template.get("session_type") == "pomodoro":
            payload["focus_minutes"] = template.get("focus_minutes", 25)
            payload["break_minutes"] = template.get("break_minutes", 5)
            payload["cycles"] = template.get("cycles", 4)
        return payload

    def cmd_get_templates(self) -> dict:
        with self.daemon.lock:
            templates = sorted(
                self.load_templates(),
                key=lambda t: (t.get("last_used_at") or "", t.get("updated_at") or ""),
                reverse=True,
            )
            return {"status": "ok", "templates": templates}

    def cmd_add_template(self, cmd: dict) -> dict:
        with self.daemon.lock:
            ok, message, template = self.normalize_template(cmd)
            if not ok:
                return {"status": "error", "message": message}
            templates = self.load_templates()
            if any(t.get("name", "").lower() == template["name"].lower() for t in templates):
                return {"status": "error", "message": "A template with this name already exists."}
            templates.append(template)
            self.save_templates(templates)
            return {"status": "ok", "message": f"Template '{template['name']}' saved.", "template": template}

    def cmd_update_template(self, cmd: dict) -> dict:
        template_id = str(cmd.get("id", "")).strip()
        if not template_id:
            return {"status": "error", "message": "Template id is required."}
        with self.daemon.lock:
            templates = self.load_templates()
            for idx, existing in enumerate(templates):
                if existing.get("id") == template_id:
                    ok, message, template = self.normalize_template(cmd, existing)
                    if not ok:
                        return {"status": "error", "message": message}
                    duplicate = any(
                        t.get("id") != template_id and t.get("name", "").lower() == template["name"].lower()
                        for t in templates
                    )
                    if duplicate:
                        return {"status": "error", "message": "A template with this name already exists."}
                    templates[idx] = template
                    self.save_templates(templates)
                    return {"status": "ok", "message": f"Template '{template['name']}' updated.", "template": template}
        return {"status": "error", "message": "Template not found."}

    def cmd_remove_template(self, cmd: dict) -> dict:
        template_id = str(cmd.get("id", "")).strip()
        if not template_id:
            return {"status": "error", "message": "Template id is required."}
        with self.daemon.lock:
            templates = self.load_templates()
            remaining = [t for t in templates if t.get("id") != template_id]
            if len(remaining) == len(templates):
                return {"status": "error", "message": "Template not found."}
            self.save_templates(remaining)
            return {"status": "ok", "message": "Template removed.", "templates": remaining}

    def cmd_duplicate_template(self, cmd: dict) -> dict:
        template_id = str(cmd.get("id", "")).strip()
        with self.daemon.lock:
            templates = self.load_templates()
            source = next((t for t in templates if t.get("id") == template_id), None)
            if not source:
                return {"status": "error", "message": "Template not found."}
            clone = dict(source)
            clone["id"] = str(uuid.uuid4())
            clone["name"] = str(cmd.get("name") or f"{source.get('name', 'Template')} Copy").strip()
            clone["created_at"] = datetime.now().isoformat()
            clone["updated_at"] = clone["created_at"]
            clone["last_used_at"] = None
            clone["use_count"] = 0
            ok, message, clone = self.normalize_template(clone)
            if not ok:
                return {"status": "error", "message": message}
            templates.append(clone)
            self.save_templates(templates)
            return {"status": "ok", "message": f"Template '{clone['name']}' duplicated.", "template": clone}

    def cmd_start_template(self, cmd: dict) -> dict:
        template_id = str(cmd.get("id", "")).strip()
        with self.daemon.lock:
            templates = self.load_templates()
            template = next((t for t in templates if t.get("id") == template_id), None)
            if not template:
                return {"status": "error", "message": "Template not found."}
            start_payload = self.template_start_payload(template)

        result = self.daemon._start_session(start_payload)
        if result.get("status") == "ok":
            with self.daemon.lock:
                templates = self.load_templates()
                for idx, existing in enumerate(templates):
                    if existing.get("id") == template_id:
                        existing["last_used_at"] = datetime.now().isoformat()
                        existing["use_count"] = int(existing.get("use_count", 0) or 0) + 1
                        templates[idx] = existing
                        self.save_templates(templates)
                        result["template"] = existing
                        break
        return result

    def cmd_get_recurring_schedules(self) -> dict:
        with self.daemon.lock:
            return {"status": "ok", "recurring_schedules": self.recurring_schedules_response()}

    def normalize_recurring_schedule(self, cmd: dict, existing: dict | None = None) -> tuple[bool, str, dict]:
        if not isinstance(cmd, dict):
            return False, "Schedule payload must be an object.", {}

        now = datetime.now().isoformat()
        rule = dict(existing or {})
        name = str(cmd.get("name", rule.get("name", "Focus Ritual"))).strip() or "Focus Ritual"
        if len(name) > 80:
            return False, "Schedule name must be 80 characters or fewer.", {}

        days_raw = cmd.get("days_of_week", rule.get("days_of_week", []))
        if not isinstance(days_raw, list) or not days_raw:
            return False, "days_of_week must include at least one day.", {}
        days = []
        for day in days_raw:
            if isinstance(day, bool):
                return False, "days_of_week values must be integers 0-6.", {}
            try:
                day_int = int(day)
            except (TypeError, ValueError):
                return False, "days_of_week values must be integers 0-6.", {}
            if day_int < 0 or day_int > 6:
                return False, "days_of_week values must be between 0 and 6.", {}
            if day_int not in days:
                days.append(day_int)
        days.sort()

        start_time_raw = str(cmd.get("start_time", rule.get("start_time", ""))).strip()
        time_match = re.fullmatch(r"(\d{1,2}):(\d{2})", start_time_raw)
        if not time_match:
            return False, "start_time must be HH:MM.", {}
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        if hour > 23 or minute > 59:
            return False, "start_time must be a valid 24-hour time.", {}
        start_time = f"{hour:02d}:{minute:02d}"

        mode = cmd.get("mode", rule.get("mode", "blacklist"))
        session_type = cmd.get("session_type", rule.get("session_type", "standard"))
        if session_type == "rescue":
            mode = "whitelist"
        if mode not in ("blacklist", "whitelist", "ban"):
            return False, "Invalid mode.", {}
        if session_type not in ("standard", "pomodoro", "rescue"):
            return False, "Invalid session type.", {}

        duration = self._coerce_int(cmd.get("duration_minutes", rule.get("duration_minutes", 120)))
        if duration is None or duration < 1 or duration > 1440:
            return False, "Duration must be 1–1440 minutes.", {}

        focus = self._coerce_int(cmd.get("focus_minutes", rule.get("focus_minutes", 25)), 25)
        break_minutes = self._coerce_int(cmd.get("break_minutes", rule.get("break_minutes", 5)), 5)
        cycles = self._coerce_int(cmd.get("cycles", rule.get("cycles", 4)), 4)
        if session_type == "pomodoro":
            if focus < 1 or focus > 240:
                return False, "Focus minutes must be 1–240.", {}
            if break_minutes < 1 or break_minutes > 60:
                return False, "Break minutes must be 1–60.", {}
            if cycles < 1 or cycles > 50:
                return False, "Cycles must be 1–50.", {}
            duration = (focus + break_minutes) * cycles
            if duration > 1440:
                return False, "Pomodoro schedule duration must be 1440 minutes or less.", {}

        groups_raw = cmd.get("groups", rule.get("groups", []))
        if not isinstance(groups_raw, list):
            return False, "Groups must be a list.", {}
        known_groups = self.daemon.domains_manager.load_groups()
        groups = []
        for group in groups_raw:
            group_name = str(group).strip()
            if not group_name or group_name in groups:
                continue
            if known_groups and group_name not in known_groups:
                continue
            groups.append(group_name)

        enabled = cmd.get("enabled", rule.get("enabled", True))
        if not isinstance(enabled, bool):
            return False, "enabled must be a boolean.", {}

        rule.update(
            {
                "id": rule.get("id") or str(uuid.uuid4()),
                "name": name,
                "enabled": enabled,
                "days_of_week": days,
                "start_time": start_time,
                "duration_minutes": duration,
                "mode": mode,
                "groups": groups,
                "session_type": session_type,
                "focus_minutes": focus,
                "break_minutes": break_minutes,
                "cycles": cycles,
                "created_at": rule.get("created_at") or now,
                "updated_at": now,
                "last_triggered": rule.get("last_triggered", ""),
                "last_result": rule.get("last_result", ""),
                "last_result_message": rule.get("last_result_message", ""),
            }
        )
        return True, "", rule

    @staticmethod
    def _next_recurring_run(rule: dict, now: datetime | None = None) -> datetime | None:
        if not rule.get("enabled", True):
            return None
        days = rule.get("days_of_week", [])
        start_time = rule.get("start_time", "")
        try:
            hour, minute = [int(part) for part in start_time.split(":", 1)]
        except Exception:
            return None
        now = now or datetime.now()
        for offset in range(8):
            candidate = now + timedelta(days=offset)
            if candidate.weekday() not in days:
                continue
            start_dt = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if start_dt > now:
                return start_dt
        return None

    def recurring_schedules_response(self) -> list[dict]:
        now = datetime.now()
        result = []
        for rule in self.daemon.recurring_schedules:
            enriched = dict(rule)
            next_run = self._next_recurring_run(rule, now)
            enriched["next_run_at"] = next_run.isoformat() if next_run else None
            enriched["next_run_label"] = next_run.strftime("%a %I:%M %p").replace(" 0", " ") if next_run else "Paused"
            result.append(enriched)
        return result

    def cmd_add_recurring_schedule(self, cmd: dict) -> dict:
        with self.daemon.lock:
            ok, message, new_rule = self.normalize_recurring_schedule(cmd)
            if not ok:
                return {"status": "error", "message": message}
            self.daemon.recurring_schedules.append(new_rule)
            self.daemon._persist_session_lock()
            self.daemon.notifications_manager.broadcast_state_changed()
            return {"status": "ok", "message": "Recurring schedule added.", "rule": self.recurring_schedules_response()[-1]}

    def cmd_update_recurring_schedule(self, cmd: dict) -> dict:
        with self.daemon.lock:
            rule_id = cmd.get("id")
            if not rule_id:
                return {"status": "error", "message": "Rule ID is required."}
            for idx, existing in enumerate(self.daemon.recurring_schedules):
                if existing.get("id") == rule_id:
                    ok, message, updated = self.normalize_recurring_schedule(cmd, existing)
                    if not ok:
                        return {"status": "error", "message": message}
                    self.daemon.recurring_schedules[idx] = updated
                    self.daemon._persist_session_lock()
                    self.daemon.notifications_manager.broadcast_state_changed()
                    return {"status": "ok", "message": "Recurring schedule updated.", "rule": self.recurring_schedules_response()[idx]}
            return {"status": "error", "message": "Recurring schedule not found."}

    def cmd_toggle_recurring_schedule(self, cmd: dict, enabled: bool) -> dict:
        payload = dict(cmd)
        payload["enabled"] = enabled
        return self.cmd_update_recurring_schedule(payload)

    def cmd_duplicate_recurring_schedule(self, cmd: dict) -> dict:
        with self.daemon.lock:
            rule_id = cmd.get("id")
            source = next((rule for rule in self.daemon.recurring_schedules if rule.get("id") == rule_id), None)
            if not source:
                return {"status": "error", "message": "Recurring schedule not found."}
            clone = dict(source)
            clone.pop("id", None)
            clone["name"] = str(cmd.get("name") or f"{source.get('name', 'Focus Ritual')} Copy").strip()
            clone["last_triggered"] = ""
            clone["last_result"] = ""
            clone["last_result_message"] = ""
            ok, message, new_rule = self.normalize_recurring_schedule(clone)
            if not ok:
                return {"status": "error", "message": message}
            self.daemon.recurring_schedules.append(new_rule)
            self.daemon._persist_session_lock()
            self.daemon.notifications_manager.broadcast_state_changed()
            return {"status": "ok", "message": "Recurring schedule duplicated.", "rule": self.recurring_schedules_response()[-1]}

    def cmd_remove_recurring_schedule(self, cmd: dict) -> dict:
        with self.daemon.lock:
            rule_id = cmd.get("id")
            if not rule_id:
                return {"status": "error", "message": "Rule ID is required."}
            
            initial_len = len(self.daemon.recurring_schedules)
            self.daemon.recurring_schedules = [r for r in self.daemon.recurring_schedules if r.get("id") != rule_id]
            if len(self.daemon.recurring_schedules) < initial_len:
                self.daemon._persist_session_lock()
                self.daemon.notifications_manager.broadcast_state_changed()
                return {"status": "ok", "message": "Recurring schedule removed."}
            return {"status": "error", "message": "Recurring schedule not found."}

    def cmd_cancel_schedule(self, cmd: dict) -> dict:
        with self.daemon.lock:
            if not self.daemon.schedules:
                return {"status": "error", "message": "No scheduled sessions to cancel."}
                
            index = cmd.get("index")
            start_time_iso = cmd.get("start_time_iso")
            
            def _can_cancel(sch):
                remaining = (sch["start_time"] - datetime.now()).total_seconds()
                return remaining > 20 * 60
            
            if index is not None:
                try:
                    idx = int(index)
                    if 0 <= idx < len(self.daemon.schedules):
                        if not _can_cancel(self.daemon.schedules[idx]):
                            return {"status": "error", "message": "Cannot cancel schedule with 20 minutes or less remaining."}
                        sch = self.daemon.schedules.pop(idx)
                        self.daemon._persist_session_lock()
                        self.daemon.notifications_manager.broadcast_state_changed()
                        return {"status": "ok", "message": f"Cancelled schedule for {sch['start_time'].strftime('%H:%M')}."}
                    else:
                        return {"status": "error", "message": "Invalid schedule index."}
                except ValueError:
                    return {"status": "error", "message": "Invalid index format."}
            elif start_time_iso:
                for i, sch in enumerate(self.daemon.schedules):
                    if sch["start_time"].isoformat() == start_time_iso:
                        if not _can_cancel(sch):
                            return {"status": "error", "message": "Cannot cancel schedule with 20 minutes or less remaining."}
                        self.daemon.schedules.pop(i)
                        self.daemon._persist_session_lock()
                        self.daemon.notifications_manager.broadcast_state_changed()
                        return {"status": "ok", "message": f"Cancelled schedule for {sch['start_time'].strftime('%H:%M')}."}
                return {"status": "error", "message": "Schedule not found by start_time_iso."}
            
            return {"status": "error", "message": "Must provide index or start_time_iso."}
