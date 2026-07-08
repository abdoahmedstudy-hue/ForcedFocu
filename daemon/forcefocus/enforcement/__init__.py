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

from .dns import DNSMixin
from .firewall import FirewallMixin
from .system import SystemMixin

class EnforcementManager(DNSMixin, FirewallMixin, SystemMixin):
    def __init__(self, daemon):
        self.daemon = daemon
        from forcefocus.events import Event
        self.daemon.events.subscribe(Event.SESSION_STARTED, self._enforce_current_mode)
        self.daemon.events.subscribe(Event.SESSION_ENDED, self._on_session_ended)
        self.daemon.events.subscribe(Event.PERMA_BLOCK_UPDATED, self._enforce_perma_block)

    def _on_session_ended(self, **kwargs):
        try:
            subprocess.run(["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5)
            content = self._strip_block(HOSTS_PATH.read_text())
            HOSTS_PATH.write_text(content)
            self.daemon.hosts_hash = None
            if self.daemon.state.session.mode in ("whitelist", "ban"):
                if self.daemon.dns_proxy:
                    self.daemon.dns_proxy.stop()
                    self.daemon.dns_proxy = None
                if hasattr(self.daemon, "_stop_sni_proxy"):
                    self.daemon._stop_sni_proxy()
            else:
                # Blacklist mode: briefly toggle DNS to localhost to trigger macOS SCNetworkReachability
                # This forces browsers (Chrome/Safari) to instantly flush their internal DNS caches,
                # resolving the "ERR_CONNECTION_REFUSED" cache bug on break transition.
                self._set_dns_to_localhost()

            self._restore_dns()
            self._clear_browser_caches()
            if self.daemon.perma_blocklist:
                self._enforce_firewall(True)
            else:
                self._enforce_firewall(False)
            self._enforce_browser_policies(False)
            self._flush_dns()
            self._enforce_perma_block()
        except Exception as exc:
            logging.error("Enforcement cleanup error: %s", exc)

    def _enforce_current_mode(self, **kwargs):
            if self.daemon.state.session.mode in ("whitelist", "ban"):
                threading.Thread(target=self._enforce_whitelist, daemon=True).start()
            else:
                threading.Thread(target=self._enforce_block, daemon=True).start()

