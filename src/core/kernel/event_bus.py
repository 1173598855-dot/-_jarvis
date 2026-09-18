"""
Event Bus module for J.A.R.V.I.S.
Provides pub/sub event system with history tracking.
"""

import threading
import time
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
        with self._lock:
            sub_id = self._sub_id_counter
            self._sub_id_counter += 1
            self._subscribers.setdefault(event_type, []).append(
                {"id": sub_id, "callback": callback, "once": once}
            )
        return sub_id

    def unsubscribe(self, sub_id: int) -> bool:
        """Unsubscribe by ID. Returns True if found."""
        if type(sub_id) is not int:
            return False
        removed = False
        with self._lock:
            for event_type in list(self._subscribers):
                subs = self._subscribers[event_type]
                self._subscribers[event_type] = [s for s in subs if s["id"] != sub_id]
                if len(self._subscribers[event_type]) != len(subs):
                    removed = True
                if not self._subscribers[event_type]:
                    del self._subscribers[event_type]
        return removed

    def emit(self, event_type: str, payload: Any = None) -> None:
        """Emit an event to all subscribers."""
        event = Event(event_type=event_type, source="event_bus", data=payload)
        self._dispatch(event)

    def _dispatch(self, event: Event) -> None:
        """Record and dispatch the supplied event without changing its source."""
        with self._lock:
            self._history.append(event)

        self._notify(event)

    def _notify(self, event: Event) -> None:
        """Notify subscribers for an already recorded event."""
        subscribers_to_call = []
        with self._lock:
            subscription_types = [event.event_type]
            if event.event_type != "*":
                subscription_types.append("*")
            for subscription_type in subscription_types:
                subscribers = self._subscribers.get(subscription_type)
                if not subscribers:
                    continue
                subscribers_to_call.extend(subscribers)
                retained = [sub for sub in subscribers if not sub["once"]]
                if retained:
                    self._subscribers[subscription_type] = retained
                else:
                    del self._subscribers[subscription_type]

        for sub in subscribers_to_call:
            try:
                sub["callback"](event)
            except Exception:
                pass

    def publish(self, event: Event) -> None:
        """Publish an Event object."""
        self._dispatch(event)

    def record_many(
        self, events: List[Event], *, deadline: float | None = None
    ) -> bool:
        """Atomically record events without invoking subscribers."""
        pending = list(events)
        if any(not isinstance(event, Event) for event in pending):
            raise ValueError("events must contain only Event objects")
        if deadline is None:
            self._lock.acquire()
        else:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._lock.acquire(timeout=remaining):
                return False
            if time.monotonic() >= deadline:
                self._lock.release()
                return False
        try:
            self._history.extend(pending)
            return True
        finally:
            self._lock.release()

    def get_history(self, event_type: Optional[str] = None, limit: int = 100) -> List[Event]:
        """Get event history, optionally filtered by type."""
        if type(limit) is not int or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        if limit == 0:
            return []
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
