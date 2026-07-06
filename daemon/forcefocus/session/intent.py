import logging
import threading
import uuid
import time
import json
from pathlib import Path
from datetime import datetime, timedelta
from forcefocus.constants import *
from forcefocus.utils import get_continuous_time
from forcefocus.events import Event

class IntentMixin:
    def cmd_set_intent(self, cmd: dict) -> dict:
            intent = cmd.get("intent")
            intent_tasks = cmd.get("intent_tasks")
            with self.daemon.lock:
                if not self.daemon.state.session.active:
                    return {
                        "status": "error",
                        "message": "No active session to set intent for.",
                    }
                if intent is not None:
                    self.daemon.state.session.intent = intent.strip() if intent else None
                if intent_tasks is not None:
                    self.daemon.state.session.intent_tasks = intent_tasks
                self._persist_session_lock()
                self.daemon.notifications_manager.broadcast_state_changed()
                logging.info("Session intent updated.")
                return {"status": "ok", "message": "Intent updated."}

