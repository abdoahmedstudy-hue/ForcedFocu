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
from pathlib import Path
from datetime import datetime
from forcefocus.constants import *

class FirewallMixin:
    def _update_blocked_ips(self):
            """Resolves active/permanently blocked domains to IPs and updates the PF table with a 30m backlog."""
            try:
                domains_to_resolve_blocks = set(self.daemon.perma_blocklist)
                domains_to_resolve_whitelist = set()
    
                is_break = self.daemon.state.session.session_type == "pomodoro" and self.daemon.state.pomodoro.pomo_phase == "break"
                if self.daemon.state.session.active and not is_break:
                    if self.daemon.state.session.mode == "blacklist":
                        domains_to_resolve_blocks.update(self.daemon.state.active_domains)
                    elif self.daemon.state.session.mode in ("whitelist", "ban"):
                        domains_to_resolve_whitelist.update(self.daemon.state.active_domains)
                
                if not domains_to_resolve_blocks and not domains_to_resolve_whitelist:
                    pass
    
                current_time = time.monotonic()
                
                def _resolve_and_update(domains, backlog):
                    # Clean up domains no longer in the active list
                    for d in list(backlog.keys()):
                        if d not in domains:
                            del backlog[d]
                    
                    if not domains:
                        return []
                        
                    for domain in domains:
                        if domain not in backlog:
                            backlog[domain] = {}
                        try:
                            addr_info = socket.getaddrinfo(domain, None, 0, socket.SOCK_STREAM)
                            for res in addr_info:
                                ip = res[4][0]
                                backlog[domain][ip] = current_time + (30 * 60)
                        except socket.gaierror:
                            pass
                        
                        # Cleanup expired IPs for this domain
                        expired = [ip for ip, exp in backlog[domain].items() if current_time > exp]
                        for ip in expired:
                            del backlog[domain][ip]
                            
                    # Flatten all IPs
                    all_ips = set()
                    for d_ips in backlog.values():
                        all_ips.update(d_ips.keys())
                    return list(all_ips)
    
                active_block_ips = _resolve_and_update(domains_to_resolve_blocks, self.daemon._ip_backlog)
                active_whitelist_ips = _resolve_and_update(domains_to_resolve_whitelist, self.daemon._whitelisted_ip_backlog)
    
                def _update_table(table_name, ips):
                    process = subprocess.Popen(
                        ["pfctl", "-a", "forcefocus", "-t", table_name, "-T", "replace", "-f", "-"],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    ips_str = "\n".join(ips) + "\n" if ips else ""
                    process.communicate(input=ips_str)
    
                _update_table("ff_blocked_ips", active_block_ips)
                _update_table("ff_whitelisted_ips", active_whitelist_ips)
    
            except Exception as exc:
                logging.error("_update_blocked_ips failed: %s", exc)
            finally:
                with self.daemon.lock:
                    self.daemon._ip_resolution_running = False

    def _enforce_firewall(self, enable: bool, upstream_dns: str = None):
            """Nuclear firewall enforcement: Blocks QUIC, DoT, and known DoH IPs."""
            try:
                if enable:
                    # 1. Enable PF
                    subprocess.run(["pfctl", "-E"], capture_output=True, timeout=5)
                    # 2. Construct nuclear ruleset
                    tables = [
                        "table <ff_blocked_ips> persist",
                        "table <ff_whitelisted_ips> persist",
                    ]
                    translations = []
                    filters = [
                        "pass out quick on lo0 all",  # Exempt localhost (for Local DNS Proxy & Web UI)
                        "pass in quick on lo0 all",
                    ]

                    # Explicitly allow port 53 to prevent Resolver Catch-22
                    if upstream_dns:
                        filters.append(f"pass out quick proto {{tcp udp}} from any to {upstream_dns} port 53")
                    else:
                        filters.append("pass out quick proto {tcp udp} from any to any port 53")

                    filters.extend(
                        [
                            "block return out proto udp from any to any port 443",  # QUIC bypass
                            "block return out proto {tcp udp} from any to any port 853",  # DNS-over-TLS bypass
                            "block return out proto {tcp udp} from any to any port {1080, 8080, 3128, 9050, 9051}",  # Proxy/Tor bypass
                            "block return out proto {tcp udp} from any to any port 51820",  # WireGuard
                            "block return out proto {tcp udp} from any to any port 1194",  # OpenVPN
                            "block return out proto {tcp udp} from any to any port {500, 4500}",  # IPSec/IKEv2
                            "block return out proto {tcp udp} from any to any port {1723, 1701}",  # PPTP/L2TP
                            "block return out proto {tcp udp} from any to any port {8388, 8389}",  # Shadowsocks
                            "block return out proto {tcp udp} from any to any port {10808, 10809}",  # V2Ray
                            "block return out proto {tcp udp} from any to any port {7890, 7891, 7892, 7893}",  # Clash proxy
                            "block return out proto tcp from any to any port 22",  # SSH tunneling
                            "block return out quick from any to <ff_blocked_ips>",  # IP-level domain block
                        ]
                    )

                    is_break = self.daemon.state.session.session_type == "pomodoro" and self.daemon.state.pomodoro.pomo_phase == "break"
                    if (self.daemon.state.session.active and self.daemon.state.session.mode in ("whitelist", "ban") and not is_break) or getattr(self.daemon, "prayer_ban_active", ""):
                        filters.extend(
                            [
                                "pass out quick from any to <ff_whitelisted_ips>",
                                "block return out proto tcp from any to any port 443",
                                "block return out proto tcp from any to any port 80",
                            ]
                        )

                    # Block known DoH provider IPs to prevent direct IP-based bypass (only block port 443, not all ports)
                    for ip in DOH_IPS:
                        filters.append(
                            f"block return out proto tcp from any to {ip} port 443"
                        )

                    rules_str = "\n".join(tables + translations + filters) + "\n"
                    process = subprocess.Popen(
                        ["pfctl", "-a", "forcefocus", "-f", "-"],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    out, err = process.communicate(input=rules_str)
                    if process.returncode != 0:
                        logging.error(f"pfctl failed to load rules. Exit code: {process.returncode}. Stderr: {err}")
    
                    # 3. Kill any existing states for blocked domains (clears cached connections)
                    # Targeted state kill for common bypass ports.
                    subprocess.run(
                        ["pfctl", "-k", "0.0.0.0/0", "-k", "443"], capture_output=True
                    )
                    subprocess.run(
                        ["pfctl", "-k", "0.0.0.0/0", "-k", "80"], capture_output=True
                    )
    
                    logging.info(
                        "Firewall: Nuclear rules applied (QUIC/DoT/Proxies/DoH IPs blocked)."
                    )
                    # Immediately run IP resolution in background to populate tables without 60s delay
                    threading.Thread(target=self._update_blocked_ips, daemon=True).start()
                else:
                    subprocess.run(
                        ["pfctl", "-a", "forcefocus", "-F", "all"],
                        capture_output=True,
                        timeout=5,
                    )
                    logging.info("Firewall: rules cleared.")
            except Exception as exc:
                logging.error("Firewall enforcement failed: %s", exc)

