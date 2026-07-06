import time
import socket
import struct
import select
import logging
import threading
import concurrent.futures

class LocalDNSProxy(threading.Thread):
    def __init__(self, ff_daemon):
        super().__init__(daemon=True)
        self.ff_daemon = ff_daemon
        self.sock = None
        self.active = True

        self.upstream_dns = "8.8.8.8"
        if self.ff_daemon.original_dns:
            for svc, dns_list in self.ff_daemon.original_dns.items():
                if dns_list and "aren't any" not in dns_list and dns_list.strip():
                    first = dns_list.strip().split()[0]
                    # Never forward to ourselves — would create infinite loop
                    if first and first not in ("127.0.0.1", "::1"):
                        self.upstream_dns = first
                        break
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)

    def _bind_with_retry(self, max_attempts=10, initial_delay=1.0):
        """Retry binding to port 53 with exponential backoff for boot race."""
        delay = initial_delay
        temp_socks = []
        for attempt in range(max_attempts):
            try:
                self.socks = []
                temp_socks = []
                # IPv4
                s4 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                temp_socks.append(s4)
                s4.bind(("127.0.0.1", 53))
                self.socks.append(s4)
                # IPv6
                try:
                    s6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
                    s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    temp_socks.append(s6)
                    s6.bind(("::1", 53))
                    self.socks.append(s6)
                except Exception as exc:
                    logging.warning(
                        "IPv6 DNS Proxy bind failed (non-critical): %s", exc
                    )

                logging.info("DNS Proxy bound to port 53 (attempt %d).", attempt + 1)
                return True
            except OSError as exc:
                logging.warning(
                    "DNS Proxy bind failed (attempt %d/%d): %s",
                    attempt + 1,
                    max_attempts,
                    exc,
                )
                # Clean up any opened sockets from this attempt
                for s in temp_socks:
                    try:
                        s.close()
                    except OSError:
                        pass
                time.sleep(delay)
                delay = min(delay * 2, 10.0)
        logging.error("DNS Proxy: exhausted all bind attempts.")
        return False

    def run(self):
        if not self._bind_with_retry():
            self.active = False
            return

        logging.info("DNS Proxy listening on 127.0.0.1:53 and ::1:53")
        while self.active:
            try:
                # Ensure sockets are still open before select
                valid_socks = [s for s in getattr(self, "socks", []) if s.fileno() != -1]
                if not valid_socks:
                    break
                r, _, _ = select.select(valid_socks, [], [], 1.0)
                if not r or not self.active:
                    continue
                for s in r:
                    try:
                        data, addr = s.recvfrom(4096)
                        if not data:
                            continue
                        self._handle_query(data, addr, s)
                    except (OSError, ValueError):
                        continue
            except Exception as exc:
                if self.active:  # Only log if we didn't intend to stop
                    logging.error("DNS Proxy loop error: %s", exc)

    def stop(self):
        self.active = False
        try:
            self.executor.shutdown(wait=False)
        except Exception:
            pass
        try:
            for s in getattr(self, "socks", []):
                s.close()
        except OSError:
            pass

    def _extract_domain(self, data: bytes) -> str:
        parts = []
        idx = 12
        try:
            while idx < len(data) and data[idx] != 0:
                length = data[idx]
                parts.append(data[idx + 1 : idx + 1 + length].decode("utf-8"))
                idx += 1 + length
            return ".".join(parts).lower()
        except Exception:
            return ""

    def _make_nxdomain(self, query: bytes) -> bytes:
        try:
            hdr = struct.unpack("!HHHHHH", query[:12])
            flags = (hdr[1] | 0x8000) & 0xFE00
            flags = flags | 0x0080 | 3
            idx = 12
            while query[idx] != 0:
                idx += 1 + query[idx]
            idx += 5
            resp_hdr = struct.pack("!HHHHHH", hdr[0], flags, hdr[2], 0, 0, 0)
            return resp_hdr + query[12:idx]
        except Exception:
            return b""

    def _handle_query(self, data: bytes, addr, sock):
        domain = self._extract_domain(data)
        if not domain:
            return

        allowed = False
        if domain == "localhost" or domain.endswith(".local") or domain == "api.aladhan.com":
            allowed = True
        else:
            parts = domain.split(".")
            for i in range(len(parts)):
                if ".".join(parts[i:]) in self.ff_daemon.active_domains_set:
                    allowed = True
                    break

        if allowed:
            self.executor.submit(self._forward_query, data, addr, sock, domain)
        else:
            resp = self._make_nxdomain(data)
            if resp:
                sock.sendto(resp, addr)

    def _forward_query(self, data: bytes, addr, sock, domain: str = ""):
        fw = None
        try:
            family = socket.AF_INET6 if ":" in self.upstream_dns else socket.AF_INET
            fw = socket.socket(family, socket.SOCK_DGRAM)
            fw.settimeout(2.0)
            fw.sendto(data, (self.upstream_dns, 53))
            resp, _ = fw.recvfrom(4096)
            sock.sendto(resp, addr)
            
            # Extract IPs from DNS response to instantly authorize them in the firewall
            if domain and resp:
                import struct, time, subprocess
                ips = []
                try:
                    qdcount, ancount, _, _ = struct.unpack("!HHHH", resp[4:12])
                    idx = 12
                    for _ in range(qdcount):
                        while idx < len(resp) and resp[idx] != 0:
                            idx += 1 + resp[idx]
                        idx += 5
                    for _ in range(ancount):
                        if idx >= len(resp): break
                        if (resp[idx] & 0xC0) == 0xC0:
                            idx += 2
                        else:
                            while idx < len(resp) and resp[idx] != 0:
                                if (resp[idx] & 0xC0) == 0xC0:
                                    idx += 2
                                    break
                                idx += 1 + resp[idx]
                            else:
                                idx += 1
                        if idx + 10 > len(resp): break
                        rtype, _, _, rdlength = struct.unpack("!HHIH", resp[idx:idx+10])
                        idx += 10
                        if rtype == 1 and rdlength == 4:
                            ips.append(socket.inet_ntoa(resp[idx:idx+4]))
                        elif rtype == 28 and rdlength == 16:
                            ips.append(socket.inet_ntop(socket.AF_INET6, resp[idx:idx+16]))
                        idx += rdlength
                except Exception:
                    pass

                if ips and hasattr(self.ff_daemon, "_whitelisted_ip_backlog"):
                    current_time = time.monotonic()
                    if domain not in self.ff_daemon._whitelisted_ip_backlog:
                        self.ff_daemon._whitelisted_ip_backlog[domain] = {}
                    
                    new_ips = []
                    for ip in ips:
                        if ip not in self.ff_daemon._whitelisted_ip_backlog[domain]:
                            new_ips.append(ip)
                        self.ff_daemon._whitelisted_ip_backlog[domain][ip] = current_time + (30 * 60)
                    
                    if new_ips:
                        try:
                            subprocess.run(
                                ["pfctl", "-a", "forcefocus", "-t", "ff_whitelisted_ips", "-T", "add"] + new_ips,
                                capture_output=True, timeout=2
                            )
                        except Exception:
                            pass
        except Exception:
            pass
        finally:
            if fw:
                fw.close()
