import json
import logging
from datetime import datetime
from forcefocus.constants import SETTINGS_FILE, DEFAULT_SETTINGS, PRAYER_CACHE_FILE, CONFIG_DIR

class SettingsManager:
    def __init__(self, daemon):
        self.daemon = daemon

    def load_settings(self):
        """Load settings from JSON, merging with defaults."""
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text())
                # Merge defaults to ensure new settings exist
                final = DEFAULT_SETTINGS.copy()
                final.update(data)
                return final
        except Exception as exc:
            logging.error("Failed to load settings: %s", exc)
        return DEFAULT_SETTINGS.copy()

    def save_settings(self, new_settings):
        """Save settings to JSON."""
        try:
            if hasattr(self.daemon, 'settings'):
                old_lat = self.daemon.settings.get("prayer_latitude")
                old_lon = self.daemon.settings.get("prayer_longitude")
                old_method = self.daemon.settings.get("prayer_method")
                new_lat = new_settings.get("prayer_latitude")
                new_lon = new_settings.get("prayer_longitude")
                new_method = new_settings.get("prayer_method")
                
                if old_lat != new_lat or old_lon != new_lon or old_method != new_method:
                    if PRAYER_CACHE_FILE.exists():
                        try:
                            PRAYER_CACHE_FILE.unlink()
                        except Exception:
                            pass

            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            self.daemon._atomic_write_json(SETTINGS_FILE, new_settings, indent=2)
            self.daemon.settings = new_settings
            return True
        except Exception as exc:
            logging.error("Failed to save settings: %s", exc)
            return False

    def cmd_get_settings(self) -> dict:
        return {"status": "ok", "settings": getattr(self.daemon, 'settings', {})}

    def validate_settings(self, settings_dict: dict) -> tuple[bool, str, dict]:
        """Validate settings types, keys, and values to prevent injection and drift."""
        validated = self.daemon.settings.copy() if hasattr(self.daemon, 'settings') else DEFAULT_SETTINGS.copy()
        
        for k, v in settings_dict.items():
            if k not in DEFAULT_SETTINGS:
                return False, f"Unknown setting key: {k}", {}
                
            if k == "intent_notification_enabled":
                if not isinstance(v, bool):
                    return False, f"intent_notification_enabled must be a boolean, got {type(v).__name__}", {}
                validated[k] = v
            elif k == "intent_notification_interval":
                if not isinstance(v, int) or isinstance(v, bool):
                    return False, f"intent_notification_interval must be an integer, got {type(v).__name__}", {}
                if v <= 0:
                    return False, "intent_notification_interval must be positive", {}
                validated[k] = v
            elif k == "daily_focus_goal_hours":
                if not isinstance(v, (int, float)):
                    return False, f"daily_focus_goal_hours must be a number, got {type(v).__name__}", {}
                if v < 0 or v > 24:
                    return False, "daily_focus_goal_hours must be between 0 and 24", {}
                validated[k] = v
            elif k.startswith("sound_"):
                if v is not None and not isinstance(v, str):
                    return False, f"{k} must be a string or null, got {type(v).__name__}", {}
                if isinstance(v, str) and v != "":
                    if "/" in v or "\\" in v or ".." in v:
                        return False, f"{k} contains invalid path characters", {}
                validated[k] = v
            elif k == "prayer_block_enabled":
                if not isinstance(v, bool):
                    return False, f"prayer_block_enabled must be a boolean", {}
                validated[k] = v
            elif k in ("prayer_latitude", "prayer_longitude"):
                if not isinstance(v, (int, float)):
                    return False, f"{k} must be a number", {}
                validated[k] = v
            elif k in ("prayer_method", "prayer_minutes_before", "prayer_minutes_after"):
                if not isinstance(v, int) or isinstance(v, bool):
                    return False, f"{k} must be an integer", {}
                validated[k] = v
            elif k == "prayer_skipped":
                if not isinstance(v, dict):
                    return False, f"prayer_skipped must be a dict", {}
                pass
                
        if "prayer_skipped" in settings_dict:
            validated["prayer_skipped"] = getattr(self.daemon, 'settings', {}).get("prayer_skipped", {})
                
        return True, "", validated

    def cmd_save_settings(self, cmd: dict) -> dict:
        new_settings = cmd.get("settings")
        if new_settings is None or not isinstance(new_settings, dict):
            return {"status": "error", "message": "Settings must be a dictionary."}
        if not new_settings:
            return {"status": "error", "message": "No settings provided."}
            
        success, err_msg, validated_settings = self.validate_settings(new_settings)
        if not success:
            return {"status": "error", "message": f"Invalid settings: {err_msg}"}
            
        # Check prayer block disable constraint
        was_enabled = getattr(self.daemon, 'settings', {}).get("prayer_block_enabled", False)
        is_enabled = validated_settings.get("prayer_block_enabled", False)
        if was_enabled and not is_enabled:
            now = datetime.now()
            prayers = self.daemon.prayer_manager._get_prayer_times_for_date(now)
            next_p = next((p for p in prayers if p["time"] > now), None)
            if next_p:
                rem_mins = (next_p["time"] - now).total_seconds() / 60.0
                if rem_mins <= 30:
                    return {"status": "error", "message": "Cannot disable prayer mode within 30 minutes of a prayer."}
            
        if self.save_settings(validated_settings):
            self.daemon.notifications_manager.broadcast_state_changed()
            return {
                "status": "ok",
                "message": "Settings saved.",
                "settings": getattr(self.daemon, 'settings', {}),
            }
        return {"status": "error", "message": "Failed to save settings."}
