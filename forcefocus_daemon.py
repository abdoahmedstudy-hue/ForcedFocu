#!/usr/bin/env python3
"""
ForcedFocus Daemon v2 — Root-level macOS website blocker.

Supports blacklist mode (block listed sites) and whitelist mode
(allow ONLY listed sites by redirecting DNS + pinning IPs).
"""

import os
import sys
import json
import base64
import time
import signal
import socket
import struct
import select
import hashlib
import hmac
import logging
import threading
import queue
import subprocess
import concurrent.futures
import mimetypes
import re
from pathlib import Path
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote


def get_continuous_time() -> float:
    # CLOCK_MONOTONIC_RAW on macOS maps to mach_continuous_time (includes sleep time)
    return time.clock_gettime(time.CLOCK_MONOTONIC_RAW)


# Constants for optimizations
COMMON_PREFIXES = (
    "www.",
    "m.",
    "api.",
    "cdn.",
    "static.",
    "app.",
    "mail.",
    "login.",
    "accounts.",
    "mobile.",
    "touch.",
    "new.",
    "dev.",
    "assets.",
    "cdn1.",
    "cdn2.",
    "v.",
    "video.",
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONFIG_DIR = Path("/etc/forcefocus")
SESSION_LOCK = CONFIG_DIR / "session.lock"
KS_HASH_FILE = CONFIG_DIR / "ks_hash"
LISTS_FILE = CONFIG_DIR / "lists.json"
GROUPS_FILE = CONFIG_DIR / "groups.json"
API_TOKEN_FILE = CONFIG_DIR / "api_token"
SOCK_PATH = "/var/run/forcefocus.sock"
HOSTS_PATH = Path("/private/etc/hosts")
WEB_HOST = "127.0.0.1"
WEB_PORT = 7070
_local_web = Path(__file__).resolve().parent / "web"
WEB_DIR = _local_web if _local_web.exists() else Path("/usr/local/share/forcefocus/web")
SETTINGS_FILE = CONFIG_DIR / "settings.json"
PERMA_BLOCK_FILE = CONFIG_DIR / "perma_blocklist.json"

DEFAULT_SETTINGS = {
    "sound_start": "Start Blocking.mp3",
    "sound_rescue": "Rescue Mode.mp3",
    "sound_unlock": "Request Unlock .mp3",
    "sound_break": "Break Time.mp3",
    "sound_end": "Session End .mp3",
    "sound_scheduled": "Scheduled meeting.mp3",
    "sound_blocked": "Blocked site open.mp3",
    "intent_notification_enabled": True,
    "intent_notification_interval": 15,
}

MARKER_BEGIN = "# ──── BEGIN FORCEFOCUS ────"
MARKER_END = "# ──── END FORCEFOCUS ────"
PERMA_MARKER_BEGIN = "# ──── BEGIN FORCEFOCUS PERMANENT ────"
PERMA_MARKER_END = "# ──── END FORCEFOCUS PERMANENT ────"

WATCHDOG_INTERVAL = 0.25
SOCKET_TIMEOUT = 1.0
DELAYED_UNLOCK_S = 20 * 60
PERMA_UNLOCK_DELAY_S = 30 * 60  # 30 minutes to unblock a permanently blocked domain

# Subdomains to auto-resolve in whitelist mode
WHITELIST_PREFIXES = ["", "www.", "m.", "api.", "cdn.", "static."]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DEFAULT BLOCKLIST (fallback when lists.json blacklist is empty)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DEFAULT_BLOCKLIST = {
    "social_media": [
        "reddit.com",
        "www.reddit.com",
        "old.reddit.com",
        "twitter.com",
        "www.twitter.com",
        "x.com",
        "www.x.com",
        "facebook.com",
        "www.facebook.com",
        "m.facebook.com",
        "instagram.com",
        "www.instagram.com",
        "tiktok.com",
        "www.tiktok.com",
        "snapchat.com",
        "www.snapchat.com",
    ],
    "video_streaming": [
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "twitch.tv",
        "www.twitch.tv",
    ],
    "news_entertainment": [
        "news.ycombinator.com",
        "9gag.com",
        "www.9gag.com",
        "buzzfeed.com",
        "www.buzzfeed.com",
    ],
    "messaging": [
        "discord.com",
        "www.discord.com",
        "web.telegram.org",
    ],
}

# DNS-over-HTTPS providers that browsers use to bypass /etc/hosts.
# Blocking these forces Chrome/Firefox/etc back to system DNS.
DOH_BLOCK_DOMAINS = [
    "dns.google",
    "dns.google.com",
    "dns64.dns.google",
    "cloudflare-dns.com",
    "one.one.one.one",
    "mozilla.cloudflare-dns.com",
    "dns.quad9.net",
    "doh.opendns.com",
    "dns.nextdns.io",
    "doh.cleanbrowsing.org",
    "dns.adguard-dns.com",
    "doh.dns.sb",
    "dns.controld.com",
    "freedns.controld.com",
    "chrome.cloudflare-dns.com",
    "mask.icloud.com",
    "mask-h2.icloud.com",
    "mask-api.icloud.com",
    "dns.google.com",
    "dns.tuna.tsinghua.edu.cn",
    "doh.pub",
    "doh.li",
    "doh.tiar.app",
    "doh.seby.io",
    "dns.flatuslifir.is",
    "doh.pwneddns.net",
    "doh-jp.blahdns.com",
    "doh-de.blahdns.com",
    "doh-fi.blahdns.com",
    "dns.rubyfish.cn",
    "dot.pub",
    "dns.alidns.com",
    "doh.360.cn",
]

CDN_INFRASTRUCTURE_DOMAINS = [
    # Major CDNs
    "cloudflare.com",
    "cdnjs.cloudflare.com",
    "cloudfront.net",
    "akamaized.net",
    "akamai.net",
    "akamaihd.net",
    "fastly.net",
    "fastlylb.net",
    "edgecastcdn.net",
    "stackpathdns.com",
    "azureedge.net",
    "azurefd.net",
    # Google shared infrastructure
    "gstatic.com",
    "googleapis.com",
    "googleusercontent.com",
    # Fonts & typography
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "use.typekit.net",
    "use.fontawesome.com",
    # JS/CSS package CDNs
    "jsdelivr.net",
    "unpkg.com",
    "cdnjs.com",
    "bootstrapcdn.com",
    # Media / image CDNs
    "imgix.net",
    "wp.com",
    "gravatar.com",
    "twimg.com",
    # Authentication providers
    "accounts.google.com",
    "appleid.apple.com",
    "login.microsoftonline.com",
    # Analytics/functional
    "hcaptcha.com",
    "recaptcha.net",
    "challenges.cloudflare.com",
]

SITE_BUNDLES = {
    "youtube.com": [
        "googlevideo.com",
        "ytimg.com",
        "ggpht.com",
        "youtu.be",
        "youtube-nocookie.com",
    ],
    "netflix.com": ["nflxvideo.net", "nflximg.net", "nflxext.com", "nflxso.net"],
    "x.com": ["twitter.com", "t.co", "abs.twimg.com"],
    "twitter.com": ["x.com", "t.co", "abs.twimg.com"],
    "facebook.com": ["fbcdn.net", "fbsbx.com", "facebook.net"],
    "instagram.com": ["cdninstagram.com", "fbcdn.net"],
    "github.com": ["githubusercontent.com", "githubassets.com", "github.io"],
    "reddit.com": ["redd.it", "redditstatic.com", "redditmedia.com"],
    "twitch.tv": ["jtvnw.net", "ttvnw.net", "twitchcdn.net"],
    "spotify.com": ["spotifycdn.com", "scdn.co"],
    "amazon.com": ["ssl-images-amazon.com", "media-amazon.com", "images-amazon.com"],
    "chatgpt.com": ["oaiusercontent.com", "oaistatic.com", "openai.com"],
    "openai.com": ["oaiusercontent.com", "oaistatic.com", "chatgpt.com"],
    "zoom.us": ["zoom.com", "zoomcdn.com"],
    "zoom.com": ["zoom.us", "zoomcdn.com"],
    "whatsapp.com": ["whatsapp.net"],
}

VPN_PROCESSES = [
    "Tailscale",
    "WireGuard",
    "Cisco AnyConnect",
    "Tunnelblick",
    "NordVPN",
    "ExpressVPN",
    "Mullvad",
    "ProtonVPN",
    "Surfshark",
    "GlobalProtect",
    "ivpn-gui",
    "Windscribe",
]

DOH_IPS = [
    "1.1.1.1",
    "1.0.0.1",
    "8.8.8.8",
    "8.8.4.4",
    "9.9.9.9",
    "149.112.112.112",
    "208.67.222.222",
    "208.67.220.220",
    "45.11.45.11",
    "94.140.14.14",
]

# Processes that can be used to bypass blocking
RESTRICTED_PROCESSES = [
    # VPNs & Tunnels
    "Tailscale",
    "WireGuard",
    "Cisco AnyConnect",
    "Tunnelblick",
    "NordVPN",
    "ExpressVPN",
    "Mullvad",
    "ProtonVPN",
    "Surfshark",
    "GlobalProtect",
    "ivpn-gui",
    "Windscribe",
    "CloudflareWARP",
    # Unmanaged Browsers (that might bypass system policies)
    "Opera",
    "Vivaldi",
    "TorBrowser",
    "Arc",
    "Sidekick",
    "SigmaOS",
    "Orion",
    "Waterfox",
    "Pale Moon",
    "Ghostery",
    # Potential Bypass Tools
    "Activity Monitor",
]

BROWSER_RESISTANCE_URLS = [
    "chrome://settings",
    "chrome://extensions",
    "chrome://flags",
    "chrome://policy",
    "chrome://inspect",
    "chrome://net-internals",
    "chrome://serviceworker-internals",
    "chrome://webuijserror",
    "chrome://badcastcrash",
    "chrome://inducebrowsercrashforrealz",
    "chrome://inducebrowserdcheckforrealz",
    "chrome://crash",
    "chrome://crash/rust",
    "chrome://crashdump",
    "chrome://kill",
    "chrome://hang",
    "chrome://shorthang",
    "chrome://gpuclean",
    "chrome://gpucrash",
    "chrome://gpuhang",
    "chrome://memory-exhaust",
    "chrome://memory-pressure-critical",
    "chrome://memory-pressure-moderate",
    "chrome://quit",
    "chrome://restart",
    "edge://settings",
    "edge://extensions",
    "edge://flags",
    "edge://policy",
    "edge://inspect",
    "about:config",
    "about:addons",
    "about:policies",
]


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DAEMON
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


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
                valid_socks = [s for s in self.socks if s.fileno() != -1]
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
        if domain == "localhost" or domain.endswith(".local"):
            allowed = True
        else:
            parts = domain.split(".")
            for i in range(len(parts)):
                if ".".join(parts[i:]) in self.ff_daemon.active_domains_set:
                    allowed = True
                    break

        if allowed:
            fw = None
            try:
                # Use appropriate socket family for upstream if needed, but usually v4 is fine for forwarding
                fw = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                fw.settimeout(2.0)
                fw.sendto(data, (self.upstream_dns, 53))
                resp, _ = fw.recvfrom(4096)
                sock.sendto(resp, addr)
            except Exception:
                pass
            finally:
                if fw:
                    fw.close()
        else:
            resp = self._make_nxdomain(data)
            if resp:
                sock.sendto(resp, addr)


class ForcedFocusDaemon:
    def __init__(self):
        self.active = False
        self.mode = "blacklist"
        self.state_changed = threading.Event()
        self._sse_listeners = set()
        self._sse_listeners_lock = threading.Lock()
        self.active_domains: list[str] = []
        self.active_domains_set: set[str] = set()
        self.session_base_domains: list[str] = (
            []
        )  # Raw domains before /etc/hosts expansion
        self.session_expiry: datetime | None = None
        self.pending_unlock_at: datetime | None = None
        self.hosts_hash: str | None = None
        self._hosts_stat: tuple | None = None  # ⚡ (mtime, size) for cheap watchdog pre-check
        self.dns_proxy = None
        self.original_dns: dict[str, str] = {}
        self.whitelist_resolved: dict[str, list[str]] = {}
        self._cached_lists: dict | None = None
        self._cached_lists_mtime: float = 0.0
        self._cached_groups: dict | None = None
        self._cached_groups_mtime: float = 0.0
        self.whitelist_count: int = 0
        self.whitelist_expanded_count: int = 0
        self.total_duration_seconds: int = 0
        self.session_type: str = "standard"
        self.pomo_focus_minutes: int = 0
        self.pomo_break_minutes: int = 0
        self.pomo_total_cycles: int = 0
        self.pomo_current_cycle: int = 0
        self.pomo_phase: str = "focus"
        self.pomo_phase_expiry: datetime | None = None
        self.intent: str | None = None
        self.intent_tasks: list = []
        self.lock = threading.Lock()
        self._passphrase_attempts = 0
        self._last_attempt_time = 0.0
        # Monotonic time anchors (immune to clock manipulation)
        self._mono_session_end: float = 0.0
        self._mono_unlock_end: float = 0.0
        self._mono_pomo_phase_end: float = 0.0
        self._mono_last_intent_notif: float = 0.0
        self._mono_last_recurring_check: float = 0.0
        self._reenforce_flag = False  # Set by signal handler, handled by watchdog
        self.schedules: list = []
        self.recurring_schedules: list = []
        self.settings = self._load_settings()
        # Permanent blocklist state (independent from session blacklist)
        self.perma_blocklist: list[str] = []
        self.perma_pending_unlocks: dict[str, datetime] = {}  # domain → unlock-ready-at
        self._mono_perma_unlock_ends: dict[str, float] = {}  # domain → monotonic anchor
        self._perma_hosts_hash: str | None = None  # SHA256 of permanent block in /etc/hosts
        self._perma_passphrase_attempts = 0
        self._perma_last_attempt_time = 0.0
        self._perma_hosts_stat: tuple[float, int] | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def register_sse_listener(self, q):
        with self._sse_listeners_lock:
            self._sse_listeners.add(q)

    def unregister_sse_listener(self, q):
        with self._sse_listeners_lock:
            self._sse_listeners.discard(q)

    def broadcast_state_changed(self):
        self.state_changed.set()
        with self._sse_listeners_lock:
            for q in self._sse_listeners:
                try:
                    q.put_nowait(True)
                except queue.Full:
                    pass

    def run(self):
        setup_logging()
        logging.info("ForcedFocus daemon v2 starting (PID %d).", os.getpid())
        self._ensure_config_dir()
        self._ensure_lists_file()
        self._ensure_groups_file()
        self._ensure_perma_blocklist_file()
        self._generate_api_token()
        self._install_signal_handlers()
        # Load permanent blocklist and enforce immediately (before session restore)
        self._load_perma_state()
        self._enforce_perma_block()
        # Restore session BEFORE starting watchdog to avoid race (C2)
        with self.lock:
            self._restore_session()

        wt = threading.Thread(target=self._watchdog_loop, name="watchdog", daemon=True)
        wt.start()

        ht = threading.Thread(target=self._http_server, name="http", daemon=True)
        ht.start()

        self._socket_server()

    @staticmethod
    def _ensure_config_dir():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(str(CONFIG_DIR), 0o700)

    @staticmethod
    def _ensure_lists_file():
        if not LISTS_FILE.exists():
            LISTS_FILE.write_text(
                json.dumps({"blacklist": [], "whitelist": []}, indent=2)
            )
            os.chmod(str(LISTS_FILE), 0o644)

    @staticmethod
    def _ensure_groups_file():
        if not GROUPS_FILE.exists():
            GROUPS_FILE.write_text(json.dumps({}, indent=2))
            os.chmod(str(GROUPS_FILE), 0o644)

    @staticmethod
    def _ensure_perma_blocklist_file():
        if not PERMA_BLOCK_FILE.exists():
            PERMA_BLOCK_FILE.write_text(
                json.dumps({"domains": [], "pending_unlocks": {}}, indent=2)
            )
            os.chmod(str(PERMA_BLOCK_FILE), 0o644)

    def _generate_api_token(self):
        """Generate a per-launch API token for HTTP mutation endpoint auth."""
        import secrets

        self.api_token = secrets.token_hex(32)
        try:
            API_TOKEN_FILE.write_text(self.api_token)
            os.chmod(str(API_TOKEN_FILE), 0o600)
            # Chown to the real user so the web UI can read it
            user_file = Path("/etc/forcefocus/user")
            if user_file.exists():
                import pwd

                username = user_file.read_text().strip()
                try:
                    pw = pwd.getpwnam(username)
                    os.chown(str(API_TOKEN_FILE), pw.pw_uid, pw.pw_gid)
                except (KeyError, OSError):
                    pass
            logging.info("API token generated and written to %s", API_TOKEN_FILE)
        except OSError as exc:
            logging.error("Failed to write API token: %s", exc)

    def _install_signal_handlers(self):
        def _handler(signum, _frame):
            # Non-blocking: just set flag, watchdog will re-enforce (C1 fix)
            # We keep this handler minimal as only a few functions are signal-safe.
            self._reenforce_flag = True

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGHUP, _handler)

    # ── Lists Management ──────────────────────────────────────────────────────

    def _load_lists(self) -> dict:
        try:
            mtime = LISTS_FILE.stat().st_mtime
        except FileNotFoundError:
            return {"blacklist": [], "whitelist": []}

        if self._cached_lists is not None and mtime == self._cached_lists_mtime:
            return {
                k: v.copy() if isinstance(v, list) else v
                for k, v in self._cached_lists.items()
            }

        try:
            self._cached_lists = json.loads(LISTS_FILE.read_text())
            self._cached_lists_mtime = mtime
            return {
                k: v.copy() if isinstance(v, list) else v
                for k, v in self._cached_lists.items()
            }
        except Exception:
            return {"blacklist": [], "whitelist": []}

    def _save_lists(self, lists: dict):
        self._atomic_write_json(LISTS_FILE, lists, indent=2)

    def _load_groups(self) -> dict:
        try:
            mtime = GROUPS_FILE.stat().st_mtime
        except FileNotFoundError:
            return {}

        if self._cached_groups is not None and mtime == self._cached_groups_mtime:
            return {
                k: v.copy() if isinstance(v, list) else v
                for k, v in self._cached_groups.items()
            }

        try:
            self._cached_groups = json.loads(GROUPS_FILE.read_text())
            self._cached_groups_mtime = mtime
            return {
                k: v.copy() if isinstance(v, list) else v
                for k, v in self._cached_groups.items()
            }
        except Exception:
            return {}

    def _save_groups(self, groups: dict):
        self._atomic_write_json(GROUPS_FILE, groups, indent=2)

    # ── Permanent Blocklist Management ────────────────────────────────────────

    def _load_perma_state(self):
        """Load permanent blocklist from disk into memory, restoring pending unlocks."""
        try:
            if not PERMA_BLOCK_FILE.exists():
                return
            data = json.loads(PERMA_BLOCK_FILE.read_text())
            self.perma_blocklist = data.get("domains", [])
            now_mono = get_continuous_time()
            raw_pending = data.get("pending_unlocks", {})
            for domain, info in raw_pending.items():
                try:
                    unlocks_at = datetime.fromisoformat(info["unlocks_at"])
                    remaining = (unlocks_at - datetime.now()).total_seconds()
                    if remaining <= 0:
                        # Timer expired during downtime — remove domain
                        if domain in self.perma_blocklist:
                            self.perma_blocklist.remove(domain)
                        logging.info(
                            "Permanent unblock for '%s' completed during downtime.", domain
                        )
                    else:
                        self.perma_pending_unlocks[domain] = unlocks_at
                        self._mono_perma_unlock_ends[domain] = now_mono + remaining
                except (KeyError, ValueError) as exc:
                    logging.warning(
                        "Invalid pending unlock entry for '%s': %s", domain, exc
                    )
            # Save cleaned state back
            self._save_perma_state()
            if self.perma_blocklist:
                logging.info(
                    "Permanent blocklist loaded: %d domains, %d pending unlocks.",
                    len(self.perma_blocklist),
                    len(self.perma_pending_unlocks),
                )
        except Exception as exc:
            logging.error("Failed to load permanent blocklist: %s", exc)

    def _save_perma_state(self):
        """Persist permanent blocklist and pending unlocks to disk."""
        pending = {}
        for domain, unlocks_at in self.perma_pending_unlocks.items():
            pending[domain] = {
                "requested_at": (
                    unlocks_at - timedelta(seconds=PERMA_UNLOCK_DELAY_S)
                ).isoformat(),
                "unlocks_at": unlocks_at.isoformat(),
            }
        data = {"domains": self.perma_blocklist, "pending_unlocks": pending}
        try:
            self._atomic_write_json(PERMA_BLOCK_FILE, data, indent=2)
        except Exception as exc:
            logging.error("Failed to save permanent blocklist: %s", exc)

    def _cmd_get_perma_blocklist(self) -> dict:
        """Return permanent blocklist and pending unlock status."""
        now_mono = get_continuous_time()
        pending = {}
        for domain, unlocks_at in self.perma_pending_unlocks.items():
            mono_end = self._mono_perma_unlock_ends.get(domain, 0)
            remaining = int(max(0, mono_end - now_mono))
            pending[domain] = {
                "unlocks_at": unlocks_at.strftime("%H:%M:%S"),
                "remaining_seconds": remaining,
            }
        return {
            "status": "ok",
            "domains": self.perma_blocklist,
            "pending_unlocks": pending,
        }

    def _cmd_add_perma_block(self, cmd: dict) -> dict:
        """Add domain(s) to the permanent blocklist. Can be done anytime."""
        domains_raw = cmd.get("domains", [])
        single = cmd.get("domain", "")
        if single:
            domains_raw = [single]
        if not domains_raw:
            return {"status": "error", "message": "No domains provided."}

        with self.lock:
            added = 0
            for d in domains_raw:
                domain = d.strip().lower()
                if not self._validate_domain(domain):
                    continue
                if domain not in self.perma_blocklist:
                    self.perma_blocklist.append(domain)
                    added += 1
            if added == 0:
                return {"status": "error", "message": "No valid new domains to add."}
            self._save_perma_state()
            self._enforce_perma_block()
            self.broadcast_state_changed()
            logging.info("Added %d domain(s) to permanent blocklist.", added)
            return {
                "status": "ok",
                "message": f"Added {added} domain(s) to permanent blocklist.",
                "domains": self.perma_blocklist,
            }

    def _cmd_request_perma_unblock(self, cmd: dict) -> dict:
        """Request removal of a domain from permanent blocklist (passphrase + 30m delay)."""
        domain = cmd.get("domain", "").strip().lower()
        passphrase = cmd.get("key", "")
        if not domain:
            return {"status": "error", "message": "No domain specified."}

        with self.lock:
            if domain not in self.perma_blocklist:
                return {"status": "error", "message": f"'{domain}' is not permanently blocked."}

            # Check if already pending
            if domain in self.perma_pending_unlocks:
                now_mono = get_continuous_time()
                mono_end = self._mono_perma_unlock_ends.get(domain, 0)
                rem = int(max(0, mono_end - now_mono))
                if rem > 0:
                    return {
                        "status": "pending",
                        "message": f"Unblock already pending. {rem // 60}m {rem % 60}s remaining.",
                        "remaining_seconds": rem,
                    }

            # Rate limit passphrase attempts (decoupled from session rate limiter)
            now_mono_rl = time.monotonic()
            if self._perma_passphrase_attempts >= 5:
                cooldown = min(60, 2 ** (self._perma_passphrase_attempts - 5))
                elapsed = now_mono_rl - self._perma_last_attempt_time
                if elapsed < cooldown:
                    wait = int(cooldown - elapsed)
                    return {
                        "status": "error",
                        "message": f"Too many attempts. Wait {wait}s.",
                    }
            self._perma_last_attempt_time = now_mono_rl

            if not self._verify_passphrase(passphrase):
                self._perma_passphrase_attempts += 1
                logging.warning(
                    "Invalid passphrase for permanent unblock attempt (#%d).",
                    self._perma_passphrase_attempts,
                )
                return {"status": "error", "message": "Invalid passphrase."}

            # Reset rate limiter on success
            self._perma_passphrase_attempts = 0

            # Start 30-minute cooldown
            unlocks_at = datetime.now() + timedelta(seconds=PERMA_UNLOCK_DELAY_S)
            self.perma_pending_unlocks[domain] = unlocks_at
            self._mono_perma_unlock_ends[domain] = (
                get_continuous_time() + PERMA_UNLOCK_DELAY_S
            )
            self._save_perma_state()
            self.broadcast_state_changed()
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

    def _cmd_cancel_perma_unblock(self, cmd: dict) -> dict:
        """Cancel a pending permanent unblock — re-lock the domain immediately."""
        domain = cmd.get("domain", "").strip().lower()
        if not domain:
            return {"status": "error", "message": "No domain specified."}

        with self.lock:
            if domain not in self.perma_pending_unlocks:
                return {
                    "status": "error",
                    "message": f"No pending unblock for '{domain}'.",
                }
            del self.perma_pending_unlocks[domain]
            self._mono_perma_unlock_ends.pop(domain, None)
            self._save_perma_state()
            self.broadcast_state_changed()
            logging.info("Cancelled permanent unblock for '%s'.", domain)
            return {
                "status": "ok",
                "message": f"Unblock cancelled. '{domain}' remains permanently blocked.",
            }

    # ── Permanent Block Enforcement ───────────────────────────────────────────

    def _enforce_perma_block(self):
        """Write permanent block entries to /etc/hosts using PERMA markers (independent from session)."""
        if not self.perma_blocklist:
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
            logging.info(
                "Permanent block enforced: %d domains in /etc/hosts.",
                len(self.perma_blocklist),
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
        for d in self.perma_blocklist:
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

    @staticmethod
    def _atomic_write_json(path: Path, data: dict, indent=None):
        temp_path = path.with_suffix(".tmp")
        try:
            temp_path.write_text(json.dumps(data, indent=indent))
            os.replace(temp_path, path)
        except Exception as exc:
            logging.error("Atomic write failed for %s: %s", path, exc)
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise

    def _cmd_get_session_domains(self) -> dict:
        """Return the effective domain list for the current session.

        For blacklist mode: returns base (un-expanded) domains because Chrome's
        urlFilter '||domain' already handles subdomain matching natively.
        The /etc/hosts-expanded list would exceed Chrome's 5000 rule limit.

        For whitelist mode: returns the CDN-expanded domain list because Chrome
        needs to know about all allowed CDN/infrastructure domains.
        """
        if not self.active:
            return {"status": "ok", "domains": [], "mode": None}
        if self.mode == "blacklist":
            return {
                "status": "ok",
                "domains": self.session_base_domains,
                "mode": self.mode,
            }
        return {"status": "ok", "domains": self.active_domains, "mode": self.mode}

    def _cmd_get_lists(self) -> dict:
        lists = self._load_lists()
        return {"status": "ok", "lists": lists}

    @staticmethod
    def _validate_domain(domain: str) -> bool:
        """Validate domain format: ASCII alphanumeric + hyphens + dots, reasonable length."""
        # re imported at module level
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

    def _cmd_add_domain(self, cmd: dict) -> dict:
        list_name = cmd.get("list", "blacklist")
        domain = cmd.get("domain", "").strip().lower()
        if not self._validate_domain(domain):
            return {"status": "error", "message": "Invalid domain."}
        if list_name not in ("blacklist", "whitelist"):
            return {"status": "error", "message": "Invalid list name."}

        with self.lock:
            if self.active:
                return {
                    "status": "error",
                    "message": "Cannot modify lists during active session.",
                }
            lists = self._load_lists()
            if domain not in lists[list_name]:
                lists[list_name].append(domain)
                self._save_lists(lists)
            return {
                "status": "ok",
                "message": f"Added {domain} to {list_name}.",
                "lists": lists,
            }

    def _cmd_add_domains(self, cmd: dict) -> dict:
        """Bulk-add multiple domains to a list."""
        list_name = cmd.get("list", "blacklist")
        domains = cmd.get("domains", [])
        if list_name not in ("blacklist", "whitelist"):
            return {"status": "error", "message": "Invalid list name."}

        with self.lock:
            if self.active:
                return {
                    "status": "error",
                    "message": "Cannot modify lists during active session.",
                }
            lists = self._load_lists()
            added = 0
            for d in domains:
                domain = d.strip().lower()
                if self._validate_domain(domain) and domain not in lists[list_name]:
                    lists[list_name].append(domain)
                    added += 1
            self._save_lists(lists)
            return {
                "status": "ok",
                "message": f"Added {added} domains to {list_name}.",
                "lists": lists,
            }

    def _cmd_remove_domain(self, cmd: dict) -> dict:
        list_name = cmd.get("list", "blacklist")
        domain = cmd.get("domain", "").strip().lower()
        if list_name not in ("blacklist", "whitelist"):
            return {"status": "error", "message": "Invalid list name."}

        with self.lock:
            if self.active:
                return {
                    "status": "error",
                    "message": "Cannot modify lists during active session.",
                }
            lists = self._load_lists()
            if domain in lists[list_name]:
                lists[list_name].remove(domain)
                self._save_lists(lists)
            return {
                "status": "ok",
                "message": f"Removed {domain} from {list_name}.",
                "lists": lists,
            }

    def _cmd_get_groups(self) -> dict:
        return {"status": "ok", "groups": self._load_groups()}

    def _cmd_add_group(self, cmd: dict) -> dict:
        name = cmd.get("name", "").strip()
        domains = cmd.get("domains", [])
        if not name:
            return {"status": "error", "message": "Group name is required."}
        with self.lock:
            if self.active:
                return {
                    "status": "error",
                    "message": "Cannot modify groups during active session.",
                }
            groups = self._load_groups()
            valid_domains = [
                d.strip().lower()
                for d in domains
                if self._validate_domain(d.strip().lower())
            ]
            if not valid_domains and domains:
                return {
                    "status": "error",
                    "message": "None of the provided domains are valid.",
                }
            groups[name] = valid_domains
            self._save_groups(groups)
            return {
                "status": "ok",
                "message": f"Group '{name}' saved.",
                "groups": groups,
            }

    def _cmd_remove_group(self, cmd: dict) -> dict:
        name = cmd.get("name", "").strip()
        if not name:
            return {"status": "error", "message": "Group name is required."}
        with self.lock:
            if self.active:
                return {
                    "status": "error",
                    "message": "Cannot modify groups during active session.",
                }
            groups = self._load_groups()
            if name in groups:
                del groups[name]
                self._save_groups(groups)
                return {
                    "status": "ok",
                    "message": f"Group '{name}' removed.",
                    "groups": groups,
                }
            return {"status": "error", "message": f"Group '{name}' not found."}

    # ── Session Management ────────────────────────────────────────────────────

    def _restore_session(self):
        if not SESSION_LOCK.exists():
            logging.info("No persisted session found. Daemon idle.")
            return
        try:
            data = json.loads(SESSION_LOCK.read_text())
        except (json.JSONDecodeError, ValueError) as exc:
            logging.error("Corrupt session.lock (%s). Removing.", exc)
            SESSION_LOCK.unlink(missing_ok=True)
            return

        # Restore schedules first (they exist independently of active sessions)
        if data.get("schedules"):
            try:
                for sch in data["schedules"]:
                    sch_time = datetime.fromisoformat(sch["start_time"])
                    # Skip schedules whose end_time has already passed
                    end_time = datetime.fromisoformat(sch["end_time"])
                    if end_time <= datetime.now():
                        continue
                    mono_start = get_continuous_time() + (sch_time - datetime.now()).total_seconds()
                    self.schedules.append(
                        {
                            "start_time": sch_time,
                            "end_time": end_time,
                            "mono_start": mono_start,
                            "cmd": sch["cmd"],
                        }
                    )
                self.schedules.sort(key=lambda x: x["start_time"])
                if self.schedules:
                    logging.info("Restored %d scheduled sessions.", len(self.schedules))
            except Exception as exc:
                logging.error("Failed to restore scheduled sessions: %s", exc)
                self.schedules = []

        if data.get("recurring_schedules"):
            self.recurring_schedules = data["recurring_schedules"]
            logging.info("Restored %d recurring schedules.", len(self.recurring_schedules))

        # If no active session data, we're done (schedule-only lockfile)
        if not data.get("expiry"):
            if self.schedules:
                self._persist_session_lock()
            return

        try:
            expiry = datetime.fromisoformat(data["expiry"])
        except (KeyError, ValueError) as exc:
            logging.error(
                "Invalid expiry in session.lock (%s). Removing active session data.",
                exc,
            )
            if self.schedules:
                self._persist_session_lock()
            else:
                SESSION_LOCK.unlink(missing_ok=True)
            return

        if datetime.now() >= expiry:
            logging.info("Persisted session expired. Cleaning up.")
            self.mode = data.get("mode", "blacklist")
            if self.mode == "whitelist":
                self.original_dns = data.get("original_dns", {})
            self._cleanup_session()
            return

        wall_remaining = (expiry - datetime.now()).total_seconds()
        self.total_duration_seconds = data.get("duration_minutes", 120) * 60

        if "mono_elapsed" in data and "last_persist_wall" in data:
            wall_gap = (
                datetime.now() - datetime.fromisoformat(data["last_persist_wall"])
            ).total_seconds()
            mono_remaining = (
                self.total_duration_seconds - data["mono_elapsed"] - wall_gap
            )
            remaining = min(wall_remaining, mono_remaining)
        else:
            remaining = wall_remaining
        remaining = max(0, remaining)

        self.mode = data.get("mode", "blacklist")
        self.session_expiry = expiry
        self.remaining_seconds = remaining
        self.session_type = data.get("session_type", "standard")
        self.intent = data.get("intent", None)
        self.intent_tasks = data.get("intent_tasks", [])
        self.pomo_focus_minutes = data.get("pomo_focus_minutes", 0)
        self.pomo_break_minutes = data.get("pomo_break_minutes", 0)
        self.pomo_total_cycles = data.get("pomo_total_cycles", 0)
        self.pomo_current_cycle = data.get("pomo_current_cycle", 0)
        self.pomo_phase = data.get("pomo_phase", "focus")

        now_mono = get_continuous_time()

        if data.get("pending_unlock_at"):
            self.pending_unlock_at = datetime.fromisoformat(data["pending_unlock_at"])
            unlock_remaining = max(
                0, (self.pending_unlock_at - datetime.now()).total_seconds()
            )
            if unlock_remaining <= 0:
                logging.info("Pending unlock expired during downtime. Ending session.")
                if self.mode == "whitelist":
                    self.original_dns = data.get("original_dns", {})
                self._cleanup_session()
                return
            self._mono_unlock_end = now_mono + unlock_remaining
            self.pending_unlock_seconds = unlock_remaining
        else:
            self.pending_unlock_at = None
            self.pending_unlock_seconds = 0
            self._mono_unlock_end = 0.0

        if data.get("pomo_phase_expiry"):
            self.pomo_phase_expiry = datetime.fromisoformat(data["pomo_phase_expiry"])
            self.pomo_phase_remaining = max(
                0, (self.pomo_phase_expiry - datetime.now()).total_seconds()
            )
        else:
            self.pomo_phase_expiry = None
            self.pomo_phase_remaining = 0

        # Set monotonic anchors from remaining wall-clock time
        self._mono_session_end = now_mono + remaining

        if self.pomo_phase_expiry:
            self._mono_pomo_phase_end = now_mono + max(
                0, (self.pomo_phase_expiry - datetime.now()).total_seconds()
            )

        self.active = True

        if self.mode == "whitelist":
            self.original_dns = data.get("original_dns", {})
            self.active_domains = data.get(
                "active_domains", data.get("blocked_domains", [])
            )
            self.active_domains_set = set(self.active_domains)
            self.whitelist_resolved = data.get("whitelist_resolved", {})
            self.whitelist_count = data.get("whitelist_count", len(self.active_domains))
            self.whitelist_expanded_count = data.get(
                "whitelist_expanded_count", len(self.active_domains)
            )
        else:
            self.active_domains = data.get(
                "active_domains",
                data.get("blocked_domains", self._get_blacklist_domains()),
            )
            self.active_domains_set = set(self.active_domains)
        self.session_base_domains = data.get("session_base_domains", [])

        if self.session_type == "pomodoro" and self.pomo_phase_expiry:
            if datetime.now() >= self.pomo_phase_expiry:
                logging.info("Pomodoro phase expired during downtime. Advancing.")
                self._transition_pomodoro_phase()
                logging.info(
                    "Resuming %s session — %d min remaining.",
                    self.mode,
                    int(remaining / 60),
                )
                return

        is_break = self.session_type == "pomodoro" and self.pomo_phase == "break"
        if self.mode == "whitelist":
            if not is_break:
                self._enforce_whitelist()
        else:
            if not is_break:
                self._enforce_block()
        logging.info(
            "Resuming %s session — %d min remaining.", self.mode, int(remaining / 60)
        )

    def _set_intent(self, cmd: dict) -> dict:
        intent = cmd.get("intent")
        intent_tasks = cmd.get("intent_tasks")
        with self.lock:
            if not self.active:
                return {
                    "status": "error",
                    "message": "No active session to set intent for.",
                }
            if intent is not None:
                self.intent = intent.strip() if intent else None
            if intent_tasks is not None:
                self.intent_tasks = intent_tasks
            self._persist_session_lock()
            self.broadcast_state_changed()
            logging.info("Session intent updated.")
            return {"status": "ok", "message": "Intent updated."}

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
        if mode not in ("blacklist", "whitelist"):
            return {"status": "error", "message": "Invalid mode."}
        with self.lock:
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
            if self.active:
                if not is_scheduling:
                    if self.session_type != cmd.get("session_type", "standard"):
                        return {"status": "error", "message": "Cannot merge different session types (e.g. standard and pomodoro)."}
                    if self.mode != mode:
                        return {"status": "error", "message": "Cannot merge different modes (whitelist/blacklist)."}

                    new_expiry = datetime.now() + timedelta(minutes=duration_minutes)
                    added_minutes = 0
                    if new_expiry > self.session_expiry:
                        added_minutes = int((new_expiry - self.session_expiry).total_seconds() / 60)
                        self.session_expiry = new_expiry
                        self._mono_session_end = get_continuous_time() + (duration_minutes * 60)
                        self.total_duration_seconds = max(self.total_duration_seconds, duration_minutes * 60)

                    # Merge groups
                    selected_groups = cmd.get("groups", [])
                    if selected_groups:
                        groups = self._load_groups()
                        new_domains = []
                        for gname in selected_groups:
                            if gname in groups:
                                new_domains.extend(groups[gname])
                        
                        if self.mode == "blacklist":
                            self.session_base_domains.extend(new_domains)
                            self.session_base_domains = list(set(d.strip().lower() for d in self.session_base_domains if d.strip() and "." in d))
                            
                            new_expanded = self._get_blacklist_domains(selected_groups)
                            self.active_domains.extend(new_expanded)
                            self.active_domains = list(set(self.active_domains))
                            self.active_domains_set = set(self.active_domains)
                            self._enforce_block()
                        # For whitelist, adding domains makes it less restrictive. 
                        # We skip expanding the whitelist during a merge to enforce strictness.

                    self._persist_session_lock()
                    self.broadcast_state_changed()
                    
                    msg = f"Session merged. Extended by {added_minutes} minutes." if added_minutes > 0 else "Session merged. Constraints updated."
                    logging.info(msg)
                    return {
                        "status": "ok",
                        "message": msg,
                        "mode": self.mode,
                        "domains_count": len(self.active_domains),
                        "expires_at": self.session_expiry.strftime("%H:%M:%S"),
                        "event": "merged",
                        "added_minutes": added_minutes
                    }
                else:
                    # Allow scheduling even if it overlaps. It will be merged when it executes.
                    pass

            if is_scheduling:
                end_time = start_time + timedelta(minutes=duration_minutes)

                # Check overlap with existing schedules
                for sch in self.schedules:
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
                self.schedules.append(
                    {
                        "start_time": start_time,
                        "end_time": end_time,
                        "mono_start": mono_start,
                        "cmd": sch_cmd,
                    }
                )
                self.schedules.sort(key=lambda x: x["start_time"])
                self._persist_session_lock()

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

            self.mode = mode
            self.session_type = cmd.get("session_type", "standard")
            self.intent = (
                cmd.get("intent", None) or self.intent
            )  # Keep existing intent if set via /api/intent and not provided in start
            self.intent_tasks = (
                cmd.get("intent_tasks", None) or getattr(self, "intent_tasks", [])
            )
            self.session_expiry = datetime.now() + timedelta(minutes=duration_minutes)
            self.active = True
            self.total_duration_seconds = duration_minutes * 60
            self.pending_unlock_at = None
            # Monotonic anchors
            now_mono = get_continuous_time()
            self._mono_session_end = now_mono + (duration_minutes * 60)
            self._mono_unlock_end = 0.0
            self._mono_last_intent_notif = now_mono

            # Extract pomodoro params from command
            if self.session_type == "pomodoro":
                self.pomo_focus_minutes = cmd.get("focus_minutes", 25)
                self.pomo_break_minutes = cmd.get("break_minutes", 5)
                self.pomo_total_cycles = cmd.get("cycles", 4)
                self.pomo_current_cycle = 1
                self.pomo_phase = "focus"
                self.pomo_phase_expiry = datetime.now() + timedelta(
                    minutes=self.pomo_focus_minutes
                )
                self._mono_pomo_phase_end = now_mono + (self.pomo_focus_minutes * 60)
                # S7: Override duration with exact Pomodoro calculation to prevent timer divergence
                pomo_total = (
                    self.pomo_focus_minutes + self.pomo_break_minutes
                ) * self.pomo_total_cycles
                duration_minutes = pomo_total
                self.total_duration_seconds = pomo_total * 60
                self.session_expiry = datetime.now() + timedelta(minutes=pomo_total)
                self._mono_session_end = now_mono + (pomo_total * 60)

            # MEDIUM #1 fix: Use self.session_expiry (post-Pomodoro override)
            # instead of the stale local `expiry` variable.
            session_data = {
                "started": datetime.now().isoformat(),
                "expiry": self.session_expiry.isoformat(),
                "mode": mode,
                "duration_minutes": duration_minutes,
                "session_type": self.session_type,
                "pomo_focus_minutes": self.pomo_focus_minutes,
                "pomo_break_minutes": self.pomo_break_minutes,
                "pomo_total_cycles": self.pomo_total_cycles,
                "pomo_current_cycle": self.pomo_current_cycle,
                "pomo_phase": self.pomo_phase,
                "pomo_phase_expiry": (
                    self.pomo_phase_expiry.isoformat()
                    if self.pomo_phase_expiry
                    else None
                ),
                "settings": self.settings,
                "mono_elapsed": 0.0,
                "last_persist_wall": datetime.now().isoformat(),
                "schedules": [
                    {
                        "start_time": sch["start_time"].isoformat(),
                        "end_time": sch["end_time"].isoformat(),
                        "cmd": sch["cmd"],
                    }
                    for sch in self.schedules
                ],
                "recurring_schedules": self.recurring_schedules,
            }
            self.remaining_seconds = duration_minutes * 60
            self.pending_unlock_seconds = 0
            if self.session_type == "pomodoro":
                self.pomo_phase_remaining = self.pomo_focus_minutes * 60

            selected_groups = cmd.get("groups", [])
            if mode == "whitelist":
                self.original_dns = self._get_current_dns_servers()
                if self.session_type == "rescue":
                    wl_domains = []
                else:
                    wl_domains = self._load_lists().get("whitelist", [])
                    if selected_groups:
                        groups = self._load_groups()
                        for gname in selected_groups:
                            if gname in groups:
                                wl_domains.extend(groups[gname])
                self.session_base_domains = list(
                    set(d.strip().lower() for d in wl_domains if d.strip())
                )

                # Whitelist mode: active_domains holds the ALLOW-list.
                if self.session_type == "rescue":
                    wl_domains_expanded = []
                else:
                    wl_domains_expanded = self._expand_whitelist_domains(wl_domains)
                self.active_domains = wl_domains_expanded
                self.active_domains_set = set(self.active_domains)
                count = len(wl_domains)
                expanded_count = len(wl_domains_expanded)
                self.whitelist_count = count
                self.whitelist_expanded_count = expanded_count
                session_data["active_domains"] = self.active_domains
                session_data["session_base_domains"] = self.session_base_domains
                session_data["original_dns"] = self.original_dns
                session_data["whitelist_count"] = count
                session_data["whitelist_expanded_count"] = expanded_count
                self._atomic_write_json(SESSION_LOCK, session_data)
                self._enforce_whitelist()
                if self.session_type == "pomodoro":
                    msg = f"Pomodoro (Whitelist): {count} domains allowed ({expanded_count} total with CDNs) for {self.pomo_total_cycles} cycles."
                elif self.session_type == "rescue":
                    msg = f"Rescue Throne activated: All sites blocked for {duration_minutes} min."
                else:
                    msg = f"Whitelist mode: {count} domains allowed ({expanded_count} total with CDNs) for {duration_minutes} min."
            else:
                # Build base domain list (for Chrome extension — no subdomain expansion)
                base_bl = self._load_lists().get("blacklist", [])
                if selected_groups:
                    groups = self._load_groups()
                    for gname in selected_groups:
                        if gname in groups:
                            base_bl.extend(groups[gname])
                if not base_bl:
                    for sites in DEFAULT_BLOCKLIST.values():
                        base_bl.extend(sites)
                self.session_base_domains = list(
                    set(d.strip().lower() for d in base_bl if d.strip() and "." in d)
                )
                # Build expanded domain list (for /etc/hosts — needs explicit subdomain entries)
                self.active_domains = self._get_blacklist_domains(selected_groups)
                self.active_domains_set = set(self.active_domains)
                session_data["active_domains"] = self.active_domains
                session_data["session_base_domains"] = self.session_base_domains
                self._atomic_write_json(SESSION_LOCK, session_data)
                self._enforce_block()
                count = len(self.active_domains)
                if self.session_type == "pomodoro":
                    msg = f"Pomodoro (Blacklist): {count} domains blocked for {self.pomo_total_cycles} cycles."
                else:
                    msg = f"Blacklist mode: {count} domains blocked for {duration_minutes} min."

            logging.info(
                "Session started (%s) — expires %s.",
                mode,
                self.session_expiry.strftime("%H:%M:%S"),
            )
            # Centralized sound + notification for ALL session starts
            if self.session_type == "rescue":
                self._play_sound("rescue")
                self._send_mac_notification(
                    "Rescue Mode",
                    f"All sites blocked for {duration_minutes} min. Stay focused!",
                )
            else:
                self._play_sound("start")
                self._send_mac_notification(
                    "Session Started",
                    msg,
                    subtitle=self.session_expiry.strftime("Expires at %H:%M"),
                )
            self.broadcast_state_changed()
            return {
                "status": "ok",
                "message": msg,
                "mode": mode,
                "domains_count": count,
                "expires_at": self.session_expiry.strftime("%H:%M:%S"),
            }

    def _request_stop(self, passphrase: str) -> dict:
        with self.lock:
            if not self.active:
                return {"status": "ok", "message": "No active session."}
            # Rate limit passphrase attempts
            now_mono = time.monotonic()
            if self._passphrase_attempts >= 5:
                cooldown = min(60, 2 ** (self._passphrase_attempts - 5))
                elapsed = now_mono - self._last_attempt_time
                if elapsed < cooldown:
                    wait = int(cooldown - elapsed)
                    logging.warning("Passphrase rate-limited. %ds remaining.", wait)
                    return {
                        "status": "error",
                        "message": f"Too many attempts. Wait {wait}s.",
                    }
            self._last_attempt_time = now_mono
            if not self._verify_passphrase(passphrase):
                self._passphrase_attempts += 1
                logging.warning(
                    "Invalid kill-switch passphrase attempt (#%d).",
                    self._passphrase_attempts,
                )
                return {"status": "error", "message": "Invalid passphrase."}
            # Reset rate limiter on success
            self._passphrase_attempts = 0
            if self.pending_unlock_at:
                now_mono = get_continuous_time()
                rem_mono = self._mono_unlock_end - now_mono
                if rem_mono > 0:
                    return {
                        "status": "pending",
                        "message": f"Unlock already pending. {int(rem_mono/60)}m {int(rem_mono%60)}s remaining.",
                    }
            self.pending_unlock_at = datetime.now() + timedelta(
                seconds=DELAYED_UNLOCK_S
            )
            self._mono_unlock_end = get_continuous_time() + DELAYED_UNLOCK_S
            self._persist_session_lock()
            self._play_sound("unlock")
            self.broadcast_state_changed()
            unlock_str = self.pending_unlock_at.strftime("%H:%M:%S")
            logging.info("Delayed unlock requested — scheduled at %s.", unlock_str)
            return {
                "status": "pending",
                "message": f"Unlock request accepted. Releases at {unlock_str} (20-min delay).",
            }

    def _cmd_cancel_schedule(self, cmd: dict) -> dict:
        """Cancel an upcoming scheduled session."""
        with self.lock:
            if not self.schedules:
                return {"status": "error", "message": "No scheduled sessions to cancel."}
                
            index = cmd.get("index")
            start_time_iso = cmd.get("start_time_iso")
            
            # Helper function to check if cancellation is allowed
            def _can_cancel(sch):
                remaining = (sch["start_time"] - datetime.now()).total_seconds()
                return remaining > 20 * 60
            
            if index is not None:
                try:
                    idx = int(index)
                    if 0 <= idx < len(self.schedules):
                        if not _can_cancel(self.schedules[idx]):
                            return {"status": "error", "message": "Cannot cancel schedule with 20 minutes or less remaining."}
                        sch = self.schedules.pop(idx)
                        self._persist_session_lock()
                        self.broadcast_state_changed()
                        return {"status": "ok", "message": f"Cancelled schedule for {sch['start_time'].strftime('%H:%M')}."}
                    else:
                        return {"status": "error", "message": "Invalid schedule index."}
                except ValueError:
                    return {"status": "error", "message": "Invalid index format."}
            elif start_time_iso:
                for i, sch in enumerate(self.schedules):
                    if sch["start_time"].isoformat() == start_time_iso:
                        if not _can_cancel(sch):
                            return {"status": "error", "message": "Cannot cancel schedule with 20 minutes or less remaining."}
                        self.schedules.pop(i)
                        self._persist_session_lock()
                        self.broadcast_state_changed()
                        return {"status": "ok", "message": f"Cancelled schedule for {sch['start_time'].strftime('%H:%M')}."}
                return {"status": "error", "message": "Schedule not found."}
                
            return {"status": "error", "message": "Must provide index or start_time_iso to cancel."}

    def _cmd_get_recurring_schedules(self) -> dict:
        with self.lock:
            return {"status": "ok", "recurring_schedules": self.recurring_schedules}

    def _cmd_add_recurring_schedule(self, cmd: dict) -> dict:
        import uuid
        with self.lock:
            days = cmd.get("days_of_week", [])
            start_time = cmd.get("start_time", "")
            duration = cmd.get("duration_minutes", 120)
            mode = cmd.get("mode", "blacklist")
            groups = cmd.get("groups", [])
            session_type = cmd.get("session_type", "standard")

            if not days or not start_time:
                return {"status": "error", "message": "days_of_week and start_time are required."}

            new_rule = {
                "id": str(uuid.uuid4()),
                "days_of_week": days,
                "start_time": start_time,
                "duration_minutes": duration,
                "mode": mode,
                "groups": groups,
                "session_type": session_type,
                "last_triggered": ""
            }
            # Persist pomodoro params if applicable
            if session_type == "pomodoro":
                new_rule["focus_minutes"] = cmd.get("focus_minutes", 25)
                new_rule["break_minutes"] = cmd.get("break_minutes", 5)
                new_rule["cycles"] = cmd.get("cycles", 4)
            self.recurring_schedules.append(new_rule)
            self._persist_session_lock()
            self.broadcast_state_changed()
            return {"status": "ok", "message": "Recurring schedule added.", "rule": new_rule}

    def _cmd_remove_recurring_schedule(self, cmd: dict) -> dict:
        with self.lock:
            rule_id = cmd.get("id")
            if not rule_id:
                return {"status": "error", "message": "Rule ID is required."}
            
            initial_len = len(self.recurring_schedules)
            self.recurring_schedules = [r for r in self.recurring_schedules if r["id"] != rule_id]
            if len(self.recurring_schedules) < initial_len:
                self._persist_session_lock()
                self.broadcast_state_changed()
                return {"status": "ok", "message": "Recurring schedule removed."}
            return {"status": "error", "message": "Recurring schedule not found."}

    def _get_status(self) -> dict:
        with self.lock:
            schedules_res = []
            for sch in self.schedules:
                schedules_res.append(
                    {
                        "starts_at": sch["start_time"].strftime("%Y-%m-%d %I:%M %p"),
                        "start_time_iso": sch["start_time"].isoformat(),
                        "mode": sch["cmd"].get("mode", "blacklist"),
                        "session_type": sch["cmd"].get("session_type", "standard"),
                        "duration_minutes": sch["cmd"].get("duration_minutes", 120),
                    }
                )

            if not self.active:
                return {
                    "status": "ok",
                    "active": False,
                    "state": "idle",
                    "mode": None,
                    "message": "Idle.",
                    "schedules": schedules_res,
                    "recurring_schedules": self.recurring_schedules,
                }

            # C3: Use monotonic time for all remaining-seconds fields
            now_mono = get_continuous_time()
            rem = int(max(0, self._mono_session_end - now_mono))

            # Safety net: if session is expired but watchdog hasn't cleaned up,
            # trigger cleanup now to prevent stuck sessions
            if (
                rem <= 0
                and self._mono_session_end > 0
                and now_mono >= self._mono_session_end
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
                    "recurring_schedules": self.recurring_schedules,
                }
            result = {
                "status": "ok",
                "active": True,
                "mode": self.mode,
                "expires_at": self.session_expiry.strftime("%H:%M:%S"),
                "remaining_seconds": rem,
                "total_duration_seconds": self.total_duration_seconds,
                "domains_count": (
                    len(self.active_domains)
                    if self.mode == "blacklist"
                    else self.whitelist_count
                ),
                "whitelist_total_count": (
                    None if self.mode == "blacklist" else self.whitelist_expanded_count
                ),
                "pending_unlock": (
                    self.pending_unlock_at.strftime("%H:%M:%S")
                    if self.pending_unlock_at
                    else None
                ),
                "pending_unlock_seconds": (
                    int(max(0, self._mono_unlock_end - now_mono))
                    if self._mono_unlock_end > 0
                    else None
                ),
                "session_type": self.session_type,
                "schedules": schedules_res,
                "recurring_schedules": self.recurring_schedules,
                "intent": self.intent,
                "intent_tasks": getattr(self, "intent_tasks", []),
            }
            if self.session_type == "pomodoro":
                result["pomo_phase"] = self.pomo_phase
                result["pomo_current_cycle"] = self.pomo_current_cycle
                result["pomo_total_cycles"] = self.pomo_total_cycles
                result["pomo_focus_minutes"] = self.pomo_focus_minutes
                result["pomo_break_minutes"] = self.pomo_break_minutes
                if self.pomo_phase_expiry:
                    time_str = self.pomo_phase_expiry.strftime("%I:%M %p").lstrip("0")
                    result["pomo_phase_expiry_time"] = time_str
                if self._mono_pomo_phase_end > 0:
                    phase_rem = int(max(0, self._mono_pomo_phase_end - now_mono))
                    result["pomo_phase_remaining"] = phase_rem
                    result["pomo_phase_total"] = (
                        self.pomo_focus_minutes
                        if self.pomo_phase == "focus"
                        else self.pomo_break_minutes
                    ) * 60
            return result

    # ── Blacklist Enforcement ─────────────────────────────────────────────────

    def _get_blacklist_domains(self, selected_groups: list[str] = None) -> list[str]:
        lists = self._load_lists()
        bl = lists.get("blacklist", [])

        if selected_groups:
            groups = self._load_groups()
            for gname in selected_groups:
                if gname in groups:
                    bl.extend(groups[gname])

        if bl:
            expanded = set()
            for d in bl:
                domain = d.strip().lower()
                # L4: Skip domains without a TLD (validated at input time)
                if "." not in domain:
                    continue

                expanded.add(domain)

                # Special case: YouTube needs aggressive asset blocking
                if "youtube.com" in domain or "youtu.be" in domain:
                    for asset in ["googlevideo.com", "ytimg.com", "ggpht.com"]:
                        expanded.add(asset)
                        for prefix in [
                            "www.",
                            "r1---",
                            "r2---",
                            "r3---",
                            "r4---",
                            "r5---",
                        ]:
                            expanded.add(prefix + asset)

                # Expand with common subdomain prefixes for broader /etc/hosts coverage
                if domain.startswith(COMMON_PREFIXES):
                    for prefix in COMMON_PREFIXES:
                        if not domain.startswith(prefix):
                            expanded.add(prefix + domain)
                else:
                    for prefix in COMMON_PREFIXES:
                        expanded.add(prefix + domain)
            return sorted(expanded)
        # Fallback to hard-coded default
        domains = []
        for sites in DEFAULT_BLOCKLIST.values():
            domains.extend(sites)
        return domains

    def _expand_whitelist_domains(self, domains: list[str]) -> list[str]:
        """Expands a whitelist to include CDN infrastructure and site-specific bundles."""
        expanded = set()

        # Layer 1: Always allow common CDN/infrastructure domains
        expanded.update(CDN_INFRASTRUCTURE_DOMAINS)

        # Add user domains and Layer 2 bundles
        for d in domains:
            domain = d.strip().lower()
            if not domain:
                continue

            expanded.add(domain)

            # Strip www. for bundle matching
            root = domain
            if root.startswith("www."):
                root = root[4:]

            if root in SITE_BUNDLES:
                for bundle_dom in SITE_BUNDLES[root]:
                    expanded.add(bundle_dom)

        # Log the expansion
        before = len(set(d.strip().lower() for d in domains if d.strip()))
        after = len(expanded)
        if after > before:
            logging.info(
                "Whitelist auto-expanded: %d user domains -> %d total domains (added %d CDN/bundle domains)",
                before,
                after,
                after - before,
            )

        return sorted(expanded)

    def _enforce_block(self):
        """Blacklist mode: inject 127.0.0.1 entries into /etc/hosts."""
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
            self._clear_browser_caches()
            self._flush_dns()
            self.hosts_hash = hashlib.sha256(content.encode()).hexdigest()
            # ⚡ Cache stat for cheap watchdog pre-check (avoids full read+hash every 250ms)
            try:
                st = HOSTS_PATH.stat()
                self._hosts_stat = (st.st_mtime, st.st_size)
            except OSError:
                self._hosts_stat = None
        except Exception as exc:
            logging.error("enforce_block failed: %s", exc)

    def _build_blacklist_block(self) -> str:
        lines = [
            MARKER_BEGIN,
            "# Mode: BLACKLIST",
            f"# Expires: {self.session_expiry.isoformat()}",
        ]
        for domain in self.active_domains:
            lines.append(f"127.0.0.1\t{domain}")
            lines.append(f"::1\t\t{domain}")
        # Block DNS-over-HTTPS providers to prevent browser bypass
        lines.append("# DoH providers (anti-bypass)")
        for domain in DOH_BLOCK_DOMAINS:
            lines.append(f"127.0.0.1\t{domain}")
            lines.append(f"::1\t\t{domain}")
        lines.append(MARKER_END)
        return "\n".join(lines)

    # ── Whitelist Enforcement ─────────────────────────────────────────────────

    @staticmethod
    def _get_network_services() -> list[str]:
        """Get all network service names, including hardware-disabled ones.

        We include *-prefixed services because they can become active
        mid-session (e.g., plugging in Ethernet).
        """
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
                return []

            lines = out.stdout.strip().split("\n")
            # First line is always the header: "An asterisk (*) denotes..."
            services = []
            for line in lines[1:]:
                stripped = line.strip().lstrip("*").strip()
                if stripped:
                    services.append(stripped)
            return services
        except Exception as exc:
            logging.error("Failed to get network services: %s", exc)
            return []

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
                return svc, dns_out.stdout.strip()

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
        """Whitelist mode: redirect DNS to local proxy + block DoH in /etc/hosts."""
        try:
            if not self.dns_proxy:
                self.dns_proxy = LocalDNSProxy(self)
                self.dns_proxy.start()
            self._set_dns_to_localhost()
            # M4: Block DoH providers in /etc/hosts for whitelist mode too
            self._enforce_doh_block()
            self._enforce_firewall(True, upstream_dns=self.dns_proxy.upstream_dns)
            self._clear_browser_caches()
            self._flush_dns()
            logging.info("Whitelist enforced via Local DNS Proxy.")
        except Exception as exc:
            logging.error("enforce_whitelist failed: %s", exc)

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
                f"# Expires: {self.session_expiry.isoformat()}",
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
            if not self.original_dns:
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
            for svc, dns_str in self.original_dns.items():
                try:
                    if "There aren't any DNS Servers" in dns_str or not dns_str.strip():
                        result = subprocess.run(
                            ["networksetup", "-setdnsservers", svc, "empty"],
                            capture_output=True,
                            timeout=5,
                        )
                    else:
                        servers = dns_str.strip().split("\n")
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
            logging.info("DNS servers restored for %d services.", success_count)
        except Exception as exc:
            logging.error("Critical failure restoring DNS: %s", exc)

    # ── Common Helpers ────────────────────────────────────────────────────────

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

    def _send_mac_notification(self, title: str, message: str, subtitle: str = None):
        """Send a macOS system notification via osascript using positional arguments for safety."""
        try:
            # We use positional arguments (argv) to prevent command injection.
            # argv[1] = message, argv[2] = title, argv[3] = subtitle (if present)
            
            # Helper to generate the core notification logic
            def get_notif_logic(wrapped_in_app: bool = False):
                indent = "    " if wrapped_in_app else "  "
                logic = f'{indent}set msg to item 1 of argv\n'
                logic += f'{indent}set t to item 2 of argv\n'
                logic += f'{indent}if (count of argv) is 3 then\n'
                logic += f'{indent}  set sub to item 3 of argv\n'
                logic += f'{indent}  display notification msg with title t subtitle sub sound name "Glass"\n'
                logic += f'{indent}else\n'
                logic += f'{indent}  display notification msg with title t sound name "Glass"\n'
                logic += f'{indent}end if\n'

                if wrapped_in_app:
                    return f'  tell application "ForcedFocusBar"\n{logic}  end tell\n'
                return logic

            # script for fallback (direct notification)
            script = f'on run argv\n{get_notif_logic(False)}end run'
            
            # app_script for primary attempt (linked with ForcedFocusBar)
            app_script = f'on run argv\n{get_notif_logic(True)}end run'

            args = [message, title]
            if subtitle:
                args.append(subtitle)

            # Try to link with Mac Menu app
            proc = subprocess.run(
                ["osascript", "-e", app_script] + args, capture_output=True, timeout=2
            )

            if proc.returncode != 0:
                # Fallback to direct notification if the menu app is not running/available
                subprocess.run(
                    ["osascript", "-e", script] + args, capture_output=True, timeout=2
                )
        except Exception as e:
            logging.error("Failed to send notification: %s", e)

    def _enforce_current_mode(self):
        if self.mode == "whitelist":
            self._enforce_whitelist()
        else:
            self._enforce_block()

    def _remove_block(self):
        """Remove blocking from /etc/hosts without ending the session."""
        try:
            subprocess.run(
                ["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5
            )
            content = self._strip_block(HOSTS_PATH.read_text())
            HOSTS_PATH.write_text(content)
            self.hosts_hash = None
            if self.mode == "whitelist":
                if self.dns_proxy:
                    self.dns_proxy.stop()
                    self.dns_proxy = None
                self._restore_dns()
            self._flush_dns()
        except Exception as exc:
            logging.error("_remove_block error: %s", exc)

    def _play_sound(self, category: str):
        """Play a configured sound file using macOS afplay."""
        setting_key = f"sound_{category.lower().replace(' ', '_')}"
        filename = self.settings.get(setting_key)

        if not filename:
            # Fallback if the specific key doesn't exist
            return

        sound_path = WEB_DIR / "sounds" / filename
        if sound_path.exists():
            subprocess.Popen(
                ["afplay", str(sound_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def _transition_pomodoro_phase(self):
        if self.pomo_phase == "focus":
            self.pomo_phase = "break"
            self.pomo_phase_remaining = self.pomo_break_minutes * 60
            self.pomo_phase_expiry = datetime.now() + timedelta(
                seconds=self.pomo_phase_remaining
            )
            self._mono_pomo_phase_end = (
                get_continuous_time() + self.pomo_phase_remaining
            )
            self._remove_block()
            self._persist_session_lock()
            self._play_sound("break")
            self._send_mac_notification(
                "Break Started",
                f"Take a {self.pomo_break_minutes}m break! Good job focusing.",
            )
            logging.info(
                "Pomodoro: cycle %d focus ended. Break for %dm.",
                self.pomo_current_cycle,
                self.pomo_break_minutes,
            )
        else:
            self.pomo_current_cycle += 1
            if self.pomo_current_cycle > self.pomo_total_cycles:
                logging.info(
                    "Pomodoro: all %d cycles complete.", self.pomo_total_cycles
                )
                self._cleanup_session()
                return
            self.pomo_phase = "focus"
            self.pomo_phase_remaining = self.pomo_focus_minutes * 60
            self.pomo_phase_expiry = datetime.now() + timedelta(
                seconds=self.pomo_phase_remaining
            )
            self._mono_pomo_phase_end = (
                get_continuous_time() + self.pomo_focus_minutes * 60
            )
            self._enforce_current_mode()
            self._persist_session_lock()
            self._play_sound("start")
            self._send_mac_notification(
                "Focus Time",
                f"Cycle {self.pomo_current_cycle} of {self.pomo_total_cycles} has started.",
            )
            logging.info(
                "Pomodoro: cycle %d/%d focus started.",
                self.pomo_current_cycle,
                self.pomo_total_cycles,
            )
        self.broadcast_state_changed()

    def _cleanup_session(self):
        logging.info("Cleaning up session (mode=%s)...", self.mode)
        self._play_sound("end")
        self._send_mac_notification(
            "Session Complete", "Great job! Your ForcedFocus session has ended."
        )
        was_whitelist = self.mode == "whitelist"

        try:
            subprocess.run(
                ["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5
            )
            content = self._strip_block(HOSTS_PATH.read_text())
            HOSTS_PATH.write_text(content)
            if was_whitelist:
                if self.dns_proxy:
                    self.dns_proxy.stop()
                    self.dns_proxy = None
                self._restore_dns()
            self._enforce_firewall(False)
            self._enforce_browser_policies(False)
            self._flush_dns()
        except Exception as exc:
            logging.error("cleanup_session error: %s", exc)

        self.active = False

        if getattr(self, "schedules", []) or self.recurring_schedules:
            self._persist_session_lock()
        else:
            SESSION_LOCK.unlink(missing_ok=True)

        self.hosts_hash = None
        self._hosts_stat = None
        self.session_expiry = None
        self.pending_unlock_at = None
        self.active_domains = []
        self.active_domains_set = set(self.active_domains)
        self.session_base_domains = []
        self.original_dns = {}
        self.whitelist_resolved = {}
        self.whitelist_count = 0
        self.whitelist_expanded_count = 0
        self.total_duration_seconds = 0
        self.mode = "blacklist"
        self.session_type = "standard"
        self.pomo_focus_minutes = 0
        self.pomo_break_minutes = 0
        self.pomo_total_cycles = 0
        self.pomo_current_cycle = 0

        self._reenforce_flag = False
        self.pomo_phase = "focus"
        self.pomo_phase_expiry = None
        self._mono_session_end = 0.0
        self._mono_unlock_end = 0.0
        self._mono_pomo_phase_end = 0.0
        self._passphrase_attempts = 0
        self.intent = None
        self.intent_tasks = []
        self.broadcast_state_changed()
        # Do NOT clear schedules on session cleanup!
        logging.info("Session ended. Hosts restored. DNS flushed.")
        # Re-enforce permanent blocks (session cleanup may have modified /etc/hosts)
        if self.perma_blocklist:
            self._enforce_perma_block()

    @staticmethod
    def _flush_dns():
        """Aggressive DNS flush — clears macOS cache and forces browsers to re-resolve."""
        subprocess.run(["dscacheutil", "-flushcache"], capture_output=True, timeout=5)
        subprocess.run(
            ["killall", "-HUP", "mDNSResponder"], capture_output=True, timeout=5
        )
        # Full mDNSResponder reset (clears all cached records)
        subprocess.run(
            ["killall", "-USR1", "mDNSResponder"], capture_output=True, timeout=5
        )

    def _clear_browser_caches(self):
        """Deep clean of browser caches and service workers across all profiles.

        Can be disabled via settings: {"aggressive_cache_clear": false}
        """
        if not self.settings.get("aggressive_cache_clear", True):
            logging.debug("Aggressive cache clearing disabled by settings.")
            return
        try:
            user_file = Path("/etc/forcefocus/user")
            if not user_file.exists():
                return
            username = user_file.read_text().strip()
            home = Path(f"/Users/{username}")
            if not home.exists():
                return

            import shutil

            # 1. Targeted fixed paths
            all_paths = [
                home / "Library/Caches/com.apple.Safari",
                home / "Library/Safari/ServiceWorkers",
                home / "Library/Caches/Firefox",
                home / "Library/Containers/com.apple.Safari/Data/Library/Caches",
                home / "Library/Containers/com.apple.Safari/Data/Library/WebKit",
            ]

            # 2. Chromium browsers (Chrome, Edge, Brave, Dia) - handle all profiles
            chromium_bases = [
                home / "Library/Application Support/Google/Chrome",
                home / "Library/Application Support/Microsoft Edge",
                home / "Library/Application Support/BraveSoftware/Brave-Browser",
                home / "Library/Application Support/Dia",
                home / "Library/Caches/Google/Chrome",
                home / "Library/Caches/Microsoft Edge",
                home / "Library/Caches/BraveSoftware/Brave-Browser",
                home / "Library/Caches/Dia",
            ]

            for base in chromium_bases:
                if not base.exists():
                    continue

                # Check for nested 'User Data' folder (Dia uses this)
                scan_targets = [base]
                user_data = base / "User Data"
                if user_data.exists():
                    scan_targets.append(user_data)

                for target in scan_targets:
                    try:
                        for profile_dir in target.iterdir():
                            if profile_dir.is_dir() and (
                                profile_dir.name == "Default"
                                or profile_dir.name.startswith("Profile")
                            ):
                                all_paths.append(profile_dir / "Service Worker")
                                all_paths.append(profile_dir / "Cache")
                                all_paths.append(profile_dir / "Code Cache")
                                all_paths.append(profile_dir / "IndexedDB")
                    except Exception:
                        continue

            for p in all_paths:
                if p.exists():
                    try:
                        if p.is_dir():
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            p.unlink(missing_ok=True)
                    except Exception:
                        pass

            logging.info("Deep browser cache clean completed for user '%s'.", username)
        except Exception as exc:
            logging.error("Failed to clear browser caches: %s", exc)

    def _enforce_firewall(self, enable: bool, upstream_dns: str = None):
        """Nuclear firewall enforcement: Blocks QUIC, DoT, and known DoH IPs."""
        try:
            if enable:
                # 1. Enable PF
                subprocess.run(["pfctl", "-e"], capture_output=True, timeout=5)
                # 2. Construct nuclear ruleset
                rules = [
                    "pass out quick on lo0 all",  # Exempt localhost (for Local DNS Proxy & Web UI)
                    "pass in quick on lo0 all",
                ]

                # Exempt the DNS proxy's upstream resolver
                if upstream_dns:
                    rules.append(
                        f"pass out quick proto {{tcp udp}} from any to {upstream_dns} port 53"
                    )

                rules.extend(
                    [
                        "block return out proto udp from any to any port 443",  # QUIC bypass
                        "block return out proto {tcp udp} from any to any port 853",  # DNS-over-TLS bypass
                        "block return out proto {tcp udp} from any to any port {1080 8080 3128 9050 9051}",  # Proxy/Tor bypass
                    ]
                )

                # Block known DoH provider IPs to prevent direct IP-based bypass (only block port 443, not all ports)
                for ip in DOH_IPS:
                    rules.append(
                        f"block return out proto tcp from any to {ip} port 443"
                    )

                rules_str = "\n".join(rules) + "\n"
                process = subprocess.Popen(
                    ["pfctl", "-a", "forcefocus", "-f", "-"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                process.communicate(input=rules_str)

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
            else:
                subprocess.run(
                    ["pfctl", "-a", "forcefocus", "-F", "all"],
                    capture_output=True,
                    timeout=5,
                )
                logging.info("Firewall: rules cleared.")
        except Exception as exc:
            logging.error("Firewall enforcement failed: %s", exc)

    def _enforce_browser_policies(self, enable: bool):
        """Inject managed policies into browsers to block internal settings/extensions."""
        try:
            # Paths for managed preferences
            managed_pref_dir = Path("/Library/Managed Preferences")
            managed_pref_dir.mkdir(parents=True, exist_ok=True)

            targets = [
                managed_pref_dir / "com.google.Chrome.plist",
                managed_pref_dir / "com.microsoft.Edge.plist",
            ]

            if enable:
                # 1. Chrome/Edge Managed Policies
                # We use plutil to create a clean XML plist
                import plistlib

                policy_data = {"URLBlocklist": BROWSER_RESISTANCE_URLS}
                plist_bytes = plistlib.dumps(policy_data)

                for path in targets:
                    path.write_bytes(plist_bytes)
                    # Force ownership to root
                    os.chmod(path, 0o644)

                # 2. Firefox Policies (distribution/policies.json)
                # We try to find Firefox in common locations
                ff_paths = [
                    Path(
                        "/Applications/Firefox.app/Contents/Resources/distribution/policies.json"
                    ),
                    Path(
                        "/Applications/Firefox.app/Contents/MacOS/distribution/policies.json"
                    ),
                ]
                ff_policy = {
                    "policies": {
                        "BlockAboutConfig": True,
                        "BlockAboutAddons": True,
                        "BlockAboutSupport": True,
                    }
                }
                for p in ff_paths:
                    try:
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_text(json.dumps(ff_policy, indent=2))
                    except Exception:
                        pass

                logging.info(
                    "Browser Policies: Resistance URLs blocked via managed preferences."
                )
            else:
                # Cleanup policies
                for path in targets:
                    path.unlink(missing_ok=True)

                # Firefox cleanup
                ff_paths = [
                    Path(
                        "/Applications/Firefox.app/Contents/Resources/distribution/policies.json"
                    ),
                    Path(
                        "/Applications/Firefox.app/Contents/MacOS/distribution/policies.json"
                    ),
                ]
                for p in ff_paths:
                    p.unlink(missing_ok=True)

                logging.info("Browser Policies: Managed preferences cleared.")
        except Exception as exc:
            logging.error("Browser policy enforcement failed: %s", exc)

    def _kill_vpns(self):
        """Terminate known VPN processes that could bypass host-file blocking."""
        if not VPN_PROCESSES:
            return
        try:
            # Targeted killall for all processes at once to reduce subprocess overhead
            # Targeted killall
            subprocess.run(
                ["killall", "-9"] + VPN_PROCESSES, capture_output=True, timeout=2
            )
        except Exception:
            pass

    def _kill_restricted_apps(self):
        """Terminate restricted processes (VPNs, bypass browsers, tools) during active sessions."""
        if not RESTRICTED_PROCESSES:
            return
        try:
            subprocess.run(
                ["killall", "-9"] + RESTRICTED_PROCESSES, capture_output=True, timeout=2
            )
        except subprocess.TimeoutExpired:
            pass
        except OSError:
            pass

    # ── Watchdog ──────────────────────────────────────────────────────────────

    def _persist_session_lock(self):
        """Re-create session.lock from in-memory state."""
        data = {
            "schedules": [
                {
                    "start_time": sch["start_time"].isoformat(),
                    "end_time": sch["end_time"].isoformat(),
                    "cmd": sch["cmd"],
                }
                for sch in self.schedules
            ],
            "recurring_schedules": self.recurring_schedules
        }
        if self.active and self.session_expiry:
            data.update(
                {
                    "started": (
                        self.session_expiry
                        - timedelta(seconds=self.total_duration_seconds)
                    ).isoformat(),
                    "expiry": self.session_expiry.isoformat(),
                    "duration_minutes": self.total_duration_seconds // 60,
                    "mode": self.mode,
                    "session_type": self.session_type,
                    "mono_elapsed": get_continuous_time()
                    - (self._mono_session_end - self.total_duration_seconds),
                    "last_persist_wall": datetime.now().isoformat(),
                    "settings": self.settings,
                }
            )
            if self.pending_unlock_at:
                data["pending_unlock_at"] = self.pending_unlock_at.isoformat()

            if self.session_type == "pomodoro":
                data.update(
                    {
                        "pomo_focus_minutes": self.pomo_focus_minutes,
                        "pomo_break_minutes": self.pomo_break_minutes,
                        "pomo_total_cycles": self.pomo_total_cycles,
                        "pomo_current_cycle": self.pomo_current_cycle,
                        "pomo_phase": self.pomo_phase,
                        "pomo_phase_expiry": (
                            self.pomo_phase_expiry.isoformat()
                            if self.pomo_phase_expiry
                            else None
                        ),
                    }
                )
            if self.mode == "whitelist":
                data["original_dns"] = self.original_dns
                data["whitelist_resolved"] = self.whitelist_resolved
                data["active_domains"] = self.active_domains
                data["whitelist_count"] = getattr(self, "whitelist_count", 0)
                data["whitelist_expanded_count"] = getattr(
                    self, "whitelist_expanded_count", 0
                )
            else:
                data["active_domains"] = self.active_domains
            data["session_base_domains"] = getattr(self, "session_base_domains", [])
            data["intent"] = getattr(self, "intent", None)
            data["intent_tasks"] = getattr(self, "intent_tasks", [])

        try:
            self._atomic_write_json(SESSION_LOCK, data)
            logging.info("session.lock re-created from memory.")
        except Exception as exc:
            logging.error("Failed to persist session.lock: %s", exc)

    def _load_settings(self):
        """Load settings from JSON, merging with defaults."""
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text())
                # Merge defaults to ensure new settings exist
                final = DEFAULT_SETTINGS.copy()
                final.update(data)
                return final
        except Exception as exc:
            logging.error("Failed to load settings: %s", exc)
        return DEFAULT_SETTINGS.copy()

    def _save_settings(self, new_settings):
        """Save settings to JSON."""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            self._atomic_write_json(SETTINGS_FILE, new_settings, indent=2)
            self.settings = new_settings
            return True
        except Exception as exc:
            logging.error("Failed to save settings: %s", exc)
            return False

    def _cmd_get_sounds(self) -> dict:
        """List all available sound files in web/sounds."""
        sounds_dir = WEB_DIR / "sounds"
        if not sounds_dir.exists():
            return {"status": "ok", "sounds": []}
        try:
            files = [f.name for f in sounds_dir.iterdir() if f.suffix.lower() == ".mp3"]
            return {"status": "ok", "sounds": sorted(files)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _cmd_get_settings(self) -> dict:
        return {"status": "ok", "settings": self.settings}

    def _cmd_save_settings(self, cmd: dict) -> dict:
        new_settings = cmd.get("settings", {})
        if not new_settings:
            return {"status": "error", "message": "No settings provided."}
        if self._save_settings(new_settings):
            return {
                "status": "ok",
                "message": "Settings saved.",
                "settings": self.settings,
            }
        return {"status": "error", "message": "Failed to save settings."}

    def _cmd_delete_sound(self, cmd: dict) -> dict:
        filename = cmd.get("filename", "").strip()
        if not filename:
            return {"status": "error", "message": "No filename provided."}

        # Sanitize and check path
        safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ")
        target_path = WEB_DIR / "sounds" / safe_name

        try:
            target_path.resolve().relative_to(WEB_DIR.resolve() / "sounds")
            if target_path.exists():
                target_path.unlink()
                logging.info("User deleted sound: %s", safe_name)
                return {"status": "ok", "message": f"Sound '{safe_name}' deleted."}
            return {"status": "error", "message": "File not found."}
        except Exception as exc:
            return {"status": "error", "message": f"Delete failed: {str(exc)}"}

    def _cmd_upload_sound(self, cmd: dict) -> dict:
        MAX_SOUND_SIZE = 5 * 1024 * 1024  # 5MB limit per sound file
        filename = cmd.get("filename", "").strip()
        data_b64 = cmd.get("data", "")

        if not filename or not data_b64:
            return {"status": "error", "message": "Missing filename or data."}

        if not filename.lower().endswith(".mp3"):
            return {"status": "error", "message": "Only .mp3 files are allowed."}

        # Sanitize filename
        safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ")
        if not safe_name:
            return {"status": "error", "message": "Invalid filename."}
        target_path = WEB_DIR / "sounds" / safe_name

        # Path traversal protection (matches _cmd_delete_sound)
        try:
            sounds_dir = (WEB_DIR / "sounds").resolve()
            target_path.resolve().relative_to(sounds_dir)
        except ValueError:
            return {"status": "error", "message": "Invalid file path."}

        try:
            # Ensure sounds dir exists
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Decode and validate size
            audio_data = base64.b64decode(data_b64)
            if len(audio_data) > MAX_SOUND_SIZE:
                return {
                    "status": "error",
                    "message": f"File too large (max {MAX_SOUND_SIZE // (1024*1024)}MB).",
                }

            target_path.write_bytes(audio_data)

            logging.info(
                "User uploaded new sound: %s (%d bytes)", safe_name, len(audio_data)
            )
            return {
                "status": "ok",
                "message": f"Sound '{safe_name}' uploaded successfully.",
            }
        except Exception as exc:
            logging.error("Upload error: %s", exc)
            return {"status": "error", "message": f"Upload failed: {str(exc)}"}

    def _verify_dns_redirect(self):
        """Whitelist mode: verify DNS still points to 127.0.0.1, re-enforce if tampered."""
        try:
            services = self._get_network_services()
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
                            and "::1" not in current_dns
                            and "aren't any" not in current_dns.lower()
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

    def _watchdog_loop(self):
        logging.info(
            "Watchdog thread started (interval=%.0fms).", WATCHDOG_INTERVAL * 1000
        )
        self._wd_dns_counter = 0
        self._wd_persist_counter = 0
        while True:
            time.sleep(WATCHDOG_INTERVAL)
            try:
                self._watchdog_tick()
            except Exception as exc:
                logging.error("Watchdog tick error (non-fatal): %s", exc, exc_info=True)

    def _watchdog_tick(self):
        cmd_to_start = None

        with self.lock:
            now_mono = get_continuous_time()
            now = datetime.now()

            # 1. Evaluate recurring schedules every ~10 seconds (to avoid missing minute boundaries due to tick alignment/sleep)
            is_recurring_trigger = False
            if self.recurring_schedules:
                if now_mono - self._mono_last_recurring_check >= 10.0:
                    self._mono_last_recurring_check = now_mono
                    current_day = now.weekday()
                    current_time = now.strftime("%H:%M")
                    
                    for r_sch in self.recurring_schedules:
                        if current_day in r_sch.get("days_of_week", []):
                            if r_sch.get("start_time") == current_time:
                                last_triggered = r_sch.get("last_triggered")
                                if last_triggered != now.strftime("%Y-%m-%d"):
                                    r_sch["last_triggered"] = now.strftime("%Y-%m-%d")
                                    cmd_to_start = {
                                        "action": "start",
                                        "duration_minutes": r_sch.get("duration_minutes", 120),
                                        "mode": r_sch.get("mode", "blacklist"),
                                        "groups": r_sch.get("groups", []),
                                        "session_type": r_sch.get("session_type", "standard"),
                                    }
                                    # Forward pomodoro params if present
                                    if r_sch.get("session_type") == "pomodoro":
                                        cmd_to_start["focus_minutes"] = r_sch.get("focus_minutes", 25)
                                        cmd_to_start["break_minutes"] = r_sch.get("break_minutes", 5)
                                        cmd_to_start["cycles"] = r_sch.get("cycles", 4)
                                    is_recurring_trigger = True
                                    self._persist_session_lock()
                                    logging.info("Recurring schedule %s triggered.", r_sch.get("id"))
                                    break

            # 2. Check one-off schedules if no recurring triggered
            if not cmd_to_start and self.schedules:
                # Check if the first schedule (sorted by start_time) is ready
                if get_continuous_time() >= self.schedules[0].get("mono_start", float('inf')):
                    sch = self.schedules.pop(0)
                    cmd_to_start = sch["cmd"]
                    self._persist_session_lock()
                    # Do NOT cleanup_session here! We want _start_session to merge it.

        if cmd_to_start:
            if is_recurring_trigger:
                logging.info("Recurring schedule triggered. Starting session.")
                self._play_sound("scheduled")
                self._send_mac_notification(
                    "Recurring Schedule",
                    "Your recurring focus session is starting now.",
                )
            else:
                logging.info("Scheduled time reached. Automatically starting session.")
                self._play_sound("scheduled")
                self._send_mac_notification(
                    "Scheduled Session",
                    "Your scheduled focus session is starting now.",
                )
            result = self._start_session(cmd_to_start)
            if result.get("status") != "ok":
                logging.warning(
                    "Scheduled session failed to start: %s",
                    result.get("message", "unknown error"),
                )
            return

        with self.lock:
            # C1: Handle signal-driven re-enforce (flag set without lock)
            if self._reenforce_flag:
                self._reenforce_flag = False
                logging.warning(
                    "Caught signal — setting re-enforce flag (deferred from handler)."
                )
                if self.active and not (
                    self.session_type == "pomodoro" and self.pomo_phase == "break"
                ):
                    logging.info("Signal re-enforce: re-applying block rules.")
                    try:
                        self._enforce_current_mode()
                    except Exception as exc:
                        logging.error("Signal re-enforce failed: %s", exc)

            # ── Permanent Block Watchdog (runs regardless of session state) ──
            if self.perma_blocklist or self.perma_pending_unlocks:
                now_mono_perma = get_continuous_time()

                # Process pending permanent unlocks (expire after 30 min)
                expired = []
                for domain, mono_end in list(self._mono_perma_unlock_ends.items()):
                    if now_mono_perma >= mono_end:
                        expired.append(domain)
                if expired:
                    for domain in expired:
                        if domain in self.perma_blocklist:
                            self.perma_blocklist.remove(domain)
                        self.perma_pending_unlocks.pop(domain, None)
                        self._mono_perma_unlock_ends.pop(domain, None)
                        logging.info(
                            "Permanent unblock completed: '%s' removed from blocklist.",
                            domain,
                        )
                    self._save_perma_state()
                    self._enforce_perma_block()
                    self.broadcast_state_changed()

                # Integrity check: permanent block markers in /etc/hosts (~every 2s)
                self._wd_perma_counter = getattr(self, "_wd_perma_counter", 0) + 1
                if self._wd_perma_counter >= 8:  # 8 * 250ms = 2s
                    self._wd_perma_counter = 0
                    if self.perma_blocklist:
                        if not self._perma_hosts_hash:
                            logging.warning(
                                "Permanent blocklist active but hosts hash is missing. Enforcing."
                            )
                            self._enforce_perma_block()
                        else:
                            try:
                                st = HOSTS_PATH.stat()
                                current_stat = (st.st_mtime, st.st_size)
                                if self._perma_hosts_stat is not None and current_stat == self._perma_hosts_stat:
                                    pass  # File untouched since last verified check
                                else:
                                    content = HOSTS_PATH.read_text()
                                    lines = content.split("\n")
                                    normalized_lines = [line.rstrip("\r") for line in lines]
                                    
                                    # Locate markers and detect duplicates
                                    begin_idx = -1
                                    end_idx = -1
                                    tampered = False
                                    
                                    for idx, line in enumerate(normalized_lines):
                                        if PERMA_MARKER_BEGIN in line:
                                            if begin_idx != -1:
                                                tampered = True
                                                break
                                            begin_idx = idx
                                        if PERMA_MARKER_END in line:
                                            if end_idx != -1:
                                                tampered = True
                                                break
                                            end_idx = idx
                                    
                                    if tampered or begin_idx == -1 or end_idx == -1 or begin_idx >= end_idx:
                                        logging.warning("PERMANENT BLOCK TAMPER DETECTED (markers missing or invalid). Re-enforcing.")
                                        self._enforce_perma_block()
                                    else:
                                        # Extract block content and verify hash
                                        block_lines = normalized_lines[begin_idx : end_idx + 1]
                                        block_content = "\n".join(block_lines)
                                        current_hash = hashlib.sha256(block_content.encode("utf-8")).hexdigest()
                                        if current_hash != self._perma_hosts_hash:
                                            logging.warning("PERMANENT BLOCK TAMPER DETECTED (content mismatch). Re-enforcing.")
                                            self._enforce_perma_block()
                                        else:
                                            # Hash is correct, save stat cache
                                            self._perma_hosts_stat = current_stat
                            except Exception as exc:
                                logging.error("Watchdog perma hosts check error: %s", exc)

            if not self.active:
                return

            now_mono = get_continuous_time()

            # Intent Continuous Notification
            if self.intent and self.settings.get("intent_notification_enabled", True):
                interval = (
                    int(self.settings.get("intent_notification_interval", 15)) * 60
                )
                last_notif = getattr(self, "_mono_last_intent_notif", 0)
                if last_notif == 0:
                    # Initialize to now so it doesn't trigger immediately upon start,
                    # but rather after the first interval
                    self._mono_last_intent_notif = now_mono
                elif now_mono - last_notif >= interval:
                    self._mono_last_intent_notif = now_mono
                    self._send_mac_notification(
                        "Focus Reminder", f"Target: {self.intent}"
                    )

            self._wd_persist_counter += 1
            if self._wd_persist_counter >= 120:  # 120 * 250ms = 30s
                self._wd_persist_counter = 0
                self._persist_session_lock()

            # Use monotonic time for duration checks (immune to clock changes)
            if now_mono >= self._mono_session_end:
                logging.info("Session timer expired.")
                self._cleanup_session()
                return
            if self._mono_unlock_end > 0 and now_mono >= self._mono_unlock_end:
                logging.info("Delayed unlock period reached. Unlocking.")
                self._cleanup_session()
                return

            # Pomodoro phase check
            if self.session_type == "pomodoro" and self._mono_pomo_phase_end > 0:
                if now_mono >= self._mono_pomo_phase_end:
                    self._transition_pomodoro_phase()
                    return

            # Skip integrity checks during pomodoro break
            if self.session_type == "pomodoro" and self.pomo_phase == "break":
                return

            # Integrity check: /etc/hosts (blacklist mode only)
            # ⚡ Two-tier check: fast stat() pre-check (~2μs) gates expensive
            #    read+SHA256 (~200μs). Eliminates ~99% of unnecessary disk I/O.
            if self.mode != "whitelist":
                try:
                    st = HOSTS_PATH.stat()
                    current_stat = (st.st_mtime, st.st_size)
                    # Fast path: if mtime and size haven't changed, skip the hash
                    if self._hosts_stat is not None and current_stat == self._hosts_stat:
                        pass  # File untouched — no I/O needed
                    else:
                        # Slow path: stat changed, verify with full hash
                        current = HOSTS_PATH.read_text()
                        h = hashlib.sha256(current.encode()).hexdigest()
                        if h != self.hosts_hash:
                            logging.warning("HOSTS TAMPER DETECTED. Re-enforcing.")
                            self._enforce_block()
                        else:
                            # Hash matches but stat drifted (e.g. touch without edit) — update cache
                            self._hosts_stat = current_stat
                except Exception as exc:
                    logging.error("Watchdog hosts error: %s", exc)

            # Integrity check: Firewall (QUIC block) every ~1s
            if self._wd_persist_counter % 4 == 0:
                try:
                    res = subprocess.run(
                        ["pfctl", "-a", "forcefocus", "-s", "rules"],
                        capture_output=True,
                        text=True,
                        timeout=2,
                    )
                    # Check for '443' and 'udp' in ruleset output
                    if "443" not in res.stdout or "udp" not in res.stdout:
                        logging.warning(
                            "FIREWALL TAMPER DETECTED. Rules: '%s'. Re-enforcing.",
                            res.stdout.strip(),
                        )
                        upstream = (
                            self.dns_proxy.upstream_dns
                            if (
                                self.mode == "whitelist"
                                and getattr(self, "dns_proxy", None)
                            )
                            else None
                        )
                        self._enforce_firewall(True, upstream_dns=upstream)
                except Exception as exc:
                    logging.error("Watchdog firewall error: %s", exc)

            # Integrity check: session.lock existence
            if not SESSION_LOCK.exists():
                logging.warning("SESSION.LOCK DELETED. Re-creating from memory.")
                self._persist_session_lock()
                # Also re-enforce block since file was tampered
                if self.mode == "whitelist":
                    self._enforce_whitelist()
                else:
                    self._enforce_block()

            # Integrity check: DNS (whitelist mode, every ~30 seconds)
            if self.mode == "whitelist":
                if (
                    self.dns_proxy
                    and not self.dns_proxy.is_alive()
                    and not (
                        self.session_type == "pomodoro" and self.pomo_phase == "break"
                    )
                ):
                    logging.warning("DNS Proxy thread died. Restarting.")
                    self.dns_proxy = LocalDNSProxy(self)
                    self.dns_proxy.start()

                self._wd_dns_counter += 1
                if self._wd_dns_counter >= 120:  # 120 * 250ms = 30s
                    self._wd_dns_counter = 0
                    self._verify_dns_redirect()

            # Integrity check: Proxy/VPN/App Watchdog (every ~5s)
            if self._wd_persist_counter % 20 == 0:
                self._kill_restricted_apps()

    # ── Passphrase ────────────────────────────────────────────────────────────

    @staticmethod
    def _verify_passphrase(passphrase: str) -> bool:
        if not KS_HASH_FILE.exists():
            return False
        try:
            stored = json.loads(KS_HASH_FILE.read_text())
            salt = bytes.fromhex(stored["salt"])
            expected = stored["hash"]
        except (json.JSONDecodeError, KeyError, ValueError):
            return False
        computed = hashlib.pbkdf2_hmac(
            "sha256", passphrase.encode("utf-8"), salt, 100_000
        ).hex()
        return hmac.compare_digest(computed, expected)

    # ── Socket Server ─────────────────────────────────────────────────────────

    def _socket_server(self):
        if os.path.exists(SOCK_PATH):
            os.unlink(SOCK_PATH)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(SOCK_PATH)
        os.chmod(SOCK_PATH, 0o600)

        user_file = Path("/etc/forcefocus/user")
        if user_file.exists():
            try:
                import pwd

                username = user_file.read_text().strip()
                uid = pwd.getpwnam(username).pw_uid
                os.chown(SOCK_PATH, uid, -1)
            except Exception as exc:
                logging.error("Failed to chown socket: %s", exc)

        sock.listen(5)
        sock.settimeout(SOCKET_TIMEOUT)
        logging.info("Command socket listening at %s.", SOCK_PATH)

        while True:
            try:
                conn, _ = sock.accept()
            except socket.timeout:
                continue
            except OSError as exc:
                logging.error("Socket accept error: %s", exc)
                time.sleep(1)
                continue
            try:
                conn.settimeout(5.0)
                MAX_MSG_SIZE = 1 * 1024 * 1024  # 1MB — generous for any valid command
                chunks = []
                total_size = 0
                while True:
                    chunk = conn.recv(8192)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > MAX_MSG_SIZE:
                        logging.warning(
                            "Socket message exceeded %d bytes. Disconnecting client.",
                            MAX_MSG_SIZE,
                        )
                        conn.sendall(
                            json.dumps(
                                {"status": "error", "message": "Message too large."}
                            ).encode("utf-8")
                        )
                        chunks = []
                        break
                    chunks.append(chunk)
                raw = b"".join(chunks).decode("utf-8").strip()
                if not raw:
                    continue
                response = self._dispatch_command(raw)
                conn.sendall(json.dumps(response).encode("utf-8"))
            except Exception as exc:
                logging.error("Socket handler error: %s", exc)
                try:
                    conn.sendall(
                        json.dumps({"status": "error", "message": str(exc)}).encode(
                            "utf-8"
                        )
                    )
                except Exception:
                    pass
            finally:
                conn.close()

    def _dispatch_command(self, raw: str) -> dict:
        try:
            cmd = json.loads(raw)
        except json.JSONDecodeError:
            return {"status": "error", "message": "Malformed JSON."}

        action = cmd.get("action", "")

        if action == "start":
            return self._start_session(cmd)
        elif action == "stop":
            return self._request_stop(cmd.get("key", ""))
        elif action == "status":
            return self._get_status()
        elif action == "get_lists":
            return self._cmd_get_lists()
        elif action == "add_domain":
            return self._cmd_add_domain(cmd)
        elif action == "add_domains":
            return self._cmd_add_domains(cmd)
        elif action == "remove_domain":
            return self._cmd_remove_domain(cmd)
        elif action == "get_groups":
            return self._cmd_get_groups()
        elif action == "add_group":
            return self._cmd_add_group(cmd)
        elif action == "remove_group":
            return self._cmd_remove_group(cmd)
        elif action == "get_perma_blocklist":
            return self._cmd_get_perma_blocklist()
        elif action == "add_perma_block":
            return self._cmd_add_perma_block(cmd)
        elif action == "request_perma_unblock":
            return self._cmd_request_perma_unblock(cmd)
        elif action == "cancel_perma_unblock":
            return self._cmd_cancel_perma_unblock(cmd)
        elif action == "get_recurring_schedules":
            return self._cmd_get_recurring_schedules()
        elif action == "add_recurring_schedule":
            return self._cmd_add_recurring_schedule(cmd)
        elif action == "remove_recurring_schedule":
            return self._cmd_remove_recurring_schedule(cmd)
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}

    def _http_server(self):
        try:
            server = EmbeddedHTTPServer((WEB_HOST, WEB_PORT), EmbeddedWebHandler)
            server.daemon_ref = self
            server.web_dir = WEB_DIR
            logging.info(
                "Web UI listening at http://%s:%d (serving from %s)",
                WEB_HOST,
                WEB_PORT,
                WEB_DIR,
            )
            server.serve_forever()
        except Exception as exc:
            logging.error("HTTP server failed: %s", exc)


class EmbeddedHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_ref = None
    web_dir = WEB_DIR  # Default, overridden per-instance


class EmbeddedWebHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _is_origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        if origin in ("http://localhost:7070", "http://127.0.0.1:7070"):
            return True
        if origin == "chrome-extension://hcgpgflhkpdccdjkkobofpaemcgjmhdc":
            return True
        return False

    def _is_api_token_valid(self) -> bool:
        """Verify the X-API-Token header matches the daemon's per-launch token."""
        token = self.headers.get("X-API-Token")
        if not token:
            return False
        daemon = self.server.daemon_ref
        return hasattr(daemon, "api_token") and hmac.compare_digest(
            token, daemon.api_token
        )

    def _get_cors_origin(self) -> str:
        origin = self.headers.get("Origin")
        if origin and (
            origin in ("http://localhost:7070", "http://127.0.0.1:7070")
            or origin == "chrome-extension://hcgpgflhkpdccdjkkobofpaemcgjmhdc"
        ):
            return origin
        return "http://127.0.0.1:7070"

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", self._get_cors_origin())
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, filepath: Path):
        if not filepath.exists() or not filepath.is_file():
            self.send_error(404)
            return
        try:
            filepath.resolve().relative_to(self.server.web_dir.resolve())
        except ValueError:
            self.send_error(403)
            return

        mime, _ = mimetypes.guess_type(str(filepath))
        if mime is None:
            mime = "application/octet-stream"

        body = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        # S9: Allow Chrome extension to load static assets (sounds, etc.)
        self.send_header("Access-Control-Allow-Origin", self._get_cors_origin())
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        MAX_BODY = 10 * 1024 * 1024  # 10MB limit for audio uploads
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        if length > MAX_BODY:
            logging.error("Body size %d exceeds MAX_BODY %d", length, MAX_BODY)
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path).rstrip("/")
        if not path:
            path = "/"

        if path.startswith("/api/") and not self._is_origin_allowed():
            self._send_json(
                {"status": "error", "message": "CORS policy: Origin not allowed."}, 403
            )
            return

        elif path == "/api/status":
            self._send_json(self.server.daemon_ref._get_status())
        elif path == "/api/schedules/recurring":
            self._send_json(self.server.daemon_ref._cmd_get_recurring_schedules())
        elif path == "/api/stream":
            # Server-Sent Events (SSE) endpoint for real-time state updates
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", self._get_cors_origin())
            self.end_headers()
            
            daemon = self.server.daemon_ref
            q = queue.Queue(maxsize=10)
            daemon.register_sse_listener(q)
            
            last_written_body = None
            last_written_time = 0.0
            
            try:
                while True:
                    status_data = daemon._get_status()
                    body = json.dumps(status_data)
                    now = time.time()
                    
                    if body != last_written_body or now - last_written_time >= 10.0:
                        self.wfile.write(f"data: {body}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        last_written_body = body
                        last_written_time = now
                        
                    timeout = 0.5 if daemon.active else 5.0
                    try:
                        q.get(timeout=timeout)
                        while not q.empty():
                            try:
                                q.get_nowait()
                            except queue.Empty:
                                break
                    except queue.Empty:
                        pass
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass
            finally:
                daemon.unregister_sse_listener(q)
            return
        elif path == "/api/session-domains":
            self._send_json(self.server.daemon_ref._cmd_get_session_domains())
        elif path == "/api/lists":
            self._send_json(self.server.daemon_ref._cmd_get_lists())
        elif path == "/api/sounds":
            self._send_json(self.server.daemon_ref._cmd_get_sounds())
        elif path == "/api/settings":
            self._send_json(self.server.daemon_ref._cmd_get_settings())
        elif path == "/api/groups":
            self._send_json(self.server.daemon_ref._cmd_get_groups())
        elif path == "/api/perma-blocklist":
            self._send_json(self.server.daemon_ref._cmd_get_perma_blocklist())
        elif path == "/api/token":
            token = getattr(self.server.daemon_ref, "api_token", "")
            self._send_json({"token": token})
        elif path == "/" or path == "":
            self._send_file(self.server.web_dir / "index.html")
        elif path == "/menubar":
            self._send_file(self.server.web_dir / "menubar.html")
        else:
            self._send_file(self.server.web_dir / path.lstrip("/"))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path).rstrip("/")
        if not path:
            path = "/"

        if not self._is_origin_allowed():
            self._send_json(
                {"status": "error", "message": "CORS policy: Origin not allowed."}, 403
            )
            return

        if not self._is_api_token_valid():
            self._send_json(
                {
                    "status": "error",
                    "message": "Unauthorized: invalid or missing API token.",
                },
                401,
            )
            return

        body = self._read_body()

        if path == "/api/start":
            cmd = {
                "action": "start",
                "duration_minutes": body.get("duration", 120),
                "mode": body.get("mode", "blacklist"),
                "session_type": body.get("session_type", "standard"),
                "focus_minutes": body.get("focus_minutes", 25),
                "break_minutes": body.get("break_minutes", 5),
                "cycles": body.get("cycles", 4),
                "groups": body.get("groups", []),
                "intent": body.get("intent", ""),
                "intent_tasks": body.get("intent_tasks", []),
            }
            if "schedule_in" in body:
                cmd["schedule_in_minutes"] = body["schedule_in"]
            if "schedule_at" in body:
                cmd["schedule_at_time"] = body["schedule_at"]
            self._send_json(self.server.daemon_ref._start_session(cmd))
        elif path == "/api/cancel-schedule":
            self._send_json(self.server.daemon_ref._cmd_cancel_schedule(body))
        elif path == "/api/intent":
            self._send_json(self.server.daemon_ref._set_intent(body))
        elif path == "/api/settings":
            self._send_json(self.server.daemon_ref._cmd_save_settings(body))
        elif path == "/api/upload-sound":
            self._send_json(self.server.daemon_ref._cmd_upload_sound(body))
        elif path == "/api/delete-sound":
            self._send_json(self.server.daemon_ref._cmd_delete_sound(body))
        elif path == "/api/stop":
            self._send_json(self.server.daemon_ref._request_stop(body.get("key", "")))
        elif path == "/api/schedules/recurring":
            self._send_json(self.server.daemon_ref._cmd_add_recurring_schedule(body))
        elif path.startswith("/api/lists/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[3] == "bulk":
                cmd = {
                    "action": "add_domains",
                    "list": parts[2],
                    "domains": body.get("domains", []),
                }
                self._send_json(self.server.daemon_ref._cmd_add_domains(cmd))
            else:
                cmd = {
                    "action": "add_domain",
                    "list": parts[2],
                    "domain": body.get("domain", ""),
                }
                self._send_json(self.server.daemon_ref._cmd_add_domain(cmd))
        elif path == "/api/groups":
            cmd = {
                "action": "add_group",
                "name": body.get("name", ""),
                "domains": body.get("domains", []),
            }
            self._send_json(self.server.daemon_ref._cmd_add_group(cmd))
        elif path == "/api/perma-blocklist":
            cmd = {
                "action": "add_perma_block",
                "domain": body.get("domain", ""),
                "domains": body.get("domains", []),
            }
            self._send_json(self.server.daemon_ref._cmd_add_perma_block(cmd))
        elif path == "/api/perma-blocklist/unblock":
            cmd = {
                "action": "request_perma_unblock",
                "domain": body.get("domain", ""),
                "key": body.get("key", ""),
            }
            self._send_json(self.server.daemon_ref._cmd_request_perma_unblock(cmd))
        elif path == "/api/perma-blocklist/cancel-unblock":
            cmd = {
                "action": "cancel_perma_unblock",
                "domain": body.get("domain", ""),
            }
            self._send_json(self.server.daemon_ref._cmd_cancel_perma_unblock(cmd))
        else:
            self._send_json({"status": "error", "message": "Unknown endpoint."}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path).rstrip("/")
        if not path:
            path = "/"

        if not self._is_origin_allowed():
            self._send_json(
                {"status": "error", "message": "CORS policy: Origin not allowed."}, 403
            )
            return

        if not self._is_api_token_valid():
            self._send_json(
                {
                    "status": "error",
                    "message": "Unauthorized: invalid or missing API token.",
                },
                401,
            )
            return

        parts = path.strip("/").split("/")
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "lists":
            cmd = {
                "action": "remove_domain",
                "list": parts[2],
                "domain": "/".join(parts[3:]),
            }
            self._send_json(self.server.daemon_ref._cmd_remove_domain(cmd))
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "groups":
            cmd = {
                "action": "remove_group",
                "name": parts[2],
            }
            self._send_json(self.server.daemon_ref._cmd_remove_group(cmd))
        elif len(parts) == 4 and parts[0] == "api" and parts[1] == "schedules" and parts[2] == "recurring":
            cmd = {
                "action": "remove_recurring_schedule",
                "id": parts[3]
            }
            self._send_json(self.server.daemon_ref._cmd_remove_recurring_schedule(cmd))
        else:
            self._send_json({"status": "error", "message": "Unknown endpoint."}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self._get_cors_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Token")
        self.end_headers()

    def __getattr__(self, name):
        if name.startswith("do_"):
            return lambda: self._send_json(
                {"status": "error", "message": "Method not allowed."}, 405
            )
        raise AttributeError(name)


def main():
    if os.geteuid() != 0:
        print("ERROR: ForcedFocus daemon must run as root.", file=sys.stderr)
        sys.exit(1)
    daemon = ForcedFocusDaemon()
    daemon.run()


if __name__ == "__main__":
    main()
