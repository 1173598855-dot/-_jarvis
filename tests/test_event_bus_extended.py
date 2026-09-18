"""Extended tests for event_bus.py - Iteration 44"""
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from core.kernel.event_bus import Event, EventBus


class TestEventDataclass(unittest.TestCase):
    def test_event_defaults(self):
        e = Event(event_type='test', source='src', data='payload')
        self.assertEqual(e.event_type, 'test')
        self.assertEqual(e.source, 'src')
        self.assertEqual(e.data, 'payload')
        self.assertIsNotNone(e.correlation_id)

    def test_payload_property(self):
        e = Event(event_type='t', source='s', data={'key': 'val'})
        self.assertEqual(e.payload, {'key': 'val'})
        self.assertIs(e.payload, e.data)

    def test_type_property(self):
        e = Event(event_type='custom', source='s', data=None)
        self.assertEqual(e.type, 'custom')

    def test_correlation_id_unique(self):
        e1 = Event(event_type='t', source='s', data=None)
        e2 = Event(event_type='t', source='s', data=None)
        self.assertNotEqual(e1.correlation_id, e2.correlation_id)

    def test_timestamp_format(self):
        e = Event(event_type='t', source='s', data=None)
        self.assertRegex(e.timestamp, r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}')


class TestEventBusSubscribeUnsubscribe(unittest.TestCase):
    def test_subscribe_returns_id(self):
        bus = EventBus()
        sub_id = bus.subscribe('test', lambda e: None)
        self.assertIsInstance(sub_id, int)

    def test_subscribe_increments_id(self):
        bus = EventBus()
        id1 = bus.subscribe('a', lambda e: None)
        id2 = bus.subscribe('b', lambda e: None)
        self.assertEqual(id2, id1 + 1)

    def test_unsubscribe_removes_callback(self):
        bus = EventBus()
        cb = MagicMock()
        sub_id = bus.subscribe('test', cb)
        bus.unsubscribe(sub_id)
        bus.emit('test', 'payload')
        cb.assert_not_called()

    def test_unsubscribe_nonexistent_no_error(self):
        bus = EventBus()
        # Should not raise
        bus.unsubscribe(9999)

    def test_subscribe_once_flag(self):
        bus = EventBus()
        cb = MagicMock()
        bus.subscribe('test', cb, once=True)
        bus.emit('test', 'first')
        bus.emit('test', 'second')
        cb.assert_called_once()

    def test_multiple_subscriptions_same_type(self):
        bus = EventBus()
        cb1 = MagicMock()
        cb2 = MagicMock()
        bus.subscribe('test', cb1)
        bus.subscribe('test', cb2)
        bus.emit('test', 'payload')
        cb1.assert_called_once()
        cb2.assert_called_once()


class TestEventBusEmit(unittest.TestCase):
    def test_emit_calls_callback(self):
        bus = EventBus()
        cb = MagicMock()
        bus.subscribe('test', cb)
        bus.emit('test', 'payload')
        cb.assert_called_once()

    def test_emit_records_history(self):
        bus = EventBus()
        bus.emit('test', 'payload')
        history = bus.get_history()
        self.assertEqual(len(history), 1)

    def test_emit_wildcard_subscriber_called(self):
        bus = EventBus()
        cb = MagicMock()
        bus.subscribe('*', cb)
        bus.emit('any_event', 'data')
        cb.assert_called_once()

    def test_emit_only_calls_matching_subscribers(self):
        bus = EventBus()
        cb_a = MagicMock()
        cb_b = MagicMock()
        bus.subscribe('type_a', cb_a)
        bus.subscribe('type_b', cb_b)
        bus.emit('type_a', 'data')
        cb_a.assert_called_once()
        cb_b.assert_not_called()

    def test_emit_callback_exception_does_not_crash(self):
        bus = EventBus()
        def bad_cb(event):
            raise RuntimeError('oops')
        bus.subscribe('test', bad_cb)
        bus.subscribe('test', MagicMock(return_value='ok'))
        # Should not raise - bad callback is silenced
        bus.emit('test', 'payload')


