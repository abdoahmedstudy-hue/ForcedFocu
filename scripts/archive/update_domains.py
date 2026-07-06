import os
import re

daemon_file = "/Users/aboda/Documents/ForcedFocu/daemon/forcefocus_daemon.py"
with open(daemon_file, "r") as f:
    content = f.read()

# 1. Add import
if "from forcefocus.domains import DomainsManager" not in content:
    content = content.replace(
        "from forcefocus.settings import SettingsManager",
        "from forcefocus.settings import SettingsManager\nfrom forcefocus.domains import DomainsManager"
    )

# 2. Add initialization
if "self.domains_manager =" not in content:
    content = content.replace(
        "self.settings_manager = SettingsManager(self)",
        "self.settings_manager = SettingsManager(self)\n        self.domains_manager = DomainsManager(self)"
    )

# 3. Replace methods in ForcedFocusDaemon

# _load_lists
content = re.sub(
    r'    def _load_lists\(self\) -> dict:.*?return \{"blacklist": \[\], "whitelist": \[\]\}\n',
    '    def _load_lists(self) -> dict:\n        return self.domains_manager.load_lists()\n',
    content,
    flags=re.DOTALL
)

# _save_lists
content = re.sub(
    r'    def _save_lists\(self, lists: dict\):.*?self\.broadcast_state_changed\(\)\n',
    '    def _save_lists(self, lists: dict):\n        self.domains_manager.save_lists(lists)\n',
    content,
    flags=re.DOTALL
)

# _load_groups
content = re.sub(
    r'    def _load_groups\(self\) -> dict:.*?return \{\}\n',
    '    def _load_groups(self) -> dict:\n        return self.domains_manager.load_groups()\n',
    content,
    flags=re.DOTALL
)

# _save_groups
content = re.sub(
    r'    def _save_groups\(self, groups: dict\):.*?self\.broadcast_state_changed\(\)\n',
    '    def _save_groups(self, groups: dict):\n        self.domains_manager.save_groups(groups)\n',
    content,
    flags=re.DOTALL
)

# Replace _cmd_get_lists to _cmd_remove_group
content = re.sub(
    r'    def _cmd_get_lists\(self\) -> dict:.*?return \{"status": "error", "message": f"Group \'\{name\}\' not found\."\}\n',
    '''    def _cmd_get_lists(self) -> dict:
        return self.domains_manager.cmd_get_lists()

    def _cmd_add_domain(self, cmd: dict) -> dict:
        return self.domains_manager.cmd_add_domain(cmd)

    def _cmd_add_domains(self, cmd: dict) -> dict:
        return self.domains_manager.cmd_add_domains(cmd)

    def _cmd_remove_domain(self, cmd: dict) -> dict:
        return self.domains_manager.cmd_remove_domain(cmd)

    def _cmd_get_groups(self) -> dict:
        return self.domains_manager.cmd_get_groups()

    def _cmd_add_group(self, cmd: dict) -> dict:
        return self.domains_manager.cmd_add_group(cmd)

    def _cmd_remove_group(self, cmd: dict) -> dict:
        return self.domains_manager.cmd_remove_group(cmd)\n''',
    content,
    flags=re.DOTALL
)

# Replace _get_blacklist_domains
content = re.sub(
    r'    def _get_blacklist_domains\(self, selected_groups: list\[str\] = None\) -> list\[str\]:.*?return domains\n',
    '    def _get_blacklist_domains(self, selected_groups: list[str] = None) -> list[str]:\n        return self.domains_manager.get_blacklist_domains(selected_groups)\n',
    content,
    flags=re.DOTALL
)

# Replace _expand_whitelist_domains
content = re.sub(
    r'    def _expand_whitelist_domains\(self, domains: list\[str\]\) -> list\[str\]:.*?return sorted\(expanded\)\n',
    '    def _expand_whitelist_domains(self, domains: list[str]) -> list[str]:\n        return self.domains_manager.expand_whitelist_domains(domains)\n',
    content,
    flags=re.DOTALL
)

# Update perma_block usages of self._extract_domain and self._validate_domain
content = content.replace("self._extract_domain(", "self.domains_manager.extract_domain(")
content = content.replace("self._validate_domain(", "self.domains_manager.validate_domain(")

# Restore DNS proxy's _extract_domain call
content = content.replace(
    "domain = self.domains_manager.extract_domain(data)",
    "domain = self._extract_domain(data)"
)

with open(daemon_file, "w") as f:
    f.write(content)

print("Updated domains delegation")
