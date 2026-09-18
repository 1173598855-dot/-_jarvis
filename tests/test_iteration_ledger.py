"""Iteration ledger consistency guardrails."""

import re
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "tests"))

CHANGELOG = ROOT / "CHANGELOG.md"
REPORTS = ROOT / "docs" / "reports"


def changelog_text():
    return CHANGELOG.read_text(encoding="utf-8")


def latest_changelog_entry():
    match = re.search(r"^## Iteration #(\d+) - ", changelog_text(), re.MULTILINE)
    if not match:
        raise AssertionError("CHANGELOG.md must start with an iteration entry")
    return match


def latest_changelog_iteration():
    match = latest_changelog_entry()
    return int(match.group(1))


def latest_changelog_date():
    match = re.search(r"^## Iteration #\d+ - (\d{4}-\d{2}-\d{2})$", changelog_text(), re.MULTILINE)
    if not match:
        raise AssertionError("CHANGELOG.md latest iteration entry must declare a date")
    return match.group(1)


def latest_changelog_status():
    match = re.search(r"^\*\*Status\*\*: ([A-Za-z]+)$", changelog_text(), re.MULTILINE)
    if not match:
        raise AssertionError("CHANGELOG.md latest iteration entry must declare a status")
    return match.group(1)


def latest_changelog_files_changed():
    entry_match = re.search(
        r"^## Iteration #\d+ - .+?^---$",
        changelog_text(),
        re.MULTILINE | re.DOTALL,
    )
    if not entry_match:
        raise AssertionError("CHANGELOG.md latest iteration entry must be delimited")

    files_match = re.search(
        r"^### Files Changed$(?P<body>.+?)^---$",
        entry_match.group(0),
        re.MULTILINE | re.DOTALL,
    )
    if not files_match:
        raise AssertionError("CHANGELOG.md latest iteration entry must list files changed")

    return re.findall(r"^- `([^`]+)`$", files_match.group("body"), re.MULTILINE)


def latest_changelog_run_all_metrics():
    entry_match = re.search(
        r"^## Iteration #\d+ - .+?^---$",
        changelog_text(),
        re.MULTILINE | re.DOTALL,
    )
    if not entry_match:
        raise AssertionError("CHANGELOG.md latest iteration entry must be delimited")

    metric_match = re.search(
        r"^- `python tests/run_all\.py`: (\d+) total \((\d+) passed, (\d+) skipped\)$",
        entry_match.group(0),
        re.MULTILINE,
    )
    if not metric_match:
        raise AssertionError(
            "CHANGELOG.md latest iteration entry must record run_all total, passed, and skipped counts"
        )

    return {
        "total": int(metric_match.group(1)),
        "passed": int(metric_match.group(2)),
        "skipped": int(metric_match.group(3)),
    }


def aggregate_suite_test_count():
    main_module = sys.modules.get("__main__")
    if main_module and hasattr(main_module, "build_aggregate_suite"):
        return main_module.build_aggregate_suite().countTestCases()

    import run_all
    return run_all.build_aggregate_suite().countTestCases()


def audit_report_iterations():
    iterations = []
    for path in REPORTS.glob("AUDIT_REPORT_*.md"):
        match = re.fullmatch(r"AUDIT_REPORT_(\d+)\.md", path.name)
        if match:
            iterations.append(int(match.group(1)))
    return iterations


def latest_audit_report_iteration():
    iterations = audit_report_iterations()
    if not iterations:
        raise AssertionError("docs/reports must contain at least one AUDIT_REPORT_N.md")
    return max(iterations)