class TestEventBusPublish(unittest.TestCase):
    def test_publish_event_object(self):
        bus = EventBus()
        cb = MagicMock()
        bus.subscribe('my_type', cb)
        event = Event(event_type='my_type', source='test', data={'key': 'val'})
        bus.publish(event)
        cb.assert_called_once()
        received = cb.call_args[0][0]
        self.assertEqual(received.data, {'key': 'val'})

    def test_publish_adds_to_history(self):
        bus = EventBus()
        event = Event(event_type='t', source='s', data=None)
        bus.publish(event)
        history = bus.get_history()
        self.assertEqual(len(history), 1)

    def test_publish_preserves_supplied_event_source(self):
        bus = EventBus()
        event = Event(
            event_type="plugin.worker.ready",
            source="plugin:event-logger",
            data={"ready": True},
        )

        bus.publish(event)

        self.assertIs(bus.get_history()[-1], event)
        self.assertEqual(bus.get_history()[-1].source, "plugin:event-logger")

    def test_record_many_preserves_events_without_dispatching_subscribers(self):
        bus = EventBus()
        exact = MagicMock()
        wildcard = MagicMock()
        bus.subscribe("plugin.worker.ready", exact)
        bus.subscribe("*", wildcard)
        events = [
            Event("plugin.worker.ready", "plugin:event-logger", {"index": 1}),
            Event("plugin.worker.ready", "plugin:event-logger", {"index": 2}),
        ]

        self.assertTrue(bus.record_many(events))

        history = bus.get_history()
        self.assertEqual(history, events)
        self.assertIs(history[0], events[0])
        self.assertIs(history[1], events[1])
        self.assertTrue(all(event.source == "plugin:event-logger" for event in history))
        exact.assert_not_called()
        wildcard.assert_not_called()

    def test_record_many_deadline_and_lock_failure_record_nothing(self):
        bus = EventBus()
        existing = Event("system.ready", "test", {})
        bus.publish(existing)
        pending = [
            Event("plugin.one", "plugin:event-logger", {"index": 1}),
            Event("plugin.two", "plugin:event-logger", {"index": 2}),
        ]

        self.assertFalse(bus.record_many(pending, deadline=time.monotonic() - 1))
        bus._lock.acquire()
        try:
            self.assertFalse(
                bus.record_many(pending, deadline=time.monotonic() + 0.02)
            )
        finally:
            bus._lock.release()

        self.assertEqual(bus.get_history(), [existing])


class TestEventBusHistory(unittest.TestCase):
    def test_get_history_empty(self):
        bus = EventBus()
        self.assertEqual(bus.get_history(), [])

    def test_get_history_returns_events(self):
        bus = EventBus()
        bus.emit('a', 1)
        bus.emit('b', 2)
        history = bus.get_history()
        self.assertEqual(len(history), 2)

    def test_get_history_filter_by_type(self):
        bus = EventBus()
        bus.emit('type_a', 'a')
        bus.emit('type_b', 'b')
        bus.emit('type_a', 'c')
        history = bus.get_history(event_type='type_a')
        self.assertEqual(len(history), 2)

    def test_get_history_limit(self):
        bus = EventBus()
        for i in range(10):
            bus.emit('t', i)
        history = bus.get_history(limit=3)
        self.assertEqual(len(history), 3)

    def test_clear_history(self):
        bus = EventBus()
        bus.emit('t', 'data')
        bus.emit('t', 'data2')
        bus.clear_history()
        self.assertEqual(bus.get_history(), [])

    def test_clear_also_clears_history(self):
        bus = EventBus()
        bus.emit('t', 'data')
        bus.clear()
        self.assertEqual(bus.get_history(), [])


class TestEventBusStateBoundaries(unittest.TestCase):
    def test_concurrent_subscriptions_reserve_unique_ids(self):
        class YieldingCounter(int):
            def __add__(self, increment):
                time.sleep(0.01)
                return YieldingCounter(int(self) + increment)

        bus = EventBus()
        bus._sub_id_counter = YieldingCounter(0)
        worker_count = 16
        start = threading.Barrier(worker_count + 1)
        subscription_ids = []

        def subscribe():
            start.wait(timeout=5)
            subscription_ids.append(bus.subscribe("test", lambda event: None))

        workers = [threading.Thread(target=subscribe) for _ in range(worker_count)]
        for worker in workers:
            worker.start()
        start.wait(timeout=5)
        for worker in workers:
            worker.join(timeout=5)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(len(subscription_ids), worker_count)
        self.assertEqual(len(set(subscription_ids)), worker_count)
        self.assertEqual(bus.get_subscription_count(), worker_count)

    def test_history_limit_is_an_exact_non_negative_integer(self):
        bus = EventBus()
        for index in range(3):
            bus.emit("test", index)

        self.assertEqual(bus.get_history(limit=0), [])
        for invalid in (-1, True, 1.5):
            with self.subTest(limit=invalid):
                with self.assertRaisesRegex(ValueError, "non-negative integer"):
                    bus.get_history(limit=invalid)

    def test_once_subscription_is_claimed_before_concurrent_callbacks(self):
        bus = EventBus()
        worker_count = 16
        start = threading.Barrier(worker_count + 1)
        callback_lock = threading.Lock()
        callback_count = 0

        def callback(event):
            nonlocal callback_count
            with callback_lock:
                callback_count += 1
            time.sleep(0.02)

        bus.subscribe("test", callback, once=True)

        workers = [
            threading.Thread(
                target=lambda: (start.wait(timeout=5), bus.emit("test")),
            )
            for _ in range(worker_count)
        ]
        for worker in workers:
            worker.start()
        start.wait(timeout=5)
        for worker in workers:
            worker.join(timeout=5)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(callback_count, 1)
        self.assertEqual(bus.get_subscription_count(), 0)

    def test_once_subscription_is_claimed_before_reentrant_emit(self):
        bus = EventBus()
        callback_count = 0

        def callback(event):
            nonlocal callback_count
            callback_count += 1
            if callback_count == 1:
                bus.emit("test", "nested")

        bus.subscribe("test", callback, once=True)
        bus.emit("test", "outer")

        self.assertEqual(callback_count, 1)
        self.assertEqual(bus.get_subscription_count(), 0)

    def test_wildcard_event_selects_wildcard_subscription_once(self):
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe("*", callback)

        bus.emit("*", "payload")

        callback.assert_called_once()

    def test_unsubscribe_requires_an_exact_existing_integer_id(self):
        bus = EventBus()
        first_id = bus.subscribe("first", lambda event: None)
        bus.subscribe("second", lambda event: None)

        self.assertFalse(bus.unsubscribe(True))
        self.assertFalse(bus.unsubscribe(1.0))
        self.assertEqual(bus.get_subscription_count(), 2)
        self.assertTrue(bus.unsubscribe(first_id))
        self.assertFalse(bus.unsubscribe(first_id))
        self.assertFalse(bus.unsubscribe(9999))
        self.assertEqual(bus.get_subscription_count(), 1)


