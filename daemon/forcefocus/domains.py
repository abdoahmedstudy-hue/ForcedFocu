import json
import re
import logging
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse
from forcefocus.constants import LISTS_FILE, GROUPS_FILE, COMMON_PREFIXES, DEFAULT_BLOCKLIST, CDN_INFRASTRUCTURE_DOMAINS, SITE_BUNDLES, PERMA_BLOCK_FILE, PERMA_UNLOCK_DELAY_S
from forcefocus.events import Event
from forcefocus.utils import get_continuous_time

class DomainsManager:
    def __init__(self, daemon):
        self.daemon = daemon

    def load_lists(self) -> dict:
        with self.daemon.lock:
            try:
                mtime = LISTS_FILE.stat().st_mtime
            except FileNotFoundError:
                return {"blacklist": [], "whitelist": []}

            if getattr(self.daemon, '_cached_lists', None) is not None and mtime == getattr(self.daemon, '_cached_lists_mtime', None):
                return {
                    k: v.copy() if isinstance(v, list) else v
                    for k, v in self.daemon._cached_lists.items()
                }

            try:
                self.daemon._cached_lists = json.loads(LISTS_FILE.read_text())
                self.daemon._cached_lists_mtime = mtime
                return {
                    k: v.copy() if isinstance(v, list) else v
                    for k, v in self.daemon._cached_lists.items()
                }
            except Exception:
                return {"blacklist": [], "whitelist": []}

    def save_lists(self, lists: dict):
        self.daemon._atomic_write_json(LISTS_FILE, lists, indent=2)
        self.daemon.notifications_manager.broadcast_state_changed()

    def load_groups(self) -> dict:
        with self.daemon.lock:
            try:
                mtime = GROUPS_FILE.stat().st_mtime
            except FileNotFoundError:
                return {}

            if getattr(self.daemon, '_cached_groups', None) is not None and mtime == getattr(self.daemon, '_cached_groups_mtime', None):
                return {
                    k: v.copy() if isinstance(v, list) else v
                    for k, v in self.daemon._cached_groups.items()
                }

            try:
                self.daemon._cached_groups = json.loads(GROUPS_FILE.read_text())
                self.daemon._cached_groups_mtime = mtime
                return {
                    k: v.copy() if isinstance(v, list) else v
                    for k, v in self.daemon._cached_groups.items()
                }
            except Exception:
                return {}

    def save_groups(self, groups: dict):
        self.daemon._atomic_write_json(GROUPS_FILE, groups, indent=2)
        self.daemon.notifications_manager.broadcast_state_changed()

    @staticmethod
    def extract_domain(raw_input: str) -> str:
        domain = raw_input.strip().lower()
        if not domain:
            return ""
        if "://" in domain:
            parsed = urlparse(domain)
            domain = parsed.netloc or parsed.path
        else:
            domain = domain.split("/")[0]
        domain = domain.split(":")[0]
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    @staticmethod
    def validate_domain(domain: str) -> bool:
        if not domain or len(domain) > 253:
            return False
        if any(c in domain for c in "\n\r\t \\/"):
            return False
        if "." not in domain:
            return False
        if domain[0] in ".-" or domain[-1] in ".-":
            return False
        if not re.match(r"^[a-z0-9]([a-z0-9\-\.]*[a-z0-9])?$", domain):
            return False
        if ".." in domain:
            return False
        return True

    def cmd_get_lists(self) -> dict:
        lists = self.load_lists()
        return {"status": "ok", "lists": lists}

    def cmd_add_domain(self, cmd: dict) -> dict:
        list_name = cmd.get("list", "blacklist")
        domain = self.extract_domain(cmd.get("domain", ""))
        if not self.validate_domain(domain):
            return {"status": "error", "message": "Invalid domain."}
        if list_name not in ("blacklist", "whitelist"):
            return {"status": "error", "message": "Invalid list name."}

        with self.daemon.lock:
            if self.daemon.state.session.active:
                return {"status": "error", "message": "Cannot modify lists during active session."}
            lists = self.load_lists()
            if domain not in lists[list_name]:
                lists[list_name].append(domain)
                self.save_lists(lists)
            return {"status": "ok", "message": f"Added {domain} to {list_name}.", "lists": lists}

    def cmd_add_domains(self, cmd: dict) -> dict:
        list_name = cmd.get("list", "blacklist")
        domains_raw = cmd.get("domains", [])
        if list_name not in ("blacklist", "whitelist"):
            return {"status": "error", "message": "Invalid list name."}

        with self.daemon.lock:
            if self.daemon.state.session.active:
                return {"status": "error", "message": "Cannot modify lists during active session."}
            lists = self.load_lists()
            domains = []
            for d in domains_raw:
                extracted = self.extract_domain(d)
                if self.validate_domain(extracted):
                    domains.append(extracted)
            
            added = 0
            for domain in domains:
                if domain not in lists[list_name]:
                    lists[list_name].append(domain)
                    added += 1
            self.save_lists(lists)
            return {"status": "ok", "message": f"Added {added} domains to {list_name}.", "lists": lists}

    def cmd_remove_domain(self, cmd: dict) -> dict:
        list_name = cmd.get("list", "blacklist")
        domain = self.extract_domain(cmd.get("domain", ""))
        if list_name not in ("blacklist", "whitelist"):
            return {"status": "error", "message": "Invalid list name."}

        with self.daemon.lock:
            if self.daemon.state.session.active:
                return {"status": "error", "message": "Cannot modify lists during active session."}
            lists = self.load_lists()
            if domain in lists[list_name]:
                lists[list_name].remove(domain)
                self.save_lists(lists)
            return {"status": "ok", "message": f"Removed {domain} from {list_name}.", "lists": lists}

    def cmd_get_groups(self) -> dict:
        return {"status": "ok", "groups": self.load_groups()}

    def cmd_add_group(self, cmd: dict) -> dict:
        name = cmd.get("name", "").strip()
        domains = cmd.get("domains", [])
        if not name:
            return {"status": "error", "message": "Group name is required."}
        with self.daemon.lock:
            if self.daemon.state.session.active:
                return {"status": "error", "message": "Cannot modify groups during active session."}
            groups = self.load_groups()
            valid_domains = [d.strip().lower() for d in domains if self.validate_domain(d.strip().lower())]
            if not valid_domains and domains:
                return {"status": "error", "message": "None of the provided domains are valid."}
            groups[name] = valid_domains
            self.save_groups(groups)
            return {"status": "ok", "message": f"Group '{name}' saved.", "groups": groups}

    def cmd_remove_group(self, cmd: dict) -> dict:
        name = cmd.get("name", "").strip()
        if not name:
            return {"status": "error", "message": "Group name is required."}
        with self.daemon.lock:
            if self.daemon.state.session.active:
                return {"status": "error", "message": "Cannot modify groups during active session."}
            groups = self.load_groups()
            if name in groups:
                del groups[name]
                self.save_groups(groups)
                return {"status": "ok", "message": f"Group '{name}' removed.", "groups": groups}
            return {"status": "error", "message": f"Group '{name}' not found."}

    def get_blacklist_domains(self, selected_groups: list[str] = None) -> list[str]:
        lists = self.load_lists()
        bl = lists.get("blacklist", [])

        if selected_groups:
            groups = self.load_groups()
            for gname in selected_groups:
                if gname in groups:
                    bl.extend(groups[gname])

        if not bl:
            for sites in DEFAULT_BLOCKLIST.values():
                bl.extend(sites)

        expanded = set()
        for d in bl:
            domain = d.strip().lower()
            if "." not in domain:
                continue

            expanded.add(domain)

            if "youtube.com" in domain or "youtu.be" in domain:
                for asset in ["googlevideo.com", "ytimg.com", "ggpht.com"]:
                    expanded.add(asset)
                    for prefix in ["www.", "r1---", "r2---", "r3---", "r4---", "r5---"]:
                        expanded.add(prefix + asset)

            if domain.startswith(COMMON_PREFIXES):
                for prefix in COMMON_PREFIXES:
                    if not domain.startswith(prefix):
                        expanded.add(prefix + domain)
            else:
                for prefix in COMMON_PREFIXES:
                    expanded.add(prefix + domain)
        return sorted(expanded)

    def expand_whitelist_domains(self, domains: list[str]) -> list[str]:
        expanded = set()
        expanded.update(CDN_INFRASTRUCTURE_DOMAINS)

        for d in domains:
            domain = d.strip().lower()
            if not domain:
                continue

            expanded.add(domain)

            root = domain
            if root.startswith("www."):
                root = root[4:]

            if root in SITE_BUNDLES:
                for bundle_dom in SITE_BUNDLES[root]:
                    expanded.add(bundle_dom)

        before = len(set(d.strip().lower() for d in domains if d.strip()))
        after = len(expanded)
        if after > before:
            logging.info("Whitelist auto-expanded: %d user domains -> %d total domains (added %d CDN/bundle domains)", before, after, after - before)

        return sorted(expanded)



    def _load_perma_state(self):
        """Load permanent blocklist from disk into memory, restoring pending unlocks."""
        try:
            if not PERMA_BLOCK_FILE.exists():
                return
            data = json.loads(PERMA_BLOCK_FILE.read_text())
            self.daemon.perma_blocklist = data.get("domains", [])
            now_mono = get_continuous_time()
            raw_pending = data.get("pending_unlocks", {})
            for domain, info in raw_pending.items():
                try:
                    unlocks_at = datetime.fromisoformat(info["unlocks_at"])
                    remaining = (unlocks_at - datetime.now()).total_seconds()
                    if remaining <= 0:
                        # Timer expired during downtime — remove domain
                        if domain in self.daemon.perma_blocklist:
                            self.daemon.perma_blocklist.remove(domain)
                        logging.info(
                            "Permanent unblock for '%s' completed during downtime.", domain
                        )
                    else:
                        self.daemon.perma_pending_unlocks[domain] = unlocks_at
                        self.daemon._mono_perma_unlock_ends[domain] = now_mono + remaining
                except (KeyError, ValueError) as exc:
                    logging.warning(
                        "Invalid pending unlock entry for '%s': %s", domain, exc
                    )
            # Save cleaned state back
            self._save_perma_state()
            if self.daemon.perma_blocklist:
                logging.info(
                    "Permanent blocklist loaded: %d domains, %d pending unlocks.",
                    len(self.daemon.perma_blocklist),
                    len(self.daemon.perma_pending_unlocks),
                )
        except Exception as exc:
            logging.error("Failed to load permanent blocklist: %s", exc)


    def _save_perma_state(self):
        """Persist permanent blocklist and pending unlocks to disk."""
        pending = {}
        for domain, unlocks_at in self.daemon.perma_pending_unlocks.items():
            pending[domain] = {
                "requested_at": (
                    unlocks_at - timedelta(seconds=PERMA_UNLOCK_DELAY_S)
                ).isoformat(),
                "unlocks_at": unlocks_at.isoformat(),
            }
        data = {"domains": self.daemon.perma_blocklist, "pending_unlocks": pending}
        try:
            self.daemon._atomic_write_json(PERMA_BLOCK_FILE, data, indent=2)
        except Exception as exc:
            logging.error("Failed to save permanent blocklist: %s", exc)








    def cmd_get_perma_blocklist(self) -> dict:
        """Return permanent blocklist and pending unlock status."""
        now_mono = get_continuous_time()
        pending = {}
        for domain, unlocks_at in self.daemon.perma_pending_unlocks.items():
            mono_end = self.daemon._mono_perma_unlock_ends.get(domain, 0)
            remaining = int(max(0, mono_end - now_mono))
            pending[domain] = {
                "unlocks_at": unlocks_at.strftime("%H:%M:%S"),
                "remaining_seconds": remaining,
            }
        return {
            "status": "ok",
            "domains": self.daemon.perma_blocklist,
            "pending_unlocks": pending,
        }

    def cmd_add_perma_block(self, cmd: dict) -> dict:
        """Add domain(s) to the permanent blocklist. Can be done anytime."""
        domains_raw = cmd.get("domains", [])
        single = cmd.get("domain", "")
        if single:
            domains_raw = [single]
        if not domains_raw:
            return {"status": "error", "message": "No domains provided."}
        with self.daemon.lock:
            added = 0
            for d in domains_raw:
                domain = self.extract_domain(d)
                if not self.validate_domain(domain):
                    continue
                if domain not in self.daemon.perma_blocklist:
                    self.daemon.perma_blocklist.append(domain)
                    added += 1
            if added == 0:
                return {"status": "error", "message": "No valid new domains to add."}
            self._save_perma_state()
            self.daemon.events.emit(Event.PERMA_BLOCK_UPDATED)
            self.daemon.notifications_manager.broadcast_state_changed()
            logging.info("Added %d domain(s) to permanent blocklist.", added)
            return {
                "status": "ok",
                "message": f"Added {added} domain(s) to permanent blocklist.",
                "domains": self.daemon.perma_blocklist,
            }

    def cmd_request_perma_unblock(self, cmd: dict) -> dict:
        """Request removal of a domain from permanent blocklist (passphrase + 30m delay)."""
        domain = self.extract_domain(cmd.get("domain", ""))
        passphrase = cmd.get("key", "")
        if not domain:
            return {"status": "error", "message": "No domain specified."}
        with self.daemon.lock:
            if domain not in self.daemon.perma_blocklist:
                return {"status": "error", "message": f"'{domain}' is not permanently blocked."}
            # Check if already pending
            if domain in self.daemon.perma_pending_unlocks:
                now_mono = get_continuous_time()
                mono_end = self.daemon._mono_perma_unlock_ends.get(domain, 0)
                rem = int(max(0, mono_end - now_mono))
                if rem > 0:
                    return {
                        "status": "pending",
                        "message": f"Unblock already pending. {rem // 60}m {rem % 60}s remaining.",
                        "remaining_seconds": rem,
                    }
            # Rate limit passphrase attempts (decoupled from session rate limiter)
            now_mono_rl = time.monotonic()
            if self.daemon._perma_passphrase_attempts >= 5:
                cooldown = min(60, 2 ** (self.daemon._perma_passphrase_attempts - 5))
                elapsed = now_mono_rl - self.daemon._perma_last_attempt_time
                if elapsed < cooldown:
                    wait = int(cooldown - elapsed)
                    return {
                        "status": "error",
                        "message": f"Too many attempts. Wait {wait}s.",
                    }
            self.daemon._perma_last_attempt_time = now_mono_rl
            if not self.daemon._verify_passphrase(passphrase):
                self.daemon._perma_passphrase_attempts += 1
                logging.warning(
                    "Invalid passphrase for permanent unblock attempt (#%d).",
                    self.daemon._perma_passphrase_attempts,
                )
                return {"status": "error", "message": "Invalid passphrase."}
            # Reset rate limiter on success
            self.daemon._perma_passphrase_attempts = 0
            # Start 30-minute cooldown
            unlocks_at = datetime.now() + timedelta(seconds=PERMA_UNLOCK_DELAY_S)
            self.daemon.perma_pending_unlocks[domain] = unlocks_at
            self.daemon._mono_perma_unlock_ends[domain] = (
                get_continuous_time() + PERMA_UNLOCK_DELAY_S
            )
            self._save_perma_state()
            self.daemon.notifications_manager.broadcast_state_changed()
            unlock_str = unlocks_at.strftime("%H:%M:%S")
            logging.info(
                "Permanent unblock requested for '%s' — unlocks at %s.",
                domain,
                unlock_str,
            )
            return {
                "status": "pending",
                "message": f"Unblock request accepted. '{domain}' will be removed at {unlock_str} (30-min delay).",
                "unlocks_at": unlock_str,
                "remaining_seconds": PERMA_UNLOCK_DELAY_S,
            }

    def cmd_cancel_perma_unblock(self, cmd: dict) -> dict:
        """Cancel a pending permanent unblock — re-lock the domain immediately."""
        domain = self.extract_domain(cmd.get("domain", ""))
        if not domain:
            return {"status": "error", "message": "No domain specified."}
        with self.daemon.lock:
            if domain not in self.daemon.perma_pending_unlocks:
                return {
                    "status": "error",
                    "message": f"No pending unblock for '{domain}'.",
                }
            del self.daemon.perma_pending_unlocks[domain]
            self.daemon._mono_perma_unlock_ends.pop(domain, None)
            self._save_perma_state()
            self.daemon.notifications_manager.broadcast_state_changed()
            logging.info("Cancelled permanent unblock for '%s'.", domain)
            return {
                "status": "ok",
                "message": f"Unblock cancelled. '{domain}' remains permanently blocked.",
            }

    def cmd_get_session_domains(self) -> dict:
        """Return the effective domain list for the current session.
        For blacklist mode: returns base (un-expanded) domains because Chrome's
        urlFilter '||domain' already handles subdomain matching natively.
        The /etc/hosts-expanded list would exceed Chrome's 5000 rule limit.
        For whitelist mode: returns the CDN-expanded domain list because Chrome
        needs to know about all allowed CDN/infrastructure domains.
        """
        with self.daemon.lock:
            if not self.daemon.state.session.active:
                return {"status": "ok", "domains": [], "mode": None}
            if self.daemon.state.session.mode == "blacklist":
                return {
                    "status": "ok",
                    "domains": self.daemon.session_base_domains,
                    "mode": self.daemon.state.session.mode,
                }
            return {"status": "ok", "domains": self.daemon.state.active_domains, "mode": self.daemon.state.session.mode}
