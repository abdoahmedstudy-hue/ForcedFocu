import sys

def main():
    file_path = '/Users/aboda/Documents/ForcedFocu/daemon/forcefocus_daemon.py'
    with open(file_path, 'r') as f:
        lines = f.readlines()
        
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Instantiate SchedulesManager in __init__
        if "self.domains_manager = DomainsManager(self)" in line:
            new_lines.append(line)
            new_lines.append("        from forcefocus.schedules import SchedulesManager\n")
            new_lines.append("        self.schedules_manager = SchedulesManager(self)\n")
            i += 1
            continue
            
        if "def _load_templates(" in line:
            # Skip all template methods until _load_perma_state
            while i < len(lines) and "def _load_perma_state(" not in lines[i]:
                i += 1
            
            # Add delegated methods
            delegation = """    def _load_templates(self) -> list[dict]:
        return self.schedules_manager.load_templates()

    def _save_templates(self, templates: list[dict]):
        self.schedules_manager.save_templates(templates)

    def _cmd_get_templates(self) -> dict:
        return self.schedules_manager.cmd_get_templates()

    def _cmd_add_template(self, cmd: dict) -> dict:
        return self.schedules_manager.cmd_add_template(cmd)

    def _cmd_update_template(self, cmd: dict) -> dict:
        return self.schedules_manager.cmd_update_template(cmd)

    def _cmd_remove_template(self, cmd: dict) -> dict:
        return self.schedules_manager.cmd_remove_template(cmd)

    def _cmd_duplicate_template(self, cmd: dict) -> dict:
        return self.schedules_manager.cmd_duplicate_template(cmd)

    def _cmd_start_template(self, cmd: dict) -> dict:
        return self.schedules_manager.cmd_start_template(cmd)

    # ── Permanent Blocklist Management ────────────────────────────────────────

"""
            new_lines.extend(delegation.splitlines(True))
            continue
            
        if "def _cmd_cancel_schedule(" in line:
            # Skip _cmd_cancel_schedule
            while i < len(lines) and "def _cmd_get_recurring_schedules(" not in lines[i]:
                i += 1
            
            # Add delegated cancel schedule
            new_lines.append("    def _cmd_cancel_schedule(self, cmd: dict) -> dict:\n")
            new_lines.append("        return self.schedules_manager.cmd_cancel_schedule(cmd)\n\n")
            continue
            
        if "def _cmd_get_recurring_schedules(" in line:
            # Skip all recurring schedule methods until Session History
            while i < len(lines) and "# ── Session History / Tracking ─────────────────────────────────────────────" not in lines[i]:
                i += 1
                
            delegation = """    def _cmd_get_recurring_schedules(self) -> dict:
        return self.schedules_manager.cmd_get_recurring_schedules()

    def _cmd_add_recurring_schedule(self, cmd: dict) -> dict:
        return self.schedules_manager.cmd_add_recurring_schedule(cmd)

    def _cmd_update_recurring_schedule(self, cmd: dict) -> dict:
        return self.schedules_manager.cmd_update_recurring_schedule(cmd)

    def _cmd_toggle_recurring_schedule(self, cmd: dict, enabled: bool) -> dict:
        return self.schedules_manager.cmd_toggle_recurring_schedule(cmd, enabled)

    def _cmd_duplicate_recurring_schedule(self, cmd: dict) -> dict:
        return self.schedules_manager.cmd_duplicate_recurring_schedule(cmd)

    def _cmd_remove_recurring_schedule(self, cmd: dict) -> dict:
        return self.schedules_manager.cmd_remove_recurring_schedule(cmd)

"""
            new_lines.extend(delegation.splitlines(True))
            continue

        new_lines.append(line)
        i += 1
        
    with open(file_path, 'w') as f:
        f.writelines(new_lines)

if __name__ == "__main__":
    main()
