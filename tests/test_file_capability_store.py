"""Security tests for verified, disabled capability package installation."""

import hashlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from adapters.file_capability_store import (  # noqa: E402
    CapabilityPackageLimits,
    CapabilityStoreError,
    FileCapabilityStore,
    InstalledCapability,
)
from core.kernel.capability_manifest import CapabilityKind, CapabilityLifecycle  # noqa: E402


def manifest_bytes(**overrides):
    manifest = {
        "schema_version": 1,
        "capability_id": "skill:package-example",
        "kind": "skill",
        "name": "Package Example",
        "version": "1.2.3",
        "description": "A verified local package fixture",
        "source_url": "https://github.com/example/package-example",
        "license": "MIT",
        "entrypoint": "payload/main.py",
        "permissions": ["memory.read"],
        "compatibility": {"python": ">=3.10,<4"},
    }
    manifest.update(overrides)
    return json.dumps(
        manifest,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def zip_bytes(entries, *, compression=zipfile.ZIP_DEFLATED):
    stream = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(stream, "w", compression=compression) as archive:
            for name, content in entries:
                archive.writestr(name, content)
    return stream.getvalue()


def package_bytes(*, manifest=None, payload=None, extra_entries=()):
    entries = [
        ("capability.json", manifest if manifest is not None else manifest_bytes()),
        ("payload/main.py", payload if payload is not None else b"VALUE = 1\n"),
    ]
    entries.extend(extra_entries)
    return zip_bytes(entries)


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def set_zip_flag(bundle, flag):
    value = bytearray(bundle)
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        position = 0
        while True:
            position = value.find(signature, position)
            if position < 0:
                break
            offset = position + flag_offset
            flags = int.from_bytes(value[offset:offset + 2], "little") | flag
            value[offset:offset + 2] = flags.to_bytes(2, "little")
            position += len(signature)
    return bytes(value)


def set_encrypted_flag(bundle):
    return set_zip_flag(bundle, 0x1)


def non_utf8_name_bundle():
    bundle = package_bytes()
    original = b"payload/main.py"
    replacement = b"payload/ma\x82n.py"
    if bundle.count(original) != 2:
        raise AssertionError("expected one local and one central ZIP filename")
    return bundle.replace(original, replacement)


def invalid_utf8_flag_bundle():
    return set_zip_flag(non_utf8_name_bundle(), 0x800)


def corrupt_member_data(bundle, member_name):
    value = bytearray(bundle)
    with zipfile.ZipFile(io.BytesIO(bundle), "r") as archive:
        info = archive.getinfo(member_name)
    offset = info.header_offset
    name_length = int.from_bytes(value[offset + 26:offset + 28], "little")
    extra_length = int.from_bytes(value[offset + 28:offset + 30], "little")
    data_offset = offset + 30 + name_length + extra_length
    value[data_offset + max(0, info.compress_size // 2)] ^= 0xFF
    return bytes(value)


def backslash_name_bundle():
    bundle = package_bytes(extra_entries=(("payload/backslash.py", b"x"),))
    original = b"payload/backslash.py"
    replacement = b"payload\\backslash.py"
    if bundle.count(original) != 2:
        raise AssertionError("expected one local and one central ZIP filename")
    return bundle.replace(original, replacement)


_DEFAULT_DIGEST = object()


class TestCapabilityPackageRejection(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temporary.name) / "store"
        self.store = FileCapabilityStore(self.temp_root)

    def tearDown(self):
        self.temporary.cleanup()

    def assert_rejected(self, bundle, code, *, store=None, digest=_DEFAULT_DIGEST):
        active_store = store or self.store
        expected_digest = sha256(bundle) if digest is _DEFAULT_DIGEST else digest
        with self.assertRaises(CapabilityStoreError) as raised:
            active_store.install(bundle, expected_digest)
        self.assertEqual(raised.exception.code, code)
        self.assertTrue(str(raised.exception).startswith(f"{code}:"))
        return raised.exception

    def assert_no_published_revision(self):
        revisions = self.temp_root / "capabilities"
        if revisions.exists():
            self.assertEqual(list(revisions.rglob("*")), [])

    def test_install_rejects_traversal_before_writing_payload(self):
        outside = self.temp_root.parent / "escape.py"
        bundle = package_bytes(extra_entries=(("../escape.py", b"x"),))

        self.assert_rejected(bundle, "ARCHIVE_PATH_INVALID")

        self.assertFalse(outside.exists())
        self.assert_no_published_revision()

    def test_install_rejects_absolute_drive_and_backslash_paths(self):
        invalid_names = (
            "/payload/absolute.py",
            "C:/payload/drive.py",
            "//server/share.py",
        )
        for invalid_name in invalid_names:
            with self.subTest(invalid_name=invalid_name):
                bundle = package_bytes(extra_entries=((invalid_name, b"x"),))
                self.assert_rejected(bundle, "ARCHIVE_PATH_INVALID")
                self.assert_no_published_revision()

        bundle = backslash_name_bundle()
        self.assert_rejected(bundle, "ARCHIVE_PATH_INVALID")
        self.assert_no_published_revision()

    def test_install_rejects_paths_that_require_posix_normalization(self):
        for index, invalid_name in enumerate((
            "payload//extra.py",
            "./payload/extra.py",
            "payload/./extra.py",
        )):
            with self.subTest(invalid_name=invalid_name):
                root = self.temp_root / f"normalized-{index}"
                store = FileCapabilityStore(root)
                bundle = package_bytes(extra_entries=((invalid_name, b"x"),))
                self.assert_rejected(bundle, "ARCHIVE_PATH_INVALID", store=store)
                self.assertFalse((root / "capabilities").exists())

    def test_install_rejects_symlink_and_non_regular_entries(self):
        symlink = zipfile.ZipInfo("payload/link.py")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle = package_bytes(extra_entries=((symlink, b"main.py"),))

        self.assert_rejected(bundle, "ARCHIVE_ENTRY_TYPE_INVALID")
        self.assert_no_published_revision()

    def test_install_rejects_encrypted_entries_before_reading_content(self):
        bundle = set_encrypted_flag(package_bytes())

        self.assert_rejected(bundle, "ARCHIVE_ENCRYPTED")
        self.assert_no_published_revision()

    def test_install_rejects_memory_heavy_compression_methods(self):
        bundle = zip_bytes(
            (
                ("capability.json", manifest_bytes()),
                ("payload/main.py", b"VALUE = 1\n"),
            ),
            compression=zipfile.ZIP_BZIP2,
        )

        self.assert_rejected(bundle, "ARCHIVE_COMPRESSION_UNSUPPORTED")
        self.assert_no_published_revision()

    def test_install_rejects_duplicate_entries(self):
        bundle = package_bytes(extra_entries=(("payload/main.py", b"SECOND = 2\n"),))

        self.assert_rejected(bundle, "ARCHIVE_ENTRY_DUPLICATE")
        self.assert_no_published_revision()

    def test_install_rejects_file_directory_prefix_conflicts(self):
        bundle = package_bytes(extra_entries=(
            ("payload/node", b"file"),
            ("payload/node/child.py", b"child"),
        ))

        self.assert_rejected(bundle, "ARCHIVE_ENTRY_CONFLICT")
        self.assert_no_published_revision()

    def test_install_rejects_non_utf8_names(self):
        bundle = non_utf8_name_bundle()

        self.assert_rejected(bundle, "ARCHIVE_NAME_ENCODING_INVALID")
        self.assert_no_published_revision()

    def test_install_normalizes_invalid_utf8_and_deflate_failures(self):
        invalid_name = invalid_utf8_flag_bundle()
        compressed = package_bytes(payload=b"A" * 4096)
        corrupt_deflate = corrupt_member_data(compressed, "payload/main.py")

        self.assert_rejected(invalid_name, "ARCHIVE_NAME_ENCODING_INVALID")
        self.assert_rejected(corrupt_deflate, "ARCHIVE_INVALID")
        self.assert_no_published_revision()

    def test_install_rejects_nonportable_windows_path_components(self):
        invalid_names = (
            "payload/main.py:hidden",
            "payload/CON.py",
            "payload/trailing.",
            "payload/trailing ",
            "payload/" + "a" * 256,
        )
        for index, invalid_name in enumerate(invalid_names):
            with self.subTest(invalid_name=invalid_name):
                root = self.temp_root / f"portable-{index}"
                store = FileCapabilityStore(root)
                bundle = package_bytes(extra_entries=((invalid_name, b"x"),))
                self.assert_rejected(bundle, "ARCHIVE_PATH_INVALID", store=store)
                self.assertFalse((root / "capabilities").exists())

    def test_install_rejects_missing_manifest_payload_and_unknown_roots(self):
        invalid_bundles = (
            (zip_bytes((("payload/main.py", b"x"),)), "MANIFEST_MISSING"),
            (zip_bytes((("capability.json", manifest_bytes()),)), "PAYLOAD_MISSING"),
            (
                package_bytes(extra_entries=(("README.md", b"unexpected"),)),
                "ARCHIVE_LAYOUT_INVALID",
            ),
        )
        for bundle, code in invalid_bundles:
            with self.subTest(code=code):
                self.assert_rejected(bundle, code)
                self.assert_no_published_revision()

    def test_install_rejects_invalid_zip_after_digest_verification(self):
        bundle = b"not a zip file"

        self.assert_rejected(bundle, "ARCHIVE_INVALID")
        self.assert_no_published_revision()

    def test_install_rejects_archive_file_and_expanded_size_limits(self):
        bundle = package_bytes(extra_entries=(("payload/extra.py", b"x"),))
        file_limited = FileCapabilityStore(
            self.temp_root,
            CapabilityPackageLimits(max_files=2),
        )
        archive_limited = FileCapabilityStore(
            self.temp_root,
            CapabilityPackageLimits(max_archive_bytes=len(bundle) - 1),
        )
        large_payload = b"x" * 1024
        per_file_bundle = package_bytes(payload=large_payload)
        per_file_limited = FileCapabilityStore(
            self.temp_root,
            CapabilityPackageLimits(max_file_bytes=512),
        )
        manifest = manifest_bytes()
        total_bundle = package_bytes(
            manifest=manifest,
            payload=b"a" * 300,
            extra_entries=(("payload/extra.py", b"b" * 300),),
        )
        total_limited = FileCapabilityStore(
            self.temp_root,
            CapabilityPackageLimits(
                max_file_bytes=512,
                max_uncompressed_bytes=len(manifest) + 599,
            ),
        )

        cases = (
            (file_limited, bundle, "ARCHIVE_FILE_LIMIT"),
            (archive_limited, bundle, "ARCHIVE_SIZE_LIMIT"),
            (per_file_limited, per_file_bundle, "ARCHIVE_FILE_SIZE_LIMIT"),
            (total_limited, total_bundle, "ARCHIVE_EXPANDED_SIZE_LIMIT"),
        )
        for store, candidate, code in cases:
            with self.subTest(code=code):
                self.assert_rejected(candidate, code, store=store)
                self.assert_no_published_revision()

    def test_install_rejects_digest_mismatch_before_parsing_archive(self):
        bundle = b"not a zip file"

        self.assert_rejected(bundle, "DIGEST_MISMATCH", digest="0" * 64)
        self.assert_no_published_revision()

    def test_install_rejects_malformed_digest_shape(self):
        bundle = package_bytes()
        invalid_digests = ("", "A" * 64, "0" * 63, 123)
        for digest in invalid_digests:
            with self.subTest(digest=digest):
                self.assert_rejected(bundle, "DIGEST_INVALID", digest=digest)
                self.assert_no_published_revision()

    def test_install_rejects_malformed_manifest_json_and_shape(self):
        invalid_manifests = (
            b"{",
            b"\xff\xfe",
            json.dumps([]).encode("utf-8"),
            manifest_bytes(schema_version=2),
            manifest_bytes(name="invalid\ud800name"),
        )
        for manifest in invalid_manifests:
            with self.subTest(manifest=manifest[:20]):
                bundle = package_bytes(manifest=manifest)
                self.assert_rejected(bundle, "MANIFEST_INVALID")
                self.assert_no_published_revision()

    def test_install_rejects_non_https_or_ambiguous_source_url(self):
        invalid_urls = (
            "http://example.com/package",
            "https://",
            "https://user:secret@example.com/package",
            "https://example.com/package#fragment",
            "https://example.com\\@attacker.invalid/package",
        )
        for source_url in invalid_urls:
            with self.subTest(source_url=source_url):
                bundle = package_bytes(manifest=manifest_bytes(source_url=source_url))
                self.assert_rejected(bundle, "MANIFEST_SOURCE_INVALID")
                self.assert_no_published_revision()

    def test_install_rejects_unsupported_license(self):
        for license_name in ("GPL-3.0-only", "Proprietary", "mit", None, []):
            with self.subTest(license_name=license_name):
                bundle = package_bytes(manifest=manifest_bytes(license=license_name))
                self.assert_rejected(bundle, "MANIFEST_LICENSE_UNSUPPORTED")
                self.assert_no_published_revision()

    def test_install_rejects_invalid_or_missing_entrypoint(self):
        invalid_entrypoints = (
            "../main.py",
            "/payload/main.py",
            "C:/payload/main.py",
            "payload\\main.py",
            "payload/missing.py",
            "capability.json",
        )
        for entrypoint in invalid_entrypoints:
            with self.subTest(entrypoint=entrypoint):
                bundle = package_bytes(manifest=manifest_bytes(entrypoint=entrypoint))
                self.assert_rejected(bundle, "MANIFEST_ENTRYPOINT_INVALID")
                self.assert_no_published_revision()


class TestFileCapabilityStore(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temporary.name) / "store"
        self.store = FileCapabilityStore(self.temp_root)
        self.bundle = package_bytes()
        self.digest = sha256(self.bundle)

    def tearDown(self):
        self.temporary.cleanup()

    def test_valid_package_installs_disabled_and_exact_retry_is_idempotent(self):
        first = self.store.install(self.bundle, self.digest)
        index_before_retry = (self.temp_root / "index.json").read_bytes()
        second = self.store.install(self.bundle, self.digest)

        self.assertIsInstance(first, InstalledCapability)
        self.assertEqual(first, second)
        self.assertEqual(first.capability_id, "skill:package-example")
        self.assertIs(first.kind, CapabilityKind.SKILL)
        self.assertIs(first.lifecycle, CapabilityLifecycle.DISABLED)
        self.assertEqual(first.revision_id, self.digest)
        self.assertEqual(first.bundle_sha256, self.digest)
        self.assertEqual(len(self.store.list_revisions(first.capability_id)), 1)
        self.assertEqual((self.temp_root / "index.json").read_bytes(), index_before_retry)

    def test_installed_revision_is_content_addressed_and_public_state_is_relative(self):
        installed = self.store.install(self.bundle, self.digest)
        revision_root = self.temp_root / Path(installed.relative_path)
        public_json = json.dumps(installed.to_public_dict(), sort_keys=True)

        self.assertEqual(
            installed.relative_path,
            f"capabilities/skill/package-example/revisions/{self.digest}",
        )
        self.assertEqual((revision_root / "bundle.zip").read_bytes(), self.bundle)
        self.assertEqual(
            (revision_root / "capability.json").read_bytes(),
            manifest_bytes(),
        )
        self.assertEqual(
            (revision_root / "payload" / "main.py").read_bytes(),
            b"VALUE = 1\n",
        )
        revision_state = json.loads(
            (revision_root / "revision.json").read_text(encoding="utf-8")
        )
        self.assertEqual(revision_state["schema_version"], 1)
        self.assertEqual(revision_state["record_schema_version"], 1)
        self.assertNotIn(str(self.temp_root), public_json)
        self.assertEqual(installed.to_public_dict()["lifecycle"], "disabled")
        self.assertEqual(
            installed.to_public_dict()["revision"]["bundle_sha256"],
            self.digest,
        )

    def test_reopened_store_lists_verified_revision_without_executing_payload(self):
        marker = self.temp_root.parent / "imported.txt"
        payload = (
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
        ).encode("utf-8")
        bundle = package_bytes(payload=payload)
        digest = sha256(bundle)

        installed = self.store.install(bundle, digest)
        reopened = FileCapabilityStore(self.temp_root)
        revisions = reopened.list_revisions(installed.capability_id)

        self.assertEqual(revisions, (installed,))
        self.assertFalse(marker.exists())

    def test_install_rejects_different_revision_until_upgrade_is_explicit(self):
        original = self.store.install(self.bundle, self.digest)
        changed_bundle = package_bytes(payload=b"VALUE = 2\n")

        with self.assertRaises(CapabilityStoreError) as raised:
            self.store.install(changed_bundle, sha256(changed_bundle))

        self.assertEqual(raised.exception.code, "CAPABILITY_ALREADY_INSTALLED")
        self.assertEqual(self.store.list_revisions(original.capability_id), (original,))

    def test_install_does_not_follow_symlinked_store_components(self):
        capabilities = self.temp_root / "capabilities"
        capabilities.mkdir(parents=True)
        outside = self.temp_root.parent / "outside"
        outside.mkdir()
        link = capabilities / "skill"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symlinks are unavailable: {exc}")

        with self.assertRaises(CapabilityStoreError) as raised:
            self.store.install(self.bundle, self.digest)

        self.assertEqual(raised.exception.code, "STORE_STATE_INVALID")
        self.assertEqual(list(outside.rglob("*")), [])

    def test_install_does_not_follow_store_symlink_redirects_within_root(self):
        capabilities = self.temp_root / "capabilities"
        capabilities.mkdir(parents=True)
        redirect = self.temp_root / "redirect"
        redirect.mkdir()
        link = capabilities / "skill"
        try:
            link.symlink_to(redirect, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symlinks are unavailable: {exc}")

        with self.assertRaises(CapabilityStoreError) as raised:
            self.store.install(self.bundle, self.digest)

        self.assertEqual(raised.exception.code, "STORE_STATE_INVALID")
        self.assertEqual(list(redirect.rglob("*")), [])

    def test_storage_paths_do_not_alias_valid_capability_identifiers(self):
        first = self.store.install(self.bundle, self.digest)
        dotted_bundle = package_bytes(manifest=manifest_bytes(
            capability_id="skill:package-example.",
            name="Package Example Dotted",
        ))
        dotted = self.store.install(dotted_bundle, sha256(dotted_bundle))

        first_root = (self.temp_root / Path(first.relative_path)).parent.parent.resolve()
        dotted_root = (self.temp_root / Path(dotted.relative_path)).parent.parent.resolve()
        self.assertNotEqual(first_root, dotted_root)
        self.assertEqual(len(self.store.list_revisions(first.capability_id)), 1)
        self.assertEqual(len(self.store.list_revisions(dotted.capability_id)), 1)

    def test_publication_failures_are_retryable_and_leave_no_temporary_paths(self):
        real_replace = os.replace

        def fail_index_once(source, destination):
            if Path(destination) == self.temp_root / "index.json":
                raise OSError("injected index replacement failure")
            return real_replace(source, destination)

        with patch(
            "adapters.file_capability_store.os.replace",
            side_effect=fail_index_once,
        ):
            with self.assertRaises(CapabilityStoreError) as raised:
                self.store.install(self.bundle, self.digest)
        self.assertEqual(raised.exception.code, "STORE_IO_ERROR")
        self.assertFalse((self.temp_root / "index.json").exists())
        self.assertEqual(list(self.temp_root.rglob("*.tmp")), [])

        recovered = self.store.install(self.bundle, self.digest)
        self.assertEqual(recovered.revision_id, self.digest)
        self.assertEqual(self.store.list_revisions(recovered.capability_id), (recovered,))

    def test_revision_replacement_failure_cleans_staging_before_retry(self):
        real_replace = os.replace
        revision_path = self.temp_root / (
            f"capabilities/skill/package-example/revisions/{self.digest}"
        )

        def fail_revision_once(source, destination):
            if Path(destination) == revision_path:
                raise OSError("injected revision replacement failure")
            return real_replace(source, destination)

        with patch(
            "adapters.file_capability_store.os.replace",
            side_effect=fail_revision_once,
        ):
            with self.assertRaises(CapabilityStoreError) as raised:
                self.store.install(self.bundle, self.digest)
        self.assertEqual(raised.exception.code, "STORE_IO_ERROR")
        self.assertFalse(revision_path.exists())
        self.assertFalse((self.temp_root / "index.json").exists())
        self.assertEqual(list(self.temp_root.rglob("*.tmp")), [])

        recovered = self.store.install(self.bundle, self.digest)
        self.assertEqual(recovered.revision_id, self.digest)

    def test_all_allowlisted_licenses_install_as_verified_and_disabled(self):
        licenses = ("MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause")
        for index, license_name in enumerate(licenses):
            with self.subTest(license_name=license_name):
                root = self.temp_root / f"license-{index}"
                store = FileCapabilityStore(root)
                bundle = package_bytes(manifest=manifest_bytes(license=license_name))
                installed = store.install(bundle, sha256(bundle))
                self.assertEqual(installed.record.license_name, license_name)
                self.assertIs(installed.lifecycle, CapabilityLifecycle.DISABLED)

    def test_reloaded_revision_revalidates_verified_package_invariants(self):
        installed = self.store.install(self.bundle, self.digest)
        state_path = self.temp_root / Path(installed.relative_path) / "revision.json"
        original = json.loads(state_path.read_text(encoding="utf-8"))

        def remove_entrypoint_hash(value):
            value["file_sha256"].pop("payload/main.py")

        mutations = (
            lambda value: value.__setitem__("source_url", "http://example.com/package"),
            lambda value: value.__setitem__("license", "Proprietary"),
            lambda value: value.__setitem__("entrypoint", "payload/missing.py"),
            lambda value: value.__setitem__("compatibility", []),
            lambda value: value.__setitem__("provenance_status", "complete"),
            remove_entrypoint_hash,
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                value = json.loads(json.dumps(original))
                mutation(value)
                state_path.write_text(json.dumps(value), encoding="utf-8")

                with self.assertRaises(CapabilityStoreError) as raised:
                    FileCapabilityStore(self.temp_root).list_revisions(
                        installed.capability_id
                    )
                self.assertEqual(raised.exception.code, "STORE_STATE_INVALID")

        state_path.write_text(json.dumps(original), encoding="utf-8")

    def test_corrupt_index_shapes_fail_closed_with_stable_error(self):
        installed = self.store.install(self.bundle, self.digest)
        index_path = self.temp_root / "index.json"
        original = json.loads(index_path.read_text(encoding="utf-8"))

        def boolean_schema(value):
            value["schema_version"] = True

        def non_string_revision(value):
            entry = value["capabilities"][installed.capability_id]
            entry["selected_revision"] = {}
            entry["revisions"] = [{}]

        def capabilities_list(value):
            value["capabilities"] = []

        for mutation in (boolean_schema, non_string_revision, capabilities_list):
            with self.subTest(mutation=mutation):
                value = json.loads(json.dumps(original))
                mutation(value)
                index_path.write_text(json.dumps(value), encoding="utf-8")

                with self.assertRaises(CapabilityStoreError) as raised:
                    FileCapabilityStore(self.temp_root).list_revisions(
                        installed.capability_id
                    )
                self.assertEqual(raised.exception.code, "STORE_STATE_INVALID")

        index_path.write_text(json.dumps(original), encoding="utf-8")


class TestCapabilityPackageLimits(unittest.TestCase):
    def test_limits_require_positive_plain_integers_and_consistent_totals(self):
        invalid = (
            {"max_archive_bytes": 0},
            {"max_files": True},
            {"max_file_bytes": -1},
            {"max_uncompressed_bytes": "1024"},
            {"max_file_bytes": 2, "max_uncompressed_bytes": 1},
        )
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    CapabilityPackageLimits(**arguments)


if __name__ == "__main__":
    unittest.main()
