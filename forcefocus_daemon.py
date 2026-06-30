#!/usr/bin/env python3
"""
ForcedFocus Daemon v3.1 — Root-level macOS website blocker.

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
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote
import urllib.request
import ssl
import traceback


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
TEMPLATES_FILE = CONFIG_DIR / "templates.json"
HISTORY_FILE = CONFIG_DIR / "session_history.json"
MAX_HISTORY_ENTRIES = 10000

PRAYER_CACHE_FILE = CONFIG_DIR / "prayer_cache.json"
PRAYER_DURATION_S = 30 * 60                    # 30-minute enforcement window
PRAYER_SKIP_LOCK_S = 30 * 60                   # Skip disabled when <= 30 min remain
PRAYER_API_URL = "https://api.aladhan.com/v1/timings"
PRAYER_NAMES = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]

DEFAULT_SETTINGS = {
    "sound_prayer": "Adhan.mp3",
    "prayer_enabled": True,
    "sound_start": "Start Blocking.mp3",
    "sound_rescue": "Rescue Mode.mp3",
    "sound_unlock": "Request Unlock .mp3",
    "sound_break": "Break Time.mp3",
    "sound_end": "Session End .mp3",
    "sound_scheduled": "Scheduled meeting.mp3",
    "sound_blocked": "Blocked site open.mp3",
    "intent_notification_enabled": True,
    "intent_notification_interval": 15,
    "daily_focus_goal_hours": 0,
    "prayer_latitude": None,
    "prayer_longitude": None,
    "allowed_extension_ids": ["hcgpgflhkpdccdjkkobofpaemcgjmhdc"],
}

MARKER_BEGIN = "# ──── BEGIN FORCEFOCUS ────"
MARKER_END = "# ──── END FORCEFOCUS ────"
PERMA_MARKER_BEGIN = "# ──── BEGIN FORCEFOCUS PERMANENT ────"
PERMA_MARKER_END = "# ──── END FORCEFOCUS PERMANENT ────"

WATCHDOG_INTERVAL = 0.25
SOCKET_TIMEOUT = 1.0
DELAYED_UNLOCK_S = 20 * 60
PERMA_UNLOCK_DELAY_S = 30 * 60  # 30 minutes to unblock a permanently blocked domain
RECURRING_START_GRACE_S = 5 * 60

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
    # ── VPNs & Tunnels ──
    "Tailscale", "tailscaled",
    "WireGuard",
    "Cisco AnyConnect", "vpnagentd", "aciseagent",
    "Tunnelblick",
    "NordVPN", "NordLayer", "nordvpnd", "NordLynx",
    "ExpressVPN", "expressvpnd", "lightway",
    "Mullvad", "mullvad-daemon", "mullvad-vpn",
    "ProtonVPN", "ProtonVPNAgent",
    "Surfshark",
    "GlobalProtect", "PanGPS", "PanGPA",
    "ivpn-gui", "IVPN",
    "Windscribe", "WindscribeService",
    "CloudflareWARP", "warp-svc", "warp-cli",
    "CyberGhost", "CyberGhostVPN",
    "IPVanish", "IPVanishVPN",
    "Private Internet Access", "pia-daemon",
    "HotspotShield",
    "Psiphon",
    "Outline", "OutlineClient", "outline-go-tun2socks",
    "Lantern",
    "OpenVPN", "openvpn", "OpenVPN Connect",
    "strongSwan", "charon",
    "Viscosity",
    "Shimo",
    "ZeroTier One", "zerotier-one",
    # ── Proxy & Tunneling Tools ──
    "Proxifier", "ProxifierAgent",
    "Charles", "Charles Proxy",
    "mitmproxy", "mitmdump", "mitmweb",
    "Proxyman",
    "Fiddler",
    "Surge", "surge-cli",
    "ClashX", "ClashX Pro", "clash", "clash-meta",
    "V2RayXS", "V2RayU", "v2ray", "v2ray-core",
    "Xray", "xray",
    "ShadowsocksX-NG", "ShadowsocksX", "ss-local", "sslocal",
    "Trojan-Qt5", "trojan", "trojan-go",
    "Clash Verge", "clash-verge",
    "Hiddify",
    "NekoRay", "nekoray",
    "sing-box",
    "Brook", "brook",
    "gost",
    "chisel",
    "frpc", "frps",
    "ngrok",
    "socat",
    # ── Unmanaged Browsers ──
    "Opera", "Opera GX",
    "Vivaldi",
    "TorBrowser", "tor", "Tor Browser",
    "Arc",
    "Sidekick",
    "SigmaOS",
    "Orion",
    "Waterfox",
    "Pale Moon",
    "Ghostery",
    "LibreWolf",
    "Chromium",
    "Falkon",
    "Min",
    "Iridium",
    "Yandex Browser",
    "Epic Privacy Browser",
    "Brave Browser",
    # ── Potential Bypass Tools ──
    "Activity Monitor",
    "Wireshark",
    "tshark",
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
        while self.running:
            try:
                # Ensure sockets are still open before select
                valid_socks = [s for s in self.socks if s.fileno() != -1]
                if not valid_socks:
                    break
                r, _, _ = select.select(valid_socks, [], [], 1.0)
                if not r or not self.running:
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
                if self.running:  # Only log if we didn't intend to stop
                    logging.error("DNS Proxy loop error: %s", exc)

    def stop(self):
        self.running = False
        for s in getattr(self, "socks", []):
            try:
                s.close()
            except OSError:
                pass
        try:
            self.executor.shutdown(wait=False)
        except Exception:
            pass

    def _extract_domain(self, data: bytes) -> str:
        parts = []
        idx = 12
        while idx < len(data):
            length = data[idx]
            if length == 0:
                break
            if (length & 0xC0) == 0xC0:
                break
            if idx + 1 + length > len(data):
                break
            parts.append(data[idx + 1 : idx + 1 + length].decode("utf-8", errors="replace"))
            idx += 1 + length
        return ".".join(parts).lower()

    def _make_nxdomain(self, data: bytes) -> bytes:
        try:
            hdr = struct.unpack("!HHHHHH", data[:12])
            flags = (hdr[1] | 0x8000) & 0xFF00
            flags = flags | 0x0080 | 3
            resp_hdr = struct.pack("!HHHHHH", hdr[0], flags, hdr[2], 0, 0, 0)
            
            idx = 12
            while idx < len(data) and data[idx] != 0:
                idx += 1 + data[idx]
            idx += 5
            
            # Additional bounds check for malformed queries
            if idx > len(data):
                return b""
                
            return resp_hdr + data[12:idx]
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
            in_set = False
            parts = domain.split(".")
            for i in range(len(parts)):
                if ".".join(parts[i:]) in self.ff_daemon.active_domains_set:
                    in_set = True
                    break
            
            if getattr(self.ff_daemon, "mode", "blacklist") == "blacklist":
                allowed = not in_set
            else:
                allowed = in_set

        if allowed:
            self.executor.submit(self._forward_query, data, addr, sock)
        else:
            resp = self._make_nxdomain(data)
            if resp:
                sock.sendto(resp, addr)

    def _forward_query(self, data: bytes, addr, sock):
        fw = None
        try:
            family = socket.AF_INET6 if ":" in self.upstream_dns else socket.AF_INET
            fw = socket.socket(family, socket.SOCK_DGRAM)
            fw.settimeout(2.0)
            fw.sendto(data, (self.upstream_dns, 53))
            resp, _ = fw.recvfrom(4096)
            sock.sendto(resp, addr)
        except Exception:
            pass
        finally:
            if fw:
                fw.close()


class PrayerManager:
    """Manages prayer time fetching, caching, and scheduling."""
    
    def __init__(self, daemon: 'ForcedFocusDaemon'):
        self.daemon = daemon
        self._today_prayers: dict[str, datetime] = {}   # {"Fajr": datetime, ...}
        self._cache_date: str = ""                       # "YYYY-MM-DD"
        self._skipped_prayers: set[str] = set()          # prayer names skipped today
        self._skip_history: list[str] = []               # ordered history of skipped prayers
        self._suspended_session: dict | None = None      # snapshot of paused session
        self._prayer_active: bool = False                # is PRAYER_RESCUE running?
        self._current_prayer_name: str = ""               # which prayer is active
        self._mono_prayer_end: float = 0.0               # monotonic end anchor
        self._fetch_lock = threading.Lock()
        self._last_fetch_attempt: float = 0.0
        self._deferred_schedule_cmd: dict | None = None
        
    def load_cache(self) -> bool:
        if not PRAYER_CACHE_FILE.exists():
            return False
        try:
            data = json.loads(PRAYER_CACHE_FILE.read_text())
            cache_date = data.get("date", "")
            today = datetime.now().strftime("%Y-%m-%d")
            
            timings = data.get("timings", {})
            if not timings:
                return False
            
            # Parse times into datetime objects for today
            self._today_prayers = {}
            for name in PRAYER_NAMES:
                if name in timings:
                    h, m = map(int, timings[name].split(":"))
                    self._today_prayers[name] = datetime.now().replace(
                        hour=h, minute=m, second=0, microsecond=0
                    )
            
            if cache_date == today:
                self._cache_date = today
                logging.info("Prayer cache loaded for today (%s).", today)
            else:
                # Fallback pattern: use yesterday's times (drift is minimal)
                self._cache_date = today  # Mark as "today"
                logging.info("Prayer cache is from %s. Using as fallback for %s.", cache_date, today)
            return True
        except Exception as exc:
            logging.error("Failed to load prayer cache: %s", exc)
            return False

    def save_cache(self, date_str: str, timings: dict, raw_response: dict) -> None:
        try:
            data = {
                "date": date_str,
                "timings": timings,
                "raw_api_response": raw_response,
                "fetched_at": datetime.now().isoformat()
            }
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = PRAYER_CACHE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            os.replace(tmp, PRAYER_CACHE_FILE)
            os.chmod(PRAYER_CACHE_FILE, 0o644)
        except Exception as exc:
            logging.error("Failed to save prayer cache: %s", exc)

    def fetch_today(self) -> bool:
        if not self._fetch_lock.acquire(blocking=False):
            return False
        try:
            lat = self.daemon.settings.get("prayer_latitude")
            lng = self.daemon.settings.get("prayer_longitude")

            if lat is None or lng is None:
                logging.warning("Prayer location not set. Detect location from Settings.")
                return False

            ctx = ssl._create_unverified_context()
            today = datetime.now().strftime("%d-%m-%Y")
            aladhan_url = f"{PRAYER_API_URL}/{today}?latitude={lat}&longitude={lng}"
            req = urllib.request.Request(aladhan_url, headers={'User-Agent': 'Mozilla/5.0'})
            res = urllib.request.urlopen(req, context=ctx, timeout=10)
            data = json.loads(res.read())

            if data.get("code") == 200:
                timings = data["data"]["timings"]
                today = datetime.now().strftime("%Y-%m-%d")
                self.save_cache(today, timings, data)
                self.load_cache()  # Reload to populate `_today_prayers`
                logging.info("Successfully fetched prayer times for coordinates (%.4f, %.4f)", lat, lng)
                return True
            else:
                logging.error("Aladhan API error: %s", data)
                return False
        except Exception as exc:
            logging.error("Prayer fetch error: %s", exc)
            return False
        finally:
            self._fetch_lock.release()

    def get_next_prayer(self) -> tuple[str, datetime] | None:
        if not self._today_prayers:
            return None
        now = datetime.now()
        upcoming = []
        for name in PRAYER_NAMES:
            if name in self._today_prayers:
                ptime = self._today_prayers[name]
                if ptime > now and name not in self._skipped_prayers:
                    upcoming.append((name, ptime))
        upcoming.sort(key=lambda x: x[1])
        return upcoming[0] if upcoming else None

    def skip_next_prayer(self) -> dict:
        if not self.daemon.settings.get("prayer_enabled", True):
            return {"status": "error", "message": "Prayer mode disabled."}
        if not self.can_skip():
            return {"status": "error", "message": "Cannot skip prayer (within 30m lock or no upcoming prayer)."}
        next_prayer = self.get_next_prayer()
        if next_prayer:
            self._skipped_prayers.add(next_prayer[0])
            self._skip_history.append(next_prayer[0])
            self.daemon.broadcast_state_changed()
            return {"status": "ok", "message": f"Prayer {next_prayer[0]} skipped."}
        return {"status": "error", "message": "No prayer to skip."}

    def unskip_last_prayer(self) -> dict:
        if not hasattr(self, '_skip_history') or not self._skip_history:
            return {"status": "error", "message": "No skipped prayers to cancel."}
        
        prayer_name = self._skip_history.pop()
        if prayer_name in self._skipped_prayers:
            self._skipped_prayers.remove(prayer_name)
        
        self.daemon.broadcast_state_changed()
        return {"status": "ok", "message": f"Prayer {prayer_name} skip cancelled."}

    def can_skip(self) -> bool:
        rem = self.seconds_until_next()
        if rem is None:
            return False
        return rem > PRAYER_SKIP_LOCK_S

    def seconds_until_next(self) -> int | None:
        next_prayer = self.get_next_prayer()
        if not next_prayer:
            return None
        return int(max(0, (next_prayer[1] - datetime.now()).total_seconds()))

    def get_status_payload(self) -> dict:
        next_prayer = self.get_next_prayer()
        return {
            "enabled": self.daemon.settings.get("prayer_enabled", True),
            "available": bool(self._today_prayers),
            "prayer_active": self._prayer_active,
            "current_prayer": self._current_prayer_name if self._prayer_active else None,
            "prayer_remaining_seconds": int(max(0, self._mono_prayer_end - get_continuous_time())) if self._prayer_active else None,
            "next_prayer_name": next_prayer[0] if next_prayer else None,
            "next_prayer_time": next_prayer[1].strftime("%H:%M") if next_prayer else None,
            "next_prayer_seconds": self.seconds_until_next(),
            "can_skip": self.can_skip(),
            "has_suspended_session": self._suspended_session is not None,
            "today_prayers": {name: t.strftime("%H:%M") for name, t in self._today_prayers.items()},
            "skipped": list(self._skipped_prayers),
            "cache_date": self._cache_date,
            "last_skipped_prayer": self._skip_history[-1] if hasattr(self, '_skip_history') and self._skip_history else None,
        }

    def _capture_session_snapshot(self) -> dict:
        daemon = self.daemon
        return {
            "active": daemon.active,
            "mode": daemon.mode,
            "session_type": daemon.session_type,
            "session_expiry": daemon.session_expiry.isoformat() if daemon.session_expiry else None,
            "total_duration_seconds": daemon.total_duration_seconds,
            "remaining_seconds": max(0, daemon._mono_session_end - get_continuous_time()),
            "active_domains": list(daemon.active_domains),
            "session_base_domains": list(daemon.session_base_domains),
            "session_groups": list(daemon.session_groups),
            "intent": daemon.intent,
            "intent_tasks": list(daemon.intent_tasks),
            "session_group_id": daemon.session_group_id,
            "pomo_focus_minutes": daemon.pomo_focus_minutes,
            "pomo_break_minutes": daemon.pomo_break_minutes,
            "pomo_total_cycles": daemon.pomo_total_cycles,
            "pomo_current_cycle": daemon.pomo_current_cycle,
            "pomo_phase": daemon.pomo_phase,
            "pomo_phases_tracked_seconds": getattr(daemon, "pomo_phases_tracked_seconds", 0),
            "pomo_phase_remaining": max(0, daemon._mono_pomo_phase_end - get_continuous_time()) if daemon._mono_pomo_phase_end > 0 else 0,
            "original_dns": daemon.original_dns,
            "whitelist_resolved": daemon.whitelist_resolved,
            "whitelist_count": daemon.whitelist_count,
            "whitelist_expanded_count": getattr(daemon, "whitelist_expanded_count", 0),
            "pending_unlock_remaining": max(0, daemon._mono_unlock_end - get_continuous_time()) if daemon._mono_unlock_end > 0 else 0,
        }

    def _restore_session_from_snapshot(self, snapshot: dict) -> None:
        daemon = self.daemon
        remaining = snapshot.get("remaining_seconds", 0)
        if remaining <= 0:
            logging.info("Suspended session expired during prayer. Cleaning up.")
            daemon._cleanup_session()
            return
        
        now_mono = get_continuous_time()
        daemon.mode = snapshot["mode"]
        daemon.session_type = snapshot["session_type"]
        daemon.session_expiry = datetime.now() + timedelta(seconds=remaining)
        daemon.total_duration_seconds = snapshot["total_duration_seconds"]
        daemon._mono_session_end = now_mono + remaining
        daemon.active = True
        daemon.active_domains = snapshot["active_domains"]
        daemon.active_domains_set = set(daemon.active_domains)
        daemon.session_base_domains = snapshot["session_base_domains"]
        daemon.session_groups = snapshot["session_groups"]
        daemon.intent = snapshot["intent"]
        daemon.intent_tasks = snapshot["intent_tasks"]
        daemon.session_group_id = snapshot["session_group_id"]
        
        if daemon.session_type == "pomodoro":
            daemon.pomo_focus_minutes = snapshot["pomo_focus_minutes"]
            daemon.pomo_break_minutes = snapshot["pomo_break_minutes"]
            daemon.pomo_total_cycles = snapshot["pomo_total_cycles"]
            daemon.pomo_current_cycle = snapshot["pomo_current_cycle"]
            daemon.pomo_phase = snapshot["pomo_phase"]
            daemon.pomo_phases_tracked_seconds = snapshot.get("pomo_phases_tracked_seconds", 0)
            phase_rem = snapshot["pomo_phase_remaining"]
            if phase_rem > 0:
                daemon.pomo_phase_expiry = datetime.now() + timedelta(seconds=phase_rem)
                daemon._mono_pomo_phase_end = now_mono + phase_rem
            else:
                daemon.pomo_phase_expiry = None
                daemon._mono_pomo_phase_end = 0.0

        if daemon.mode == "whitelist":
            daemon.original_dns = snapshot["original_dns"]
            daemon.whitelist_resolved = snapshot["whitelist_resolved"]
            daemon.whitelist_count = snapshot["whitelist_count"]
            daemon.whitelist_expanded_count = snapshot["whitelist_expanded_count"]
        
        unlock_rem = snapshot.get("pending_unlock_remaining", 0)
        if unlock_rem > 0:
            daemon.pending_unlock_at = datetime.now() + timedelta(seconds=unlock_rem)
            daemon._mono_unlock_end = now_mono + unlock_rem
        else:
            daemon.pending_unlock_at = None
            daemon._mono_unlock_end = 0.0

        daemon._persist_session_lock()
        if daemon.mode == "whitelist":
            if not (daemon.session_type == "pomodoro" and daemon.pomo_phase == "break"):
                threading.Thread(target=daemon._enforce_whitelist, name="enforce_whitelist", daemon=True).start()
        else:
            if not (daemon.session_type == "pomodoro" and daemon.pomo_phase == "break"):
                threading.Thread(target=daemon._enforce_block, name="enforce_block", daemon=True).start()
        
        daemon.broadcast_state_changed()
        logging.info("Resumed suspended session (%s mode, %d sec remaining).", daemon.mode, int(remaining))

    def start_prayer_rescue(self, prayer_name: str):
        daemon = self.daemon
        with daemon.lock:
            self._prayer_active = True
            self._current_prayer_name = prayer_name
            self._mono_prayer_end = get_continuous_time() + PRAYER_DURATION_S
            self._skipped_prayers.add(prayer_name)
            daemon._play_sound("prayer")
            daemon._send_mac_notification(
                f"🕌 {prayer_name} Prayer Time",
                "Prayer Rescue Mode activated for 30 minutes.",
            )
            
            # Case B: Active MANUAL Rescue session
            if daemon.active and daemon.session_type == "rescue" and not self._prayer_active:
                now_mono = get_continuous_time()
                rescue_remaining = daemon._mono_session_end - now_mono
                if rescue_remaining < PRAYER_DURATION_S:
                    extension = PRAYER_DURATION_S - rescue_remaining
                    daemon._mono_session_end += extension
                    daemon.session_expiry += timedelta(seconds=extension)
                    daemon.total_duration_seconds += int(extension)
                    daemon._persist_session_lock()
                    logging.info("Prayer %s: Extended active Rescue by %ds to cover prayer window.", prayer_name, int(extension))
                else:
                    logging.info("Prayer %s: Active Rescue has %ds remaining. No action needed.", prayer_name, int(rescue_remaining))
                self._skipped_prayers.add(prayer_name)
                daemon.broadcast_state_changed()
                return

            # Case C: Active Whitelist/Blacklist
            if daemon.active and daemon.session_type != "rescue" and not self._prayer_active:
                self._suspended_session = self._capture_session_snapshot()
                logging.info("Prayer %s: Suspending active session.", prayer_name)
                daemon._remove_block()

            # Case A: Start PRAYER_RESCUE
            self._prayer_active = True
            self._current_prayer_name = prayer_name
            now_mono = get_continuous_time()
            self._mono_prayer_end = now_mono + PRAYER_DURATION_S
            
            daemon.mode = "whitelist"
            daemon.session_type = "prayer"
            daemon.active = True
            daemon.session_expiry = datetime.now() + timedelta(seconds=PRAYER_DURATION_S)
            daemon.total_duration_seconds = PRAYER_DURATION_S
            daemon._mono_session_end = self._mono_prayer_end
            daemon._mono_unlock_end = 0.0
            daemon.session_base_domains = []
            daemon.active_domains = []
            daemon.active_domains_set = set()
            daemon.whitelist_count = 0
            daemon.whitelist_expanded_count = 0
            if not daemon.original_dns:
                daemon.original_dns = daemon._get_current_dns_servers()
            daemon.intent = f"🕌 {prayer_name} Prayer Time"
            daemon.intent_tasks = []
            daemon.pending_unlock_at = None
            
            threading.Thread(target=daemon._enforce_whitelist, name="enforce_prayer_whitelist", daemon=True).start()
            daemon._persist_session_lock()
            daemon.broadcast_state_changed()
            logging.info("PRAYER_RESCUE activated for %s.", prayer_name)

    def end_prayer_rescue(self) -> None:
        daemon = self.daemon
        with daemon.lock:
            if not self._prayer_active:
                return
            
            logging.info("PRAYER_RESCUE ended for %s.", self._current_prayer_name)
            self._prayer_active = False
            self._current_prayer_name = ""
            self._mono_prayer_end = 0.0
            
            daemon._cleanup_session()
            
            deferred = getattr(self, '_deferred_schedule_cmd', None)
            if deferred:
                self._deferred_schedule_cmd = None
                logging.info("Starting deferred recurring schedule after prayer.")
                daemon._start_session(deferred)
                return
            
            if self._suspended_session:
                snapshot = self._suspended_session
                self._suspended_session = None
                self._restore_session_from_snapshot(snapshot)
                return
            
            logging.info("No suspended session. Daemon returns to IDLE.")
            daemon.broadcast_state_changed()

class ForcedFocusDaemon:
    def __init__(self):
        self.active = False
        self.mode = "blacklist"
        self.state_changed = threading.Event()
        self.state_revision = 0
        self.notification_warning: dict | None = None
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
        self._hosts_stat: tuple[float, int] | None = None  # ⚡ (mtime, size) for cheap watchdog pre-check
        self.dns_proxy = None
        self.original_dns: dict[str, str] = {}
        self.whitelist_resolved: dict[str, list[str]] = {}
        self._cached_lists: dict | None = None
        self._cached_lists_mtime: float = 0.0
        self.enforcement_lock = threading.RLock()
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
        self.pomo_phases_tracked_seconds: int = 0
        self.intent: str | None = None
        self.intent_tasks: list = []
        self.session_group_id: str | None = None
        self.lock = threading.RLock()
        self._passphrase_attempts = 0
        self._last_attempt_time = 0.0
        # Monotonic time anchors (immune to clock manipulation)
        self._mono_session_end: float = 0.0
        self._mono_unlock_end: float = 0.0
        self._mono_pomo_phase_end: float = 0.0
        self._mono_last_intent_notif: float = 0.0
        self._mono_last_recurring_check: float = 0.0
        self._reenforce_event = threading.Event()  # Set by signal handler, handled by watchdog
        self.session_groups: list[str] = []  # Group names active in current session
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
        self._ip_backlog: dict[str, float] = {}  # IP string -> Expiry timestamp (monotonic)
        self._whitelisted_ip_backlog: dict[str, float] = {}  # IP string -> Expiry timestamp
        self._ip_resolution_running = False
        self._net_services_cache: list[str] = []
        self._net_services_cache_time: float = 0.0
        self._cached_history: list | None = None
        self._cached_history_mtime: float = 0.0
        self._cached_history_mtime: float = 0.0
        self._wd_firewall_counter: int = 0
        self.prayer_manager = None
    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def register_sse_listener(self, q):
        with self._sse_listeners_lock:
            self._sse_listeners.add(q)

    def unregister_sse_listener(self, q):
        with self._sse_listeners_lock:
            self._sse_listeners.discard(q)

    def broadcast_state_changed(self):
        with self.lock:
            self.state_revision += 1
        self.state_changed.set()
        with self._sse_listeners_lock:
            for q in self._sse_listeners:
                try:
                    q.put_nowait(True)
                except queue.Full:
                    pass

    def run(self):
        setup_logging()
        logging.info("ForcedFocus daemon v3.1 starting (PID %d).", os.getpid())
        self._ensure_config_dir()
        self._ensure_lists_file()
        self._ensure_groups_file()
        self._ensure_perma_blocklist_file()
        self._ensure_templates_file()
        self._generate_api_token()
        self._install_signal_handlers()
        # Load permanent blocklist and enforce immediately (before session restore)
        self._load_perma_state()
        self._enforce_perma_block()
        # Restore session BEFORE starting watchdog to avoid race (C2)
        with self.lock:
            self._restore_session()

        self.prayer_manager = PrayerManager(self)
        self.prayer_manager.load_cache()
        threading.Thread(target=self.prayer_manager.fetch_today, name="prayer_init", daemon=True).start()

        wt = threading.Thread(target=self._watchdog_loop, name="watchdog", daemon=True)
        wt.start()

        ht = threading.Thread(target=self._http_server, name="http", daemon=True)
        ht.start()

        self._socket_server()

    @staticmethod
    def _ensure_config_dir():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(str(CONFIG_DIR), 0o711)

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

    @staticmethod
    def _ensure_templates_file():
        if not TEMPLATES_FILE.exists():
            TEMPLATES_FILE.write_text(json.dumps({"templates": []}, indent=2))
            os.chmod(str(TEMPLATES_FILE), 0o644)

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
            if not self.active and signum in (signal.SIGINT, signal.SIGTERM):
                logging.info("Daemon idle, exiting gracefully on signal %d.", signum)
                sys.exit(0)
            # Non-blocking: just set flag, watchdog will re-enforce (C1 fix)
            # We keep this handler minimal as only a few functions are signal-safe.
            self._reenforce_event.set()

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGHUP, _handler)

    # ── Lists Management ──────────────────────────────────────────────────────

    def _load_lists(self) -> dict:
        with self.lock:
            try:
                mtime = LISTS_FILE.stat().st_mtime
            except FileNotFoundError:
                return {"blacklist": [], "whitelist": []}

            if self._cached_lists is not None and mtime == self._cached_lists_mtime:
                return {
                    k: list(v) if isinstance(v, list) else v
                    for k, v in self._cached_lists.items()
                }

        # Read the file outside the lock to prevent I/O contention
        try:
            raw = LISTS_FILE.read_text()
            parsed = json.loads(raw)
        except Exception:
            return {"blacklist": [], "whitelist": []}

        with self.lock:
            self._cached_lists = parsed
            self._cached_lists_mtime = mtime
            return {
                k: list(v) if isinstance(v, list) else v
                for k, v in self._cached_lists.items()
            }

    def _save_lists(self, lists: dict):
        self._atomic_write_json(LISTS_FILE, lists, indent=2)

    def _load_groups(self) -> dict:
        with self.lock:
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
            raw = GROUPS_FILE.read_text()
            parsed = json.loads(raw)
        except Exception:
            return {}

        with self.lock:
            self._cached_groups = parsed
            self._cached_groups_mtime = mtime
            return {
                k: v.copy() if isinstance(v, list) else v
                for k, v in self._cached_groups.items()
            }

    def _save_groups(self, groups: dict):
        self._atomic_write_json(GROUPS_FILE, groups, indent=2)

    # ── Session Templates ─────────────────────────────────────────────────────

    def _load_templates(self) -> list[dict]:
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

    def _save_templates(self, templates: list[dict]):
        self._atomic_write_json(TEMPLATES_FILE, {"templates": templates}, indent=2)

    @staticmethod
    def _coerce_int(value, default=None):
        try:
            if value is None:
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    def _normalize_template(self, raw: dict, existing: dict | None = None) -> tuple[bool, str, dict]:
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
        if mode not in ("blacklist", "whitelist", "rescue"):
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
        known_groups = self._load_groups()
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

    def _template_start_payload(self, template: dict) -> dict:
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

    def _cmd_get_templates(self) -> dict:
        with self.lock:
            templates = sorted(
                self._load_templates(),
                key=lambda t: (t.get("last_used_at") or "", t.get("updated_at") or ""),
                reverse=True,
            )
            return {"status": "ok", "templates": templates}

    def _cmd_add_template(self, cmd: dict) -> dict:
        with self.lock:
            ok, message, template = self._normalize_template(cmd)
            if not ok:
                return {"status": "error", "message": message}
            templates = self._load_templates()
            if any(t.get("name", "").lower() == template["name"].lower() for t in templates):
                return {"status": "error", "message": "A template with this name already exists."}
            templates.append(template)
            self._save_templates(templates)
            return {"status": "ok", "message": f"Template '{template['name']}' saved.", "template": template}

    def _cmd_update_template(self, cmd: dict) -> dict:
        template_id = str(cmd.get("id", "")).strip()
        if not template_id:
            return {"status": "error", "message": "Template id is required."}
        with self.lock:
            templates = self._load_templates()
            for idx, existing in enumerate(templates):
                if existing.get("id") == template_id:
                    ok, message, template = self._normalize_template(cmd, existing)
                    if not ok:
                        return {"status": "error", "message": message}
                    duplicate = any(
                        t.get("id") != template_id and t.get("name", "").lower() == template["name"].lower()
                        for t in templates
                    )
                    if duplicate:
                        return {"status": "error", "message": "A template with this name already exists."}
                    templates[idx] = template
                    self._save_templates(templates)
                    return {"status": "ok", "message": f"Template '{template['name']}' updated.", "template": template}
        return {"status": "error", "message": "Template not found."}

    def _cmd_remove_template(self, cmd: dict) -> dict:
        template_id = str(cmd.get("id", "")).strip()
        if not template_id:
            return {"status": "error", "message": "Template id is required."}
        with self.lock:
            templates = self._load_templates()
            remaining = [t for t in templates if t.get("id") != template_id]
            if len(remaining) == len(templates):
                return {"status": "error", "message": "Template not found."}
            self._save_templates(remaining)
            return {"status": "ok", "message": "Template removed.", "templates": remaining}

    def _cmd_duplicate_template(self, cmd: dict) -> dict:
        import copy
        template_id = str(cmd.get("id", "")).strip()
        with self.lock:
            templates = self._load_templates()
            source = next((t for t in templates if t.get("id") == template_id), None)
            if not source:
                return {"status": "error", "message": "Template not found."}
            clone = copy.deepcopy(source)
            clone["id"] = str(uuid.uuid4())
            clone["name"] = str(cmd.get("name") or f"{source.get('name', 'Template')} Copy").strip()
            clone["created_at"] = datetime.now().isoformat()
            clone["updated_at"] = clone["created_at"]
            clone["last_used_at"] = None
            clone["use_count"] = 0
            ok, message, clone = self._normalize_template(clone)
            if not ok:
                return {"status": "error", "message": message}
            templates.append(clone)
            self._save_templates(templates)
            return {"status": "ok", "message": f"Template '{clone['name']}' duplicated.", "template": clone}

    def _cmd_start_template(self, cmd: dict) -> dict:
        template_id = str(cmd.get("id", "")).strip()
        with self.lock:
            templates = self._load_templates()
            template = next((t for t in templates if t.get("id") == template_id), None)
            if not template:
                return {"status": "error", "message": "Template not found."}
            start_payload = self._template_start_payload(template)

        result = self._start_session(start_payload)
        if result.get("status") == "ok":
            with self.lock:
                templates = self._load_templates()
                for idx, existing in enumerate(templates):
                    if existing.get("id") == template_id:
                        existing["last_used_at"] = datetime.now().isoformat()
                        existing["use_count"] = int(existing.get("use_count", 0) or 0) + 1
                        templates[idx] = existing
                        self._save_templates(templates)
                        result["template"] = existing
                        break
        return result

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
        with self.enforcement_lock:
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
                    if self.active:
                        self._enforce_firewall(True, upstream_dns=self.dns_proxy.upstream_dns if self.dns_proxy else None)
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
                self._enforce_firewall(True, upstream_dns=self.dns_proxy.upstream_dns if self.dns_proxy else None)
                logging.info(
                    "Permanent block enforced: %d domains in /etc/hosts.",
                    len(self.perma_blocklist)
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
        with self.lock:
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
            restored = []
            for raw_rule in data["recurring_schedules"]:
                ok, message, rule = self._normalize_recurring_schedule(raw_rule)
                if ok:
                    restored.append(rule)
                else:
                    logging.warning("Skipped invalid recurring schedule during restore: %s", message)
            self.recurring_schedules = restored
            logging.info("Restored %d recurring schedules.", len(self.recurring_schedules))

        # If no active session data, we're done (schedule-only lockfile)
        if not data.get("expiry"):
            if self.schedules or data.get("prayer_state"):
                if data.get("prayer_state"):
                    self._restore_prayer_state(data["prayer_state"])
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
            if self.mode in ("whitelist", "rescue"):
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
        self.session_type = data.get("session_type", "standard")
        self.intent = data.get("intent", None)
        self.intent_tasks = data.get("intent_tasks", [])
        self.session_groups = data.get("session_groups", [])
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
                if self.mode in ("whitelist", "rescue"):
                    self.original_dns = data.get("original_dns", {})
                self._cleanup_session()
                return
            self._mono_unlock_end = now_mono + unlock_remaining
        else:
            self.pending_unlock_at = None
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

        self.session_group_id = data.get("session_group_id")
        self.active = True

        if self.mode in ("whitelist", "rescue"):
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
        if self.mode in ("whitelist", "rescue"):
            if not is_break:
                self._enforce_whitelist()
        else:
            if not is_break:
                self._enforce_block()
        logging.info(
            "Resuming %s session — %d min remaining.", self.mode, int(remaining / 60)
        )
        
        if data.get("prayer_state"):
            self._restore_prayer_state(data["prayer_state"])

    def _restore_prayer_state(self, ps: dict):
        if not self.prayer_manager:
            return
        pm = self.prayer_manager
        pm._skipped_prayers = set(ps.get("skipped_prayers", []))
        if ps.get("prayer_active"):
            remaining = ps.get("mono_prayer_end_remaining", 0)
            if remaining > 0:
                pm._prayer_active = True
                pm._current_prayer_name = ps.get("current_prayer_name", "")
                pm._mono_prayer_end = get_continuous_time() + remaining
                pm._suspended_session = ps.get("suspended_session")
                logging.info("Restored active prayer rescue: %s (%ds remaining).", pm._current_prayer_name, int(remaining))
            else:
                pm.end_prayer_rescue()

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
        if mode not in ("blacklist", "whitelist", "rescue"):
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
                        self.session_groups = list(set(self.session_groups + selected_groups))
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
                            threading.Thread(target=self._enforce_block, name="enforce_block", daemon=True).start()
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
            if not self.active:
                self.session_group_id = str(uuid.uuid4())
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
            self.session_groups = list(selected_groups)
            if mode in ("whitelist", "rescue"):
                self.original_dns = self._get_current_dns_servers()
                if self.session_type in ("rescue", "prayer") or mode == "rescue":
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
                if self.session_type in ("rescue", "prayer") or mode == "rescue":
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
                threading.Thread(target=self._enforce_whitelist, name="enforce_whitelist", daemon=True).start()
                if self.session_type == "pomodoro":
                    msg = f"Pomodoro (Whitelist): {count} domains allowed ({expanded_count} total with CDNs) for {self.pomo_total_cycles} cycles."
                elif self.session_type == "rescue" or mode == "rescue":
                    msg = f"Rescue Mode activated: All sites blocked for {duration_minutes} min."
                elif self.session_type == "prayer":
                    msg = f"Prayer Session activated: All sites blocked for {duration_minutes} min."
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
                threading.Thread(target=self._enforce_block, name="enforce_block", daemon=True).start()
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
            if self.session_type == "rescue" or mode == "rescue":
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
            if self.session_type == "prayer":
                return {"status": "error", "message": "Prayer blocks cannot be stopped early."}
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

    def _cancel_stop(self) -> dict:
        with self.lock:
            if not self.active:
                return {"status": "error", "message": "No active session."}
            if not self.pending_unlock_at:
                return {"status": "error", "message": "No unlock pending."}
            self.pending_unlock_at = None
            self._mono_unlock_end = 0.0
            self._persist_session_lock()
            self.broadcast_state_changed()
            logging.info("Pending unlock cancelled. Focus session continues.")
            return {"status": "ok", "message": "Unlock request cancelled. Continuing focus."}

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
            return {"status": "ok", "recurring_schedules": self._recurring_schedules_response()}

    def _normalize_recurring_schedule(self, cmd: dict, existing: dict | None = None) -> tuple[bool, str, dict]:
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
        if mode not in ("blacklist", "whitelist", "rescue"):
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
        known_groups = self._load_groups()
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

    def _recurring_schedules_response(self) -> list[dict]:
        now = datetime.now()
        result = []
        for rule in self.recurring_schedules:
            enriched = dict(rule)
            next_run = self._next_recurring_run(rule, now)
            enriched["next_run_at"] = next_run.isoformat() if next_run else None
            enriched["next_run_label"] = next_run.strftime("%a %I:%M %p").replace(" 0", " ") if next_run else "Paused"
            result.append(enriched)
        return result

    def _cmd_add_recurring_schedule(self, cmd: dict) -> dict:
        with self.lock:
            ok, message, new_rule = self._normalize_recurring_schedule(cmd)
            if not ok:
                return {"status": "error", "message": message}
            self.recurring_schedules.append(new_rule)
            self._persist_session_lock()
            self.broadcast_state_changed()
            return {"status": "ok", "message": "Recurring schedule added.", "rule": self._recurring_schedules_response()[-1]}

    def _cmd_update_recurring_schedule(self, cmd: dict) -> dict:
        with self.lock:
            rule_id = cmd.get("id")
            if not rule_id:
                return {"status": "error", "message": "Rule ID is required."}
            for idx, existing in enumerate(self.recurring_schedules):
                if existing.get("id") == rule_id:
                    ok, message, updated = self._normalize_recurring_schedule(cmd, existing)
                    if not ok:
                        return {"status": "error", "message": message}
                    self.recurring_schedules[idx] = updated
                    self._persist_session_lock()
                    self.broadcast_state_changed()
                    return {"status": "ok", "message": "Recurring schedule updated.", "rule": self._recurring_schedules_response()[idx]}
            return {"status": "error", "message": "Recurring schedule not found."}

    def _cmd_toggle_recurring_schedule(self, cmd: dict, enabled: bool) -> dict:
        payload = dict(cmd)
        payload["enabled"] = enabled
        return self._cmd_update_recurring_schedule(payload)

    def _cmd_duplicate_recurring_schedule(self, cmd: dict) -> dict:
        with self.lock:
            rule_id = cmd.get("id")
            source = next((rule for rule in self.recurring_schedules if rule.get("id") == rule_id), None)
            if not source:
                return {"status": "error", "message": "Recurring schedule not found."}
            clone = dict(source)
            clone.pop("id", None)
            clone["name"] = str(cmd.get("name") or f"{source.get('name', 'Focus Ritual')} Copy").strip()
            clone["last_triggered"] = ""
            clone["last_result"] = ""
            clone["last_result_message"] = ""
            ok, message, new_rule = self._normalize_recurring_schedule(clone)
            if not ok:
                return {"status": "error", "message": message}
            self.recurring_schedules.append(new_rule)
            self._persist_session_lock()
            self.broadcast_state_changed()
            return {"status": "ok", "message": "Recurring schedule duplicated.", "rule": self._recurring_schedules_response()[-1]}

    def _cmd_remove_recurring_schedule(self, cmd: dict) -> dict:
        with self.lock:
            rule_id = cmd.get("id")
            if not rule_id:
                return {"status": "error", "message": "Rule ID is required."}
            
            initial_len = len(self.recurring_schedules)
            self.recurring_schedules = [r for r in self.recurring_schedules if r.get("id") != rule_id]
            if len(self.recurring_schedules) < initial_len:
                self._persist_session_lock()
                self.broadcast_state_changed()
                return {"status": "ok", "message": "Recurring schedule removed."}
            return {"status": "error", "message": "Recurring schedule not found."}

    # ── Session History / Tracking ─────────────────────────────────────────────

    def _load_history(self) -> list:
        """Load session history from disk with mtime-based cache."""
        try:
            if not HISTORY_FILE.exists():
                return []
            mtime = HISTORY_FILE.stat().st_mtime
            if self._cached_history is not None and mtime == self._cached_history_mtime:
                return list(self._cached_history)  # Return shallow copy
            data = json.loads(HISTORY_FILE.read_text())
            if isinstance(data, list):
                self._cached_history = data
                self._cached_history_mtime = mtime
                return list(data)
        except Exception as exc:
            logging.error("Failed to load session history: %s", exc)
        return []

    def _save_history(self, entries: list):
        """Persist session history to disk with cap enforcement."""
        if len(entries) > MAX_HISTORY_ENTRIES:
            entries = entries[-MAX_HISTORY_ENTRIES:]
        self._atomic_write_json(HISTORY_FILE, entries)
        # Invalidate cache so next _load_history reads fresh data
        self._cached_history = entries
        try:
            self._cached_history_mtime = HISTORY_FILE.stat().st_mtime
        except Exception:
            self._cached_history_mtime = 0.0

    def _record_session_history(self):
        """Record the current session as a history entry. Called from _cleanup_session() before state reset."""
        if not self.session_expiry or self.total_duration_seconds <= 0:
            return
        if self.session_type == "prayer":
            return

        now = datetime.now()
        started_at = self.session_expiry - timedelta(seconds=self.total_duration_seconds)
        completed_normally = self.pending_unlock_at is None

        tasks = getattr(self, "intent_tasks", []) or []
        tasks_total = len(tasks)
        tasks_completed = sum(1 for t in tasks if isinstance(t, dict) and t.get("completed"))

        duration_minutes = self.total_duration_seconds // 60
        net_focus_minutes = self.total_duration_seconds // 60
        
        if self.session_type == "pomodoro":
            # Only record the untracked remainder
            elapsed_seconds = max(0, (now - started_at).total_seconds())
            remainder_seconds = max(0, elapsed_seconds - getattr(self, "pomo_phases_tracked_seconds", 0))
            if remainder_seconds < 60:
                return  # Skip tiny untracked remnants
            
            duration_minutes = int(remainder_seconds // 60)
            started_at = started_at + timedelta(seconds=getattr(self, "pomo_phases_tracked_seconds", 0))
            if self.pomo_phase == "focus":
                net_focus_minutes = duration_minutes
            else:
                net_focus_minutes = 0

        entry = {
            "id": str(uuid.uuid4()),
            "started_at": started_at.isoformat(),
            "ended_at": now.isoformat(),
            "duration_minutes": duration_minutes,
            "net_focus_minutes": net_focus_minutes,
            "mode": self.mode,
            "session_type": self.session_type,
            "session_group_id": getattr(self, "session_group_id", None) or str(uuid.uuid4()),
            "pomo_phase": getattr(self, "pomo_phase", "focus") if self.session_type == "pomodoro" else None,
            "intent": getattr(self, "intent", None) or "",
            "tasks_total": tasks_total,
            "tasks_completed": tasks_completed,
            "completed_normally": completed_normally,
            "pomo_focus_minutes": self.pomo_focus_minutes if self.session_type == "pomodoro" else None,
            "pomo_break_minutes": self.pomo_break_minutes if self.session_type == "pomodoro" else None,
            "pomo_cycles_completed": self.pomo_current_cycle if self.session_type == "pomodoro" else None,
            "pomo_total_cycles": self.pomo_total_cycles if self.session_type == "pomodoro" else None,
            "groups": list(getattr(self, "session_groups", []) or []),
            "day_of_week": started_at.weekday(),
            "hour_started": started_at.hour,
        }

        history = self._load_history()
        history.append(entry)
        self._save_history(history)
        logging.info("Session history recorded: %s (%dm, %s, %s)",
                     entry["id"][:8], entry["duration_minutes"], entry["mode"], entry["session_type"])

    def _record_pomodoro_phase(self, phase_name: str, duration_minutes: int, started_at: datetime, ended_at: datetime, completed_normally: bool):
        entry = {
            "id": str(uuid.uuid4()),
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_minutes": duration_minutes,
            "net_focus_minutes": duration_minutes if phase_name == "focus" else 0,
            "mode": self.mode,
            "session_type": "pomodoro",
            "session_group_id": getattr(self, "session_group_id", None) or str(uuid.uuid4()),
            "pomo_phase": phase_name,
            "intent": getattr(self, "intent", None) or "",
            "tasks_total": len(getattr(self, "intent_tasks", []) or []),
            "tasks_completed": sum(1 for t in (getattr(self, "intent_tasks", []) or []) if isinstance(t, dict) and t.get("completed")),
            "completed_normally": completed_normally,
            "pomo_focus_minutes": self.pomo_focus_minutes,
            "pomo_break_minutes": self.pomo_break_minutes,
            "pomo_cycles_completed": self.pomo_current_cycle,
            "pomo_total_cycles": self.pomo_total_cycles,
            "groups": list(getattr(self, "session_groups", []) or []),
            "day_of_week": started_at.weekday(),
            "hour_started": started_at.hour,
        }
        history = self._load_history()
        history.append(entry)
        self._save_history(history)
        logging.info("Pomodoro phase recorded: %s (%dm, %s)", entry["id"][:8], duration_minutes, phase_name)

    def _cmd_get_session_history(self, cmd: dict) -> dict:
        """Return session history with server-side aggregation."""
        history = self._load_history()
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

    def _cmd_clear_session_history(self) -> dict:
        """Delete all session history."""
        try:
            if HISTORY_FILE.exists():
                HISTORY_FILE.unlink()
            return {"status": "ok", "message": "Session history cleared."}
        except Exception as exc:
            logging.error("Failed to clear session history: %s", exc)
            return {"status": "error", "message": f"Failed to clear history: {exc}"}

    def _get_status(self) -> dict:
        with self.lock:
            schedules_res = []
            recurring_res = self._recurring_schedules_response()
            prayer_payload = self.prayer_manager.get_status_payload() if self.prayer_manager else {}
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
                    "recurring_schedules": recurring_res,
                    "state_revision": self.state_revision,
                    "notification_warning": self.notification_warning,
                    "prayer": prayer_payload,
                }

            # C3: Use monotonic time for all remaining-seconds fields
            now_mono = get_continuous_time()
            rem = int(max(0, self._mono_session_end - now_mono))

            # Safety net: if session is expired but watchdog hasn't cleaned up,
            # return idle status. The watchdog will handle cleanup within ~250ms.
            if (
                rem <= 0
                and self._mono_session_end > 0
                and now_mono >= self._mono_session_end
            ):
                logging.warning(
                    "Status: session expired but watchdog hasn't cleaned up yet. Returning idle."
                )
                return {
                    "status": "ok",
                    "active": False,
                    "state": "idle",
                    "mode": None,
                    "message": "Session expiring...",
                    "schedules": schedules_res,
                    "recurring_schedules": recurring_res,
                    "state_revision": self.state_revision,
                    "notification_warning": self.notification_warning,
                    "prayer": prayer_payload,
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
                "recurring_schedules": recurring_res,
                "intent": self.intent,
                "intent_tasks": getattr(self, "intent_tasks", []),
                "state_revision": self.state_revision,
                "notification_warning": self.notification_warning,
                "prayer": prayer_payload,
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
        with self.enforcement_lock:
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
                self.hosts_hash = hashlib.sha256(block.encode()).hexdigest()
                # ⚡ Cache stat for cheap watchdog pre-check (avoids full read+hash every 250ms)
                try:
                    st = HOSTS_PATH.stat()
                    self._hosts_stat = (st.st_mtime, st.st_size)
                except Exception:
                    self._hosts_stat = None
            except Exception as exc:
                logging.error("Block enforcement failed: %s", exc)

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

    def _get_network_services(self) -> list[str]:
        """Get all network service names, with 60s cache to reduce subprocess overhead.

        We include *-prefixed services because they can become active
        mid-session (e.g., plugging in Ethernet).
        """
        now = time.monotonic()
        if self._net_services_cache and (now - self._net_services_cache_time) < 60.0:
            return list(self._net_services_cache)
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
                return list(self._net_services_cache) if self._net_services_cache else []

            lines = out.stdout.strip().split("\n")
            # First line is always the header: "An asterisk (*) denotes..."
            services = []
            for line in lines[1:]:
                stripped = line.strip().lstrip("*").strip()
                if stripped:
                    services.append(stripped)
            self._net_services_cache = services
            self._net_services_cache_time = now
            return services
        except Exception as exc:
            logging.error("Failed to get network services: %s", exc)
            return list(self._net_services_cache) if self._net_services_cache else []

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
        """Whitelist mode: restore clean /etc/hosts, enforce PF firewall blocking all except whitelist."""
        with self.enforcement_lock:
            try:
                # 1. Start DNS proxy before breaking the network
                if not self.dns_proxy:
                    self._start_dns_proxy()

                # 2. Pre-resolve whitelisted domain IPs BEFORE any network changes
                #    This must happen while DNS still works normally.
                self._pre_resolve_whitelist_ips()

                # 3. Re-route system DNS to our proxy (localhost)
                self._route_dns_to_proxy()

                # 4. Clean /etc/hosts (we don't need 127.0.0.1 blocks in whitelist mode)
                self._restore_hosts()

                # 5. Enforce strict PF firewall whitelist (IPs already in table)
                upstream = getattr(self.dns_proxy, 'upstream_dns', None) if self.dns_proxy else None
                self._enforce_firewall(True, upstream_dns=upstream)

                # 6. Additional enforcements (same as blacklist to prevent bypasses)
                self._enforce_browser_policies(True)
                self._reset_system_proxies()
                self._kill_vpn_interfaces()
                self._kill_restricted_apps()
                self._clear_browser_caches()
                self._flush_dns()
                
            except Exception as exc:
                logging.error("Whitelist enforcement failed: %s", exc)

    def _start_dns_proxy(self):
        """Start the local DNS proxy for whitelist-mode domain filtering."""
        if self.dns_proxy and self.dns_proxy.running:
            return
        self.dns_proxy = LocalDNSProxy(self)
        self.dns_proxy.start()
        logging.info("DNS proxy started for whitelist mode.")

    def _pre_resolve_whitelist_ips(self):
        """Resolve whitelisted domain IPs and populate PF table BEFORE firewall rules are applied."""
        try:
            domains = set(self.active_domains)
            if not domains:
                return
            
            new_ips = set()
            current_time = time.monotonic()
            for domain in domains:
                try:
                    addr_info = socket.getaddrinfo(domain, None, 0, socket.SOCK_STREAM)
                    for res in addr_info:
                        ip = res[4][0]
                        if ip not in ("127.0.0.1", "::1"):
                            new_ips.add(ip)
                except socket.gaierror:
                    pass

            for ip in new_ips:
                self._whitelisted_ip_backlog[ip] = current_time + (30 * 60)
            
            # Pre-populate the PF table
            if new_ips:
                all_ips = list(self._whitelisted_ip_backlog.keys())
                # Ensure the table exists first
                subprocess.run(["pfctl", "-e"], capture_output=True, timeout=5)
                process = subprocess.Popen(
                    ["pfctl", "-a", "forcefocus", "-t", "ff_whitelisted_ips", "-T", "replace", "-f", "-"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                ips_str = "\n".join(all_ips) + "\n"
                process.communicate(input=ips_str)
                logging.info("Pre-resolved %d whitelisted IPs from %d domains.", len(all_ips), len(domains))
        except Exception as exc:
            logging.error("_pre_resolve_whitelist_ips failed: %s", exc)

    def _route_dns_to_proxy(self):
        """Redirect all network services' DNS to the local proxy (127.0.0.1)."""
        self._set_dns_to_localhost()

    def _restore_hosts(self):
        """Remove session block markers from /etc/hosts (preserves permanent blocks)."""
        try:
            subprocess.run(
                ["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5
            )
            content = self._strip_block(HOSTS_PATH.read_text())
            HOSTS_PATH.write_text(content)
            self.hosts_hash = None
            self._hosts_stat = None
        except Exception as exc:
            logging.error("_restore_hosts failed: %s", exc)

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

    def _set_notification_warning(self, message: str):
        self.notification_warning = {
            "message": message,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.broadcast_state_changed()

    def _send_mac_notification(self, title: str, message: str, subtitle: str = None):
        """Send a macOS system notification natively via the Swift binary."""
        try:
            # Locate the app bundle
            app_path = Path("/Applications/ForcedFocusBar.app/Contents/MacOS/ForcedFocusBar")
            if not app_path.exists():
                # Fallback to local dev path
                app_path = Path(__file__).parent / "ForcedFocusBar.app/Contents/MacOS/ForcedFocusBar"
            
            if app_path.exists():
                args = [
                    str(app_path),
                    "-notify-title", title,
                    "-notify-body", message
                ]
                # Executes in <20ms, zero lag
                subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if self.notification_warning:
                    self.notification_warning = None
                    self.broadcast_state_changed()
            else:
                fallback = "macOS notification could not be delivered because ForcedFocusBar.app was not found."
                self._set_notification_warning(fallback)
                logging.error(fallback)
        except Exception as e:
            self._set_notification_warning(
                "macOS notification could not be delivered. Check Menu Bar app notification permissions."
            )
            logging.error("Failed to send native notification: %s", e)

    def _enforce_current_mode(self):
        if self.mode in ("whitelist", "rescue"):
            threading.Thread(target=self._enforce_whitelist, daemon=True).start()
        else:
            threading.Thread(target=self._enforce_block, daemon=True).start()

    def _remove_block(self):
        """Remove blocking from /etc/hosts without ending the session."""
        try:
            subprocess.run(
                ["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5
            )
            content = self._strip_block(HOSTS_PATH.read_text())
            HOSTS_PATH.write_text(content)
            self.hosts_hash = None
            if self.mode in ("whitelist", "rescue"):
                if self.dns_proxy:
                    self.dns_proxy.stop()
                    self.dns_proxy = None
                self._restore_dns()
            if self.perma_blocklist:
                self._enforce_firewall(True)
            else:
                self._enforce_firewall(False)
            self._enforce_browser_policies(False)
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

        # Defensive path traversal check
        if "/" in filename or "\\" in filename or ".." in filename:
            logging.warning("Blocked directory traversal in played sound filename: %s", filename)
            return

        sound_path = WEB_DIR / "sounds" / filename
        if sound_path.exists():
            subprocess.Popen(
                ["afplay", str(sound_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def _transition_pomodoro_phase(self):
        now = datetime.now()
        
        if self.pomo_phase == "focus":
            phase_started = now - timedelta(minutes=self.pomo_focus_minutes)
        else:
            phase_started = now - timedelta(minutes=self.pomo_break_minutes)

        if self.pomo_phase == "focus":
            self._record_pomodoro_phase("focus", self.pomo_focus_minutes, phase_started, now, True)
            self.pomo_phases_tracked_seconds = getattr(self, "pomo_phases_tracked_seconds", 0) + (self.pomo_focus_minutes * 60)

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
            self._record_pomodoro_phase("break", self.pomo_break_minutes, phase_started, now, True)
            self.pomo_phases_tracked_seconds = getattr(self, "pomo_phases_tracked_seconds", 0) + (self.pomo_break_minutes * 60)

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
        """Teardown active session completely."""
        with self.lock:
            with self.enforcement_lock:
                logging.info("Cleaning up session (mode=%s)...", self.mode)
                self._play_sound("end")
                if self.session_type == "prayer":
                    self._send_mac_notification(
                        "Prayer Complete", "May your prayers be accepted. Focus session unlocked."
                    )
                else:
                    self._send_mac_notification(
                        "Session Complete", "Great job! Your ForcedFocus session has ended."
                    )
                was_whitelist = self.mode in ("whitelist", "rescue")

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
                    if self.perma_blocklist:
                        self._enforce_firewall(True)
                    else:
                        self._enforce_firewall(False)
                    self._enforce_browser_policies(False)
                    self._flush_dns()
                except Exception as exc:
                    logging.error("cleanup_session error: %s", exc)

                # Record session history BEFORE resetting state
                try:
                    self._record_session_history()
                except Exception as exc:
                    logging.error("Failed to record session history: %s", exc)

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
                self._ip_backlog.clear()
                self._whitelisted_ip_backlog.clear()
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

                self._reenforce_event.clear()
                self.pomo_phase = "focus"
                self.pomo_phase_expiry = None
                self.pomo_phases_tracked_seconds = 0
                self.session_group_id = None
                self._mono_session_end = 0.0
                self._mono_unlock_end = 0.0
                self._mono_pomo_phase_end = 0.0
                self._passphrase_attempts = 0
                self.intent = None
                self.intent_tasks = []
                self.session_groups = []
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
    def _update_blocked_ips(self):
        """Resolves active/permanently blocked domains to IPs and updates the PF table with a 30m backlog."""
        try:
            domains_to_resolve_blocks = set(self.perma_blocklist)
            domains_to_resolve_whitelist = set()

            is_break = self.session_type == "pomodoro" and self.pomo_phase == "break"
            if self.active and not is_break:
                if self.mode == "blacklist":
                    domains_to_resolve_blocks.update(self.active_domains)
                elif self.mode in ("whitelist", "rescue"):
                    domains_to_resolve_whitelist.update(self.active_domains)
            
            if not domains_to_resolve_blocks and not domains_to_resolve_whitelist:
                pass

            current_time = time.monotonic()
            
            def _resolve_and_update(domains, backlog):
                if not domains:
                    is_break = getattr(self, "session_type", "") == "pomodoro" and getattr(self, "pomo_phase", "") == "break"
                    if not is_break:
                        backlog.clear()
                    return []
                new_ips = set()
                for domain in domains:
                    try:
                        # Fallback to direct resolution if possible, or just skip local IPs
                        addr_info = socket.getaddrinfo(domain, None, 0, socket.SOCK_STREAM)
                        for res in addr_info:
                            ip = res[4][0]
                            # Don't add localhost to firewall blocks
                            if ip != "127.0.0.1" and ip != "::1":
                                new_ips.add(ip)
                    except socket.gaierror:
                        pass
                
                for ip in new_ips:
                    backlog[ip] = current_time + (30 * 60)
                
                expired = [ip for ip, exp in backlog.items() if current_time > exp]
                for ip in expired:
                    del backlog[ip]
                    
                return list(backlog.keys())

            active_block_ips = _resolve_and_update(domains_to_resolve_blocks, self._ip_backlog)
            active_whitelist_ips = _resolve_and_update(domains_to_resolve_whitelist, self._whitelisted_ip_backlog)

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
            with self.lock:
                self._ip_resolution_running = False


    def _enforce_firewall(self, enable: bool, upstream_dns: str = None):
        """Nuclear firewall enforcement: Blocks QUIC, DoT, and known DoH IPs."""
        try:
            if enable:
                # 1. Enable PF
                subprocess.run(["pfctl", "-e"], capture_output=True, timeout=5)
                # 2. Construct nuclear ruleset
                rules = [
                    "table <ff_blocked_ips> persist",
                    "table <ff_whitelisted_ips> persist",
                    "pass out quick on lo0 all",  # Exempt localhost (for Local DNS Proxy & Web UI)
                    "pass in quick on lo0 all",
                ]

                # Explicitly allow port 53 to prevent Resolver Catch-22
                if upstream_dns:
                    rules.append(f"pass out quick proto {{tcp udp}} from any to {upstream_dns} port 53")
                else:
                    rules.append("pass out quick proto {tcp udp} from any to any port 53")

                rules.extend(
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

                # Block known DoH provider IPs to prevent direct IP-based bypass (only block port 443, not all ports)
                # This goes before the whitelist pass rule so that if a whitelisted site shares an IP,
                # the quick pass rule overrides this block.
                for ip in DOH_IPS:
                    rules.append(
                        f"block return out proto tcp from any to {ip} port 443"
                    )

                is_break = self.session_type == "pomodoro" and self.pomo_phase == "break"
                if self.active and self.mode in ("whitelist", "rescue") and not is_break:
                    rules.extend(
                        [
                            "pass out quick from any to <ff_whitelisted_ips>",
                            "block return out proto {tcp udp} from any to any port {80, 443}",
                        ]
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

    def _reset_system_proxies(self):
        """Reset macOS system proxy settings to prevent SOCKS/HTTP proxy bypass."""
        try:
            services = self._get_network_services()
            for svc in services:
                for proxy_cmd in [
                    ["-setwebproxystate", svc, "off"],
                    ["-setsecurewebproxystate", svc, "off"],
                    ["-setsocksfirewallproxystate", svc, "off"],
                    ["-setautoproxystate", svc, "off"],
                ]:
                    subprocess.run(
                        ["networksetup"] + proxy_cmd,
                        capture_output=True, timeout=5,
                    )
        except Exception as exc:
            logging.error("Failed to reset system proxies: %s", exc)

    def _kill_vpn_interfaces(self):
        """Detect and disable VPN tunnel network interfaces (utun, ipsec, ppp, etc.)."""
        try:
            result = subprocess.run(
                ["ifconfig", "-l"], capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return
            interfaces = result.stdout.strip().split()
            # utun0–3 are macOS system interfaces; higher numbers are VPN tunnels
            system_utuns = {"utun0", "utun1", "utun2", "utun3"}
            vpn_prefixes = ("utun", "ipsec", "ppp", "tun", "tap", "gif", "stf")
            for iface in interfaces:
                if any(iface.startswith(prefix) for prefix in vpn_prefixes):
                    if iface in system_utuns:
                        continue
                    subprocess.run(
                        ["ifconfig", iface, "down"],
                        capture_output=True, timeout=5,
                    )
                    logging.info("Disabled VPN interface: %s", iface)
        except Exception as exc:
            logging.error("VPN interface cleanup failed: %s", exc)

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
                        "pomo_phases_tracked_seconds": getattr(self, "pomo_phases_tracked_seconds", 0),
                    }
                )
            if self.mode in ("whitelist", "rescue"):
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
            data["session_group_id"] = getattr(self, "session_group_id", None)
            data["intent"] = getattr(self, "intent", None)
            data["intent_tasks"] = getattr(self, "intent_tasks", [])
            data["session_groups"] = getattr(self, "session_groups", [])

        if hasattr(self, 'prayer_manager') and self.prayer_manager:
            pm = self.prayer_manager
            data["prayer_state"] = {
                "prayer_active": pm._prayer_active,
                "current_prayer_name": pm._current_prayer_name,
                "mono_prayer_end_remaining": max(0, pm._mono_prayer_end - get_continuous_time()) if pm._prayer_active else 0,
                "suspended_session": pm._suspended_session,
                "skipped_prayers": list(pm._skipped_prayers),
            }

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

    def _validate_settings(self, settings_dict: dict) -> tuple[bool, str, dict]:
        """Validate settings types, keys, and values to prevent injection and drift."""
        validated = self.settings.copy()
        
        for k, v in settings_dict.items():
            if k not in DEFAULT_SETTINGS:
                return False, f"Unknown setting key: {k}", {}
                
            if k == "intent_notification_enabled":
                if not isinstance(v, bool):
                    return False, f"intent_notification_enabled must be a boolean, got {type(v).__name__}", {}
                validated[k] = v
            elif k == "intent_notification_interval":
                # Ensure it's a strict integer and not a boolean (bool is a subclass of int in Python)
                if not isinstance(v, int) or isinstance(v, bool):
                    return False, f"intent_notification_interval must be an integer, got {type(v).__name__}", {}
                if v <= 0:
                    return False, "intent_notification_interval must be positive", {}
                validated[k] = v
            elif k == "daily_focus_goal_hours":
                if not isinstance(v, (int, float)):
                    return False, f"daily_focus_goal_hours must be a number, got {type(v).__name__}", {}
                if v < 0 or v > 24:
                    return False, "daily_focus_goal_hours must be between 0 and 24", {}
                validated[k] = v
            elif k.startswith("sound_"):
                if v is not None and not isinstance(v, str):
                    return False, f"{k} must be a string or null, got {type(v).__name__}", {}
                if isinstance(v, str) and v != "":
                    # Reject traversal sequences
                    if "/" in v or "\\" in v or ".." in v:
                        return False, f"{k} contains invalid path characters", {}
                validated[k] = v
            elif k == "allowed_extension_ids":
                if not isinstance(v, list):
                    return False, "allowed_extension_ids must be a list", {}
                for eid in v:
                    if not isinstance(eid, str) or len(eid) > 64:
                        return False, "Invalid extension ID", {}
                validated[k] = v
            elif k == "prayer_latitude":
                if v is not None:
                    if not isinstance(v, (int, float)) or isinstance(v, bool):
                        return False, f"prayer_latitude must be a number or null, got {type(v).__name__}", {}
                    if v < -90 or v > 90:
                        return False, "prayer_latitude must be between -90 and 90", {}
                validated[k] = v
            elif k == "prayer_longitude":
                if v is not None:
                    if not isinstance(v, (int, float)) or isinstance(v, bool):
                        return False, f"prayer_longitude must be a number or null, got {type(v).__name__}", {}
                    if v < -180 or v > 180:
                        return False, "prayer_longitude must be between -180 and 180", {}
                validated[k] = v
            elif k in ("prayer_enabled", "aggressive_cache_clear"):
                if isinstance(v, str):
                    validated[k] = v.lower() == "true"
                else:
                    validated[k] = bool(v)
            elif k == "schedules":
                if isinstance(v, list):
                    validated[k] = v
                
        return True, "", validated

    def _cmd_save_settings(self, cmd: dict) -> dict:
        new_settings = cmd.get("settings")
        if new_settings is None or not isinstance(new_settings, dict):
            return {"status": "error", "message": "Settings must be a dictionary."}
        if not new_settings:
            return {"status": "error", "message": "No settings provided."}
            
        success, err_msg, validated_settings = self._validate_settings(new_settings)
        if not success:
            return {"status": "error", "message": f"Invalid settings: {err_msg}"}
            
        old_lat = self.settings.get("prayer_latitude")
        old_lng = self.settings.get("prayer_longitude")

        if self._save_settings(validated_settings):
            new_lat = self.settings.get("prayer_latitude")
            new_lng = self.settings.get("prayer_longitude")
            
            # Immediately fetch new prayer times if location changed
            if (old_lat != new_lat or old_lng != new_lng) and getattr(self, "prayer_manager", None):
                self.prayer_manager._cache_date = ""
                self.prayer_manager._last_fetch_attempt = 0.0
                
                # Fetch synchronously to validate coordinates against the API
                fetch_success = self.prayer_manager.fetch_today()
                if not fetch_success:
                    return {
                        "status": "warning",
                        "message": "Saved location, but Aladhan API failed to fetch prayer times. Please check your internet connection and try again.",
                        "settings": validated_settings
                    }

            self.broadcast_state_changed()
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

        # Reject path traversal attempts
        if "/" in filename or "\\" in filename or ".." in filename:
            return {"status": "error", "message": "Directory traversal detected in filename."}

        target_path = WEB_DIR / "sounds" / filename

        try:
            target_path.resolve().relative_to(WEB_DIR.resolve() / "sounds")
            if target_path.exists():
                target_path.unlink()
                logging.info("User deleted sound: %s", filename)
                return {"status": "ok", "message": f"Sound '{filename}' deleted."}
            return {"status": "error", "message": "File not found."}
        except Exception as exc:
            return {"status": "error", "message": f"Delete failed: {str(exc)}"}

    @staticmethod
    def _looks_like_mp3(audio_data: bytes) -> bool:
        """Accept ID3-tagged MP3s or raw MPEG audio frames."""
        if len(audio_data) < 4:
            return False
        if audio_data.startswith(b"ID3"):
            return True
        return audio_data[0] == 0xFF and (audio_data[1] & 0xE0) == 0xE0

    def _cmd_upload_sound(self, cmd: dict) -> dict:
        MAX_SOUND_SIZE = 5 * 1024 * 1024  # 5MB limit per sound file
        filename = cmd.get("filename", "").strip()
        data_b64 = cmd.get("data", "")

        if not filename or not data_b64:
            return {"status": "error", "message": "Missing filename or data."}

        # Reject path traversal attempts
        if "/" in filename or "\\" in filename or ".." in filename:
            return {"status": "error", "message": "Directory traversal detected in filename."}

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
            if not self._looks_like_mp3(audio_data):
                return {
                    "status": "error",
                    "message": "Invalid MP3 data.",
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

    def _watchdog_loop(self):
        logging.info(
            "Watchdog thread started (interval=%.0fms).", WATCHDOG_INTERVAL * 1000
        )
        self._wd_dns_counter = 0
        self._wd_persist_counter = 0
        self._wd_ip_update_counter = 0
        while True:
            time.sleep(WATCHDOG_INTERVAL)
            try:
                self._watchdog_tick()
            except Exception as exc:
                logging.error("Watchdog tick error (non-fatal): %s", exc, exc_info=True)

    def _watchdog_tick(self):
        cmd_to_start = None
        recurring_rule_id = None

        with self.lock:
            now_mono = get_continuous_time()
            now = datetime.now()

            if self.prayer_manager:
                if self.prayer_manager._prayer_active:
                    if not self.settings.get("prayer_enabled", True) or now_mono >= self.prayer_manager._mono_prayer_end:
                        self.prayer_manager.end_prayer_rescue()
                        return
                elif self.settings.get("prayer_enabled", True):
                    if self._check_prayer_trigger():
                        return
            
            if self.prayer_manager:
                today_str = now.strftime("%Y-%m-%d")
                if self.prayer_manager._cache_date != today_str:
                    if now_mono - self.prayer_manager._last_fetch_attempt > 60:
                        self.prayer_manager._last_fetch_attempt = now_mono
                        threading.Thread(target=self.prayer_manager.fetch_today, name="prayer_fetch", daemon=True).start()

            # 1. Evaluate recurring schedules every ~10 seconds (to avoid missing minute boundaries due to tick alignment/sleep)
            is_recurring_trigger = False
            if self.recurring_schedules:
                if now_mono - self._mono_last_recurring_check >= 10.0:
                    self._mono_last_recurring_check = now_mono
                    
                    for r_sch in self.recurring_schedules:
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
                                    # Forward pomodoro params if present
                                    if r_sch.get("session_type") == "pomodoro":
                                        cmd_to_start["focus_minutes"] = r_sch.get("focus_minutes", 25)
                                        cmd_to_start["break_minutes"] = r_sch.get("break_minutes", 5)
                                        cmd_to_start["cycles"] = r_sch.get("cycles", 4)
                                    is_recurring_trigger = True
                                    recurring_rule_id = r_sch.get("id")
                                    self._persist_session_lock()
                                    logging.info("Recurring schedule %s triggered.", r_sch.get("id"))
                                    break
                        if cmd_to_start:
                            break

            # 2. Check one-off schedules if no recurring triggered
            if not cmd_to_start and self.schedules:
                # Clean up any schedules that have completely expired while asleep
                while self.schedules and datetime.now() >= self.schedules[0].get("end_time"):
                    expired_sch = self.schedules.pop(0)
                    logging.info("Scheduled session (start: %s) expired while asleep and was skipped.", expired_sch["start_time"].strftime("%H:%M"))
                
                # Check if the first schedule is ready and active (within range)
                if self.schedules:
                    if self.schedules[0].get("start_time") <= datetime.now() < self.schedules[0].get("end_time"):
                        sch = self.schedules.pop(0)
                        cmd_to_start = sch["cmd"]
                        self._persist_session_lock()

            if cmd_to_start and self.active:
                if hasattr(self, 'prayer_manager') and self.prayer_manager and self.prayer_manager._prayer_active:
                    self.prayer_manager._deferred_schedule_cmd = cmd_to_start
                    if recurring_rule_id:
                        for r in self.recurring_schedules:
                            if r.get("id") == recurring_rule_id:
                                r["last_result"] = "deferred"
                                r["last_result_message"] = "Deferred until prayer ends."
                                break
                else:
                    if recurring_rule_id:
                        for r in self.recurring_schedules:
                            if r.get("id") == recurring_rule_id:
                                r["last_result"] = "failed"
                                r["last_result_message"] = "Could not start schedule: another session is already active."
                                break
                cmd_to_start = None
                self._persist_session_lock()
                self.broadcast_state_changed()

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
            if is_recurring_trigger and recurring_rule_id:
                with self.lock:
                    for r_sch in self.recurring_schedules:
                        if r_sch.get("id") == recurring_rule_id:
                            if result.get("status") == "ok":
                                r_sch["last_result"] = "started"
                                r_sch["last_result_message"] = result.get("message", "")
                            else:
                                r_sch["last_result"] = "failed"
                                r_sch["last_result_message"] = result.get("message", "unknown error")
                            r_sch["updated_at"] = datetime.now().isoformat()
                            self._persist_session_lock()
                            self.broadcast_state_changed()
                            break
            if result.get("status") != "ok":
                logging.warning(
                    "Scheduled session failed to start: %s",
                    result.get("message", "unknown error"),
                )
            return

        with self.lock:
            # C1: Handle signal-driven re-enforce (flag set without lock)
            if self._reenforce_event.is_set():
                self._reenforce_event.clear()
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

            # ── IP Blocking Watchdog (runs every 60s) ──
            self._wd_ip_update_counter = getattr(self, "_wd_ip_update_counter", 0) + 1
            if self._wd_ip_update_counter >= 240:  # 240 * 250ms = 60s
                self._wd_ip_update_counter = 0
                if not getattr(self, "_ip_resolution_running", False):
                    self._ip_resolution_running = True
                    threading.Thread(target=self._update_blocked_ips, daemon=True).start()

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
                if self._wd_perma_counter >= 20:  # 20 * 250ms = 5s
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
            if self.mode not in ("whitelist", "rescue"):
                try:
                    st = HOSTS_PATH.stat()
                    current_stat = (st.st_mtime, st.st_size)
                    # Fast path: if mtime and size haven't changed, skip the hash
                    if self._hosts_stat is not None and current_stat == self._hosts_stat:
                        pass  # File untouched — no I/O needed
                    else:
                        # Slow path: stat changed, verify with full hash
                        current = HOSTS_PATH.read_text()
                        
                        # Extract only the session block for comparison
                        lines = current.split("\n")
                        in_block = False
                        block_lines = []
                        for line in lines:
                            if MARKER_BEGIN in line:
                                in_block = True
                            if in_block:
                                block_lines.append(line)
                            if MARKER_END in line:
                                in_block = False
                        
                        if not block_lines:
                            # Session block completely removed — tamper
                            logging.warning("HOSTS TAMPER DETECTED (session block missing). Re-enforcing.")
                            self._enforce_block()
                        else:
                            block_content = "\n".join(block_lines)
                            h = hashlib.sha256(block_content.encode()).hexdigest()
                            if h != self.hosts_hash:
                                logging.warning("HOSTS TAMPER DETECTED. Re-enforcing.")
                                self._enforce_block()
                            else:
                                # Hash matches but stat drifted (e.g. perma block changed) — update cache
                                self._hosts_stat = current_stat
                except Exception as exc:
                    logging.error("Watchdog hosts error: %s", exc)

            # Integrity check: Firewall (QUIC block) every ~30s (was 5s) to reduce CPU
            self._wd_firewall_counter += 1
            if self._wd_firewall_counter >= 120:
                self._wd_firewall_counter = 0
                try:
                    res = subprocess.run(
                        ["pfctl", "-a", "forcefocus", "-s", "rules"],
                        capture_output=True,
                        text=True,
                        timeout=2,
                    )
                    # Check for '443' and 'udp' in ruleset output
                    if not re.search(r'\b443\b', res.stdout) or not re.search(r'\budp\b', res.stdout):
                        logging.warning(
                            "FIREWALL TAMPER DETECTED. Rules: '%s'. Re-enforcing.",
                            res.stdout.strip(),
                        )
                        upstream = (
                            self.dns_proxy.upstream_dns
                            if (
                                self.mode in ("whitelist", "rescue")
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
                if self.mode in ("whitelist", "rescue"):
                    self._enforce_whitelist()
                else:
                    self._enforce_block()

            # Integrity check: DNS (whitelist mode, every ~30 seconds)
            if self.mode in ("whitelist", "rescue"):
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

            # Integrity check: Proxy/VPN/App Watchdog (every ~30s instead of 10s)
            if self._wd_persist_counter % 120 == 0:
                self._kill_restricted_apps()
                self._kill_vpn_interfaces()

            # Integrity check: System Proxy Watchdog (every ~60s)
            self._wd_proxy_counter = getattr(self, "_wd_proxy_counter", 0) + 1
            if self._wd_proxy_counter >= 240:  # 240 * 250ms = 60s
                self._wd_proxy_counter = 0
                self._reset_system_proxies()

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
        elif action == "cancel_stop":
            return self._cancel_stop()
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
        elif action == "update_recurring_schedule":
            return self._cmd_update_recurring_schedule(cmd)
        elif action == "pause_recurring_schedule":
            return self._cmd_toggle_recurring_schedule(cmd, False)
        elif action == "resume_recurring_schedule":
            return self._cmd_toggle_recurring_schedule(cmd, True)
        elif action == "duplicate_recurring_schedule":
            return self._cmd_duplicate_recurring_schedule(cmd)
        elif action == "remove_recurring_schedule":
            return self._cmd_remove_recurring_schedule(cmd)
        elif action == "get_templates":
            return self._cmd_get_templates()
        elif action == "add_template":
            return self._cmd_add_template(cmd)
        elif action == "update_template":
            return self._cmd_update_template(cmd)
        elif action == "remove_template":
            return self._cmd_remove_template(cmd)
        elif action == "duplicate_template":
            return self._cmd_duplicate_template(cmd)
        elif action == "start_template":
            return self._cmd_start_template(cmd)
        elif action == "get_settings":
            return self._cmd_get_settings()
        elif action == "save_settings":
            return self._cmd_save_settings(cmd)
        elif action == "get_sounds":
            return self._cmd_get_sounds()
        elif action == "delete_sound":
            return self._cmd_delete_sound(cmd)
        elif action == "upload_sound":
            return self._cmd_upload_sound(cmd)
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}


    def _check_prayer_trigger(self) -> bool:
        if not hasattr(self, 'prayer_manager') or not self.prayer_manager:
            return False
        pm = self.prayer_manager
        if pm._prayer_active:
            return False
        
        now = datetime.now()
        
        for name in PRAYER_NAMES:
            if name in pm._today_prayers and name not in pm._skipped_prayers:
                ptime = pm._today_prayers[name]
                if ptime <= now < ptime + timedelta(seconds=PRAYER_DURATION_S):
                    logging.info("Prayer time reached/active: %s. Triggering PRAYER_RESCUE.", name)
                    pm.start_prayer_rescue(name)
                    return True
        return False

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

    def handle_error(self, request, client_address):
        if sys.exc_info()[0] is ConnectionResetError:
            return
        super().handle_error(request, client_address)


class EmbeddedWebHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _is_origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        if origin in ("http://localhost:7070", "http://127.0.0.1:7070"):
            return True
        if origin.startswith("chrome-extension://"):
            # Check if origin matches allowed IDs
            ext_id = origin.replace("chrome-extension://", "")
            try:
                daemon = self.server.daemon_ref
                allowed_ids = daemon.settings.get("allowed_extension_ids", ["hcgpgflhkpdccdjkkobofpaemcgjmhdc"])
                if isinstance(allowed_ids, list):
                    return ext_id in allowed_ids or "*" in allowed_ids
                if isinstance(allowed_ids, str):
                    return ext_id == allowed_ids or allowed_ids == "*"
            except Exception:
                pass
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
        if origin and self._is_origin_allowed():
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
        if filepath.suffix == ".html":
            html_str = body.decode("utf-8", errors="ignore")
            daemon = self.server.daemon_ref
            token = getattr(daemon, "api_token", "")
            # Safe JSON serialization for script tags
            safe_token = json.dumps(token).replace("<", "\\u003c")
            inject_js = f'<script>window.apiToken = {safe_token};</script>'
            if "<head>" in html_str:
                html_str = html_str.replace("<head>", f"<head>{inject_js}", 1)
            else:
                html_str = inject_js + html_str
            body = html_str.encode("utf-8")

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

        # Require token verification on configuration-revealing endpoints
        config_revealing_endpoints = {
            "/api/settings",
            "/api/lists",
            "/api/perma-blocklist",
            "/api/schedules/recurring",
            "/api/templates",
            "/api/groups",
        }
        if path in config_revealing_endpoints:
            if not self._is_api_token_valid():
                self._send_json(
                    {
                        "status": "error",
                        "message": "Unauthorized: invalid or missing API token.",
                    },
                    401,
                )
                return

        if path == "/api/status":
            self._send_json(self.server.daemon_ref._get_status())
        elif path == "/api/prayer-times":
            if hasattr(self.server.daemon_ref, 'prayer_manager') and self.server.daemon_ref.prayer_manager:
                self._send_json(self.server.daemon_ref.prayer_manager.get_status_payload())
            else:
                self._send_json({"status": "error", "message": "Prayer system not initialized."})
        elif path == "/api/schedules/recurring":
            self._send_json(self.server.daemon_ref._cmd_get_recurring_schedules())
        elif path == "/api/templates":
            self._send_json(self.server.daemon_ref._cmd_get_templates())
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
                    now = time.time()
                    force_update = False
                    
                    timeout = 0.5 if daemon.active else 5.0
                    try:
                        q.get(timeout=timeout)
                        force_update = True
                        while not q.empty():
                            try:
                                q.get_nowait()
                            except queue.Empty:
                                break
                    except queue.Empty:
                        pass
                        
                    if force_update or now - last_written_time >= 10.0:
                        status_data = daemon._get_status()
                        body = json.dumps(status_data)
                        if body != last_written_body or now - last_written_time >= 10.0:
                            self.wfile.write(f"data: {body}\n\n".encode("utf-8"))
                            self.wfile.flush()
                            last_written_body = body
                            last_written_time = time.time()
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
        elif path == "/api/history":
            query_params = dict(p.split("=", 1) for p in parsed.query.split("&") if "=" in p) if parsed.query else {}
            self._send_json(self.server.daemon_ref._cmd_get_session_history(query_params))
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
        elif path == "/api/prayer-skip":
            if hasattr(self.server.daemon_ref, 'prayer_manager') and self.server.daemon_ref.prayer_manager:
                self._send_json(self.server.daemon_ref.prayer_manager.skip_next_prayer())
            else:
                self._send_json({"status": "error", "message": "Prayer system not initialized."})
        elif path == "/api/prayer-unskip":
            if hasattr(self.server.daemon_ref, 'prayer_manager') and self.server.daemon_ref.prayer_manager:
                self._send_json(self.server.daemon_ref.prayer_manager.unskip_last_prayer())
            else:
                self._send_json({"status": "error", "message": "Prayer system not initialized."})
        elif path == "/api/intent":
            self._send_json(self.server.daemon_ref._set_intent(body))
        elif path == "/api/settings":
            self._send_json(self.server.daemon_ref._cmd_save_settings({"settings": body}))
        elif path == "/api/upload-sound":
            self._send_json(self.server.daemon_ref._cmd_upload_sound(body))
        elif path == "/api/delete-sound":
            self._send_json(self.server.daemon_ref._cmd_delete_sound(body))
        elif path == "/api/stop":
            self._send_json(self.server.daemon_ref._request_stop(body.get("key", "")))
        elif path == "/api/cancel-stop":
            self._send_json(self.server.daemon_ref._cancel_stop())
        elif path == "/api/schedules/recurring":
            self._send_json(self.server.daemon_ref._cmd_add_recurring_schedule(body))
        elif path.startswith("/api/schedules/recurring/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                self._send_json(self.server.daemon_ref._cmd_update_recurring_schedule({**body, "id": parts[3]}))
            elif len(parts) == 5 and parts[4] == "pause":
                self._send_json(self.server.daemon_ref._cmd_toggle_recurring_schedule({**body, "id": parts[3]}, False))
            elif len(parts) == 5 and parts[4] == "resume":
                self._send_json(self.server.daemon_ref._cmd_toggle_recurring_schedule({**body, "id": parts[3]}, True))
            elif len(parts) == 5 and parts[4] == "duplicate":
                self._send_json(self.server.daemon_ref._cmd_duplicate_recurring_schedule({**body, "id": parts[3]}))
            else:
                self._send_json({"status": "error", "message": "Unknown endpoint."}, 404)
        elif path == "/api/templates":
            self._send_json(self.server.daemon_ref._cmd_add_template(body))
        elif path.startswith("/api/templates/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[3] == "start":
                self._send_json(self.server.daemon_ref._cmd_start_template({"id": parts[2]}))
            elif len(parts) == 4 and parts[3] == "duplicate":
                self._send_json(self.server.daemon_ref._cmd_duplicate_template({**body, "id": parts[2]}))
            elif len(parts) == 3:
                self._send_json(self.server.daemon_ref._cmd_update_template({**body, "id": parts[2]}))
            else:
                self._send_json({"status": "error", "message": "Unknown endpoint."}, 404)
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
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "templates":
            self._send_json(self.server.daemon_ref._cmd_remove_template({"id": parts[2]}))
        elif len(parts) == 2 and parts[0] == "api" and parts[1] == "history":
            self._send_json(self.server.daemon_ref._cmd_clear_session_history())
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
    if len(sys.argv) > 1:
        print("ERROR: Daemon does not accept arguments.", file=sys.stderr)
        sys.exit(1)
    if os.geteuid() != 0:
        print("ERROR: ForcedFocus daemon must run as root.", file=sys.stderr)
        sys.exit(1)
    daemon = ForcedFocusDaemon()
    daemon.run()


if __name__ == "__main__":
    main()
