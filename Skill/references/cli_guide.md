# ForcedFocus CLI Implementation Reference 💻

The ForcedFocus CLI is structured as a modular package inside `cli/` linked to a root-level backward-compatible shim: `forcefocus_cli.py`.

---

## 📂 Code Layout

```
forcefocus_cli.py (Shim) -> Links and runs cli.main.main()
└── cli/
    ├── __init__.py      -> Package initialization
    ├── main.py          -> CLI argparse definition, pre-parsing, and routing
    ├── client.py        -> Socket client wrapper handling connect, write, and read
    ├── output.py        -> Console output formatting (Rich vs JSON mode)
    ├── proxy.py         -> Test-patching proxy interceptor classes
    └── commands/        -> Modular Command Handlers
        ├── domains.py   -> list domains / add / remove
        ├── groups.py    -> list groups / add / remove
        ├── perma_block.py -> list perma-block / add / unblock / cancel
        ├── schedule.py  -> list schedules / add / remove
        ├── set_key.py   -> set daemon passphrase (interactive)
        ├── settings.py  -> show configuration / update settings
        ├── sound.py     -> list sound files / delete sound file
        ├── start.py     -> start time-bound/pomodoro sessions
        ├── status.py    -> print current session state dashboard
        ├── stop.py      -> request session unblock countdown
        └── web.py       -> start/stop web API dashboard service
```

---

## 🧪 Testing Proxy Interceptor Mechanism

To maintain compatibility with older integration tests that patch imports directly on `forcefocus_cli` (e.g. `@patch("forcefocus_cli.send_command")`), the CLI uses a proxy layer defined in `cli/proxy.py`. 

Instead of import statements calling standard libraries directly:
```python
# Instead of:
import os
import sys
import socket

# The CLI imports:
from cli.proxy import os, sys_proxy as sys, socket
```

These proxy objects dynamically check `sys.modules` for `"forcefocus_cli"`. If it exists and has a mocked version of `os`, `sys`, or `send_command`, the proxy forwards the invocation to the mock object. Otherwise, it transparently forwards calls to the actual standard library module.

---

## 🚦 Global Pre-Parsing Precedence

Global flags override subcommand structures. To prevent subcommands from resetting global output flags (like `--agent` and `--human`), `cli/main.py` parses `sys.argv` for output tokens directly before running `parse_args()`:

```python
if any(h in sys.argv for h in ["--human", "-H"]):
    out.is_human = True
    out.is_agent = False
elif any(a in sys.argv for a in ["--agent", "-A"]):
    out.is_human = False
    out.is_agent = True
```

This guarantees consistent structured output patterns for automation scripts and AI agents.

---

## 🛠️ CLI Subcommand Details

### 1. `start`
*   **Flags**:
    *   `--duration, -d <MIN>`: Duration of the session in minutes (default: 120).
    *   `--mode, -m [blacklist|whitelist]`: Block policy (default: blacklist).
    *   `--type [standard|pomodoro]`: Set session category.
    *   `--focus <MIN>`, `--break <MIN>`, `--cycles <COUNT>`: Configure Pomodoro parameters.
    *   `--in <MIN>`: Delay session startup by N minutes.
    *   `--at <HH:MM>`: Schedule session startup at a specific time.
    *   `--groups, -g <NAMES>`: Space-separated list of domain groups to load.

### 2. `stop`
*   **Flags**:
    *   `--key, -k <PASSPHRASE>`: Required passphrase to authorize emergency stop.

### 3. `status`
Outputs current focus session state. Returns JSON in agent mode, and styled Rich panel charts in human mode.

### 4. `domains`
*   **Usage**: `forcefocus domains [show|add|remove] [blacklist|whitelist] <domains...>`
*   Manages regular block and allow lists.

### 5. `groups`
*   **Usage**: `forcefocus groups [list|add|remove] [name] <domains...>`
*   Defines logical collections of domains (e.g. `social`, `development`).

### 6. `perma-block`
*   **Usage**: `forcefocus perma-block [list|add|unblock|cancel] <domain> [--key PASSPHRASE]`
*   Enforces continuous, session-independent blocking. Unblocking triggers a 30-minute security cooldown timer.

### 7. `schedule`
*   **Usage**: `forcefocus schedule [list|add|remove] [--recurring] [--days DAYS] [--time HH:MM] [--duration MIN]`
*   Configures automated calendar-based blocking intervals.

### 8. `settings`
*   **Usage**: `forcefocus settings [show|set] [key] [value]`
*   Retrieves or sets daemon preferences. Validates values against expected types (e.g., boolean normalization from `true`, `yes`, `1` or `false`, `no`, `0`).

### 9. `sound`
*   **Usage**: `forcefocus sound [list|delete] [filename]`
*   Lists alert sound assets or deletes a specific `.mp3` file (with path resolution validation).

---

## 🔬 Testing CLI Commands

To execute tests and verify that no changes trigger regressions, run:

```bash
# Run modular tests specifically
pytest tests/test_cli_domains.py
pytest tests/test_cli_groups.py
pytest tests/test_cli_settings.py
pytest tests/test_cli_sound.py

# Run shim/integration tests
pytest tests/test_forcefocus_cli.py
```
