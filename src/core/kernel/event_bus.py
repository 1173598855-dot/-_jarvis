"""
EventBus - XiaoYi JARVIS event bus (Python)
"""

from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import logging
import uuid

logger = logging.getLogger(__name__)


@dataclass
class Event:
    type: str
    payload: Any
    timestamp: float
    source: Optional[str] = None
    correlation_id: Optional[str] = None


@dataclass
class Subscription:
    id: str
    event_type: str
    handler: Callable
    once: bool = False
    active: bool = True


class EventBus:
    def __init__(self, max_history: int = 1000):
        self._subscriptions: Dict[str, List[Subscription]] = {}
        self._history: List[Event] = []
        self._max_history = int(max_history) if not isinstance(max_history, dict) else 1000

    def subscribe(self, event_type: str, handler: Callable, once: bool = False) -> str:
        sub_id = str(uuid.uuid4())[:8]
        sub = Subscription(id=sub_id, event_type=event_type, handler=handler, once=once)
        if event_type not in self._subscriptions:
            self._subscriptions[event_type] = []
        self._subscriptions[event_type].append(sub)
        return sub_id

    def unsubscribe(self, sub_id: str) -> bool:
        for event_type, subs in self._subscriptions.items():
            for i, sub in enumerate(subs):
                if sub.id == sub_id:
                    subs.pop(i)
                    return True
        return False

    def emit(self, event_type: str, payload: Any, source: Optional[str] = None) -> None:
        event = Event(
            type=event_type,
            payload=payload,
            timestamp=datetime.now().timestamp(),
            source=source,
            correlation_id=str(uuid.uuid4())[:8],
        )
        self._history.append(event)
        while len(self._history) > self._max_history:
            self._history.pop(0)
        self._dispatch(event)

    def _dispatch(self, event: Event) -> None:
        handlers = []
        if event.type in self._subscriptions:
            handlers.extend(self._subscriptions[event.type])
        if '*' in self._subscriptions:
            handlers.extend(self._subscriptions['*'])
        for sub in handlers:
            if not sub.active:
                continue
            try:
                sub.handler(event)
                if sub.once:
                    sub.active = False
            except Exception as e:
                logger.error(f"[EventBus] handler error ({sub.id}): {e}")

    def get_history(self, event_type: Optional[str] = None, limit: int = 100) -> List[Event]:
        events = self._history
        if event_type:
            events = [e for e in events if e.type == event_type]
        return events[-limit:]

    def get_subscription_count(self, event_type: Optional[str] = None) -> int:
        if event_type:
            return sum(1 for s in self._subscriptions.get(event_type, []) if s.active)
        return sum(len(subs) for subs in self._subscriptions.values() for s in subs if s.active)

    def clear_history(self) -> None:
        self._history.clear()

    def destroy(self) -> None:
        self._subscriptions.clear()
        self._history.clear()


# Global singleton
global_event_bus = EventBus()
