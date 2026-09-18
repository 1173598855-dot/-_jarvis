"""Real Linux namespace and Landlock enforcement probe for child Workers."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from core.kernel.worker_staging import stage_worker_tree

ROOT = Path(__file__).parent.parent
RUN_ENFORCEMENT = os.environ.get("JARVIS_RUN_LINUX_ISOLATION_ENFORCEMENT") == "1"


@unittest.skipUnless(
    sys.platform.startswith("linux") and RUN_ENFORCEMENT,
    "real Linux enforcement requires an explicit Linux isolation run",
)
class TestLinuxWorkerIsolationEnforcement(unittest.TestCase):
    def test_namespace_and_landlock_enforce_worker_boundary(self) -> None:
        probe_source = (
            "import importlib.util, json, os, socket, sys\n"
            "from pathlib import Path\n"
            "from core.kernel.plugin_api import XiaoYiPluginAPI\n"
            "from core.kernel.worker_filesystem_isolation import isolate_worker_filesystem\n"
            "from core.kernel.worker_network_isolation import isolate_worker_network\n"
            "outside = Path(os.environ['PROBE_OUTSIDE'])\n"
            "trusted_src = Path(os.environ['PROBE_SRC_ROOT'])\n"
            "plugin_root = Path(os.environ['PROBE_PLUGIN_ROOT'])\n"
            "worker_root = Path(os.environ['PROBE_WORKER_ROOT'])\n"
            "port = int(os.environ['PROBE_PORT'])\n"
            "baseline = {'uid': os.geteuid(), 'gid': os.getegid()}\n"
            "try:\n"
            "    outside.read_text(encoding='utf-8')\n"
            "except OSError:\n"
            "    baseline['outside_read'] = 'denied'\n"
            "else:\n"
            "    baseline['outside_read'] = 'allowed'\n"
            "try:\n"
            "    outside.write_text('baseline', encoding='utf-8')\n"
            "except OSError:\n"
            "    baseline['outside_write'] = 'denied'\n"
            "else:\n"
            "    baseline['outside_write'] = 'allowed'\n"
            "try:\n"
            "    with socket.create_connection(('127.0.0.1', port), timeout=1):\n"
            "        pass\n"
            "except OSError:\n"
            "    baseline['loopback'] = 'denied'\n"
            "else:\n"
            "    baseline['loopback'] = 'allowed'\n"
            "applied = isolate_worker_network()\n"
            "applied += isolate_worker_filesystem(\n"
            "    worker_root,\n"
            "    allowed_paths=((Path(__file__).parent, False), (trusted_src, False), (plugin_root, False), (worker_root, True)),\n"
            "    root_writable=True,\n"
            ")\n"
            "restricted = {}\n"
            "sys.dont_write_bytecode = True\n"
            "try:\n"
            "    spec = importlib.util.spec_from_file_location('probe_plugin', plugin_root / 'plugin.py')\n"
            "    module = importlib.util.module_from_spec(spec)\n"
            "    spec.loader.exec_module(module)\n"
            "except (AttributeError, OSError):\n"
            "    restricted['plugin_import'] = 'denied'\n"
            "else:\n"
            "    restricted['plugin_import'] = 'allowed'\n"
            "try:\n"
            "    outside.read_text(encoding='utf-8')\n"
            "except OSError:\n"
            "    restricted['outside_read'] = 'denied'\n"
            "else:\n"
            "    restricted['outside_read'] = 'allowed'\n"
            "try:\n"
            "    outside.write_text('forbidden', encoding='utf-8')\n"
            "except OSError:\n"
            "    restricted['outside_write'] = 'denied'\n"
            "else:\n"
            "    restricted['outside_write'] = 'allowed'\n"
            "try:\n"
            "    with socket.create_connection(('127.0.0.1', port), timeout=1):\n"
            "        pass\n"
            "except OSError:\n"
            "    restricted['loopback'] = 'denied'\n"
            "else:\n"
            "    restricted['loopback'] = 'allowed'\n"
            "try:\n"
            "    (worker_root / 'probe-write.txt').write_text('ok', encoding='utf-8')\n"
            "except OSError:\n"
            "    restricted['worker_write'] = 'denied'\n"
            "else:\n"
            "    restricted['worker_write'] = 'allowed'\n"
            "print(json.dumps({'applied': applied, 'baseline': baseline, 'restricted': restricted}, sort_keys=True), flush=True)\n"
        )

        with tempfile.TemporaryDirectory(prefix=".test-linux-enforcement-") as temporary:
            root = Path(temporary)
            outside = root / "outside.txt"
            outside.write_text("baseline", encoding="utf-8")
            trusted_src = root / "src"
            stage_worker_tree(ROOT / "src", trusted_src)
            plugin_root = root / "plugin-template"
            stage_worker_tree(ROOT / "plugins" / "plugin-template", plugin_root)
            source = root / "probe-source"
            source.mkdir()
            probe = source / "probe.py"
            probe.write_text(probe_source, encoding="utf-8")
            worker_root = root / "worker-root"
            worker_root.mkdir()

            root.chmod(0o755)
            outside.chmod(0o666)
            source.chmod(0o755)
            probe.chmod(0o644)
            plugin_root.chmod(0o755)
            worker_root.chmod(0o777)

            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            # Leave room for both the baseline and mutation connection. If the
            # namespace is not applied, the second connect must stay observable.
            listener.listen(4)
            try:
                demote = None
                probe_uid = os.geteuid()
                probe_gid = os.getegid()
                if os.geteuid() == 0:
                    probe_uid = 12_345
                    probe_gid = 12_345

                    def demote() -> None:
                        os.setgroups([])
                        os.setgid(probe_gid)
                        os.setuid(probe_uid)

                environment = {
                    "PATH": os.environ.get("PATH", os.defpath),
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONNOUSERSITE": "1",
                    "PYTHONPATH": str(trusted_src),
                    "PYTHONUNBUFFERED": "1",
                    "PROBE_OUTSIDE": str(outside),
                    "PROBE_SRC_ROOT": str(trusted_src),
                    "PROBE_PLUGIN_ROOT": str(plugin_root),
                    "PROBE_PORT": str(listener.getsockname()[1]),
                    "PROBE_WORKER_ROOT": str(worker_root),
                }
                process = subprocess.Popen(
                    [sys.executable, "-S", "-u", str(probe)],
                    cwd=source,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    preexec_fn=demote,
                    start_new_session=True,
                )
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    self.fail("Linux isolation probe exceeded its 5-second deadline")
            finally:
                listener.close()

            self.assertEqual(
                process.returncode,
                0,
                stderr.decode("utf-8", errors="replace"),
            )
            payload = json.loads(stdout.decode("utf-8"))
            self.assertEqual(
                payload["baseline"],
                {
                    "gid": probe_gid,
                    "loopback": "allowed",
                    "outside_read": "allowed",
                    "outside_write": "allowed",
                    "uid": probe_uid,
                },
            )
            self.assertNotEqual(payload["baseline"]["uid"], 65_534)
            self.assertNotEqual(payload["baseline"]["gid"], 65_534)
            self.assertEqual(
                payload["restricted"],
                {
                    "loopback": "denied",
                    "outside_read": "denied",
                    "outside_write": "denied",
                    "plugin_import": "allowed",
                    "worker_write": "allowed",
                },
            )
            self.assertEqual(payload["applied"][:2], ["network_namespace", "landlock"])
            self.assertRegex(payload["applied"][2], r"^landlock_abi_[1-9][0-9]*$")
            self.assertEqual(outside.read_text(encoding="utf-8"), "baseline")


if __name__ == "__main__":
    unittest.main()
