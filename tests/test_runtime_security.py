"""Secure-by-default runtime boundary tests."""

import os
import unittest
from unittest.mock import patch

from core.kernel.runtime_security import (
    DEFAULT_ALLOWED_ORIGINS,
    configured_allowed_origins,
    terminal_access_enabled,
    terminal_request_is_authorized,
)
from core.kernel.terminal_policy import (
    TerminalPolicyError,
    validate_terminal_operation,
)


class TestRuntimeSecurity(unittest.TestCase):
    def test_defaults_are_loopback_origins_and_terminal_is_disabled(self):
        with patch.dict(
            os.environ,
            {
                "JARVIS_ALLOWED_ORIGINS": "",
                "JARVIS_TERMINAL_ENABLED": "",
                "JARVIS_TERMINAL_TOKEN": "",
            },
        ):
            self.assertEqual(configured_allowed_origins(), list(DEFAULT_ALLOWED_ORIGINS))
            self.assertFalse(terminal_access_enabled())

    def test_terminal_requires_explicit_flag_and_nonempty_token(self):
        with patch.dict(
            os.environ,
            {"JARVIS_TERMINAL_ENABLED": "true", "JARVIS_TERMINAL_TOKEN": ""},
        ):
            self.assertFalse(terminal_access_enabled())

        with patch.dict(
            os.environ,
            {"JARVIS_TERMINAL_ENABLED": "true", "JARVIS_TERMINAL_TOKEN": "secret"},
        ):
            self.assertTrue(terminal_access_enabled())
            self.assertTrue(terminal_request_is_authorized("secret"))
            self.assertFalse(terminal_request_is_authorized("wrong"))


class TestTerminalPolicy(unittest.TestCase):
    def test_accepts_only_documented_read_only_operations(self):
        self.assertEqual(
            validate_terminal_operation("echo", ["diagnostic"], 5),
            ("echo", ["diagnostic"], 5),
        )
        self.assertEqual(validate_terminal_operation("pwd", [], 5), ("pwd", [], 5))

    def test_rejects_interpreters_downloaders_and_argument_bearing_diagnostics(self):
        for command, args in (
            ("python", ["-c", "print(1)"]),
            ("pip", ["install", "anything"]),
            ("curl", ["http://localhost"]),
            ("pwd", ["unexpected"]),
        ):
            with self.subTest(command=command):
                with self.assertRaises(TerminalPolicyError):
                    validate_terminal_operation(command, args, 5)

    def test_rejects_unbounded_arguments_and_timeouts(self):
        with self.assertRaises(TerminalPolicyError):
            validate_terminal_operation("echo", ["x"] * 17, 5)
        with self.assertRaises(TerminalPolicyError):
            validate_terminal_operation("echo", ["x"], 31)
