import unittest

from core.kernel.secret_redaction import REDACTED, redact_text


class TestSecretRedaction(unittest.TestCase):
    def test_masks_standalone_common_credential_shapes(self):
        credentials = (
            "".join(("sk-proj-", "abcdefghijklmnop", "qrstuvwxyz0123456789")),
            "".join(("ghp_", "ABCDEFGHIJKLMNOP", "QRSTUVWXYZ0123456789")),
            "".join((
                "xoxb-",
                "123456789012-",
                "123456789012-",
                "abcdefghijklmnopqrstuvwx",
            )),
            "".join(("AKIA", "IOSFODNN", "7EXAMPLE")),
            "".join(("AIza", "SyABCDEFGHIJKLM", "NOPQRSTUVWXYZ1234567")),
            "".join((
                "eyJhbGciOiJIUzI1NiJ9.",
                "eyJzdWIiOiIxMjM0NTY3ODkwIn0.",
                "signature123",
            )),
        )

        redacted = redact_text(" ".join(credentials))

        for credential in credentials:
            self.assertNotIn(credential, redacted)
        self.assertEqual(redacted.split(), [REDACTED] * len(credentials))

    def test_preserves_normal_standalone_identifiers(self):
        text = (
            "ticket-123 run-20260728 "
            "123e4567-e89b-12d3-a456-426614174000 ordinary-query"
        )

        self.assertEqual(redact_text(text), text)

    def test_existing_assignment_bearer_and_private_key_redaction_remains(self):
        text = (
            "api_key=assigned-secret Authorization: Bearer bearer-secret\n"
            "-----BEGIN PRIVATE KEY-----\nprivate-secret\n"
            "-----END PRIVATE KEY-----"
        )

        redacted = redact_text(text)

        self.assertNotIn("assigned-secret", redacted)
        self.assertNotIn("bearer-secret", redacted)
        self.assertNotIn("private-secret", redacted)


if __name__ == "__main__":
    unittest.main()
