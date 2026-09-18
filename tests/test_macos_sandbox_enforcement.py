"""Real macOS Seatbelt enforcement probe for the Worker sandbox."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from core.kernel.worker_macos_sandbox import MacOSSandbox
from core.kernel.worker_windows_isolation import (
    WorkerWindowsIsolationError,
    default_runtime_read_paths,
)


@unittest.skipUnless(
    sys.platform == "darwin" and shutil.which("sandbox-exec"),
    "real Seatbelt enforcement requires macOS sandbox-exec",
)
class TestMacOSSandboxEnforcement(unittest.TestCase):
    def test_seatbelt_denies_ungranted_read_and_loopback_but_allows_worker_root(
        self,
    ) -> None:
        probe_source = (
            "import json, os, socket\n"
            "from pathlib import Path\n"
            "result = {}\n"
            "try:\n"
            "    Path(os.environ[\"PROBE_OUTSIDE\"]).read_text(encoding=\"utf-8\")\n"
            "except OSError:\n"
            "    result[\"outside_read\"] = \"denied\"\n"
            "else:\n"
            "    result[\"outside_read\"] = \"allowed\"\n"
            "try:\n"
            "    with socket.create_connection((\"127.0.0.1\", int(os.environ[\"PROBE_PORT\"])), timeout=1):\n"
            "        pass\n"
            "except OSError:\n"
            "    result[\"loopback\"] = \"denied\"\n"
            "else:\n"
            "    result[\"loopback\"] = \"allowed\"\n"
            "try:\n"
            "    Path(os.environ[\"TMPDIR\"], \"probe-write.txt\").write_text(\"ok\", encoding=\"utf-8\")\n"
            "except OSError:\n"
            "    result[\"write\"] = \"denied\"\n"
            "else:\n"
            "    result[\"write\"] = \"allowed\"\n"
            "print(json.dumps(result, sort_keys=True), flush=True)\n"
        )

        with tempfile.TemporaryDirectory(prefix=".test-macos-enforcement-") as temporary:
            root = Path(temporary)
            outside = root / "outside.txt"
            outside.write_text("must remain unreadable", encoding="utf-8")
            source = root / "probe-source"
            source.mkdir()
            (source / "probe.py").write_text(probe_source, encoding="utf-8")

            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            try:
                try:
                    runtime_read_paths = default_runtime_read_paths()
                except WorkerWindowsIsolationError as error:
                    self.skipTest(f"Python runtime paths are unavailable: {error}")

                sandbox = MacOSSandbox.create(runtime_read_paths=runtime_read_paths)
                try:
                    staged = sandbox.stage(source, "probe")
                    process = sandbox.spawn(
                        [str(sys.executable), "-S", "-u", "probe.py"],
                        cwd=staged,
                        environment={
                            "PATH": os.environ.get("PATH", os.defpath),
                            "PYTHONIOENCODING": "utf-8",
                            "PYTHONUNBUFFERED": "1",
                            "PYTHONNOUSERSITE": "1",
                            "TMPDIR": str(sandbox.writable_root),
                            "PROBE_OUTSIDE": str(outside),
                            "PROBE_PORT": str(listener.getsockname()[1]),
                        },
                    )
                    try:
                        stdout, stderr = process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                        self.fail("macOS Seatbelt probe exceeded its 5-second deadline")
                finally:
                    sandbox.close()
            finally:
                listener.close()

        self.assertEqual(process.returncode, 0, stderr.decode("utf-8", errors="replace"))
        self.assertEqual(
            json.loads(stdout.decode("utf-8")),
            {"outside_read": "denied", "loopback": "denied", "write": "allowed"},
        )


if __name__ == "__main__":
    unittest.main()
