import base64
import queue
import logging
import threading
import subprocess
from pathlib import Path
from datetime import datetime
from forcefocus.constants import WEB_DIR

class NotificationsManager:
    def __init__(self, daemon):
        self.daemon = daemon
        self.state_changed = threading.Event()
        self.state_revision = 0
        self.notification_warning: dict | None = None
        self._sse_listeners = set()
        self._sse_listeners_lock = threading.Lock()

    def register_sse_listener(self, q):
        with self._sse_listeners_lock:
            self._sse_listeners.add(q)

    def unregister_sse_listener(self, q):
        with self._sse_listeners_lock:
            self._sse_listeners.discard(q)

    def broadcast_state_changed(self):
        self.state_revision += 1
        self.state_changed.set()
        with self._sse_listeners_lock:
            for q in self._sse_listeners:
                try:
                    q.put_nowait(True)
                except queue.Full:
                    pass

    def set_notification_warning(self, message: str):
        self.notification_warning = {
            "message": message,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.broadcast_state_changed()

    def send_mac_notification(self, title: str, message: str, subtitle: str = None):
        """Send a macOS system notification natively via the Swift binary."""
        try:
            # Locate the app bundle
            app_path = Path("/Applications/ForcedFocusBar.app/Contents/MacOS/ForcedFocusBar")
            if not app_path.exists():
                # Fallback to local dev path
                app_path = Path(__file__).parent.parent / "ForcedFocusBar.app/Contents/MacOS/ForcedFocusBar"
            
            if app_path.exists():
                args = [
                    str(app_path),
                    "-notify-title", title,
                    "-notify-body", message
                ]
                # Executes in <20ms, zero lag
                subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if self.notification_warning:
                    self.notification_warning = None
                    self.broadcast_state_changed()
            else:
                fallback = "macOS notification could not be delivered because ForcedFocusBar.app was not found."
                self.set_notification_warning(fallback)
                logging.error(fallback)
        except Exception as e:
            self.set_notification_warning(
                "macOS notification could not be delivered. Check Menu Bar app notification permissions."
            )
            logging.error("Failed to send native notification: %s", e)

    def play_sound(self, category: str):
        """Play a configured sound file using macOS afplay."""
        setting_key = f"sound_{category.lower().replace(' ', '_')}"
        filename = getattr(self.daemon, "settings", {}).get(setting_key)

        if not filename:
            # Fallback if the specific key doesn't exist
            return

        # Defensive path traversal check
        if "/" in filename or "\\" in filename or ".." in filename:
            logging.warning("Blocked directory traversal in played sound filename: %s", filename)
            return

        sound_path = WEB_DIR / "assets" / "sounds" / filename
        if sound_path.exists():
            subprocess.Popen(
                ["afplay", str(sound_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )





    def cmd_get_sounds(self) -> dict:
        """List all available sound files in web/assets/sounds."""
        sounds_dir = WEB_DIR / "assets" / "sounds"
        if not sounds_dir.exists():
            return {"status": "ok", "sounds": []}
        try:
            files = [f.name for f in sounds_dir.iterdir() if f.suffix.lower() == ".mp3"]
            return {"status": "ok", "sounds": sorted(files)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def cmd_delete_sound(self, cmd: dict) -> dict:
        filename = cmd.get("filename", "").strip()
        if not filename:
            return {"status": "error", "message": "No filename provided."}
        # Reject path traversal attempts
        if "/" in filename or "\\" in filename or ".." in filename:
            return {"status": "error", "message": "Directory traversal detected in filename."}
        # Sanitize and check path
        safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ")
        target_path = WEB_DIR / "assets" / "sounds" / safe_name
        try:
            target_path.resolve().relative_to(WEB_DIR.resolve() / "assets" / "sounds")
            if target_path.exists():
                target_path.unlink()
                logging.info("User deleted sound: %s", safe_name)
                return {"status": "ok", "message": f"Sound '{safe_name}' deleted."}
            return {"status": "error", "message": "File not found."}
        except Exception as exc:
            return {"status": "error", "message": f"Delete failed: {str(exc)}"}

    def cmd_upload_sound(self, cmd: dict) -> dict:
        MAX_SOUND_SIZE = 5 * 1024 * 1024  # 5MB limit per sound file
        filename = cmd.get("filename", "").strip()
        data_b64 = cmd.get("data", "")
        if not filename or not data_b64:
            return {"status": "error", "message": "Missing filename or data."}
        # Reject path traversal attempts
        if "/" in filename or "\\" in filename or ".." in filename:
            return {"status": "error", "message": "Directory traversal detected in filename."}
        if not filename.lower().endswith(".mp3"):
            return {"status": "error", "message": "Only .mp3 files are allowed."}
        # Sanitize filename
        safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ")
        if not safe_name:
            return {"status": "error", "message": "Invalid filename."}
        target_path = WEB_DIR / "assets" / "sounds" / safe_name
        # Path traversal protection (matches _cmd_delete_sound)
        try:
            sounds_dir = (WEB_DIR / "assets" / "sounds").resolve()
            target_path.resolve().relative_to(sounds_dir)
        except ValueError:
            return {"status": "error", "message": "Invalid file path."}
        try:
            # Ensure sounds dir exists
            target_path.parent.mkdir(parents=True, exist_ok=True)
            # Decode and validate size
            audio_data = base64.b64decode(data_b64)
            if len(audio_data) > MAX_SOUND_SIZE:
                return {
                    "status": "error",
                    "message": f"File too large (max {MAX_SOUND_SIZE // (1024*1024)}MB).",
                }
            if not self._looks_like_mp3(audio_data):
                return {
                    "status": "error",
                    "message": "Invalid MP3 data.",
                }
            target_path.write_bytes(audio_data)
            logging.info(
                "User uploaded new sound: %s (%d bytes)", safe_name, len(audio_data)
            )
            return {
                "status": "ok",
                "message": f"Sound '{safe_name}' uploaded successfully.",
            }
        except Exception as exc:
            logging.error("Upload error: %s", exc)
            return {"status": "error", "message": f"Upload failed: {str(exc)}"}
