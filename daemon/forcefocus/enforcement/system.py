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

class SystemMixin:
    def _clear_browser_caches(self):
            """Deep clean of browser caches and service workers across all profiles.
    
            Can be disabled via settings: {"aggressive_cache_clear": false}
            """
            if not self.daemon.settings.get("aggressive_cache_clear", True):
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

