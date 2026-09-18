"""
测试模块:EventBus
Phase 12: 测试驱动自演进"""


import sys
import unittest
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.kernel.event_bus import EventBus


class TestEventBus:
    """测试 EventBus 核心功能 + edge cases (Iteration 39)"""

    @pytest.fixture
    def bus(self):
        """创建 EventBus 实例"""
        return EventBus(max_history=100)

    def test_subscribe_and_emit(self, bus):
        """订阅事件后应能接收到"""
        received = []
        bus.subscribe("test", lambda e: received.append(e))
        bus.emit("test", {"data": "hello"})
        assert len(received) == 1
        assert received[0].payload == {"data": "hello"}
        assert received[0].type == "test"

    def test_unsubscribe(self, bus):
        """取消订阅后不应再收到事件"""
        received = []
        sub_id = bus.subscribe("test", lambda e: received.append(e))
        bus.unsubscribe(sub_id)
        bus.emit("test", {"data": "hello"})
        assert len(received) == 0

    def test_wildcard_subscription(self, bus):
        """通配符订阅应接收所有事件"""
        received = []
        bus.subscribe("*", lambda e: received.append(e))
        bus.emit("event1", "data1")
        bus.emit("event2", "data2")
        assert len(received) == 2

    def test_once_subscription(self, bus):
        """once 订阅应仅触发一次"""
        received = []
        bus.subscribe("test", lambda e: received.append(e), once=True)
        bus.emit("test", "first")
        bus.emit("test", "second")
        assert len(received) == 1
        assert received[0].payload == "first"

    def test_history_limit(self, bus):
        """历史记录不应超过 max_history"""
        bus = EventBus(max_history=5)
        for i in range(10):
            bus.emit("test", i)
        history = bus.get_history()
        assert len(history) == 5
        assert history[0].payload == 5

    def test_history_filter_by_type(self, bus):
        """get_history 应按类型过滤"""
        bus.emit("type1", "a")
        bus.emit("type2", "b")
        bus.emit("type1", "c")
        history = bus.get_history("type1")
        assert len(history) == 2
        assert all(e.type == "type1" for e in history)

    def test_clear_history(self, bus):
        """clear_history 应清空所有历史"""
        bus.emit("test", "data")
        bus.clear_history()
        assert len(bus.get_history()) == 0

    def test_destroy(self, bus):
        """destroy 应清空所有订阅和历史"""
        bus.subscribe("test", lambda e: None)
        bus.emit("test", "data")
        bus.destroy()
        assert len(bus.get_history()) == 0
        assert bus.get_subscription_count() == 0

    def test_handler_error_isolation(self, bus):
        """单个处理器错误不应影响其他处理器"""
        received = []
        def bad_handler(e):
            raise ValueError("Intentional error")

        bus.subscribe("test", bad_handler)
        bus.subscribe("test", lambda e: received.append(e))
        bus.emit("test", "data")
        assert len(received) == 1

    def test_event_correlation_id(self, bus):
        """事件应自动生成 correlation_id"""
        bus.subscribe("test", lambda e: None)
        bus.emit("test", "data")
        history = bus.get_history()
        assert len(history) == 1
        assert history[0].correlation_id != ""

    def test_publish_with_event_object(self, bus):
        """publish() 应接受 Event 对象并触发订阅"""
        from core.kernel.event_bus import Event
        received = []
        bus.subscribe("mytype", lambda e: received.append(e))
        ev = Event(event_type="mytype", source="test", data={"key": "val"})
        bus.publish(ev)
        assert len(received) == 1
        assert received[0].data == {"key": "val"}

    def test_get_subscription_count(self, bus):
        """get_subscription_count 应返回活跃订阅数"""
        bus.subscribe("a", lambda e: None)
        bus.subscribe("b", lambda e: None)
        bus.subscribe("a", lambda e: None)
        assert bus.get_subscription_count() == 3

    def test_clear_preserves_subscriptions(self, bus):
        """clear() clears history but preserves subscriptions"""
        bus.subscribe("test", lambda e: None)
        bus.emit("test", "data")
        bus.clear()
        assert len(bus.get_history()) == 0
        assert bus.get_subscription_count() == 1

    def test_thread_safety_concurrent_emit(self):
        """并发 emit 不应崩溃"""
        import threading
        bus = EventBus(max_history=500)
        bus.subscribe("*", lambda e: None)
        errors = []
        def emit_many(n):
            try:
                for i in range(50):
                    bus.emit("t", i)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=emit_many, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0

    def test_history_limit_with_wildcard(self):
        """通配符订阅不应影响历史记录限制"""
        bus = EventBus(max_history=5)
        bus.subscribe("*", lambda e: None)
        for i in range(20):
            bus.emit("e", i)
        assert len(bus.get_history()) == 5



