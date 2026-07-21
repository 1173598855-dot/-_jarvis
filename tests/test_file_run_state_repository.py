import hashlib
import hmac
import json
import multiprocessing
import os
import tempfile
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from adapters.file_run_state_repository import (
    FileRunStateRepository,
    RunStateIntegrityError,
    _windows_mutex_name,
)
from core.contracts.run_state import RunState


def _save_revision_in_process(root, key, state_value, started, finished):
    repo = FileRunStateRepository(Path(root), key_provider=lambda: key)
    state = RunState.from_dict(state_value)
    started.set()
    repo.save(state, f"revision: {state.revision}\n")
    finished.set()


def _supports_posix_fd_cleanup():
    return (
        os.name != "nt"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.unlink in os.supports_dir_fd
        and os.rmdir in os.supports_dir_fd
        and os.listdir in os.supports_fd
    )


class TestFileRunStateRepository(unittest.TestCase):
    key = b"k" * 32

    def make_state(self):
        return RunState.new(
            run_id="run-20260716-043000",
            goal="Complete Phase A",
            current_stage="A",
            base_commit="a" * 40,
            active_branch="codex/iteration-101-core-contracts",
            next_action="Verify atomic state persistence",
        )

    def make_repo(self, root):
        return FileRunStateRepository(Path(root), key_provider=lambda: self.key)

    def manifest_file_path(self, root, name):
        manifest_path = Path(root) / "active-run.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return Path(root) / manifest["files"][name]["path"]

    def rewrite_manifest(self, root, mutate):
        path = Path(root) / "active-run.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        mutate(manifest)
        unsigned = dict(manifest)
        unsigned.pop("hmac_sha256", None)
        payload = json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest["hmac_sha256"] = hmac.new(
            self.key,
            payload,
            hashlib.sha256,
        ).hexdigest()
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def test_save_and_load_verify_authenticated_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self.make_repo(tmp)
            state = self.make_state()
            repo.save(state, "schema_version: 1\n", events=({"type": "started"},))

            stored = repo.load_active()

            self.assertEqual(stored.state, state)
            self.assertIn("schema_version: 1", stored.resume_markdown)
            self.assertEqual(stored.events, ({"type": "started"},))
            self.assertFalse(list(Path(tmp).rglob("*.tmp")))

    def test_tampered_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            repo.save(self.make_state(), "schema_version: 1\n")
            state_path = self.manifest_file_path(root, "state")
            state_path.write_text("{}", encoding="utf-8")

            with self.assertRaises(RunStateIntegrityError):
                repo.load_active()

    def test_missing_key_for_active_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_repo(root).save(self.make_state(), "schema_version: 1\n")
            with self.assertRaisesRegex(RunStateIntegrityError, "key"):
                FileRunStateRepository(root, lambda: None).load_active()

    def test_signed_path_escape_and_revision_mismatch_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            repo.save(self.make_state(), "schema_version: 1\n")

            self.rewrite_manifest(
                root,
                lambda manifest: manifest["files"]["state"].update(
                    {"path": "../outside.json"}
                ),
            )
            with self.assertRaisesRegex(RunStateIntegrityError, "path"):
                repo.load_active()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            repo.save(self.make_state(), "schema_version: 1\n")
            state_path = self.manifest_file_path(root, "state")
            state_value = json.loads(state_path.read_text(encoding="utf-8"))
            state_value["revision"] = 2
            state_path.write_text(
                json.dumps(state_value, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )

            def update_digest(manifest):
                manifest["files"]["state"]["sha256"] = hashlib.sha256(
                    state_path.read_bytes()
                ).hexdigest()

            self.rewrite_manifest(root, update_digest)
            with self.assertRaisesRegex(RunStateIntegrityError, "revision"):
                repo.load_active()

    def test_events_append_atomically_and_secrets_are_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            state = self.make_state()
            repo.save(
                state,
                "password=resume-secret\n",
                events=({"type": "started", "api_token": "event-secret"},),
                decisions=({"authorization": "Bearer decision-secret"},),
                artifacts={"cookie": "artifact-secret"},
                verification={"message": "token=verification-secret"},
            )
            evolved = state.evolve(next_action="Reload appended recovery events")
            repo.save(evolved, "schema_version: 1\n", events=({"type": "saved"},))

            stored = repo.load_active()
            all_bytes = b"".join(
                path.read_bytes() for path in root.rglob("*") if path.is_file()
            )

            self.assertEqual(
                stored.events,
                (
                    {"api_token": "[REDACTED]", "type": "started"},
                    {"type": "saved"},
                ),
            )
            for secret in (
                b"resume-secret",
                b"event-secret",
                b"decision-secret",
                b"artifact-secret",
                b"verification-secret",
            ):
                self.assertNotIn(secret, all_bytes)

    def test_archive_requires_matching_run_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            state = self.make_state()
            repo.save(state, "schema_version: 1\n")
            state_path = self.manifest_file_path(root, "state")

            with self.assertRaisesRegex(ValueError, "run_id"):
                repo.archive_active("run-20260716-043001")
            repo.archive_active(state.run_id)

            self.assertIsNone(repo.load_active())
            self.assertTrue(state_path.is_file())
            with self.assertRaisesRegex(
                ValueError,
                "archived or incomplete recovery data",
            ):
                repo.save(state, "schema_version: 1\n")
            self.assertTrue(
                (
                    root
                    / "runs"
                    / state.run_id
                    / "archived-run.json"
                ).is_file()
            )

    def test_archive_retry_finishes_after_active_unlink_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            state = self.make_state()
            repo.save(state, "schema_version: 1\n")
            real_unlink = Path.unlink
            failed = False

            def fail_active_unlink_once(path, *args, **kwargs):
                nonlocal failed
                if path == repo._active_path and not failed:
                    failed = True
                    raise OSError("active unlink failed")
                return real_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", fail_active_unlink_once):
                with self.assertRaisesRegex(OSError, "active unlink failed"):
                    repo.archive_active(state.run_id)

            archive_path = root / "runs" / state.run_id / "archived-run.json"
            self.assertTrue(repo._active_path.is_file())
            self.assertTrue(archive_path.is_file())
            with self.assertRaisesRegex(
                RunStateIntegrityError,
                "archive is pending",
            ):
                repo.save(
                    state.evolve(next_action="Do not revive an archived run"),
                    "schema_version: 1\nrevision: 2\n",
                )

            repo.archive_active(state.run_id)

            self.assertIsNone(repo.load_active())
            self.assertTrue(archive_path.is_file())

    def test_staging_replace_failure_can_be_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            state = self.make_state()

            with patch(
                "adapters.file_run_state_repository.os.replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    repo.save(state, "schema_version: 1\n")

            self.assertFalse(list(root.rglob("*.tmp")))
            self.assertFalse((root / "active-run.json").exists())
            staging_directories = list(root.rglob("*.staging"))
            sentinel = None
            if staging_directories:
                self.assertEqual(len(staging_directories), 1)
                sentinel = staging_directories[0] / "operator-note.txt"
                sentinel.write_text("preserve", encoding="utf-8")

            recovered = repo.save(state, "schema_version: 1\n")

            self.assertEqual(recovered.state, state)
            if sentinel is not None:
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_failed_update_keeps_previous_active_snapshot_loadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            state = self.make_state()
            original = repo.save(
                state,
                "schema_version: 1\nrevision: 1\n",
                events=({"type": "started"},),
                decisions=({"decision": "keep revision 1"},),
                artifacts={"report": "revision-1.json"},
                verification={"tests": "passed"},
            )
            evolved = state.evolve(next_action="Persist revision 2 atomically")
            real_replace = os.replace
            replace_calls = 0

            def fail_during_content_replacement(source, destination):
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 2:
                    raise OSError("replace failed during update")
                return real_replace(source, destination)

            with patch(
                "adapters.file_run_state_repository.os.replace",
                side_effect=fail_during_content_replacement,
            ):
                with self.assertRaisesRegex(OSError, "during update"):
                    repo.save(
                        evolved,
                        "schema_version: 1\nrevision: 2\n",
                        events=({"type": "updated"},),
                    )

            recovered = repo.load_active()

            self.assertIsNotNone(recovered)
            self.assertEqual(recovered.state.revision, 1)
            self.assertEqual(recovered, original)
            self.assertFalse(list(root.rglob("*.tmp")))
            staging_directories = list(root.rglob("*.staging"))
            if _supports_posix_fd_cleanup():
                self.assertFalse(staging_directories)
            else:
                self.assertEqual(len(staging_directories), 1)

    def test_concurrent_updates_cannot_regress_the_active_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initial_repo = self.make_repo(root)
            state1 = self.make_state()
            initial_repo.save(state1, "revision: 1\n")
            state2 = state1.evolve(next_action="Persist revision 2")
            state3 = state2.evolve(next_action="Persist revision 3")
            revision2_repo = self.make_repo(root)
            revision3_repo = self.make_repo(root)
            revision2_at_manifest = threading.Event()
            release_revision2 = threading.Event()
            revision3_done = threading.Event()
            errors = []
            original_revision2_write = revision2_repo._atomic_write

            def pause_revision2_manifest(path, content):
                if path == revision2_repo._active_path:
                    revision2_at_manifest.set()
                    release_revision2.wait(timeout=4)
                return original_revision2_write(path, content)

            revision2_repo._atomic_write = pause_revision2_manifest

            def save_revision2():
                try:
                    revision2_repo.save(state2, "revision: 2\n")
                except Exception as exc:
                    errors.append(exc)

            def save_revision3():
                try:
                    revision3_repo.save(state3, "revision: 3\n")
                except Exception as exc:
                    errors.append(exc)
                finally:
                    revision3_done.set()

            revision2_thread = threading.Thread(target=save_revision2, daemon=True)
            revision3_thread = threading.Thread(target=save_revision3, daemon=True)
            revision2_thread.start()
            self.assertTrue(revision2_at_manifest.wait(timeout=2))
            revision3_thread.start()
            revision3_done.wait(timeout=2)
            release_revision2.set()
            revision2_thread.join(timeout=4)
            revision3_thread.join(timeout=4)

            self.assertFalse(revision2_thread.is_alive())
            self.assertFalse(revision3_thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(initial_repo.load_active().state.revision, 3)

    def test_concurrent_reader_keeps_its_manifest_revision_loadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            writer = self.make_repo(root)
            reader = self.make_repo(root)
            state1 = self.make_state()
            state2 = state1.evolve(next_action="Publish revision 2 after the read")
            writer.save(state1, "revision: 1\n")
            manifest_loaded = threading.Event()
            release_reader = threading.Event()
            writer_done = threading.Event()
            snapshots = []
            errors = []
            original_read_json = reader._read_json

            def pause_after_manifest(path, field_name):
                value = original_read_json(path, field_name)
                if path == reader._active_path:
                    manifest_loaded.set()
                    release_reader.wait(timeout=4)
                return value

            reader._read_json = pause_after_manifest

            def load_revision1():
                try:
                    snapshots.append(reader.load_active())
                except Exception as exc:
                    errors.append(exc)

            def save_revision2():
                try:
                    writer.save(state2, "revision: 2\n")
                except Exception as exc:
                    errors.append(exc)
                finally:
                    writer_done.set()

            reader_thread = threading.Thread(target=load_revision1, daemon=True)
            writer_thread = threading.Thread(target=save_revision2, daemon=True)
            reader_thread.start()
            self.assertTrue(manifest_loaded.wait(timeout=2))
            writer_thread.start()
            writer_finished_while_reader_paused = writer_done.wait(timeout=0.25)
            revision1_exists_while_reader_paused = (
                root / "runs" / state1.run_id / "revisions" / "1"
            ).is_dir()
            release_reader.set()
            reader_thread.join(timeout=4)
            writer_thread.join(timeout=4)

            self.assertFalse(reader_thread.is_alive())
            self.assertFalse(writer_thread.is_alive())
            self.assertFalse(writer_finished_while_reader_paused)
            self.assertTrue(revision1_exists_while_reader_paused)
            self.assertEqual(errors, [])
            self.assertEqual([snapshot.state.revision for snapshot in snapshots], [1])
            self.assertEqual(writer.load_active().state.revision, 2)

    @unittest.skipUnless(
        _supports_posix_fd_cleanup(),
        "descriptor-relative no-follow cleanup is unavailable",
    )
    def test_successful_update_prunes_superseded_revision_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            state1 = self.make_state()
            state2 = state1.evolve(next_action="Persist revision 2")
            state3 = state2.evolve(next_action="Persist revision 3")

            repo.save(state1, "revision: 1\n", events=({"revision": 1},))
            repo.save(state2, "revision: 2\n", events=({"revision": 2},))
            repo.save(state3, "revision: 3\n", events=({"revision": 3},))

            revisions = root / "runs" / state1.run_id / "revisions"
            stored = repo.load_active()

            self.assertEqual(
                sorted(path.name for path in revisions.iterdir()),
                ["3"],
            )
            self.assertEqual(
                stored.events,
                ({"revision": 1}, {"revision": 2}, {"revision": 3}),
            )

    @unittest.skipUnless(os.name == "nt", "Windows named mutex behavior")
    def test_windows_repository_lock_does_not_create_a_lock_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)

            with repo._exclusive_write():
                self.assertFalse((root / ".run-state.lock").exists())

            self.assertFalse((root / ".run-state.lock").exists())

    @unittest.skipUnless(os.name == "nt", "Windows named mutex behavior")
    def test_windows_repository_mutex_is_machine_wide(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(_windows_mutex_name(Path(tmp)).startswith("Global\\"))

    @unittest.skipUnless(os.name == "nt", "Windows retains revision snapshots")
    def test_windows_retains_superseded_revision_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            state1 = self.make_state()
            state2 = state1.evolve(next_action="Persist revision 2")
            state3 = state2.evolve(next_action="Persist revision 3")

            repo.save(state1, "revision: 1\n")
            repo.save(state2, "revision: 2\n")
            repo.save(state3, "revision: 3\n")

            revisions = root / "runs" / state1.run_id / "revisions"

            self.assertEqual(repo.load_active().state.revision, 3)
            self.assertEqual(
                sorted(path.name for path in revisions.iterdir()),
                ["1", "2", "3"],
            )

    @unittest.skipUnless(os.name == "nt", "Windows retains staging snapshots")
    def test_windows_staging_cleanup_is_conservatively_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            staging = root / ".1.test.staging"
            staging.mkdir()
            recovery_file = staging / "state.json"
            recovery_file.write_text("sentinel", encoding="utf-8")

            repo._discard_staging_directory(staging)

            self.assertEqual(recovery_file.read_text(encoding="utf-8"), "sentinel")

    @unittest.skipUnless(
        _supports_posix_fd_cleanup(),
        "descriptor-relative no-follow cleanup is unavailable",
    )
    def test_posix_revision_cleanup_does_not_follow_swapped_directory(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            outside_root = Path(outside)
            repo = self.make_repo(root)
            state = self.make_state()
            repo.save(state, "revision: 1\n")
            revisions = root / "runs" / state.run_id / "revisions"
            candidate = revisions / "2"
            candidate.mkdir()
            (candidate / "state.json").write_text("local", encoding="utf-8")
            outside_sentinel = outside_root / "state.json"
            outside_sentinel.write_text("outside", encoding="utf-8")
            parked = revisions / "parked"
            real_listdir = os.listdir
            swapped = False

            def swap_before_listing(directory):
                nonlocal swapped
                if isinstance(directory, int) and not swapped:
                    candidate.rename(parked)
                    candidate.symlink_to(outside_root, target_is_directory=True)
                    swapped = True
                return real_listdir(directory)

            with patch(
                "adapters.file_run_state_repository.os.listdir",
                side_effect=swap_before_listing,
            ):
                repo._prune_revision_snapshots(state.run_id, state.revision)

            self.assertTrue(swapped)
            self.assertEqual(outside_sentinel.read_text(encoding="utf-8"), "outside")
            self.assertEqual(
                (parked / "state.json").read_text(encoding="utf-8"),
                "local",
            )

    def test_cleanup_rechecks_the_opened_revision_directory_identity(self):
        repo = self.make_repo(Path("repository"))
        directory_stat = Mock(st_mode=0o040755, st_dev=1, st_ino=10)
        replacement_stat = Mock(st_mode=0o040755, st_dev=1, st_ino=11)
        child_stat = Mock(st_mode=0o100644, st_dev=1, st_ino=12)

        def stat_entry(path, *, dir_fd, follow_symlinks):
            if path == "2":
                return replacement_stat
            return child_stat

        with (
            patch.object(os, "O_DIRECTORY", 0, create=True),
            patch.object(os, "O_NOFOLLOW", 0, create=True),
            patch(
                "adapters.file_run_state_repository.os.open",
                return_value=20,
            ),
            patch(
                "adapters.file_run_state_repository.os.fstat",
                return_value=directory_stat,
            ),
            patch(
                "adapters.file_run_state_repository.os.listdir",
                return_value=("state.json",),
            ),
            patch(
                "adapters.file_run_state_repository.os.stat",
                side_effect=stat_entry,
            ),
            patch("adapters.file_run_state_repository.os.close"),
            patch("adapters.file_run_state_repository.os.rmdir") as rmdir,
            patch("adapters.file_run_state_repository.os.unlink") as unlink,
        ):
            repo._discard_flat_directory(10, "2")

        unlink.assert_not_called()
        rmdir.assert_not_called()

    def test_cleanup_preserves_nonpositive_revision_directories(self):
        repo = self.make_repo(Path("repository"))
        discard = Mock()

        with (
            patch(
                "adapters.file_run_state_repository._supports_safe_fd_cleanup",
                return_value=True,
            ),
            patch.object(
                repo,
                "_open_repository_directory",
                return_value=nullcontext(10),
            ),
            patch(
                "adapters.file_run_state_repository.os.listdir",
                return_value=("-1", "0", "01", "1", "2", "notes"),
            ),
            patch.object(repo, "_discard_flat_directory", discard),
        ):
            repo._prune_revision_snapshots("run-20260716-043000", 1)

        discard.assert_called_once_with(10, "2")

    def test_manifest_failure_after_publication_can_be_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            state1 = self.make_state()
            state2 = state1.evolve(next_action="Retry published revision 2")
            original = repo.save(state1, "revision: 1\n")
            real_atomic_write = repo._atomic_write

            def fail_manifest(path, content):
                if path == repo._active_path:
                    raise OSError("manifest replacement failed")
                return real_atomic_write(path, content)

            repo._atomic_write = fail_manifest
            with self.assertRaisesRegex(OSError, "manifest replacement failed"):
                repo.save(state2, "revision: 2\n")
            self.assertEqual(repo.load_active(), original)

            repo._atomic_write = real_atomic_write
            recovered = repo.save(state2, "revision: 2\n")
            revisions = root / "runs" / state1.run_id / "revisions"

            self.assertEqual(recovered.state.revision, 2)
            self.assertEqual(
                sorted(path.name for path in revisions.iterdir()),
                ["2"] if _supports_posix_fd_cleanup() else ["1", "2"],
            )

    def test_initial_manifest_failure_after_publication_can_be_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            state = self.make_state()
            real_atomic_write = repo._atomic_write

            def fail_manifest(path, content):
                if path == repo._active_path:
                    raise OSError("initial manifest replacement failed")
                return real_atomic_write(path, content)

            repo._atomic_write = fail_manifest
            with self.assertRaisesRegex(OSError, "initial manifest replacement failed"):
                repo.save(state, "revision: 1\n")
            self.assertIsNone(repo.load_active())

            repo._atomic_write = real_atomic_write
            recovered = repo.save(state, "revision: 1\n")

            self.assertEqual(recovered.state.revision, 1)

    def test_committed_manifest_with_failed_read_back_is_idempotently_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            state1 = self.make_state()
            state2 = state1.evolve(next_action="Confirm committed revision 2")
            repo.save(
                state1,
                "revision: 1\n",
                events=({"revision": 1},),
                decisions=({"decision": "keep revision 1"},),
                artifacts={"report": "revision-1.json"},
                verification={"tests": "revision 1 passed"},
            )
            real_read_bytes = Path.read_bytes

            def fail_active_manifest_read_back(path):
                if path == repo._active_path:
                    raise OSError("active manifest read-back failed")
                return real_read_bytes(path)

            save_kwargs = {
                "events": ({"revision": 2},),
                "decisions": ({"decision": "publish revision 2"},),
                "artifacts": {"report": "revision-2.json"},
                "verification": {"tests": "revision 2 passed"},
            }
            with patch.object(Path, "read_bytes", fail_active_manifest_read_back):
                with self.assertRaisesRegex(OSError, "active manifest read-back failed"):
                    repo.save(state2, "revision: 2\n", **save_kwargs)

            manifest = json.loads(repo._active_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["revision"], 2)

            recovered = repo.save(state2, "revision: 2\n", **save_kwargs)

            self.assertEqual(recovered, repo.load_active())
            revisions = root / "runs" / state1.run_id / "revisions"
            self.assertEqual(
                sorted(path.name for path in revisions.iterdir()),
                ["2"] if _supports_posix_fd_cleanup() else ["1", "2"],
            )
            self.assertEqual(recovered.state, state2)
            self.assertEqual(recovered.resume_markdown, "revision: 2\n")
            self.assertEqual(
                recovered.events,
                ({"revision": 1}, {"revision": 2}),
            )
            self.assertEqual(
                recovered.decisions,
                (
                    {"decision": "keep revision 1"},
                    {"decision": "publish revision 2"},
                ),
            )
            self.assertEqual(recovered.artifacts, {"report": "revision-2.json"})
            self.assertEqual(
                recovered.verification,
                {"tests": "revision 2 passed"},
            )
            different_state_value = state2.to_dict()
            different_state_value["next_action"] = "Use different revision 2 content"
            different_state = RunState.from_dict(different_state_value)
            conflicting_requests = (
                (
                    "state",
                    different_state,
                    "revision: 2\n",
                    save_kwargs,
                ),
                ("resume", state2, "different resume\n", save_kwargs),
                (
                    "events",
                    state2,
                    "revision: 2\n",
                    {**save_kwargs, "events": ({"revision": "different"},)},
                ),
                (
                    "decisions",
                    state2,
                    "revision: 2\n",
                    {
                        **save_kwargs,
                        "decisions": ({"decision": "different decision"},),
                    },
                ),
                (
                    "artifacts",
                    state2,
                    "revision: 2\n",
                    {**save_kwargs, "artifacts": {"report": "different.json"}},
                ),
                (
                    "verification",
                    state2,
                    "revision: 2\n",
                    {**save_kwargs, "verification": {"tests": "different"}},
                ),
            )
            for field_name, state, resume, kwargs in conflicting_requests:
                with self.subTest(field_name=field_name):
                    with self.assertRaisesRegex(ValueError, "revision must increase"):
                        repo.save(state, resume, **kwargs)

    def test_authenticated_legacy_manifest_is_not_an_idempotency_credential(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            state = self.make_state()
            repo.save(state, "revision: 1\n", events=({"revision": 1},))
            self.rewrite_manifest(root, lambda manifest: manifest.pop("save_request"))

            with self.assertRaisesRegex(ValueError, "revision must increase"):
                repo.save(state, "revision: 1\n", events=({"revision": 1},))

    def test_repository_lock_serializes_a_spawned_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            state1 = self.make_state()
            state2 = state1.evolve(next_action="Wait for repository lock")
            repo.save(state1, "revision: 1\n")
            context = multiprocessing.get_context("spawn")
            started = context.Event()
            finished = context.Event()
            process = context.Process(
                target=_save_revision_in_process,
                args=(root, self.key, state2.to_dict(), started, finished),
            )

            with repo._exclusive_write():
                process.start()
                self.assertTrue(started.wait(timeout=3))
                self.assertFalse(finished.wait(timeout=0.25))

            process.join(timeout=5)

            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 0)
            self.assertTrue(finished.is_set())
            self.assertEqual(repo.load_active().state.revision, 2)

    def test_load_active_accepts_authenticated_legacy_flat_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)
            state = self.make_state()
            original = repo.save(
                state,
                "schema_version: 1\n",
                events=({"type": "started"},),
            )
            manifest_path = root / "active-run.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            legacy_paths = {}
            for name, entry in manifest["files"].items():
                source = root / entry["path"]
                destination = root / "runs" / state.run_id / source.name
                destination.write_bytes(source.read_bytes())
                legacy_paths[name] = destination.relative_to(root).as_posix()

            def use_legacy_paths(value):
                for name, path in legacy_paths.items():
                    value["files"][name]["path"] = path

            self.rewrite_manifest(root, use_legacy_paths)

            self.assertEqual(repo.load_active(), original)


if __name__ == "__main__":
    unittest.main()
