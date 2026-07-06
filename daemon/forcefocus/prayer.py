from __future__ import annotations
import json
import time
import urllib.request
import urllib.error
import logging
from datetime import datetime, timedelta
from pathlib import Path

from forcefocus.constants import *
from forcefocus.utils import get_continuous_time

class PrayerManager:
    def __init__(self, daemon):
        self.daemon = daemon

    def cmd_get_prayer(self) -> dict:
        now = datetime.now()
        prayers = self._get_prayer_times_for_date(now)
        skipped = self.daemon.settings.get("prayer_skipped", {})
        # Find next prayer
        next_prayer = None
        for p in prayers:
            if p["time"] > now:
                skip_key = f"{now.strftime('%Y-%m-%d')}-{p['name']}"
                next_prayer = {
                    "name": p["name"],
                    "time": p["time"].isoformat(),
                    "is_skipped": skip_key in skipped
                }
                break
                
        all_prayers = []
        for p in prayers:
            p_skip_key = f"{now.strftime('%Y-%m-%d')}-{p['name']}"
            all_prayers.append({
                "name": p["name"],
                "time": p["time"].isoformat(),
                "is_skipped": p_skip_key in skipped
            })

        return {
            "status": "ok",
            "enabled": self.daemon.settings.get("prayer_block_enabled", False),
            "next_prayer": next_prayer,
            "all_prayers": all_prayers,
            "active_ban": getattr(self, "prayer_ban_active", "")
        }


    def cmd_skip_prayer(self, cmd: dict) -> dict:
        logging.info("cmd_skip_prayer called with: %s", cmd)
        prayer_name = cmd.get("prayer_name")
        cancel = cmd.get("cancel", False)
        
        if not prayer_name:
            return {"status": "error", "message": "Missing prayer_name"}
            
        now = datetime.now()
        prayers = self._get_prayer_times_for_date(now)
        target = next((p for p in prayers if p["name"] == prayer_name), None)
        
        if not target:
            return {"status": "error", "message": "Prayer not found for today."}
            
        skip_key = f"{now.strftime('%Y-%m-%d')}-{prayer_name}"
        skipped = self.daemon.settings.get("prayer_skipped", {})
        
        if cancel:
            if skip_key in skipped:
                del skipped[skip_key]
                self.daemon.settings["prayer_skipped"] = skipped
                try:
                    self.daemon.settings_manager.save_settings(self.daemon.settings)
                except Exception:
                    pass
            return {"status": "ok"}
            
        # Check strict 30-minute rule
        time_diff = (target["time"] - now).total_seconds() / 60.0
        if time_diff <= 30:
            return {"status": "error", "message": "Too late to skip. Can only skip > 30 minutes before prayer."}
            
        # Register skip
        skipped[skip_key] = now.isoformat()
        
        # Clean up old skips
        yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
        keys_to_delete = [k for k in skipped.keys() if k < yesterday]
        for k in keys_to_delete:
            del skipped[k]
            
        self.daemon.settings["prayer_skipped"] = skipped
        try:
            logging.info("Saving settings with new skipped: %s", skipped)
            self.daemon.settings_manager.save_settings(self.daemon.settings)
            logging.info("Successfully skipped prayer.")
            return {"status": "ok"}
        except Exception as exc:
            logging.error("Exception in cmd_skip_prayer: %s", exc)
            return {"status": "error", "message": f"Failed to save settings: {exc}"}


    def _fetch_prayer_calendar(self, year: int, month: int) -> dict:
        """Fetch prayer calendar from Aladhan API for the given year and month."""
        lat = self.daemon.settings.get("prayer_latitude", 0.0)
        lon = self.daemon.settings.get("prayer_longitude", 0.0)
        
        if not lat and not lon:
            logging.warning("Prayer latitude and longitude not set in settings. Skipping Aladhan API fetch.")
            return []
            
        method = self.daemon.settings.get("prayer_method", 2)
        url = f"https://api.aladhan.com/v1/calendar/{year}/{month}?latitude={lat}&longitude={lon}&method={method}"
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'ForcedFocus/2.0'})
            with urllib.request.urlopen(req, timeout=10.0) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    if data.get("code") == 200:
                        return data.get("data", [])
                else:
                    logging.error("Aladhan API returned status %s", response.status)
        except Exception as exc:
            logging.error("Failed to fetch prayer calendar from %s: %s", url, exc)
        return []


    def _get_prayer_times_for_date(self, now: datetime) -> list[dict]:
        """Get prayer times for today, fetching from API if not cached."""
        cache_key = f"{now.year}-{now.month:02d}"
        day_key = f"{now.day:02d}"
        
        cache = {}
        if PRAYER_CACHE_FILE.exists():
            try:
                cache = json.loads(PRAYER_CACHE_FILE.read_text())
            except Exception:
                pass

        if cache_key not in cache or not cache[cache_key]:
            # Fetch and update cache
            month_data = self._fetch_prayer_calendar(now.year, now.month)
            if month_data:
                # Format to a simpler structure
                simple_data = {}
                for day_data in month_data:
                    dt = day_data.get("date", {}).get("gregorian", {}).get("day")
                    if dt:
                        dt = str(int(dt)).zfill(2) # ensure "05" instead of "5"
                    timings = day_data.get("timings", {})
                    # Clean timings (remove timezone string like ' (EEST)')
                    clean_timings = {}
                    for k, v in timings.items():
                        clean_timings[k] = v.split(" ")[0]
                    simple_data[dt] = clean_timings
                cache[cache_key] = simple_data
                try:
                    self.daemon._atomic_write_json(PRAYER_CACHE_FILE, cache)
                except Exception as exc:
                    logging.error("Failed to write prayer cache to %s: %s", PRAYER_CACHE_FILE, exc)
            else:
                logging.error("Prayer calendar API returned empty data, skipping cache update.")
        
        # Now extract the required prayers
        required_prayers = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
        times = []
        day_data = cache.get(cache_key, {}).get(day_key, {})
        if day_data:
            for p in required_prayers:
                if p in day_data:
                    t_str = day_data[p]
                    # Parse time
                    try:
                        hour, minute = map(int, t_str.split(":"))
                        p_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                        times.append({"name": p, "time": p_time})
                    except Exception:
                        pass
        return times


    def _evaluate_prayer_block(self, now: datetime) -> tuple[bool, str]:
        """Check if we are currently in a prayer block window."""
        if not self.daemon.settings.get("prayer_block_enabled", False):
            return False, ""
            
        prayers = self._get_prayer_times_for_date(now)
        if not prayers:
            return False, ""
            
        mins_before = self.daemon.settings.get("prayer_minutes_before", 10)
        mins_after = self.daemon.settings.get("prayer_minutes_after", 30)
        skipped = self.daemon.settings.get("prayer_skipped", {})
        
        for p in prayers:
            p_time = p["time"]
            start_block = p_time - timedelta(minutes=mins_before)
            end_block = p_time + timedelta(minutes=mins_after)
            
            if start_block <= now <= end_block:
                skip_key = f"{now.strftime('%Y-%m-%d')}-{p['name']}"
                if skip_key in skipped:
                    continue  # User skipped this prayer
                return True, p["name"]
                
        return False, ""

