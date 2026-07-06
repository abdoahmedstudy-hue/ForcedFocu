import logging
import threading
import uuid
import time
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from forcefocus.constants import *
from forcefocus.utils import get_continuous_time
from forcefocus.events import Event

class CoreMixin:
    def _start_session(self, cmd: dict) -> dict:
            duration_minutes = cmd.get("duration_minutes", 120)
            mode = cmd.get("mode", "blacklist")
            # D3: Validate inputs before acquiring lock
            try:
                duration_minutes = int(duration_minutes)
            except (TypeError, ValueError):
                return {"status": "error", "message": "Invalid duration."}
            if duration_minutes < 1 or duration_minutes > 1440:
                return {"status": "error", "message": "Duration must be 1–1440 minutes."}
            if mode not in ("blacklist", "whitelist", "ban"):
                return {"status": "error", "message": "Invalid mode."}
            with self.daemon.lock:
                # Parse scheduling arguments
                schedule_in = cmd.get("schedule_in_minutes")
                schedule_at = cmd.get("schedule_at_time")
                start_time = None
                if schedule_in:
                    start_time = datetime.now() + timedelta(minutes=int(schedule_in))
                elif schedule_at:
                    try:
                        now = datetime.now()
                        formats = [
                            "%Y-%m-%dT%H:%M",  # HTML5 datetime-local
                            "%Y-%m-%d %H:%M",  # CLI basic
                            "%Y-%m-%d %I:%M %p",  # CLI AM/PM
                            "%Y-%m-%d %I:%M%p",
                            "%I:%M %p",  # Just time AM/PM
                            "%I:%M%p",
                            "%H:%M",  # Just time 24h
                        ]
                        for fmt in formats:
                            try:
                                parsed = datetime.strptime(schedule_at.strip(), fmt)
                                if parsed.year == 1900:
                                    start_time = now.replace(
                                        hour=parsed.hour,
                                        minute=parsed.minute,
                                        second=0,
                                        microsecond=0,
                                    )
                                    if start_time <= now:
                                        start_time += timedelta(days=1)
                                else:
                                    start_time = parsed
                                break
                            except ValueError:
                                continue
    
                        if not start_time:
                            return {
                                "status": "error",
                                "message": "Invalid date/time format. Use 'YYYY-MM-DD HH:MM AM/PM' or 'HH:MM AM/PM'.",
                            }
    
                    except Exception as exc:
                        return {
                            "status": "error",
                            "message": f"Failed to parse schedule time: {exc}",
                        }
    
                # duration_minutes already validated before lock acquisition
    
                is_scheduling = start_time and start_time > datetime.now()
    
                # Check overlap if active
                if self.daemon.state.session.active:
                    if not is_scheduling:
                        if self.daemon.state.session.session_type != cmd.get("session_type", "standard"):
                            return {"status": "error", "message": "Cannot merge different session types (e.g. standard and pomodoro)."}
                        if self.daemon.state.session.mode != mode:
                            return {"status": "error", "message": "Cannot merge different modes (whitelist/blacklist)."}
    
                        new_expiry = datetime.now() + timedelta(minutes=duration_minutes)
                        added_minutes = 0
                        if new_expiry > self.daemon.state.session.session_expiry:
                            added_minutes = int((new_expiry - self.daemon.state.session.session_expiry).total_seconds() / 60)
                            self.daemon.state.session.session_expiry = new_expiry
                            self.daemon._mono_session_end = get_continuous_time() + (duration_minutes * 60)
                            self.daemon.state.session.total_duration_seconds = max(self.daemon.state.session.total_duration_seconds, duration_minutes * 60)
    
                        # Merge groups
                        selected_groups = cmd.get("groups", [])
                        if selected_groups:
                            self.daemon.state.session.session_groups = list(set(self.daemon.state.session.session_groups + selected_groups))
                            groups = self.daemon.domains_manager.load_groups()
                            new_domains = []
                            for gname in selected_groups:
                                if gname in groups:
                                    new_domains.extend(groups[gname])
                            
                            if self.daemon.state.session.mode == "blacklist":
                                self.daemon.session_base_domains.extend(new_domains)
                                self.daemon.session_base_domains = list(set(d.strip().lower() for d in self.daemon.session_base_domains if d.strip() and "." in d))
                                
                                new_expanded = self.daemon.domains_manager.get_blacklist_domains(selected_groups)
                                self.daemon.state.active_domains.extend(new_expanded)
                                self.daemon.state.active_domains = list(set(self.daemon.state.active_domains))
                                self.daemon.active_domains_set = set(self.daemon.state.active_domains)
                                self.daemon.events.emit(Event.SESSION_STARTED)
                            # For whitelist, adding domains makes it less restrictive. 
                            # We skip expanding the whitelist during a merge to enforce strictness.
    
                        self.daemon._persist_session_lock()
                        self.daemon.notifications_manager.broadcast_state_changed()
                        
                        msg = f"Session merged. Extended by {added_minutes} minutes." if added_minutes > 0 else "Session merged. Constraints updated."
                        logging.info(msg)
                        return {
                            "status": "ok",
                            "message": msg,
                            "mode": self.daemon.state.session.mode,
                            "domains_count": len(self.daemon.state.active_domains),
                            "expires_at": self.daemon.state.session.session_expiry.strftime("%H:%M:%S"),
                            "event": "merged",
                            "added_minutes": added_minutes
                        }
                    else:
                        # Allow scheduling even if it overlaps. It will be merged when it executes.
                        pass
    
                if is_scheduling:
                    end_time = start_time + timedelta(minutes=duration_minutes)
    
                    # Check overlap with existing schedules
                    for sch in self.daemon.schedules:
                        if max(start_time, sch["start_time"]) < min(
                            end_time, sch["end_time"]
                        ):
                            return {
                                "status": "error",
                                "message": f"Schedule overlaps with an existing schedule (starts at {sch['start_time'].strftime('%m-%d %H:%M')}).",
                            }
    
                    sch_cmd = cmd.copy()
                    sch_cmd.pop("schedule_in_minutes", None)
                    sch_cmd.pop("schedule_at_time", None)
    
                    mono_start = get_continuous_time() + (start_time - datetime.now()).total_seconds()
                    self.daemon.schedules.append(
                        {
                            "start_time": start_time,
                            "end_time": end_time,
                            "mono_start": mono_start,
                            "cmd": sch_cmd,
                        }
                    )
                    self.daemon.schedules.sort(key=lambda x: x["start_time"])
                    self.daemon._persist_session_lock()
    
                    logging.info(
                        "Session scheduled to start at %s.",
                        start_time.strftime("%Y-%m-%d %I:%M %p"),
                    )
                    return {
                        "status": "ok",
                        "message": f"Session scheduled to start at {start_time.strftime('%Y-%m-%d %I:%M %p')}.",
                        "scheduled": True,
                        "starts_at": start_time.strftime("%Y-%m-%d %I:%M %p"),
                    }
    
                self.daemon.state.session.mode = mode
                self.daemon.state.session.session_type = cmd.get("session_type", "standard")
                self.daemon.state.session.intent = (
                    cmd.get("intent", None) or self.daemon.state.session.intent
                )  # Keep existing intent if set via /api/intent and not provided in start
                self.daemon.state.session.intent_tasks = (
                    cmd.get("intent_tasks", None) or self.daemon.state.session.intent_tasks
                )
                self.daemon.state.session.session_expiry = datetime.now() + timedelta(minutes=duration_minutes)
                if not self.daemon.state.session.active:
                    self.daemon.state.session.session_group_id = str(uuid.uuid4())
                self.daemon.state.session.active = True
                self.daemon.state.session.total_duration_seconds = duration_minutes * 60
                self.daemon.state.session.pending_unlock_at = None
                # Monotonic anchors
                now_mono = get_continuous_time()
                self.daemon._mono_session_end = now_mono + (duration_minutes * 60)
                self.daemon._mono_unlock_end = 0.0
                self.daemon._mono_last_intent_notif = now_mono
    
                # Extract pomodoro params from command
                if self.daemon.state.session.session_type == "pomodoro":
                    self.daemon.state.pomodoro.pomo_focus_minutes = cmd.get("focus_minutes", 25)
                    self.daemon.state.pomodoro.pomo_break_minutes = cmd.get("break_minutes", 5)
                    self.daemon.state.pomodoro.pomo_total_cycles = cmd.get("cycles", 4)
                    self.daemon.state.pomodoro.pomo_current_cycle = 1
                    self.daemon.state.pomodoro.pomo_phase = "focus"
                    self.daemon.state.pomodoro.pomo_phase_expiry = datetime.now() + timedelta(
                        minutes=self.daemon.state.pomodoro.pomo_focus_minutes
                    )
                    self.daemon._mono_pomo_phase_end = now_mono + (self.daemon.state.pomodoro.pomo_focus_minutes * 60)
                    # S7: Override duration with exact Pomodoro calculation to prevent timer divergence
                    pomo_total = (
                        self.daemon.state.pomodoro.pomo_focus_minutes + self.daemon.state.pomodoro.pomo_break_minutes
                    ) * self.daemon.state.pomodoro.pomo_total_cycles
                    duration_minutes = pomo_total
                    self.daemon.state.session.total_duration_seconds = pomo_total * 60
                    self.daemon.state.session.session_expiry = datetime.now() + timedelta(minutes=pomo_total)
                    self.daemon._mono_session_end = now_mono + (pomo_total * 60)
    
                # MEDIUM #1 fix: Use self.daemon.state.session.session_expiry (post-Pomodoro override)
                # instead of the stale local `expiry` variable.
                session_data = {
                    "started": datetime.now().isoformat(),
                    "expiry": self.daemon.state.session.session_expiry.isoformat(),
                    "mode": mode,
                    "duration_minutes": duration_minutes,
                    "session_type": self.daemon.state.session.session_type,
                    "pomo_focus_minutes": self.daemon.state.pomodoro.pomo_focus_minutes,
                    "pomo_break_minutes": self.daemon.state.pomodoro.pomo_break_minutes,
                    "pomo_total_cycles": self.daemon.state.pomodoro.pomo_total_cycles,
                    "pomo_current_cycle": self.daemon.state.pomodoro.pomo_current_cycle,
                    "pomo_phase": self.daemon.state.pomodoro.pomo_phase,
                    "pomo_phase_expiry": (
                        self.daemon.state.pomodoro.pomo_phase_expiry.isoformat()
                        if self.daemon.state.pomodoro.pomo_phase_expiry
                        else None
                    ),
                    "settings": self.daemon.settings,
                    "mono_elapsed": 0.0,
                    "last_persist_wall": datetime.now().isoformat(),
                    "schedules": [
                        {
                            "start_time": sch["start_time"].isoformat(),
                            "end_time": sch["end_time"].isoformat(),
                            "cmd": sch["cmd"],
                        }
                        for sch in self.daemon.schedules
                    ],
                    "recurring_schedules": self.daemon.recurring_schedules,
                }
                self.daemon.remaining_seconds = duration_minutes * 60
                self.daemon.pending_unlock_seconds = 0
                if self.daemon.state.session.session_type == "pomodoro":
                    self.daemon.pomo_phase_remaining = self.daemon.state.pomodoro.pomo_focus_minutes * 60
    
                selected_groups = cmd.get("groups", [])
                self.daemon.state.session.session_groups = list(selected_groups)
                if mode in ("whitelist", "ban"):
                    # Original DNS is saved by the enforcement manager itself on SESSION_STARTED
                    if self.daemon.state.session.session_type == "rescue" or mode == "ban":
                        wl_domains = []
                    else:
                        wl_domains = self.daemon.domains_manager.load_lists().get("whitelist", [])
                        if selected_groups:
                            groups = self.daemon.domains_manager.load_groups()
                            for gname in selected_groups:
                                if gname in groups:
                                    wl_domains.extend(groups[gname])
                    self.daemon.session_base_domains = list(
                        set(d.strip().lower() for d in wl_domains if d.strip())
                    )
    
                    # Whitelist mode: active_domains holds the ALLOW-list.
                    if self.daemon.state.session.session_type == "rescue" or mode == "ban":
                        wl_domains_expanded = []
                    else:
                        wl_domains_expanded = self.daemon.domains_manager.expand_whitelist_domains(wl_domains)
                    self.daemon.state.active_domains = wl_domains_expanded
                    self.daemon.active_domains_set = set(self.daemon.state.active_domains)
                    count = len(wl_domains)
                    expanded_count = len(wl_domains_expanded)
                    self.daemon.whitelist_count = count
                    self.daemon.whitelist_expanded_count = expanded_count
                    session_data["active_domains"] = self.daemon.state.active_domains
                    session_data["session_base_domains"] = self.daemon.session_base_domains
                    session_data["original_dns"] = self.daemon.original_dns
                    session_data["whitelist_count"] = count
                    session_data["whitelist_expanded_count"] = expanded_count
                    self.daemon._atomic_write_json(SESSION_LOCK, session_data)
                    self.daemon.events.emit(Event.SESSION_STARTED)
                    if self.daemon.state.session.session_type == "pomodoro":
                        msg = f"Pomodoro (Whitelist): {count} domains allowed ({expanded_count} total with CDNs) for {self.daemon.state.pomodoro.pomo_total_cycles} cycles."
                    elif self.daemon.state.session.session_type == "rescue":
                        msg = f"Rescue Throne activated: All sites blocked for {duration_minutes} min."
                    elif mode == "ban":
                        if self.daemon.state.session.session_type == "pomodoro":
                            msg = f"Pomodoro (Ban): All sites blocked for {self.daemon.state.pomodoro.pomo_total_cycles} cycles."
                        else:
                            msg = f"Ban mode: All sites blocked for {duration_minutes} min."
                    else:
                        msg = f"Whitelist mode: {count} domains allowed ({expanded_count} total with CDNs) for {duration_minutes} min."
                else:
                    # Build base domain list (for Chrome extension — no subdomain expansion)
                    base_bl = self.daemon.domains_manager.load_lists().get("blacklist", [])
                    if selected_groups:
                        groups = self.daemon.domains_manager.load_groups()
                        for gname in selected_groups:
                            if gname in groups:
                                base_bl.extend(groups[gname])
                    if not base_bl:
                        for sites in DEFAULT_BLOCKLIST.values():
                            base_bl.extend(sites)
                    self.daemon.session_base_domains = list(
                        set(d.strip().lower() for d in base_bl if d.strip() and "." in d)
                    )
                    # Build expanded domain list (for /etc/hosts — needs explicit subdomain entries)
                    self.daemon.state.active_domains = self.daemon.domains_manager.get_blacklist_domains(selected_groups)
                    self.daemon.active_domains_set = set(self.daemon.state.active_domains)
                    session_data["active_domains"] = self.daemon.state.active_domains
                    session_data["session_base_domains"] = self.daemon.session_base_domains
                    self.daemon._atomic_write_json(SESSION_LOCK, session_data)
                    self.daemon.events.emit(Event.SESSION_STARTED)
                    count = len(self.daemon.state.active_domains)
                    if self.daemon.state.session.session_type == "pomodoro":
                        msg = f"Pomodoro (Blacklist): {count} domains blocked for {self.daemon.state.pomodoro.pomo_total_cycles} cycles."
                    else:
                        msg = f"Blacklist mode: {count} domains blocked for {duration_minutes} min."
    
                logging.info(
                    "Session started (%s) — expires %s.",
                    mode,
                    self.daemon.state.session.session_expiry.strftime("%H:%M:%S"),
                )
                # Centralized sound + notification for ALL session starts
                if self.daemon.state.session.session_type == "rescue":
                    self.daemon.notifications_manager.play_sound("rescue")
                    self.daemon.notifications_manager.send_mac_notification(
                        "Rescue Mode",
                        f"All sites blocked for {duration_minutes} min. Stay focused!",
                    )
                else:
                    self.daemon.notifications_manager.play_sound("start")
                    self.daemon.notifications_manager.send_mac_notification(
                        "Session Started",
                        msg,
                        subtitle=self.daemon.state.session.session_expiry.strftime("Expires at %H:%M"),
                    )
                self.daemon.notifications_manager.broadcast_state_changed()
                return {
                    "status": "ok",
                    "message": msg,
                    "mode": mode,
                    "domains_count": count,
                    "expires_at": self.daemon.state.session.session_expiry.strftime("%H:%M:%S"),
                }

    def _request_stop(self, passphrase: str) -> dict:
            with self.daemon.lock:
                if not self.daemon.state.session.active:
                    return {"status": "ok", "message": "No active session."}
                # Rate limit passphrase attempts
                now_mono = time.monotonic()
                if self.daemon._passphrase_attempts >= 5:
                    cooldown = min(60, 2 ** (self.daemon._passphrase_attempts - 5))
                    elapsed = now_mono - self._last_attempt_time
                    if elapsed < cooldown:
                        wait = int(cooldown - elapsed)
                        logging.warning("Passphrase rate-limited. %ds remaining.", wait)
                        return {
                            "status": "error",
                            "message": f"Too many attempts. Wait {wait}s.",
                        }
                self._last_attempt_time = now_mono
                if not self.daemon._verify_passphrase(passphrase):
                    self.daemon._passphrase_attempts += 1
                    logging.warning(
                        "Invalid kill-switch passphrase attempt (#%d).",
                        self.daemon._passphrase_attempts,
                    )
                    return {"status": "error", "message": "Invalid passphrase."}
                # Reset rate limiter on success
                self.daemon._passphrase_attempts = 0
                if self.daemon.state.session.pending_unlock_at:
                    now_mono = get_continuous_time()
                    rem_mono = self.daemon._mono_unlock_end - now_mono
                    if rem_mono > 0:
                        return {
                            "status": "pending",
                            "message": f"Unlock already pending. {int(rem_mono/60)}m {int(rem_mono%60)}s remaining.",
                        }
                self.daemon.state.session.pending_unlock_at = datetime.now() + timedelta(
                    seconds=DELAYED_UNLOCK_S
                )
                self.daemon._mono_unlock_end = get_continuous_time() + DELAYED_UNLOCK_S
                self.daemon._persist_session_lock()
                self.daemon.notifications_manager.play_sound("unlock")
                self.daemon.notifications_manager.broadcast_state_changed()
                unlock_str = self.daemon.state.session.pending_unlock_at.strftime("%H:%M:%S")
                logging.info("Delayed unlock requested — scheduled at %s.", unlock_str)
                return {
                    "status": "pending",
                    "message": f"Unlock request accepted. Releases at {unlock_str} (20-min delay).",
                }

    def _cancel_stop(self) -> dict:
            with self.daemon.lock:
                if not self.daemon.state.session.active:
                    return {"status": "error", "message": "No active session."}
                if not self.daemon.state.session.pending_unlock_at:
                    return {"status": "error", "message": "No unlock pending."}
                self.daemon.state.session.pending_unlock_at = None
                self.daemon._mono_unlock_end = 0.0
                self.daemon._persist_session_lock()
                self.daemon.notifications_manager.broadcast_state_changed()
                logging.info("Pending unlock cancelled. Focus session continues.")
                return {"status": "ok", "message": "Unlock request cancelled. Continuing focus."}

    def _remove_block(self):
            """Remove blocking from /etc/hosts without ending the session."""
            try:
                subprocess.run(
                    ["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5
                )
                self.daemon.events.emit(Event.SESSION_ENDED)
            except Exception as exc:
                logging.error("_remove_block error: %s", exc)

    def _cleanup_session(self):
            """Teardown active session completely."""
            with self.daemon.enforcement_lock:
                logging.info("Cleaning up session (mode=%s)...", self.daemon.state.session.mode)
                self.daemon.notifications_manager.play_sound("end")
                self.daemon.notifications_manager.send_mac_notification(
                    "Session Complete", "Great job! Your ForcedFocus session has ended."
                )
                self.daemon.state.session.active = False  # Ensure firewall logic knows session is ending
                was_whitelist = self.daemon.state.session.mode in ("whitelist", "ban")
    
                try:
                    subprocess.run(
                        ["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5
                    )
                    self.daemon.events.emit(Event.SESSION_ENDED)
                except Exception as exc:
                    logging.error("cleanup_session error: %s", exc)
    
                # Record session history BEFORE resetting state
                try:
                    self.daemon.history_manager.record_session_history()
                except Exception as exc:
                    logging.error("Failed to record session history: %s", exc)
    
    
                if getattr(self, "schedules", []) or self.daemon.recurring_schedules:
                    self.daemon._persist_session_lock()
                else:
                    SESSION_LOCK.unlink(missing_ok=True)
    
                self.daemon.hosts_hash = None
                self.daemon._hosts_stat = None
                self.daemon.state.session.session_expiry = None
                self.daemon.state.session.pending_unlock_at = None
                self.daemon.state.active_domains = []
                self.daemon.active_domains_set = set(self.daemon.state.active_domains)
                self.daemon._ip_backlog.clear()
                self.daemon._whitelisted_ip_backlog.clear()
                self.daemon.session_base_domains = []
                self.daemon.original_dns = {}
                self.daemon.whitelist_resolved = {}
                self.daemon.whitelist_count = 0
                self.daemon.whitelist_expanded_count = 0
                self.daemon.state.session.total_duration_seconds = 0
                self.daemon.state.session.mode = "blacklist"
                self.daemon.state.session.session_type = "standard"
                self.daemon.state.pomodoro.pomo_focus_minutes = 0
                self.daemon.state.pomodoro.pomo_break_minutes = 0
                self.daemon.state.pomodoro.pomo_total_cycles = 0
                self.daemon.state.pomodoro.pomo_current_cycle = 0
    
                self.daemon._reenforce_flag = False
                self.daemon.state.pomodoro.pomo_phase = "focus"
                self.daemon.state.pomodoro.pomo_phase_expiry = None
                self.daemon.state.pomodoro.pomo_phases_tracked_seconds = 0
                self.daemon.state.session.session_group_id = None
                self.daemon._mono_session_end = 0.0
                self.daemon._mono_unlock_end = 0.0
                self.daemon._mono_pomo_phase_end = 0.0
                self.daemon._passphrase_attempts = 0
                self.daemon.state.session.intent = None
                self.daemon.state.session.intent_tasks = []
                self.daemon.state.session.session_groups = []
                self.daemon.notifications_manager.broadcast_state_changed()
                # Do NOT clear schedules on session cleanup!
                logging.info("Session ended. Hosts restored. DNS flushed.")
                # Re-enforce permanent blocks (session cleanup may have modified /etc/hosts)
                # Enforcement manager handles perma_block via SESSION_ENDED event

    def cmd_get_status(self) -> dict:
            with self.daemon.lock:
                now = datetime.now()
                prayers = self.daemon.prayer_manager._get_prayer_times_for_date(now)
                next_prayer = next((p for p in prayers if p["time"] > now), None)
                skipped = self.daemon.settings.get("prayer_skipped", {})
                next_prayer_seconds = None
                if next_prayer:
                    if self.daemon.settings.get("prayer_block_enabled", False):
                        next_prayer_seconds = int(max(0, (next_prayer["time"] - now).total_seconds()))

                schedules_res = []
                recurring_res = self.daemon.schedules_manager.recurring_schedules_response()
                for sch in self.daemon.schedules:
                    schedules_res.append(
                        {
                            "starts_at": sch["start_time"].strftime("%Y-%m-%d %I:%M %p"),
                            "start_time_iso": sch["start_time"].isoformat(),
                            "mode": sch["cmd"].get("mode", "blacklist"),
                            "session_type": sch["cmd"].get("session_type", "standard"),
                            "duration_minutes": sch["cmd"].get("duration_minutes", 120),
                        }
                    )
                if getattr(self.daemon, "prayer_ban_active", ""):
                    prayer_name = self.daemon.prayer_ban_active
                    now = datetime.now()
                    prayers = self.daemon.prayer_manager._get_prayer_times_for_date(now)
                    rem = 0
                    expires_at = ""
                    total_dur = 2400
                    if prayers:
                        mins_after = self.daemon.settings.get("prayer_minutes_after", 30)
                        mins_before = self.daemon.settings.get("prayer_minutes_before", 10)
                        for p in prayers:
                            if p["name"] == prayer_name:
                                end_block = p["time"] + timedelta(minutes=mins_after)
                                rem = int(max(0, (end_block - now).total_seconds()))
                                expires_at = end_block.strftime("%H:%M:%S")
                                total_dur = (mins_before + mins_after) * 60
                                break
                    return {
                        "status": "ok",
                        "active": True,
                        "state": "prayer",
                        "mode": "ban",
                        "expires_at": expires_at,
                        "remaining_seconds": rem,
                        "total_duration_seconds": total_dur,
                        "session_type": "prayer",
                        "intent": f"Prayer Time: {prayer_name}",
                        "schedules": schedules_res,
                        "recurring_schedules": recurring_res,
                        "state_revision": self.daemon.state_revision,
                        "notification_warning": self.daemon.notification_warning,
                        "next_prayer_seconds": next_prayer_seconds,
                    }
                if not self.daemon.state.session.active:
                    return {
                        "status": "ok",
                        "active": False,
                        "state": "idle",
                        "mode": None,
                        "message": "Idle.",
                        "schedules": schedules_res,
                        "recurring_schedules": recurring_res,
                        "state_revision": self.daemon.state_revision,
                        "notification_warning": self.daemon.notification_warning,
                        "next_prayer_seconds": next_prayer_seconds,
                    }
                # C3: Use monotonic time for all remaining-seconds fields
                now_mono = get_continuous_time()
                rem = int(max(0, self.daemon._mono_session_end - now_mono))
                # Safety net: if session is expired but watchdog hasn't cleaned up,
                # trigger cleanup now to prevent stuck sessions
                if (
                    rem <= 0
                    and self.daemon._mono_session_end > 0
                    and now_mono >= self.daemon._mono_session_end
                ):
                    logging.warning(
                        "Status safety-net: session expired but not cleaned up. Forcing cleanup."
                    )
                    self._cleanup_session()
                    return {
                        "status": "ok",
                        "active": False,
                        "state": "idle",
                        "mode": None,
                        "message": "Session expired.",
                        "schedules": schedules_res,
                        "recurring_schedules": recurring_res,
                        "state_revision": self.daemon.state_revision,
                        "notification_warning": self.daemon.notification_warning,
                        "next_prayer_seconds": next_prayer_seconds,
                    }
                result = {
                    "status": "ok",
                    "active": True,
                    "mode": self.daemon.state.session.mode,
                    "expires_at": self.daemon.state.session.session_expiry.strftime("%H:%M:%S"),
                    "remaining_seconds": rem,
                    "total_duration_seconds": self.daemon.state.session.total_duration_seconds,
                    "domains_count": (
                        len(self.daemon.state.active_domains)
                        if self.daemon.state.session.mode == "blacklist"
                        else self.daemon.whitelist_count
                    ),
                    "whitelist_total_count": (
                        None if self.daemon.state.session.mode == "blacklist" else self.daemon.whitelist_expanded_count
                    ),
                    "pending_unlock": (
                        self.daemon.state.session.pending_unlock_at.strftime("%H:%M:%S")
                        if self.daemon.state.session.pending_unlock_at
                        else None
                    ),
                    "pending_unlock_seconds": (
                        int(max(0, self.daemon._mono_unlock_end - now_mono))
                        if self.daemon._mono_unlock_end > 0
                        else 0
                    ),
                    "session_type": self.daemon.state.session.session_type,
                    "schedules": schedules_res,
                    "recurring_schedules": recurring_res,
                    "intent": self.daemon.state.session.intent,
                    "intent_tasks": self.daemon.state.session.intent_tasks,
                    "state_revision": self.daemon.state_revision,
                    "notification_warning": self.daemon.notification_warning,
                    "next_prayer_seconds": next_prayer_seconds,
                }
                if self.daemon.state.session.session_type == "pomodoro":
                    result["pomo_phase"] = self.daemon.state.pomodoro.pomo_phase
                    result["pomo_current_cycle"] = self.daemon.state.pomodoro.pomo_current_cycle
                    result["pomo_total_cycles"] = self.daemon.state.pomodoro.pomo_total_cycles
                    result["pomo_focus_minutes"] = self.daemon.state.pomodoro.pomo_focus_minutes
                    result["pomo_break_minutes"] = self.daemon.state.pomodoro.pomo_break_minutes
                    if self.daemon.state.pomodoro.pomo_phase_expiry:
                        time_str = self.daemon.state.pomodoro.pomo_phase_expiry.strftime("%I:%M %p").lstrip("0")
                        result["pomo_phase_expiry_time"] = time_str
                    if self.daemon._mono_pomo_phase_end > 0:
                        phase_rem = int(max(0, self.daemon._mono_pomo_phase_end - now_mono))
                        result["pomo_phase_remaining"] = phase_rem
                        result["pomo_phase_total"] = (
                            self.daemon.state.pomodoro.pomo_focus_minutes
                            if self.daemon.state.pomodoro.pomo_phase == "focus"
                            else self.daemon.state.pomodoro.pomo_break_minutes
                        ) * 60
                return result

