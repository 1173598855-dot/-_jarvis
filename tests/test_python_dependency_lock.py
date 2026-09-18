"""Offline guardrails for the universal Python dependency lock."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).parent.parent
LOCK = ROOT / "requirements.lock"
PROJECT = ROOT / "pyproject.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

_GENERATOR_TOKENS = (
    "uv==0.12.5 pip compile",
    "pyproject.toml",
    "--extra dev",
    "--universal",
    "--python-version 3.10",
    "--generate-hashes",
    "--no-sources",
    "--output-file requirements.lock",
)
_FORBIDDEN_DIRECTIVES = (
    "--index-url",
    "--extra-index-url",
    "--trusted-host",
    "--editable",
    "-e ",
)
_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"==(?P<version>[^\s;\\]+)"
    r"(?:\s*;\s*(?P<marker>[^\\]+?))?\s*\\?$"
)
_SHA256 = re.compile(r"--hash=sha256:[0-9a-f]{64}")


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _direct_dependency_names() -> set[str]:
    with PROJECT.open("rb") as stream:
        config = tomllib.load(stream)
    project = config["project"]
    values = list(project["dependencies"])
    values.extend(project["optional-dependencies"]["dev"])
    values.extend(config.get("build-system", {}).get("requires", []))
    return {
        _normalize_name(re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*", value).group())
        for value in values
    }


def _requirement_blocks(text: str) -> list[tuple[re.Match[str], str]]:
    blocks: list[tuple[re.Match[str], str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line and not line[0].isspace() and not line.startswith("#"):
            if current:
                match = _REQUIREMENT.fullmatch(current[0])
                if match is None:
                    raise ValueError(f"invalid locked requirement: {current[0]}")
                blocks.append((match, "\n".join(current)))
            current = [line]
        elif current:
            current.append(line)
    if current:
        match = _REQUIREMENT.fullmatch(current[0])
        if match is None:
            raise ValueError(f"invalid locked requirement: {current[0]}")
        blocks.append((match, "\n".join(current)))
    return blocks


class TestPythonDependencyLock(unittest.TestCase):
    def _lock_text(self) -> str:
        self.assertTrue(LOCK.is_file(), "requirements.lock must exist")
        return LOCK.read_text(encoding="utf-8")

    def test_lock_file_exists(self):
        self.assertTrue(LOCK.is_file(), "requirements.lock must exist")

    def test_project_declares_the_build_backend_inside_the_locked_dev_graph(self):
        with PROJECT.open("rb") as stream:
            config = tomllib.load(stream)

        self.assertIn("build-system", config)
        self.assertEqual(config["build-system"]["build-backend"], "setuptools.build_meta")
        build_names = {
            _normalize_name(
                re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*", value).group()
            )
            for value in config["build-system"]["requires"]
        }
        dev_names = {
            _normalize_name(
                re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*", value).group()
            )
            for value in config["project"]["optional-dependencies"]["dev"]
        }
        self.assertIn("setuptools", build_names)
        self.assertIn("setuptools", dev_names)

    def test_lock_records_the_exact_universal_generation_command(self):
        text = self._lock_text()

        for token in _GENERATOR_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, text[:1000])

    def test_lock_contains_unique_exact_pins_for_all_direct_dependencies(self):
        blocks = _requirement_blocks(self._lock_text())
        names = [_normalize_name(match.group("name")) for match, _block in blocks]
        identities = [
            (name, (match.group("marker") or "").strip())
            for name, (match, _block) in zip(names, blocks)
        ]

        self.assertTrue(blocks, "requirements.lock must contain exact pins")
        self.assertEqual(
            len(identities),
            len(set(identities)),
            "locked package name and marker pairs must be unique",
        )
        repeated_names = {name for name in names if names.count(name) > 1}
        self.assertTrue(
            all(marker for name, marker in identities if name in repeated_names),
            "universal package forks must carry explicit markers",
        )
        self.assertTrue(_direct_dependency_names().issubset(names))

    def test_every_locked_requirement_has_a_sha256_hash(self):
        blocks = _requirement_blocks(self._lock_text())

        self.assertTrue(blocks, "requirements.lock must contain requirement blocks")
        for match, block in blocks:
            with self.subTest(package=match.group("name")):
                self.assertRegex(block, _SHA256)

    def test_requirement_parser_rejects_unrecognized_top_level_lines(self):
        malformed = "not a valid requirement\n    --hash=sha256:" + "0" * 64

        with self.assertRaisesRegex(ValueError, "invalid locked requirement"):
            _requirement_blocks(malformed)

    def test_lock_rejects_unverified_or_environment_specific_sources(self):
        text = self._lock_text()
        requirement_lines = [match.group(0) for match, _block in _requirement_blocks(text)]

        for directive in _FORBIDDEN_DIRECTIVES:
            with self.subTest(directive=directive):
                self.assertNotIn(directive, text)
        self.assertNotRegex(text, r"(?i)(?:git|hg|svn|bzr)\+")
        self.assertFalse(any(" @ " in line for line in requirement_lines))
        self.assertFalse(
            any(line.startswith(("./", "../", "/")) for line in requirement_lines)
        )

    def test_ci_installs_the_hash_lock_before_the_editable_project(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        locked_install = "python -m pip install --require-hashes -r requirements.lock"
        editable_install = (
            "python -m pip install --no-deps --no-build-isolation -e ."
        )

        self.assertGreaterEqual(text.count(locked_install), 2)
        self.assertIn(editable_install, text)
        self.assertNotIn("python -m pip install ruff", text)
        self.assertNotIn('python -m pip install -e ".[dev]"', text)


def run_all_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestPythonDependencyLock)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(run_all_tests())
