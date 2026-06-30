# ForcedFocus Watchdog Tick Mechanics ⏱️

This reference describes the watchdog thread lifecycle, scheduled task execution, and processes managed by the ForcedFocus daemon's integrity loop.

---

## 🔄 Watchdog Thread Core Loop

The ForcedFocus daemon runs a background watchdog thread running at **4Hz (one tick every 250 milliseconds)**. This thread enforces network integrity and reverses any attempts at user tampering.

| Frequency | Check Name | Description |
| :--- | :--- | :--- |
| **Every Tick (250ms)** | **One-off Schedules** | Checks standard schedules by comparing monotonic clock anchors to ensure sessions start and end accurately. |
| **Every Tick (250ms)** | **Signal Re-enforcement** | If a reload signal (`SIGINT`, `SIGTERM`, `SIGHUP`) is caught, it instantly flags and re-enforces all active block structures on the next tick. |
| **Every 1 sec (4 ticks)** | **Firewall rules** | Inspects `pfctl -a forcefocus -s rules`. If the anchor rules blocking UDP port 443 are missing or flushed, it re-creates them. |
| **Every 2 sec (8 ticks)** | **Host File Integrity** | Performed in a two-tier strategy:<br/>• *Tier 1 (Fast)*: Call `os.stat` on `/etc/hosts` to detect size/mtime change. Returns in ~2μs if unchanged.<br/>• *Tier 2 (Slow)*: If modified, recalculates SHA-256 hash. If it deviates from the expected configuration, it unlocks the file, rewrites it, and locks it back using `chflags uchg`. |
| **Every 5 sec (20 ticks)** | **Process Killer** | Iterates over the active system process table to identify and terminate unauthorized VPN, browser, or utility processes. |
| **Every 10 sec (40 ticks)** | **Recurring Schedules** | Evaluates recurring schedule blocks, checking if the current weekday index and local time (`HH:MM`) match active entries. |
| **Every 30 sec (120 ticks)** | **DNS Redirection** | (Whitelist only) Verifies that macOS primary DNS servers (`networksetup -getdnsservers`) point to `127.0.0.1`. Restores them if tampered with. |

---

## 🚫 Restricted Process List

The process killer runs every 5 seconds and instantly terminates (via `kill -9`) the following executable names:

### 1. VPN / Tunneling Software (Bypass vectors)
*   `Tailscale` / `WireGuard`
*   `Cisco AnyConnect` / `GlobalProtect`
*   `Tunnelblick` / `OpenVPN`
*   `NordVPN` / `ExpressVPN` / `Mullvad` / `ProtonVPN` / `Surfshark` / `ivpn-gui` / `Windscribe`
*   `CloudflareWARP`

### 2. Unmanaged / Privacy-Focused Web Browsers
These browsers are restricted during active sessions since they might bypass local system proxies or ignore system-wide DNS configurations:
*   `Opera`
*   `Vivaldi`
*   `TorBrowser`
*   `Arc`
*   `Sidekick`
*   `SigmaOS`
*   `Orion`
*   `Waterfox`

### 3. Bypass Tools
*   `Activity Monitor` (restricted to prevent forcing termination of the daemon process itself).

---

## 🛡️ Tamper Protections

*   **Monotonic Time Lock**: Session timers are anchored using Python's `time.monotonic()` clock. Modifying the system calendar date or timezone settings does not bypass or accelerate active blocking configurations.
*   **Atomic Persistence Writes**: Configuration changes (`settings.json`, `lists.json`, `perma_blocklist.json`) are written atomically (temp file creation followed by rename). The watchdog reloads clean defaults if files are corrupted or modified directly by unauthorized editors.
*   **Security Lockout**: If a user enters an incorrect passphrase multiple times to force-unlock a session or unblock a permanent domain, the daemon initiates an exponential backoff time penalty, culminating in a full lockout after 5 consecutive failures.
