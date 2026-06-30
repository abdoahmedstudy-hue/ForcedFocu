---
name: forcedfocus
description: "Use to manage, monitor, test, and interact with the ForcedFocus root-level macOS productivity enforcement daemon, CLI, and web interface. Make sure to use this skill whenever the user mentions ForcedFocus, domain blocking, whitelist/blacklist configuration, or when writing and reviewing code changes related to ForcedFocus daemon, CLI modules, REST APIs, or system testing."
risk: high
source: custom
date_added: "2026-05-22"
---

# ForcedFocus Agent Skill ⚡

## Overview

ForcedFocus is a multi-layered, root-level productivity enforcement system for macOS. It combines a system daemon, a native menubar utility (`ForcedFocusBar.app`), a web dashboard, and a browser extension.

This skill provides the primary reference workflows for managing, developing, and testing the ForcedFocus application.

---

## 🧭 Reference Guides Index

To avoid context pollution, detailed specifications are distributed across specialized reference files. Read the appropriate file as needed based on your current task:

*   **Architecture & Design Layers**: Refer to [architecture.md](file:///Volumes/ssd/File/App/ForcedFocus/ForcedFocu/Skill/references/architecture.md) for enforcement methodologies (PF firewall, local DNS proxy, hosts locking) and persistence directories.
*   **Watchdog Tick Daemon Logic**: Refer to [watchdog.md](file:///Volumes/ssd/File/App/ForcedFocus/ForcedFocu/Skill/references/watchdog.md) for loop intervals (4Hz), processes killed (VPNs/browsers), signals handling, and time locks.
*   **Unix Socket JSON API**: Refer to [socket_api.md](file:///Volumes/ssd/File/App/ForcedFocus/ForcedFocu/Skill/references/socket_api.md) for 1MB payload limits and JSON schemas for starting/stopping sessions, status, settings, and sounds.
*   **HTTP REST API Webserver**: Refer to [rest_api.md](file:///Volumes/ssd/File/App/ForcedFocus/ForcedFocu/Skill/references/rest_api.md) for port 7070 routing mapping, X-API-Token authentication headers, and Server-Sent Events (SSE).
*   **CLI Implementation & Testing Guides**: Refer to [cli_guide.md](file:///Volumes/ssd/File/App/ForcedFocus/ForcedFocu/Skill/references/cli_guide.md) for the `cli/` module layout, the `cli/proxy.py` system-mocking wrapper, global flag overrides, subcommands details, and test instructions.

---

## 🛠️ Typical Development & Interactivity Workflows

### 1. Modifying the Daemon or CLI Subcommands
When implementing a new feature or modifying socket/REST API endpoints:
1. Identify the target module (e.g. `cli/commands/settings.py` or `forcefocus_daemon.py`).
2. Read the appropriate API guide: [socket_api.md](file:///Volumes/ssd/File/App/ForcedFocus/ForcedFocu/Skill/references/socket_api.md) or [rest_api.md](file:///Volumes/ssd/File/App/ForcedFocus/ForcedFocu/Skill/references/rest_api.md).
3. If writing tests for your CLI subcommands, see [cli_guide.md](file:///Volumes/ssd/File/App/ForcedFocus/ForcedFocu/Skill/references/cli_guide.md) to understand how to mock imports using proxies without modifying the live filesystem.
4. Execute tests locally using Pytest to ensure zero regressions:
   ```bash
   pytest
   ```

### 2. Safeguarding Active Network Connection during Whitelist/Rescue Sessions
> [!CAUTION]
> If you start a whitelist or Rescue Throne session during development/testing without proper configurations, you may block your own container/shell network access. Always run tests using isolated mock structures or very short duration timers (e.g., 1 minute).

### 3. Deploying and Uninstalling Changes
To compile and copy modifications to the system paths:
*   Recompile menubar app: `bash build_menubar.sh`
*   Deploy new binaries and modules: `sudo bash install.sh`
*   Revert and uninstall: `sudo bash uninstall.sh`

---

## 🤖 Agent Autonomy & Handling Delayed Actions

### 1. Agent Autonomy ("Do Anything" Rule)
As an agent with terminal and root/sudo permissions, you have full control over the ForcedFocus system. You are permitted to:
*   Start sessions (`forcefocus start`) to test blocking policies.
*   Initiate emergency unlocks (`forcefocus stop --key PASSPHRASE`).
*   Modify list files and settings.
*   Interact with the socket `/var/run/forcefocus.sock` or REST API directly using custom scripts or CLI overrides.

### 2. Handling Delayed Actions ("The Waiting Rule")
ForcedFocus enforces a strict delay mechanism on two security-sensitive events:
1.  **Stopping an Active Session**: Triggers a **20-minute countdown delay** before network rules are restored to normal.
2.  **Removing a Domain from the Permanent Blocklist**: Triggers a **30-minute countdown delay** before the domain is deleted from `/etc/hosts` / `perma_blocklist.json`.

**Critical Instructions for Agents Handling Delays:**
*   **Do Not Expect Immediate Effect**: When executing `forcefocus stop` or `forcefocus perma-block unblock`, you will receive a `pending` status. This is expected behavior. Do not treat it as a bug or failure.
*   **Time Shifting Is Blocked**: Since session progress tracks using the system `monotonic` clock, you cannot speed up the delay by changing the macOS system time.
*   **Monitoring and Waiting**: If your task requires verifying that a session has fully stopped or that a domain is completely unblocked:
    1.  Read the current status (`forcefocus status --agent` or `GET /api/status`) and inspect the `pending_unlock` or `pending_unlock_seconds` fields.
    2.  Use a background task schedule/timer or a polling loop with progressive sleep intervals (e.g. checking status periodically) if verification of the complete termination is necessary.
    3.  If you are running tests or automated scripts, mock the delays or use mock daemon configurations to bypass the monotonic countdowns.

