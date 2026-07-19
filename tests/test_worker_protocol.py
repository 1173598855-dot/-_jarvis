from dataclasses import replace
import unittest

from core.contracts.worker_protocol import (
    WORKER_PROTOCOL_VERSION,
    WorkerEvent,
    WorkerEventKind,
    WorkerTaskRecord,
    WorkerTaskRequest,
    WorkerTaskStatus,
)


class TestWorkerProtocol(unittest.TestCase):
    def test_request_round_trip_uses_versioned_strict_shape(self):
        request = WorkerTaskRequest.new(
            role_name="engineer",
            prompt="Review the recovery boundary",
            timeout_seconds=30,
        )

        restored = WorkerTaskRequest.from_dict(request.to_dict())

        self.assertEqual(restored, request)
        self.assertEqual(restored.protocol_version, WORKER_PROTOCOL_VERSION)
        damaged = request.to_dict()
        damaged["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "unknown"):
            WorkerTaskRequest.from_dict(damaged)

    def test_timeout_bounds_and_nonblank_text_are_enforced(self):
        for timeout in (0, 301, True):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(ValueError, "timeout_seconds"):
                    WorkerTaskRequest.new(
                        role_name="engineer",
                        prompt="work",
                        timeout_seconds=timeout,
                    )
        with self.assertRaisesRegex(ValueError, "prompt"):
            WorkerTaskRequest.new(
                role_name="engineer",
                prompt="  ",
                timeout_seconds=30,
            )

    def test_event_requires_matching_version_positive_sequence_and_timestamp(self):
        request = WorkerTaskRequest.new("engineer", "work", 30)
        event = WorkerEvent.new(
            request,
            sequence=1,
            kind=WorkerEventKind.STARTED,
            payload={"pid": 42},
        )

        self.assertEqual(WorkerEvent.from_dict(event.to_dict()), event)
        with self.assertRaisesRegex(ValueError, "sequence"):
            replace(event, sequence=0)
        with self.assertRaisesRegex(ValueError, "timestamp"):
            replace(event, timestamp="2026-07-19T00:00:00")

    def test_timeout_and_cancelled_records_require_confirmed_termination(self):
        request = WorkerTaskRequest.new("engineer", "work", 30)
        queued = WorkerTaskRecord.from_request(request)

        for status in (WorkerTaskStatus.TIMEOUT, WorkerTaskStatus.CANCELLED):
            with self.subTest(status=status):
                with self.assertRaisesRegex(ValueError, "termination_confirmed"):
                    replace(queued, status=status)

    def test_worker_terminal_outcomes_are_distinct(self):
        terminal = {
            status.value
            for status in WorkerTaskStatus
            if status.is_terminal
        }

        self.assertEqual(
            terminal,
            {"succeeded", "failed", "timeout", "cancelled", "crashed"},
        )


if __name__ == "__main__":
    unittest.main()