def audit_report_metadata(iteration):
    path = REPORTS / f"AUDIT_REPORT_{iteration}.md"
    text = path.read_text(encoding="utf-8")

    h1_match = re.search(r"^# (AUDIT_REPORT_\d+\.md)$", text, re.MULTILINE)
    iteration_match = re.search(r"^\*\*Iteration\*\*: #(\d+)$", text, re.MULTILINE)
    date_match = re.search(r"^\*\*Date\*\*: (\d{4}-\d{2}-\d{2})$", text, re.MULTILINE)
    status_match = re.search(r"^\*\*Status\*\*: ([A-Za-z]+)$", text, re.MULTILINE)

    if not h1_match:
        raise AssertionError(f"{path.name} must start with a matching H1")
    if not iteration_match:
        raise AssertionError(f"{path.name} must declare an iteration")
    if not date_match:
        raise AssertionError(f"{path.name} must declare a date")
    if not status_match:
        raise AssertionError(f"{path.name} must declare a status")

    return {
        "h1": h1_match.group(1),
        "iteration": int(iteration_match.group(1)),
        "date": date_match.group(1),
        "status": status_match.group(1),
    }


def audit_report_run_all_metrics(iteration):
    path = REPORTS / f"AUDIT_REPORT_{iteration}.md"
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r"^\| `python tests/run_all\.py` \| Total: (\d+); passed: (\d+); skipped: (\d+) \|$",
        text,
        re.MULTILINE,
    )
    if not match:
        raise AssertionError(
            f"{path.name} must record run_all total, passed, and skipped counts"
        )
    return {
        "total": int(match.group(1)),
        "passed": int(match.group(2)),
        "skipped": int(match.group(3)),
    }


class TestIterationLedger(unittest.TestCase):
    def _changelog_text(self):
        return changelog_text()

    def _latest_changelog_iteration(self):
        return latest_changelog_iteration()

    def _report_iterations(self):
        return audit_report_iterations()

    def test_latest_changelog_iteration_has_audit_report(self):
        latest = self._latest_changelog_iteration()

        self.assertTrue((REPORTS / f"AUDIT_REPORT_{latest}.md").exists())

    def test_latest_audit_report_is_recorded_in_changelog(self):
        latest_report = latest_audit_report_iteration()
        text = self._changelog_text()

        self.assertIn(f"## Iteration #{latest_report} - ", text)
        self.assertIn(f"docs/reports/AUDIT_REPORT_{latest_report}.md", text)

    def test_latest_changelog_iteration_matches_latest_audit_report(self):
        self.assertEqual(latest_changelog_iteration(), latest_audit_report_iteration())

    def test_latest_audit_report_metadata_matches_filename(self):
        latest_report = latest_audit_report_iteration()
        metadata = audit_report_metadata(latest_report)

        self.assertEqual(metadata["h1"], f"AUDIT_REPORT_{latest_report}.md")
        self.assertEqual(metadata["iteration"], latest_report)

    def test_latest_audit_report_status_and_date_are_declared(self):
        latest_report = latest_audit_report_iteration()
        metadata = audit_report_metadata(latest_report)

        self.assertIsInstance(date.fromisoformat(metadata["date"]), date)
        self.assertEqual(metadata["status"], "Complete")

    def test_latest_changelog_date_matches_latest_audit_report_date(self):
        metadata = audit_report_metadata(latest_audit_report_iteration())

        self.assertEqual(latest_changelog_date(), metadata["date"])

    def test_latest_changelog_status_matches_latest_audit_report_status(self):
        metadata = audit_report_metadata(latest_audit_report_iteration())

        self.assertEqual(latest_changelog_status(), metadata["status"])

    def test_latest_changelog_files_changed_records_latest_audit_report(self):
        latest_report = latest_audit_report_iteration()

        self.assertIn(
            f"docs/reports/AUDIT_REPORT_{latest_report}.md",
            latest_changelog_files_changed(),
        )

    def test_latest_changelog_run_all_metric_matches_aggregate_suite_size(self):
        metrics = latest_changelog_run_all_metrics()

        self.assertEqual(metrics["total"], aggregate_suite_test_count())
        self.assertEqual(metrics["passed"] + metrics["skipped"], metrics["total"])

    def test_latest_audit_report_run_all_metric_matches_aggregate_suite_size(self):
        latest_report = latest_audit_report_iteration()
        metrics = audit_report_run_all_metrics(latest_report)

        self.assertEqual(metrics["total"], aggregate_suite_test_count())
        self.assertEqual(metrics["passed"] + metrics["skipped"], metrics["total"])


def run_all_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestIterationLedger)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
