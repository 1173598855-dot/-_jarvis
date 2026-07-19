import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adapters.file_run_state_repository import (
    FileRunStateRepository,
    RunStateIntegrityError,
)
from core.contracts.run_state import RunState


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
            state_path = root / "runs" / "run-20260716-043000" / "state.json"
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
            state_path = root / "runs" / "run-20260716-043000" / "state.json"
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

            with self.assertRaisesRegex(ValueError, "run_id"):
                repo.archive_active("run-20260716-043001")
            repo.archive_active(state.run_id)

            self.assertIsNone(repo.load_active())
            self.assertTrue((root / "runs" / state.run_id / "state.json").is_file())

    def test_replace_failure_cleans_temporary_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self.make_repo(root)

            with patch(
                "adapters.file_run_state_repository.os.replace",
                side_effect=OSError("replace failed"),
            ):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    repo.save(self.make_state(), "schema_version: 1\n")

            self.assertFalse(list(root.rglob("*.tmp")))
            self.assertFalse((root / "active-run.json").exists())


if __name__ == "__main__":
    unittest.main()
