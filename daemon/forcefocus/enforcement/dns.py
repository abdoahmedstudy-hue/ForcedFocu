import os
import subprocess
import logging
import threading
import json
import time
import socket
import tempfile
import plistlib
import ssl
import hashlib
import concurrent.futures
from pathlib import Path
from datetime import datetime
from forcefocus.constants import *

class DNSMixin:
    def _enforce_perma_block(self, **kwargs):
            """Write permanent block entries to /etc/hosts using PERMA markers (independent from session)."""
            with self.daemon.enforcement_lock:
                if not self.daemon.perma_blocklist:
                    # No domains to block — remove any stale permanent markers
                    try:
                        subprocess.run(
                            ["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5
                        )
                        content = self._strip_perma_block(HOSTS_PATH.read_text())
                        HOSTS_PATH.write_text(content)
                        subprocess.run(
                            ["chflags", "uchg", str(HOSTS_PATH)], capture_output=True, timeout=5
                        )
                        self._perma_hosts_hash = None
                        try:
                            st = HOSTS_PATH.stat()
                            self._perma_hosts_stat = (st.st_mtime, st.st_size)
                        except Exception:
                            self._perma_hosts_stat = None
                        is_break = self.daemon.state.session.session_type == "pomodoro" and (
                            self.daemon.state.pomodoro.pomo_phase == "break" or 
                            (self.daemon.state.pomodoro.pomo_phase == "done" and getattr(self.daemon.state.pomodoro, "pomo_next_phase", "") == "break")
                        )
                        if self.daemon.state.session.active and not is_break:
                            self._enforce_firewall(True, upstream_dns=self.daemon.dns_proxy.upstream_dns if self.daemon.dns_proxy else None)
                        else:
                            self._enforce_firewall(False)
                    except Exception as exc:
                        logging.error("_enforce_perma_block (cleanup) failed: %s", exc)
                        self._perma_hosts_stat = None
                    return
        
                try:
                    subprocess.run(
                        ["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5
                    )
                    content = self._strip_perma_block(HOSTS_PATH.read_text())
                    block = self._build_perma_block()
                    content = content.rstrip("\n") + "\n\n" + block + "\n"
                    HOSTS_PATH.write_text(content)
                    subprocess.run(
                        ["chflags", "uchg", str(HOSTS_PATH)], capture_output=True, timeout=5
                    )
                    self._perma_hosts_hash = hashlib.sha256(block.encode()).hexdigest()
                    try:
                        st = HOSTS_PATH.stat()
                        self._perma_hosts_stat = (st.st_mtime, st.st_size)
                    except Exception:
                        self._perma_hosts_stat = None
                    self._flush_dns()
                    self._enforce_firewall(True, upstream_dns=self.daemon.dns_proxy.upstream_dns if self.daemon.dns_proxy else None)
                    logging.info(
                        "Permanent block enforced: %d domains in /etc/hosts.",
                        len(self.daemon.perma_blocklist)
                    )
                except Exception as exc:
                    logging.error("_enforce_perma_block failed: %s", exc)
                    self._perma_hosts_stat = None

    def _build_perma_block(self) -> str:
            """Build the /etc/hosts block for permanently blocked domains."""
            lines = [
                PERMA_MARKER_BEGIN,
                "# Mode: PERMANENT BLOCK (always active)",
            ]
            # Expand domains with common subdomains (same pattern as session blacklist)
            expanded = set()
            for d in self.daemon.perma_blocklist:
                domain = d.strip().lower()
                if not domain or "." not in domain:
                    continue
                expanded.add(domain)
                # Subdomain expansion for broader coverage
                if domain.startswith(COMMON_PREFIXES):
                    for prefix in COMMON_PREFIXES:
                        if not domain.startswith(prefix):
                            expanded.add(prefix + domain)
                else:
                    for prefix in COMMON_PREFIXES:
                        expanded.add(prefix + domain)
    
            for domain in sorted(expanded):
                lines.append(f"127.0.0.1\t{domain}")
                lines.append(f"::1\t\t{domain}")
            lines.append(PERMA_MARKER_END)
            return "\n".join(lines)

    @staticmethod
    def _strip_perma_block(content: str) -> str:
            """Remove permanent block markers from hosts content (leaves session markers intact)."""
            result = []
            inside = False
            for line in content.split("\n"):
                if PERMA_MARKER_BEGIN in line:
                    inside = True
                    continue
                if PERMA_MARKER_END in line:
                    inside = False
                    continue
                if not inside:
                    result.append(line)
            while result and result[-1].strip() == "":
                result.pop()
            return "\n".join(result)

    def _enforce_block(self):
            """Blacklist mode: inject 127.0.0.1 entries into /etc/hosts."""
            with self.daemon.enforcement_lock:
                try:
                    result = subprocess.run(
                        ["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5
                    )
                    if result.returncode != 0:
                        logging.warning(
                            "chflags nouchg failed with code %d: %s",
                            result.returncode,
                            result.stderr.decode() if result.stderr else "unknown error",
                        )
    
                    content = self._strip_block(HOSTS_PATH.read_text())
                    block = self._build_blacklist_block()
                    content = content.rstrip("\n") + "\n\n" + block + "\n"
                    HOSTS_PATH.write_text(content)
    
                    result = subprocess.run(
                        ["chflags", "uchg", str(HOSTS_PATH)], capture_output=True, timeout=5
                    )
                    if result.returncode != 0:
                        logging.warning(
                            "chflags uchg failed with code %d: %s",
                            result.returncode,
                            result.stderr.decode() if result.stderr else "unknown error",
                        )
    
                    self._enforce_firewall(True)
                    self._enforce_browser_policies(True)
                    self._reset_system_proxies()
                    self._kill_vpn_interfaces()
                    self._kill_restricted_apps()
                    self._clear_browser_caches()
                    self._flush_dns()
                    self.daemon.hosts_hash = hashlib.sha256(content.encode()).hexdigest()
                    # ⚡ Cache stat for cheap watchdog pre-check (avoids full read+hash every 250ms)
                    try:
                        st = HOSTS_PATH.stat()
                        self.daemon._hosts_stat = (st.st_mtime, st.st_size)
                    except Exception:
                        self.daemon._hosts_stat = None
                except Exception as exc:
                    logging.error("Block enforcement failed: %s", exc)

    def _build_blacklist_block(self) -> str:
            lines = [
                MARKER_BEGIN,
                "# Mode: BLACKLIST",
                f"# Expires: {self.daemon.state.session.session_expiry.isoformat()}",
            ]
            for domain in self.daemon.state.active_domains:
                lines.append(f"127.0.0.1\t{domain}")
                lines.append(f"::1\t\t{domain}")
            # Block DNS-over-HTTPS providers to prevent browser bypass
            lines.append("# DoH providers (anti-bypass)")
            for domain in DOH_BLOCK_DOMAINS:
                lines.append(f"127.0.0.1\t{domain}")
                lines.append(f"::1\t\t{domain}")
            lines.append(MARKER_END)
            return "\n".join(lines)

    def _get_network_services(self) -> list[str]:
            """Get all network service names, with 60s cache to reduce subprocess overhead.
    
            We include *-prefixed services because they can become active
            mid-session (e.g., plugging in Ethernet).
            """
            now = time.monotonic()
            if self.daemon._net_services_cache and (now - self.daemon._net_services_cache_time) < 60.0:
                return list(self.daemon._net_services_cache)
            try:
                out = subprocess.run(
                    ["networksetup", "-listallnetworkservices"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if out.returncode != 0:
                    logging.error(
                        "networksetup failed with code %d: %s", out.returncode, out.stderr
                    )
                    return list(self.daemon._net_services_cache) if self.daemon._net_services_cache else []
    
                lines = out.stdout.strip().split("\n")
                # First line is always the header: "An asterisk (*) denotes..."
                services = []
                for line in lines[1:]:
                    stripped = line.strip().lstrip("*").strip()
                    if stripped:
                        services.append(stripped)
                self.daemon._net_services_cache = services
                self.daemon._net_services_cache_time = now
                return services
            except Exception as exc:
                logging.error("Failed to get network services: %s", exc)
                return list(self.daemon._net_services_cache) if self.daemon._net_services_cache else []

    def _get_current_dns_servers(self) -> dict[str, str]:
            """Get current DNS servers for all network services."""
            result = {}
            try:
                services = self._get_network_services()
    
                def get_dns(svc):
                    dns_out = subprocess.run(
                        ["networksetup", "-getdnsservers", svc],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    dns_raw = dns_out.stdout.strip()
                    filtered = [s for s in dns_raw.split("\n") if s not in ("127.0.0.1", "::1", "localhost")]
                    if not filtered or "There aren't any DNS Servers" in dns_raw:
                        dns_str = "There aren't any DNS Servers"
                    else:
                        dns_str = "\n".join(filtered)
                    return svc, dns_str
    
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(services) if services else 1)) as executor:
                    futures = {executor.submit(get_dns, svc): svc for svc in services}
                    for future in concurrent.futures.as_completed(futures):
                        try:
                            svc, dns = future.result()
                            result[svc] = dns
                        except Exception as e:
                            svc = futures[future]
                            logging.error("Failed to get DNS servers for %s: %s", svc, e)
            except Exception as exc:
                logging.error("Failed to get DNS servers: %s", exc)
            return result

    def _enforce_whitelist(self):
            """Whitelist mode: restore clean /etc/hosts, enforce PF firewall blocking all except whitelist."""
            with self.daemon.enforcement_lock:
                try:
                    # 1. Start DNS & SNI proxies before breaking the network
                    if not getattr(self.daemon, "dns_proxy", None):
                        self.start_dns_proxy()
                    if not getattr(self.daemon, "sni_proxy", None):
                        self.start_sni_proxy()
    
                    # 2. Re-route system DNS to our proxy (localhost)
                    self._set_dns_to_localhost()
    
                    # 3. Block DNS-over-HTTPS providers in /etc/hosts (anti-bypass)
                    self._enforce_doh_block()
    
                    # 4. Enforce strict PF firewall whitelist
                    self._enforce_firewall(True)
    
                    # 5. Additional enforcements (same as blacklist to prevent bypasses)
                    self._enforce_browser_policies(True)
                    self._reset_system_proxies()
                    self._kill_vpn_interfaces()
                    self._kill_restricted_apps()
                    self._clear_browser_caches()
                    self._flush_dns()
                    
                except Exception as exc:
                    logging.error("Whitelist enforcement failed: %s", exc)

    def _enforce_doh_block(self):
            """Block DNS-over-HTTPS providers in /etc/hosts (whitelist anti-bypass)."""
            try:
                subprocess.run(
                    ["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5
                )
                content = self._strip_block(HOSTS_PATH.read_text())
                lines = [
                    MARKER_BEGIN,
                    "# Mode: WHITELIST (DoH block)",
                    f"# Expires: {self.daemon.state.session.session_expiry.isoformat()}",
                ]
                lines.append("# DoH providers (anti-bypass)")
                for domain in DOH_BLOCK_DOMAINS:
                    lines.append(f"127.0.0.1\t{domain}")
                    lines.append(f"::1\t\t{domain}")
                lines.append(MARKER_END)
                block = "\n".join(lines)
                content = content.rstrip("\n") + "\n\n" + block + "\n"
                HOSTS_PATH.write_text(content)
                subprocess.run(
                    ["chflags", "uchg", str(HOSTS_PATH)], capture_output=True, timeout=5
                )
            except Exception as exc:
                logging.error("_enforce_doh_block failed: %s", exc)

    def _set_dns_to_localhost(self):
            """Redirect all network services' DNS to 127.0.0.1 and ::1."""
            try:
                services = self._get_network_services()
                success_count = 0
                for svc in services:
                    result = subprocess.run(
                        ["networksetup", "-setdnsservers", svc, "127.0.0.1", "::1"],
                        capture_output=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        success_count += 1
                    else:
                        logging.warning(
                            "Failed to set DNS for service '%s': %s",
                            svc,
                            result.stderr.decode() if result.stderr else "unknown error",
                        )
                logging.info(
                    "DNS redirected to 127.0.0.1 and ::1 for %d/%d services.",
                    success_count,
                    len(services),
                )
            except Exception as exc:
                logging.error("Failed to redirect DNS: %s", exc)

    def _restore_dns(self):
            """Restore original DNS servers from saved state."""
            try:
                if not self.daemon.original_dns:
                    # If no saved DNS, set to "empty" (use DHCP defaults)
                    services = self._get_network_services()
                    success_count = 0
                    for svc in services:
                        result = subprocess.run(
                            ["networksetup", "-setdnsservers", svc, "empty"],
                            capture_output=True,
                            timeout=5,
                        )
                        if result.returncode == 0:
                            success_count += 1
                        else:
                            logging.warning(
                                "Failed to reset DNS for service '%s': %s",
                                svc,
                                (
                                    result.stderr.decode()
                                    if result.stderr
                                    else "unknown error"
                                ),
                            )
                    logging.info(
                        "Reset DNS to defaults for %d/%d services.",
                        success_count,
                        len(services),
                    )
                    return
    
                success_count = 0
                for svc, dns_str in self.daemon.original_dns.items():
                    try:
                        if "There aren't any DNS Servers" in dns_str or not dns_str.strip():
                            result = subprocess.run(
                                ["networksetup", "-setdnsservers", svc, "empty"],
                                capture_output=True,
                                timeout=5,
                            )
                        else:
                            servers = [s for s in dns_str.strip().split("\n") if s not in ("127.0.0.1", "::1", "localhost")]
                            if not servers:
                                result = subprocess.run(
                                    ["networksetup", "-setdnsservers", svc, "empty"],
                                    capture_output=True,
                                    timeout=5,
                                )
                            else:
                                result = subprocess.run(
                                    ["networksetup", "-setdnsservers", svc] + servers,
                                capture_output=True,
                                timeout=5,
                            )
    
                        if result.returncode == 0:
                            success_count += 1
                        else:
                            logging.warning(
                                "Failed to restore DNS for service '%s': %s",
                                svc,
                                (
                                    result.stderr.decode()
                                    if result.stderr
                                    else "unknown error"
                                ),
                            )
                    except Exception as exc:
                        logging.error("Failed to restore DNS for %s: %s", svc, exc)
                try:
                    self.start_sni_proxy()
                except Exception as exc:
                    logging.error("Failed to start SNI proxy during whitelist enforcement: %s", exc)
                logging.info("DNS servers restored for %d services.", success_count)
            except Exception as exc:
                logging.error("Critical failure restoring DNS: %s", exc)

    @staticmethod
    def _strip_block(content: str) -> str:
            result = []
            inside = False
            for line in content.split("\n"):
                if MARKER_BEGIN in line:
                    inside = True
                    continue
                if MARKER_END in line:
                    inside = False
                    continue
                if not inside:
                    result.append(line)
            while result and result[-1].strip() == "":
                result.pop()
            return "\n".join(result)

    def _flush_dns(self):
        try:
            subprocess.run(
                ["dscacheutil", "-flushcache"], capture_output=True, timeout=5
            )
            subprocess.run(
                ["killall", "-HUP", "mDNSResponder"], capture_output=True, timeout=5
            )
            subprocess.run(
                ["killall", "-USR1", "mDNSResponder"], capture_output=True, timeout=5
            )
        except Exception as exc:
            logging.error("Failed to flush DNS cache: %s", exc)

    def start_dns_proxy(self):
        """Start the local DNS proxy."""
        from forcefocus.dns_proxy import LocalDNSProxy
        try:
            if not getattr(self.daemon, "dns_proxy", None):
                self.daemon.dns_proxy = LocalDNSProxy(self.daemon)
                self.daemon.dns_proxy.start()
        except Exception as exc:
            logging.error("Failed to start DNS proxy: %s", exc)

    def start_sni_proxy(self):
        """Start the transparent SNI proxy."""
        from forcefocus.sni_proxy import SniProxy
        try:
            if not getattr(self.daemon, "sni_proxy", None):
                self.daemon.sni_proxy = SniProxy(self._sni_is_allowed)
                self.daemon.sni_proxy.start_sync(host="127.0.0.1", port=8443)
        except Exception as exc:
            logging.error("Failed to start SNI proxy: %s", exc)

    def stop_sni_proxy(self):
        """Stop the SNI proxy."""
        try:
            if getattr(self.daemon, "sni_proxy", None):
                self.daemon.sni_proxy.stop_sync()
                self.daemon.sni_proxy = None
        except Exception as exc:
            logging.error("Failed to stop SNI proxy: %s", exc)

    def _sni_is_allowed(self, domain: str) -> bool:
        """Callback for SNI proxy to verify if a domain is allowed."""
        if not domain:
            return False
        domain = domain.lower()
        if self.daemon.state.session.mode == "whitelist":
            for ad in self.daemon.state.active_domains:
                if domain == ad or domain.endswith("." + ad):
                    return True
            return False
        return True
