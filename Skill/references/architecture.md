# ForcedFocus Architecture Reference 🗺️

This document describes the multi-layered system design, orchestration, and persistence architecture of ForcedFocus.

---

## 🏗️ Multi-Layer Defense Architecture

The application is structured into four main operational layers: Client (UI/CLI), Orchestration (Daemon/Webserver), Enforcement (macOS Kernel/System), and Persistence.

```mermaid
graph TB
    subgraph "Client Layer (User Interface)"
        WebUI["<b>Web Dashboard</b><br/>(React/JS)<br/><i>Polls @ 2.0s</i>"]
        MacApp["<b>Mac Menubar App</b><br/>(Swift/WKWebView)<br/><i>Polls @ 1.0s / 5.0s</i>"]
        CLIShim["<b>forcefocus_cli.py</b><br/>(Backwards-Compatible Shim)"]
        CLIMain["<b>cli/main.py</b><br/>(Argparse Entry Point)"]
        CLICmds["<b>cli/commands/*.py</b><br/>(Modular Subcommands)"]
    end

    subgraph "Orchestration Layer (Root)"
        Daemon["<b>ForcedFocus Daemon</b><br/>(Python 3.13)"]
        Watchdog["<b>Watchdog Thread</b><br/>(0.25s ticks)"]
        APIServer["<b>HTTP API Server</b><br/>(Port 7070)"]
    end

    subgraph "Enforcement Layer (macOS Kernel/System)"
        PF["<b>PF Firewall</b><br/>(pfctl rules)"]
        DNS["<b>Local DNS Proxy</b><br/>(Hijacks Port 53)"]
        Hosts["<b>/etc/hosts</b><br/>(Immutability via chflags)"]
    end

    subgraph "Persistence Layer"
        Lock["session.lock"]
        Lists["lists.json / groups.json"]
        Settings["settings.json"]
        Perma["perma_blocklist.json"]
    end

    CLIShim -- "Imports" --> CLIMain
    CLIMain -- "Routes to" --> CLICmds
    CLICmds -- "Unix Socket" --> Daemon
    WebUI -- "HTTP REST API" --> APIServer
    MacApp -- "HTTP REST API" --> APIServer

    APIServer -- "Controls" --> Daemon
    Daemon -- "Manages" --> Watchdog
    
    Daemon -- "Writes" --> Lock
    Daemon -- "Loads/Saves" --> Lists
    Daemon -- "Loads/Saves" --> Settings
    Daemon -- "Loads/Saves" --> Perma

    Watchdog -- "Verifies Integrity" --> Hosts
    Watchdog -- "Re-enforces" --> PF
    Daemon -- "Hijacks System DNS" --> DNS
```

---

## 🛡️ Enforcement Mechanisms

ForcedFocus operates at the system administration/root level of macOS to ensure blocks cannot be bypassed easily:

1.  **PF Firewall (`pfctl`)**:
    *   Used to block UDP port 443 (QUIC traffic).
    *   This forces web browsers to fallback to standard HTTP/TCP connections, which respects `/etc/hosts` DNS resolution mapping and prevents bypassing hosts-file routing.
2.  **DNS Hijacking / Upstream DNS Proxy**:
    *   In **Whitelist Mode**, the system modifies system DNS settings (`networksetup -setdnsservers`) to point to `127.0.0.1`.
    *   It runs a local DNS proxy server on Port 53 that answers `NXDOMAIN` for blocked requests and proxies allowed ones to upstream DNS.
3.  **Host File Immutability (`chflags`)**:
    *   Appends blocked domains to `/etc/hosts` mapping them to `127.0.0.1`.
    *   Sets the system immutable flag: `chflags uchg /private/etc/hosts`. This blocks any editing, deletion, or renaming of the file (even by the `root` user) until the flag is explicitly unset.

---

## 📂 Persistence Directory (`/etc/forcefocus/`)

The daemon holds state configuration files inside `/etc/forcefocus/`, requiring root permissions for read/write operations:

*   `lists.json`: Stores configured blacklisted and whitelisted domains.
*   `groups.json`: Maps user-defined groups (e.g. `social`, `work`) to domain arrays.
*   `perma_blocklist.json`: Contains the domains to block permanently (session-independent) and countdown parameters for pending unblock requests.
*   `settings.json`: Persists application setting overrides (like sound choices and intent prompts).
*   `session.lock`: Stores current session details (remaining seconds, active mode, start anchors) and pomodoro cycles.
*   `ks_hash`: Stores the PBKDF2-HMAC-SHA256 hash of the unblock security passphrase.
*   `api_token`: Houses the auto-generated authorization token used for validating REST API modifications.
