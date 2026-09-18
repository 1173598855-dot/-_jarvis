"""Regression coverage for bounded JSON files consumed by local CLIs."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from core.contracts.bounded_json import (  # noqa: E402
    MAX_CLI_JSON_BYTES,
    read_bounded_json,
)


class TestBoundedJsonReader(unittest.TestCase):
    def test_reads_valid_json_at_the_configured_limit(self):
        with tempfile.TemporaryDirectory(prefix=".test-bounded-cli-", dir=ROOT) as temp_dir:
            path = Path(temp_dir) / "input.json"
            encoded = b'{"ok": true}'
            path.write_bytes(encoded)

            self.assertEqual(
                read_bounded_json(path, max_bytes=len(encoded)),
                {"ok": True},
            )

    def test_rejects_content_that_grows_after_stat(self):
        with tempfile.TemporaryDirectory(prefix=".test-bounded-cli-", dir=ROOT) as temp_dir:
            path = Path(temp_dir) / "input.json"
            path.write_bytes(b"x" * 33)

            with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=0)):
                with self.assertRaisesRegex(ValueError, "exceeds"):
                    read_bounded_json(path, max_bytes=32)

    def test_rejects_invalid_utf8(self):
        with tempfile.TemporaryDirectory(prefix=".test-bounded-cli-", dir=ROOT) as temp_dir:
            path = Path(temp_dir) / "input.json"
            path.write_bytes(b"\xff")

            with self.assertRaisesRegex(ValueError, "UTF-8"):
                read_bounded_json(path)


class TestCliJsonLimits(unittest.TestCase):
    def _oversized_json_file(self, temp_dir: str, payload: object) -> Path:
        path = Path(temp_dir) / "oversized.json"
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        path.write_bytes(encoded + b" " * (MAX_CLI_JSON_BYTES + 1 - len(encoded)))
        return path

    def _run_cli(self, script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(script), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=30,
        )

    def test_agent_factory_batch_rejects_oversized_json(self):
        script = SRC / "core" / "brain" / "agent_factory.py"
        with tempfile.TemporaryDirectory(prefix=".test-bounded-cli-", dir=ROOT) as temp_dir:
            path = self._oversized_json_file(temp_dir, [])
            result = self._run_cli(script, "batch", str(path))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exceeds", result.stderr)

    def test_agent_factory_batch_accepts_valid_json(self):
        script = SRC / "core" / "brain" / "agent_factory.py"
        with tempfile.TemporaryDirectory(prefix=".test-bounded-cli-", dir=ROOT) as temp_dir:
            path = Path(temp_dir) / "input.json"
            path.write_text("[]", encoding="utf-8")
            result = self._run_cli(script, "batch", str(path))

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_context_compressor_rejects_oversized_json(self):
        script = SRC / "core" / "brain" / "context_compressor.py"
        with tempfile.TemporaryDirectory(prefix=".test-bounded-cli-", dir=ROOT) as temp_dir:
            path = self._oversized_json_file(temp_dir, [])
            result = self._run_cli(script, "compress", str(path))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exceeds", result.stderr)

    def test_role_registry_rejects_oversized_json(self):
        script = SRC / "core" / "brain" / "role_registry.py"
        profile = {
            "name": "oversized_cli_fixture",
            "display_name": "Oversized CLI Fixture",
            "description": "fixture",
        }
        with tempfile.TemporaryDirectory(prefix=".test-bounded-cli-", dir=ROOT) as temp_dir:
            path = self._oversized_json_file(temp_dir, profile)
            result = self._run_cli(script, "register", str(path))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exceeds", result.stderr)


if __name__ == "__main__":
    unittest.main()