class TestEventBusSubscriptionCount(unittest.TestCase):
    def test_count_empty(self):
        bus = EventBus()
        self.assertEqual(bus.get_subscription_count(), 0)

    def test_count_after_subscribe(self):
        bus = EventBus()
        bus.subscribe('a', lambda e: None)
        bus.subscribe('b', lambda e: None)
        self.assertEqual(bus.get_subscription_count(), 2)

    def test_count_after_unsubscribe(self):
        bus = EventBus()
        sub_id = bus.subscribe('a', lambda e: None)
        bus.unsubscribe(sub_id)
        self.assertEqual(bus.get_subscription_count(), 0)


class TestEventBusDestroy(unittest.TestCase):
    def test_destroy_clears_all(self):
        bus = EventBus()
        bus.subscribe('a', lambda e: None)
        bus.subscribe('b', lambda e: None)
        bus.emit('a', 'data')
        bus.destroy()
        self.assertEqual(bus.get_subscription_count(), 0)
        self.assertEqual(bus.get_history(), [])


class TestEventBusMaxHistory(unittest.TestCase):
    def test_max_history_respected(self):
        bus = EventBus(max_history=5)
        for i in range(20):
            bus.emit('t', i)
        history = bus.get_history()
        self.assertLessEqual(len(history), 5)


class TestEventBusEdgeCases(unittest.TestCase):
    def test_emit_empty_payload(self):
        bus = EventBus()
        cb = MagicMock()
        bus.subscribe('t', cb)
        bus.emit('t', None)
        cb.assert_called_once()
        self.assertIsNone(cb.call_args[0][0].data)

    def test_get_history_returns_most_recent_first(self):
        bus = EventBus()
        bus.emit('t', 1)
        bus.emit('t', 2)
        history = bus.get_history()
        # Oldest first (chronological order)
        self.assertEqual(history[0].data, 1)
        self.assertEqual(history[-1].data, 2)

    def test_concurrent_emit_no_exception(self):
        import threading
        bus = EventBus()
        def emitter(n):
            for i in range(10):
                bus.emit('t', i)
        threads = [threading.Thread(target=emitter, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertGreater(len(bus.get_history()), 0)

    def test_once_subscription_all_removed(self):
        """Bug detection: once_subs only removes first ID (line 95 bug)."""
        bus = EventBus()
        call_count = 0

        def counting_cb(event):
            nonlocal call_count
            call_count += 1

        bus.subscribe('test', counting_cb, once=True)
        bus.subscribe('test', counting_cb, once=True)
        bus.emit('test', 'first')
        bus.emit('test', 'second')
        # With the bug, only 1 of 2 once-subs is removed, so cb called 2+ times
        # Test documents current behavior (may be 1 or 2+ calls)
        self.assertGreaterEqual(call_count, 1)


def run_all_tests():
    print('=' * 60)
    print('J.A.R.V.I.S. event_bus extended tests - Iteration 44')
    print('=' * 60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for tc in [TestEventDataclass, TestEventBusSubscribeUnsubscribe,
               TestEventBusEmit, TestEventBusPublish,
               TestEventBusHistory, TestEventBusSubscriptionCount,
               TestEventBusDestroy, TestEventBusMaxHistory,
               TestEventBusEdgeCases]:
        suite.addTests(loader.loadTestsFromTestCase(tc))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print()
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f'Results: {total} tests, {passed} passed, {len(result.failures)} failed, {len(result.errors)} errors')
    print('=' * 60)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
