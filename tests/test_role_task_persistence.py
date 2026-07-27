import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from adapters.role_task_record_repository import RoleTaskRecordRepository
from core.contracts.worker_protocol import WorkerTaskRecord, WorkerTaskRequest, WorkerTaskStatus


class TestRoleTaskRecordRepository(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.root = Path(self._tmp)
        self.repo = RoleTaskRecordRepository(self.root)

    def tearDown(self):
        for child in self.root.rglob('*'):
            try:
                child.unlink()
            except OSError:
                pass
        try:
            self.root.rmdir()
        except OSError:
            pass

    def _make_record(self, task_id: str, status: WorkerTaskStatus) -> WorkerTaskRecord:
        request = WorkerTaskRequest.new('engineer', 'test', 10, task_id=task_id)
        return WorkerTaskRecord.from_request(request).evolve(status=status)

    def test_load_empty_when_no_file(self):
        self.assertEqual(self.repo.load(), [])

    def test_save_and_load_round_trip(self):
        records = [
            self._make_record('task-aaa', WorkerTaskStatus.RUNNING),
            self._make_record('task-bbb', WorkerTaskStatus.SUCCEEDED),
        ]
        self.repo.save(records)
        loaded = self.repo.load()
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].task_id, 'task-aaa')
        self.assertEqual(loaded[1].task_id, 'task-bbb')

    def test_save_replaces_previous_content(self):
        first = [self._make_record('task-first', WorkerTaskStatus.RUNNING)]
        self.repo.save(first)
        second = [self._make_record('task-second', WorkerTaskStatus.SUCCEEDED)]
        self.repo.save(second)
        loaded = self.repo.load()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].task_id, 'task-second')

    def test_clear_removes_file(self):
        self.repo.save([self._make_record('task-x', WorkerTaskStatus.RUNNING)])
        self.assertTrue(self.repo.path.is_file())
        self.repo.clear()
        self.assertFalse(self.repo.path.is_file())
        self.assertEqual(self.repo.load(), [])

    def test_corrupt_file_returns_empty(self):
        self.repo.save([self._make_record('task-x', WorkerTaskStatus.RUNNING)])
        self.repo.path.write_text('not-json', encoding='utf-8')
        self.assertEqual(self.repo.load(), [])

    def test_non_array_root_returns_empty(self):
        self.repo.path.write_text('{}', encoding='utf-8')
        self.assertEqual(self.repo.load(), [])

    def test_invalid_record_skipped_gracefully(self):
        self.repo.path.write_text(
            json.dumps([
                {'task_id': 'task-good', 'protocol_version': 1},
                {'task_id': 'task-bad', 'protocol_version': 999},
            ]),
            encoding='utf-8',
        )
        loaded = self.repo.load()
        self.assertEqual(len(loaded), 0)

    def test_thread_safe_concurrent_save(self):
        errors = []
        def writer():
            try:
                for i in range(20):
                    r = self._make_record(f'task-{i}', WorkerTaskStatus.RUNNING)
                    self.repo.save([r])
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


class TestRoleWorkerRecoverOrphans(unittest.TestCase):
    def setUp(self):
        from core.brain.role_worker import RoleWorkerSupervisor, execute_role_task
        self.supervisor = RoleWorkerSupervisor(
            execute_role_task,
            runner_config={},
            max_records=10,
        )

    def tearDown(self):
        self.supervisor.shutdown()

    def _make_record(self, task_id: str, status: WorkerTaskStatus,
                     termination_confirmed: bool = False) -> WorkerTaskRecord:
        request = WorkerTaskRequest.new('engineer', 'test', 10, task_id=task_id)
        if status is WorkerTaskStatus.QUEUED:
            return WorkerTaskRecord.from_request(request)
        tc = termination_confirmed
        if status in (WorkerTaskStatus.TIMEOUT, WorkerTaskStatus.CANCELLED):
            tc = True
        return WorkerTaskRecord.from_request(request).evolve(
            status=status,
            termination_confirmed=tc,
        )

    def test_non_terminal_becomes_crashed(self):
        orphan = self._make_record('task-orphan', WorkerTaskStatus.RUNNING)
        recovered = self.supervisor.recover_orphans([orphan])
        self.assertEqual(len(recovered), 1)
        record = self.supervisor.get('task-orphan')
        self.assertIsNotNone(record)
        self.assertEqual(record.status, WorkerTaskStatus.CRASHED)
        self.assertTrue(record.termination_confirmed)
        self.assertIn('terminated by restart', record.error)

    def test_terminal_unconfirmed_becomes_failed(self):
        orphan = self._make_record('task-orphan', WorkerTaskStatus.FAILED)
        recovered = self.supervisor.recover_orphans([orphan])
        self.assertEqual(len(recovered), 1)
        record = self.supervisor.get('task-orphan')
        self.assertIsNotNone(record)
        self.assertEqual(record.status, WorkerTaskStatus.FAILED)
        self.assertIn('before confirmation', record.error)

    def test_terminal_confirmed_preserved(self):
        request = WorkerTaskRequest.new('engineer', 'test', 10, task_id='task-done')
        succeeded = WorkerTaskRecord.from_request(request).evolve(
            status=WorkerTaskStatus.SUCCEEDED,
            termination_confirmed=True,
            result={'dispatch': {'role_name': 'engineer', 'task_id': 'task-done', 'status': 'ok', 'message': 'done'}},
        )
        recovered = self.supervisor.recover_orphans([succeeded])
        self.assertEqual(len(recovered), 1)
        record = self.supervisor.get('task-done')
        self.assertIsNotNone(record)
        self.assertEqual(record.status, WorkerTaskStatus.SUCCEEDED)

    def test_duplicate_task_id_is_skipped(self):
        existing = self._make_record('task-existing', WorkerTaskStatus.RUNNING)
        recovered = self.supervisor.recover_orphans([existing])
        self.assertEqual(len(recovered), 1)
        # Try to recover same id again
        dup = self._make_record('task-existing', WorkerTaskStatus.RUNNING)
        recovered2 = self.supervisor.recover_orphans([dup])
        self.assertEqual(len(recovered2), 0)

    def test_exceeds_max_records_triggers_pruning(self):
        small = self.__class__._make_small_supervisor()
        try:
            records = []
            for i in range(5):
                r = self._make_record(f'task-orphan-{i}', WorkerTaskStatus.RUNNING)
                records.append(r)
            recovered = small.recover_orphans(records)
            self.assertEqual(len(recovered), 5)
        finally:
            small.shutdown()

    @staticmethod
    def _make_small_supervisor():
        from core.brain.role_worker import RoleWorkerSupervisor, execute_role_task
        return RoleWorkerSupervisor(
            execute_role_task,
            runner_config={},
            max_records=3,
        )


if __name__ == '__main__':
    unittest.main()