# ============================================================
# Test: EventBus edge cases
# ============================================================

class TestEventBusEdgeCases(unittest.TestCase):
    """Test EventBus edge cases and thin wrappers"""

    def test_event_payload_property(self):
        """Event.payload returns the same as data"""
        from core.kernel.event_bus import Event
        ev = Event(event_type="test", source="src", data={"key": "val"})
        self.assertIs(ev.payload, ev.data)
        self.assertEqual(ev.payload, {"key": "val"})

    def test_event_type_property(self):
        """Event.type returns the same as event_type"""
        from core.kernel.event_bus import Event
        ev = Event(event_type="myt", source="src", data=None)
        self.assertEqual(ev.type, "myt")
        self.assertEqual(ev.type, ev.event_type)

    def test_event_correlation_id_unique(self):
        """Each Event gets a unique correlation_id"""
        from core.kernel.event_bus import Event
        ev1 = Event(event_type="t", source="s", data=None)
        ev2 = Event(event_type="t", source="s", data=None)
        self.assertNotEqual(ev1.correlation_id, ev2.correlation_id)

    def test_publish_delegates_to_emit(self):
        """publish() should trigger subscribers of the same event type"""
        bus = EventBus(max_history=10)
        received = []
        bus.subscribe("mytype", lambda e: received.append(e))
        from core.kernel.event_bus import Event
        ev = Event(event_type="mytype", source="test", data="payload_data")
        bus.publish(ev)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].data, "payload_data")

    def test_emit_with_no_subscribers(self):
        """emit with no subscribers should not raise"""
        bus = EventBus(max_history=10)
        bus.emit("nonexistent", "data")  # should not raise
        self.assertEqual(len(bus.get_history()), 1)

    def test_unsubscribe_nonexistent_returns_false(self):
        """unsubscribe returns False for a nonexistent sub_id"""
        bus = EventBus(max_history=10)
        result = bus.unsubscribe(99999)
        self.assertFalse(result)

    def test_multiple_subscribers_same_event(self):
        """All subscribers of same event type should be called"""
        bus = EventBus(max_history=10)
        results = []
        bus.subscribe("t", lambda e: results.append("a"))
        bus.subscribe("t", lambda e: results.append("b"))
        bus.subscribe("t", lambda e: results.append("c"))
        bus.emit("t", None)
        self.assertEqual(sorted(results), ["a", "b", "c"])

    def test_clear_after_destroy(self):
        """After destroy, clear should be safe to call"""
        bus = EventBus(max_history=10)
        bus.subscribe("t", lambda e: None)
        bus.destroy()
        bus.clear()  # should not raise
        self.assertEqual(len(bus.get_history()), 0)

    def test_get_history_default_limit(self):
        """get_history() with no limit argument uses default 100"""
        bus = EventBus(max_history=200)
        for i in range(50):
            bus.emit("t", i)
        history = bus.get_history()
        self.assertEqual(len(history), 50)

    def test_subscription_id_sequential(self):
        """subscribe returns sequential integer IDs"""
        bus = EventBus(max_history=10)
        ids = [bus.subscribe("t", lambda e: None) for _ in range(5)]
        self.assertEqual(ids, [0, 1, 2, 3, 4])

    def test_emit_to_specific_type_only(self):
        """emit to one type should not trigger subscribers of another type"""
        bus = EventBus(max_history=10)
        received_a = []
        received_b = []
        bus.subscribe("type_a", lambda e: received_a.append(e))
        bus.subscribe("type_b", lambda e: received_b.append(e))
        bus.emit("type_a", "data_a")
        self.assertEqual(len(received_a), 1)
        self.assertEqual(len(received_b), 0)


class TestEventTypeEnum(unittest.TestCase):
    """Test EventType enum values"""

    def test_event_type_values(self):
        """EventType has expected values"""
        from core.kernel.event_bus import EventType
        self.assertEqual(EventType.SYSTEM.value, "system")
        self.assertEqual(EventType.USER.value, "user")
        self.assertEqual(EventType.AGENT.value, "agent")
        self.assertEqual(EventType.PLUGIN.value, "plugin")
        self.assertEqual(EventType.ERROR.value, "error")

    def test_event_type_count(self):
        """EventType has exactly 5 members"""
        from core.kernel.event_bus import EventType
        self.assertEqual(len(EventType), 5)



if __name__ == "__main__":
    import pytest
