import unittest

from core.brain.resume_document import ResumeSections, render_resume_document
from core.contracts.run_state import RunState
from core.kernel.secret_redaction import redact_text, redact_value


class TestResumeDocument(unittest.TestCase):
    def make_state(self):
        return RunState.new(
            run_id="run-20260716-043000",
            goal="Complete Phase A",
            current_stage="A",
            base_commit="a" * 40,
            active_branch="codex/iteration-101-core-contracts",
            next_action="Run focused recovery tests",
        )

    def test_redaction_masks_structured_and_free_text_secrets(self):
        self.assertEqual(redact_value("abc", key="api_token"), "[REDACTED]")
        self.assertEqual(
            redact_value({"nested": {"private_key": "pem"}}),
            {"nested": {"private_key": "[REDACTED]"}},
        )
        text = redact_text(
            "Authorization: Bearer secret-value password=hunter2 "
            "run_id=run-20260716-043000 trace_id=trace-1"
        )
        self.assertNotIn("secret-value", text)
        self.assertNotIn("hunter2", text)
        self.assertIn("run-20260716-043000", text)
        self.assertIn("trace-1", text)

    def test_resume_has_machine_header_and_all_fixed_sections(self):
        state = self.make_state()
        document = render_resume_document(
            state,
            ResumeSections(
                confirmed_decisions=("Keep local-first behavior",),
                risks=("token=must-not-leak",),
            ),
        )

        for heading in (
            "## Current Goal",
            "## Confirmed Decisions",
            "## Completed Work",
            "## Files and Git State",
            "## Verification",
            "## Agent State",
            "## Downloaded Resources",
            "## Risks and Approvals",
            "## Next Step",
            "## Do Not Repeat",
        ):
            self.assertIn(heading, document)
        self.assertTrue(document.startswith("schema_version: 1\n"))
        self.assertIn("status: planning", document)
        self.assertIn("next_command: \n", document)
        self.assertNotIn("must-not-leak", document)

    def test_render_is_deterministic_and_marks_empty_sections(self):
        state = self.make_state()
        sections = ResumeSections()

        first = render_resume_document(state, sections)
        second = render_resume_document(state, sections)

        self.assertEqual(first, second)
        self.assertEqual(first.count("- None recorded."), 8)
        self.assertIn("- Complete Phase A", first)
        self.assertIn("- Run focused recovery tests", first)


if __name__ == "__main__":
    unittest.main()
