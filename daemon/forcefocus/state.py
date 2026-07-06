from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class SessionState:
    active: bool = False
    mode: str = "blacklist"
    session_type: str = "standard"
    session_expiry: datetime | None = None
    total_duration_seconds: int = 0
    pending_unlock_at: datetime | None = None
    intent: str | None = None
    intent_tasks: list = field(default_factory=list)
    session_groups: list[str] = field(default_factory=list)
    session_group_id: str | None = None

    def reset(self):
        """Atomically reset all session fields to defaults."""
        self.active = False
        self.mode = "blacklist"
        self.session_type = "standard"
        self.session_expiry = None
        self.total_duration_seconds = 0
        self.pending_unlock_at = None
        self.intent = None
        self.intent_tasks = []
        self.session_groups = []
        self.session_group_id = None


@dataclass  
class PomodoroState:
    pomo_phase: str = "focus"
    pomo_next_phase: str | None = None
    pomo_focus_minutes: int = 0
    pomo_break_minutes: int = 0
    pomo_total_cycles: int = 0
    pomo_current_cycle: int = 0
    pomo_phase_expiry: datetime | None = None
    pomo_phases_tracked_seconds: int = 0

    def reset(self):
        """Atomically reset all pomodoro fields to defaults."""
        self.pomo_phase = "focus"
        self.pomo_next_phase = None
        self.pomo_focus_minutes = 0
        self.pomo_break_minutes = 0
        self.pomo_total_cycles = 0
        self.pomo_current_cycle = 0
        self.pomo_phase_expiry = None
        self.pomo_phases_tracked_seconds = 0


@dataclass
class DaemonState:
    session: SessionState = field(default_factory=SessionState)
    pomodoro: PomodoroState = field(default_factory=PomodoroState)
    settings: dict = field(default_factory=dict)
    active_domains: list[str] = field(default_factory=list)
