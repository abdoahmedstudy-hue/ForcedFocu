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

from .core import CoreMixin
from .pomodoro import PomodoroMixin
from .intent import IntentMixin

class SessionManager(CoreMixin, PomodoroMixin, IntentMixin):
    def __init__(self, daemon):
            self.daemon = daemon

