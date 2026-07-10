"""
Event Bus module for J.A.R.V.I.S.
Provides pub/sub event system with history tracking.
"""

import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class EventType(Enum):
    """Standard event types for J.A.R.V.I.S. system events."""
    SYSTEM = "system"
    USER = "user"
    AGENT = "agent"
    PLUGIN = "plugin"
    ERROR = "error"


@dataclass
class Event:
    """Event data container."""
    event_type: str
    source: str
    data: Any
    timestamp: str = field(default_factory=lambda: __import__('time').strftime("%Y-%m-%dT%H:%M:%S"))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def payload(self) -> Any:
        """Alias for data."""
        return self.data

    @property
    def type(self) -> str:
        """Alias for event_type."""
        return self.event_type


class EventBus:
    """Thread-safe event bus with pub/sub and history tracking."""

    def __init__(self, max_history: int = 200):
        self._history: deque = deque(maxlen=max_history)
        self._subscribers: Dict[str, List[Dict]] = {}
        self._sub_id_counter = 0
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, callback: Callable, once: bool = False) -> int:
        """Subscribe to an event type. Returns subscription ID."""
        sub_id = self._sub_id_counter
        self._sub_id_counter += 1
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(
                {"id": sub_id, "callback": callback, "once": once}
            )
        return sub_id

    def unsubscribe(self, sub_id: int) -> bool:
        """Unsubscribe by ID. Returns True if found."""
        with self._lock:
            for event_type in list(self._subscribers):
                subs = self._subscribers[event_type]
                self._subscribers[event_type] = [s for s in subs if s["id"] != sub_id]
                if not self._subscribers[event_type]:
                    del self._subscribers[event_type]
        return True

    def emit(self, event_type: str, payload: Any = None) -> None:
        """Emit an event to all subscribers."""
        event = Event(event_type=event_type, source="event_bus", data=payload)
        with self._lock:
            self._history.append(event)

        subscribers_to_call = []
        with self._lock:
            if event_type in self._subscribers:
                subscribers_to_call.extend(self._subscribers[event_type])
            if "*" in self._subscribers:
                subscribers_to_call.extend(self._subscribers["*"])

        once_subs = []
        for sub in subscribers_to_call:
            try:
                sub["callback"](event)
            except Exception:
                pass
            if sub["once"]:
                once_subs.append(sub["id"])

        if once_subs:
            for sub_id in once_subs:
                self.unsubscribe(sub_id)

    def publish(self, event: Event) -> None:
        """Publish an Event object."""
        self.emit(str(event.event_type), event.data)

    def get_history(self, event_type: Optional[str] = None, limit: int = 100) -> List[Event]:
        """Get event history, optionally filtered by type."""
        with self._lock:
            history = list(self._history)
        if event_type is not None:
            history = [e for e in history if e.event_type == event_type]
        return history[-limit:]

    def clear_history(self) -> None:
        """Clear all event history."""
        with self._lock:
            self._history.clear()

    def clear(self) -> None:
        """Clear event history."""
        self.clear_history()

    def get_subscription_count(self) -> int:
        """Get total active subscriptions."""
        with self._lock:
            return sum(len(subs) for subs in self._subscribers.values())

    def destroy(self) -> None:
        """Destroy: clear all subscriptions and history."""
        with self._lock:
            self._subscribers.clear()
            self._history.clear()
