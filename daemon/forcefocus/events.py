import logging
from enum import Enum, auto

class Event(Enum):
    SESSION_STARTED = auto()
    SESSION_ENDED = auto()
    PERMA_BLOCK_UPDATED = auto()
    DOMAINS_UPDATED = auto()
    POMODORO_PHASE_CHANGED = auto()
    STATE_CHANGED = auto()

class EventManager:
    """A simple synchronous event bus for decoupling daemon components."""
    
    def __init__(self):
        self._subscribers = {event: [] for event in Event}
    
    def subscribe(self, event: Event, callback: callable):
        """Subscribe a callback to a specific event."""
        if callback not in self._subscribers[event]:
            self._subscribers[event].append(callback)
            
    def unsubscribe(self, event: Event, callback: callable):
        """Unsubscribe a callback from a specific event."""
        if callback in self._subscribers[event]:
            self._subscribers[event].remove(callback)
            
    def emit(self, event: Event, **kwargs):
        """Emit an event, calling all subscribed callbacks with kwargs."""
        for callback in self._subscribers[event]:
            try:
                callback(**kwargs)
            except Exception as e:
                logging.error(f"Error in event callback for {event.name}: {e}", exc_info=True)
