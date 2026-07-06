from pathlib import Path

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
_local_web = Path(__file__).resolve().parent.parent / "web"
WEB_DIR = _local_web if _local_web.exists() else Path("/usr/local/share/forcefocus/web")
SETTINGS_FILE = CONFIG_DIR / "settings.json"
PERMA_BLOCK_FILE = CONFIG_DIR / "perma_blocklist.json"
TEMPLATES_FILE = CONFIG_DIR / "templates.json"
HISTORY_FILE = CONFIG_DIR / "session_history.json"
PRAYER_CACHE_FILE = CONFIG_DIR / "prayer_calendar.json"
MAX_HISTORY_ENTRIES = 10000

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
    "daily_focus_goal_hours": 0,
    "allowed_extension_ids": ["hcgpgflhkpdccdjkkobofpaemcgjmhdc"],
    "prayer_block_enabled": False,
    "prayer_latitude": 0.0,
    "prayer_longitude": 0.0,
    "prayer_method": 2,
    "prayer_minutes_before": 10,
    "prayer_minutes_after": 30,
    "prayer_skipped": {},
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
