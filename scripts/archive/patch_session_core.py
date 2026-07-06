import re

with open("daemon/forcefocus/session/core.py", "r") as f:
    code = f.read()

# Replace block/whitelist thread calls with event emission
# Instead of threading.Thread(..._enforce_whitelist...).start()
# -> self.daemon.events.emit(Event.SESSION_STARTED)
code = re.sub(
    r'threading\.Thread\(target=self\.daemon\.enforcement_manager\._enforce_(whitelist|block).*?\.start\(\)',
    r'self.daemon.events.emit(Event.SESSION_STARTED)',
    code
)

# During _remove_block and _cleanup_session, replace explicit teardown with SESSION_ENDED
cleanup_pattern = r'''\s*if self\.daemon\.state\.session\.mode in \("whitelist", "ban"\):
\s*if self\.daemon\.dns_proxy:
\s*self\.daemon\.dns_proxy\.stop\(\)
\s*self\.daemon\.dns_proxy = None
\s*self\._stop_sni_proxy\(\)
\s*self\.daemon\.enforcement_manager\._restore_dns\(\)
\s*if self\.daemon\.perma_blocklist:
\s*self\.daemon\.enforcement_manager\._enforce_firewall\(True\)
\s*else:
\s*self\.daemon\.enforcement_manager\._enforce_firewall\(False\)
\s*self\.daemon\.enforcement_manager\._enforce_browser_policies\(False\)
\s*self\.daemon\.enforcement_manager\._flush_dns\(\)'''

# For _cleanup_session there is also perma_block call
perma_pattern = r'''\s*self\.daemon\.enforcement_manager\._enforce_perma_block\(\)'''

# I'll just manually replace the chunks in python
