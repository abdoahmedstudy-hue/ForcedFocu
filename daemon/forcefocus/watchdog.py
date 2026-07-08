import time
import logging
import threading
import subprocess
import concurrent.futures
import hashlib
from datetime import datetime, timedelta

from forcefocus.utils import get_continuous_time
from forcefocus.constants import (
    WATCHDOG_INTERVAL,
    RECURRING_START_GRACE_S,
    PERMA_MARKER_BEGIN,
    PERMA_MARKER_END,
    HOSTS_PATH,
    SESSION_LOCK,
)
from forcefocus.dns_proxy import LocalDNSProxy


class WatchdogManager:
    def __init__(self, daemon):
        self.daemon = daemon

    def _verify_dns_redirect(self):
        """Whitelist mode: verify DNS still points to 127.0.0.1, re-enforce if tampered."""
        try:
            services = self.daemon.enforcement_manager._get_network_services()
            tamper_count = 0
            fix_count = 0

            def verify_and_fix(svc):
                dns_result = subprocess.run(
                    ["networksetup", "-getdnsservers", svc],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return svc, dns_result

            with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(services) if services else 1)) as executor:
                futures = {executor.submit(verify_and_fix, svc): svc for svc in services}
                for future in concurrent.futures.as_completed(futures):
                    svc = futures[future]
                    try:
                        _, dns_result = future.result()
                        if dns_result.returncode != 0:
                            logging.warning(
                                "Failed to get DNS for service '%s': %s",
                                svc,
                                dns_result.stderr if dns_result.stderr else "unknown error",
                            )
                            continue

                        current_dns = dns_result.stdout.strip()
                        if (
                            "127.0.0.1" not in current_dns
                            or "::1" not in current_dns
                        ):
                            logging.warning(
                                "DNS TAMPER on '%s': '%s' — re-enforcing.", svc, current_dns
                            )
                            tamper_count += 1

                            fix_result = subprocess.run(
                                ["networksetup", "-setdnsservers", svc, "127.0.0.1", "::1"],
                                capture_output=True,
                                timeout=5,
                            )

                            if fix_result.returncode == 0:
                                fix_count += 1
                            else:
                                logging.error(
                                    "Failed to fix DNS for service '%s': %s",
                                    svc,
                                    (
                                        fix_result.stderr.decode()
                                        if fix_result.stderr
                                        else "unknown error"
                                    ),
                                )
                    except Exception as e:
                        logging.error("DNS verify error for service '%s': %s", svc, e)

            if tamper_count > 0:
                logging.info(
                    "Fixed DNS tampering for %d/%d affected services.",
                    fix_count,
                    tamper_count,
                )
        except Exception as exc:
            logging.error("DNS verify error: %s", exc)

    def watchdog_loop(self):
        logging.info(
            "Watchdog thread started (interval=%.0fms).", WATCHDOG_INTERVAL * 1000
        )
        self.daemon._wd_dns_counter = 0
        self.daemon._wd_persist_counter = 0
        self.daemon._wd_ip_update_counter = 0
        while True:
            time.sleep(WATCHDOG_INTERVAL)
            try:
                self.watchdog_tick()
            except Exception as exc:
                logging.error("Watchdog tick error (non-fatal): %s", exc, exc_info=True)

    def watchdog_tick(self):
        cmd_to_start = None
        recurring_rule_id = None

        with self.daemon.lock:
            now_mono = get_continuous_time()
            now = datetime.now()

            self._check_prayer_blocks(now)
            
            is_recurring_trigger, cmd_to_start, recurring_rule_id = self._check_recurring_schedules(now, now_mono)
            if not cmd_to_start:
                cmd_to_start = self._check_oneoff_schedules(now)

        if cmd_to_start:
            self._handle_scheduled_start(cmd_to_start, is_recurring_trigger, recurring_rule_id)
            return

        with self.daemon.lock:
            self._check_reenforce_signal()
            self._check_ip_resolution()
            self._check_perma_blocklist(get_continuous_time())
            self._check_config_integrity()

            if not self.daemon.state.session.active:
                return

            now_mono = get_continuous_time()
            self._check_intent_notification(now_mono)
            self._check_persist_lock()

            if self._check_session_expiry(now_mono): return
            if self._check_pomodoro_transitions(now_mono): return

            # Skip tampering checks during break
            if self.daemon.state.session.session_type == "pomodoro" and (
                self.daemon.state.pomodoro.pomo_phase == "break" or 
                (self.daemon.state.pomodoro.pomo_phase == "done" and getattr(self.daemon.state.pomodoro, "pomo_next_phase", "") == "break")
            ):
                return

            self._check_hosts_tamper()
            self._check_firewall_tamper()
            self._check_session_lock_tamper()
            self._check_dns_proxy()
            self._check_restricted_apps_vpn()
            self._check_system_proxies()

    def _check_prayer_blocks(self, now):
        is_prayer, p_name = self.daemon.prayer_manager._evaluate_prayer_block(now)
        current_prayer = getattr(self.daemon, "prayer_ban_active", "")
        if is_prayer:
            if current_prayer != p_name:
                logging.info("Prayer time %s starting. Enforcing absolute network ban.", p_name)
                self.daemon.prayer_ban_active = p_name
                self.daemon.notifications_manager.play_sound("prayer")
                
                if not getattr(self.daemon, "sni_proxy", None):
                    self.daemon.enforcement_manager.start_sni_proxy()
                    
                self.daemon.enforcement_manager._enforce_firewall(True)
                self.daemon.enforcement_manager._enforce_browser_policies(True)
                self.daemon.enforcement_manager._kill_vpn_interfaces()
                self.daemon.enforcement_manager._kill_restricted_apps()
                self.daemon.enforcement_manager._flush_dns()
                self.daemon.notifications_manager.broadcast_state_changed()
        else:
            if current_prayer:
                logging.info("Prayer time %s ended. Restoring normal state.", current_prayer)
                self.daemon.prayer_ban_active = ""
                self.daemon.notifications_manager.play_sound("end")
                if self.daemon.state.session.active:
                    self.daemon.enforcement_manager._enforce_current_mode()
                else:
                    self.daemon.session_manager._remove_block()
                    if getattr(self.daemon, "sni_proxy", None):
                        self.daemon.enforcement_manager.stop_sni_proxy()
                self.daemon.notifications_manager.broadcast_state_changed()

    def _check_recurring_schedules(self, now, now_mono):
        cmd_to_start = None
        is_recurring_trigger = False
        recurring_rule_id = None
        
        if self.daemon.recurring_schedules:
            if now_mono - getattr(self.daemon, "_mono_last_recurring_check", 0) >= 10.0:
                self.daemon._mono_last_recurring_check = now_mono
                
                for r_sch in self.daemon.recurring_schedules:
                    if not r_sch.get("enabled", True):
                        continue
                    start_str = r_sch.get("start_time", "")
                    if not start_str:
                        continue
                    try:
                        shour, sminute = map(int, start_str.split(":"))
                    except Exception:
                        continue
                    
                    duration = r_sch.get("duration_minutes", 120)
                    
                    if now.weekday() in r_sch.get("days_of_week", []):
                        start_dt = now.replace(hour=shour, minute=sminute, second=0, microsecond=0)
                        grace_end = start_dt + timedelta(seconds=RECURRING_START_GRACE_S)
                        
                        if start_dt <= now <= grace_end:
                            trigger_date_str = start_dt.strftime("%Y-%m-%d")
                            if r_sch.get("last_triggered") != trigger_date_str:
                                r_sch["last_triggered"] = trigger_date_str
                                r_sch["last_result"] = "starting"
                                r_sch["last_result_message"] = ""
                                r_sch["updated_at"] = datetime.now().isoformat()
                                cmd_to_start = {
                                    "action": "start",
                                    "duration_minutes": duration,
                                    "mode": r_sch.get("mode", "blacklist"),
                                    "groups": r_sch.get("groups", []),
                                    "session_type": r_sch.get("session_type", "standard"),
                                }
                                if r_sch.get("session_type") == "pomodoro":
                                    cmd_to_start["focus_minutes"] = r_sch.get("focus_minutes", 25)
                                    cmd_to_start["break_minutes"] = r_sch.get("break_minutes", 5)
                                    cmd_to_start["cycles"] = r_sch.get("cycles", 4)
                                is_recurring_trigger = True
                                recurring_rule_id = r_sch.get("id")
                                self.daemon._persist_session_lock()
                                logging.info("Recurring schedule %s triggered.", r_sch.get("id"))
                                break
        return is_recurring_trigger, cmd_to_start, recurring_rule_id

    def _check_oneoff_schedules(self, now):
        cmd_to_start = None
        if self.daemon.schedules:
            while self.daemon.schedules and now >= self.daemon.schedules[0].get("end_time"):
                expired_sch = self.daemon.schedules.pop(0)
                logging.info("Scheduled session (start: %s) expired while asleep and was skipped.", expired_sch["start_time"].strftime("%H:%M"))
            
            if self.daemon.schedules:
                first_sch = self.daemon.schedules[0]
                if first_sch.get("start_time") <= now < first_sch.get("end_time"):
                    sch = self.daemon.schedules.pop(0)
                    cmd_to_start = sch["cmd"]
                    self.daemon._persist_session_lock()
        return cmd_to_start

    def _handle_scheduled_start(self, cmd_to_start, is_recurring_trigger, recurring_rule_id):
        if is_recurring_trigger:
            logging.info("Recurring schedule triggered. Starting session.")
            self.daemon.notifications_manager.play_sound("scheduled")
            self.daemon.notifications_manager.send_mac_notification(
                "Recurring Schedule",
                "Your recurring focus session is starting now.",
            )
        else:
            logging.info("Scheduled time reached. Automatically starting session.")
            self.daemon.notifications_manager.play_sound("scheduled")
            self.daemon.notifications_manager.send_mac_notification(
                "Scheduled Session",
                "Your scheduled focus session is starting now.",
            )
        result = self.daemon.session_manager._start_session(cmd_to_start)
        if is_recurring_trigger and recurring_rule_id:
            with self.daemon.lock:
                for r_sch in self.daemon.recurring_schedules:
                    if r_sch.get("id") == recurring_rule_id:
                        if result.get("status") == "ok":
                            r_sch["last_result"] = "started"
                            r_sch["last_result_message"] = result.get("message", "")
                        else:
                            r_sch["last_result"] = "failed"
                            r_sch["last_result_message"] = result.get("message", "unknown error")
                        r_sch["updated_at"] = datetime.now().isoformat()
                        self.daemon._persist_session_lock()
                        self.daemon.notifications_manager.broadcast_state_changed()
                        break
        if result.get("status") != "ok":
            logging.warning(
                "Scheduled session failed to start: %s",
                result.get("message", "unknown error"),
            )

    def _check_reenforce_signal(self):
        if getattr(self.daemon, "_reenforce_flag", False):
            self.daemon._reenforce_flag = False
            logging.warning(
                "Caught signal — setting re-enforce flag (deferred from handler)."
            )
            if self.daemon.state.session.active and not (
                self.daemon.state.session.session_type == "pomodoro" and (
                    self.daemon.state.pomodoro.pomo_phase == "break" or 
                    (self.daemon.state.pomodoro.pomo_phase == "done" and getattr(self.daemon.state.pomodoro, "pomo_next_phase", "") == "break")
                )
            ):
                logging.info("Signal re-enforce: re-applying block rules.")
                try:
                    self.daemon.enforcement_manager._enforce_current_mode()
                except Exception as exc:
                    logging.error("Signal re-enforce failed: %s", exc)

    def _check_ip_resolution(self):
        self.daemon._wd_ip_update_counter = getattr(self.daemon, "_wd_ip_update_counter", 0) + 1
        if self.daemon._wd_ip_update_counter >= 240:
            self.daemon._wd_ip_update_counter = 0
            if not getattr(self.daemon, "_ip_resolution_running", False):
                self.daemon._ip_resolution_running = True
                threading.Thread(target=self.daemon.enforcement_manager._update_blocked_ips, daemon=True).start()

    def _check_perma_blocklist(self, now_mono_perma):
        if self.daemon.perma_blocklist or getattr(self.daemon, "perma_pending_unlocks", {}):
            expired = []
            for domain, mono_end in list(getattr(self.daemon, "_mono_perma_unlock_ends", {}).items()):
                if now_mono_perma >= mono_end:
                    expired.append(domain)
            if expired:
                for domain in expired:
                    if domain in self.daemon.perma_blocklist:
                        self.daemon.perma_blocklist.remove(domain)
                    self.daemon.perma_pending_unlocks.pop(domain, None)
                    self.daemon._mono_perma_unlock_ends.pop(domain, None)
                    logging.info("Permanent unblock completed: '%s' removed from blocklist.", domain)
                self.daemon._save_perma_state()
                self.daemon.enforcement_manager._enforce_perma_block()
                self.daemon.notifications_manager.broadcast_state_changed()

            self.daemon._wd_perma_counter = getattr(self.daemon, "_wd_perma_counter", 0) + 1
            if self.daemon._wd_perma_counter >= 20:
                self.daemon._wd_perma_counter = 0
                if self.daemon.perma_blocklist:
                    if not getattr(self.daemon.enforcement_manager, "_perma_hosts_hash", None):
                        logging.warning("Permanent blocklist active but hosts hash is missing. Enforcing.")
                        self.daemon.enforcement_manager._enforce_perma_block()
                    else:
                        try:
                            st = HOSTS_PATH.stat()
                            current_stat = (st.st_mtime, st.st_size)
                            if getattr(self.daemon.enforcement_manager, "_perma_hosts_stat", None) is not None and current_stat == self.daemon.enforcement_manager._perma_hosts_stat:
                                pass
                            else:
                                content = HOSTS_PATH.read_text()
                                lines = content.split("\n")
                                normalized_lines = [line.rstrip("\r") for line in lines]
                                
                                begin_idx, end_idx, tampered = -1, -1, False
                                for idx, line in enumerate(normalized_lines):
                                    if PERMA_MARKER_BEGIN in line:
                                        if begin_idx != -1: tampered = True; break
                                        begin_idx = idx
                                    if PERMA_MARKER_END in line:
                                        if end_idx != -1: tampered = True; break
                                        end_idx = idx
                                
                                if tampered or begin_idx == -1 or end_idx == -1 or begin_idx >= end_idx:
                                    logging.warning("PERMANENT BLOCK TAMPER DETECTED. Re-enforcing.")
                                    self.daemon.enforcement_manager._enforce_perma_block()
                                else:
                                    block_content = "\n".join(normalized_lines[begin_idx : end_idx + 1])
                                    current_hash = hashlib.sha256(block_content.encode("utf-8")).hexdigest()
                                    if current_hash != self.daemon.enforcement_manager._perma_hosts_hash:
                                        logging.warning("PERMANENT BLOCK TAMPER DETECTED (content mismatch). Re-enforcing.")
                                        self.daemon.enforcement_manager._enforce_perma_block()
                                    else:
                                        self.daemon.enforcement_manager._perma_hosts_stat = current_stat
                        except Exception as exc:
                            logging.error("Watchdog perma hosts check error: %s", exc)

    def _check_intent_notification(self, now_mono):
        if self.daemon.state.session.intent and getattr(self.daemon, "settings", {}).get("intent_notification_enabled", True):
            interval = int(getattr(self.daemon, "settings", {}).get("intent_notification_interval", 15)) * 60
            last_notif = getattr(self.daemon, "_mono_last_intent_notif", 0)
            if last_notif == 0:
                self.daemon._mono_last_intent_notif = now_mono
            elif now_mono - last_notif >= interval:
                self.daemon._mono_last_intent_notif = now_mono
                self.daemon.notifications_manager.send_mac_notification("Focus Reminder", f"Target: {self.daemon.state.session.intent}")

    def _check_persist_lock(self):
        self.daemon._wd_persist_counter += 1
        if self.daemon._wd_persist_counter >= 120:
            self.daemon._wd_persist_counter = 0
            self.daemon._persist_session_lock()

    def _check_session_expiry(self, now_mono):
        if not self.daemon.state.session.active:
            return False
        if getattr(self.daemon, "_mono_session_end", 0) > 0 and now_mono >= getattr(self.daemon, "_mono_session_end", 0):
            logging.info("Session timer expired.")
            self.daemon.session_manager._cleanup_session()
            return True
        if getattr(self.daemon, "_mono_unlock_end", 0) > 0 and now_mono >= getattr(self.daemon, "_mono_unlock_end", 0):
            logging.info("Delayed unlock period reached. Unlocking.")
            self.daemon.session_manager._cleanup_session()
            return True
        return False

    def _check_pomodoro_transitions(self, now_mono):
        if self.daemon.state.session.session_type == "pomodoro" and getattr(self.daemon, "_mono_pomo_phase_end", 0) > 0:
            if now_mono >= getattr(self.daemon, "_mono_pomo_phase_end", 0):
                self.daemon.session_manager._transition_pomodoro_phase()
                return True
        return False

    def _check_hosts_tamper(self):
        if not self.daemon.state.session.active:
            return
        if self.daemon.state.session.mode not in ("whitelist", "ban"):
            try:
                st = HOSTS_PATH.stat()
                current_stat = (st.st_mtime, st.st_size)
                if getattr(self.daemon, "_hosts_stat", None) is not None and current_stat == getattr(self.daemon, "_hosts_stat", None):
                    pass
                else:
                    current = HOSTS_PATH.read_text()
                    h = hashlib.sha256(current.encode()).hexdigest()
                    if h != getattr(self.daemon, "hosts_hash", None):
                        logging.warning("HOSTS TAMPER DETECTED. Re-enforcing.")
                        self.daemon.enforcement_manager._enforce_block()
                    else:
                        self.daemon._hosts_stat = current_stat
            except Exception as exc:
                logging.error("Watchdog hosts error: %s", exc)

    def _check_firewall_tamper(self):
        if self.daemon._wd_persist_counter % 20 == 0:
            try:
                res = subprocess.run(["pfctl", "-a", "forcefocus", "-s", "rules"], capture_output=True, text=True, timeout=2)
                if "443" not in res.stdout or "udp" not in res.stdout:
                    logging.warning("FIREWALL TAMPER DETECTED. Rules: '%s'. Re-enforcing.", res.stdout.strip())
                    upstream = self.daemon.dns_proxy.upstream_dns if (self.daemon.state.session.mode in ("whitelist", "ban") and getattr(self.daemon, "dns_proxy", None)) else None
                    self.daemon.enforcement_manager._enforce_firewall(True, upstream_dns=upstream)
            except Exception as exc:
                logging.error("Watchdog firewall error: %s", exc)

    def _check_session_lock_tamper(self):
        if not SESSION_LOCK.exists():
            logging.warning("SESSION.LOCK DELETED. Re-creating from memory.")
            self.daemon._persist_session_lock()
            if self.daemon.state.session.mode in ("whitelist", "ban"):
                self.daemon.enforcement_manager._enforce_whitelist()
            else:
                self.daemon.enforcement_manager._enforce_block()

    def _check_config_integrity(self):
        self.daemon._wd_config_counter = getattr(self.daemon, "_wd_config_counter", 0) + 1
        if self.daemon._wd_config_counter >= 20:  # Check every 5 seconds
            self.daemon._wd_config_counter = 0
            
            # 1. Check ks_hash
            from forcefocus.constants import KS_HASH_FILE, PERMA_BLOCK_FILE, LISTS_FILE
            if getattr(self.daemon, "_cached_ks_hash", None):
                try:
                    current_mtime = KS_HASH_FILE.stat().st_mtime if KS_HASH_FILE.exists() else 0
                    if current_mtime != getattr(self.daemon, "_cached_ks_hash_mtime", 0):
                        logging.warning("CONFIG TAMPER DETECTED: ks_hash modified or deleted externally. Restoring.")
                        # Restore from memory
                        if KS_HASH_FILE.exists():
                            subprocess.run(["chflags", "nouchg", str(KS_HASH_FILE)], capture_output=True)
                        self.daemon._atomic_write_json(KS_HASH_FILE, self.daemon._cached_ks_hash)
                        self.daemon._cached_ks_hash_mtime = KS_HASH_FILE.stat().st_mtime
                        subprocess.run(["chflags", "uchg", str(KS_HASH_FILE)], capture_output=True)
                except Exception as exc:
                    logging.error("ks_hash integrity check failed: %s", exc)
                    
            # 2. Check perma_blocklist.json
            cached_perma_mtime = getattr(self.daemon, "_cached_perma_mtime", None)
            if hasattr(self.daemon, "perma_blocklist") and cached_perma_mtime is not None:
                try:
                    current_mtime = PERMA_BLOCK_FILE.stat().st_mtime if PERMA_BLOCK_FILE.exists() else 0
                    if current_mtime != cached_perma_mtime:
                        logging.warning("CONFIG TAMPER DETECTED: perma_blocklist.json modified or deleted externally. Restoring.")
                        self.daemon.domains_manager._save_perma_state()
                except Exception as exc:
                    logging.error("perma_blocklist integrity check failed: %s", exc)

            # 3. Check lists.json
            cached_lists = getattr(self.daemon, "_cached_lists", None)
            cached_lists_mtime = getattr(self.daemon, "_cached_lists_mtime", None)
            if cached_lists is not None and cached_lists_mtime is not None and cached_lists_mtime != 0.0:
                try:
                    current_mtime = LISTS_FILE.stat().st_mtime if LISTS_FILE.exists() else 0
                    if current_mtime != cached_lists_mtime:
                        logging.warning("CONFIG TAMPER DETECTED: lists.json modified or deleted externally. Restoring.")
                        self.daemon.domains_manager.save_lists(cached_lists)
                except Exception as exc:
                    logging.error("lists.json integrity check failed: %s", exc)

    def _check_dns_proxy(self):
        if self.daemon.state.session.mode in ("whitelist", "ban"):
            is_break = self.daemon.state.session.session_type == "pomodoro" and (
                self.daemon.state.pomodoro.pomo_phase == "break" or 
                (self.daemon.state.pomodoro.pomo_phase == "done" and getattr(self.daemon.state.pomodoro, "pomo_next_phase", "") == "break")
            )
            if getattr(self.daemon, "dns_proxy", None) and not self.daemon.dns_proxy.is_alive() and not is_break:
                logging.warning("DNS Proxy thread died. Restarting.")
                self.daemon.dns_proxy = LocalDNSProxy(self.daemon)
                self.daemon.dns_proxy.start()

            self.daemon._wd_dns_counter += 1
            if self.daemon._wd_dns_counter >= 120:
                self.daemon._wd_dns_counter = 0
                self._verify_dns_redirect()

    def _check_restricted_apps_vpn(self):
        if self.daemon._wd_persist_counter % 40 == 0:
            self.daemon.enforcement_manager._kill_restricted_apps()
            self.daemon.enforcement_manager._kill_vpn_interfaces()

    def _check_system_proxies(self):
        self.daemon._wd_proxy_counter = getattr(self.daemon, "_wd_proxy_counter", 0) + 1
        if self.daemon._wd_proxy_counter >= 240:
            self.daemon._wd_proxy_counter = 0
            self.daemon.enforcement_manager._reset_system_proxies()
