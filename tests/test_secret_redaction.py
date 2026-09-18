import unittest

from core.kernel.secret_redaction import REDACTED, redact_text


class TestSecretRedaction(unittest.TestCase):
    def test_masks_standalone_common_credential_shapes(self):
        credentials = (
            "sk-" + "proj-abcdefghijklmnopqrstuvwxyz0123456789",
            "ghp" + "_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            "xox" + "b-123456789012-123456789012-abcdefghijklmnopqrstuvwx",
            "AKIA" + "IOSFODNN7EXAMPLE",
            "AIza" + "SyABCDEFGHIJKLMNOPQRSTUVWXYZ1234567",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0." + "signature123",
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
