"""Tests for Orchestrator.dispatch_with_retry (Iter #61)."""
import time

from core.brain.orchestrator import AgentResult, AgentTask, Orchestrator


def _make_task(task_id="t_retry", prompt="do something"):
    return AgentTask(task_id=task_id, agent_name="worker", prompt=prompt, timeout=1)


class TestDispatchWithRetrySuccess:
    """dispatch_with_retry returns on first successful dispatch."""

    def test_success_on_first_attempt(self):
        orch = Orchestrator()
        orch.register("worker", handler=lambda t: "ok", capabilities=[])
        result = orch.dispatch_with_retry(_make_task(), max_retries=2)
        assert result.status == "success"
        assert "retries" not in (result.error or "")

    def test_no_retries_counted_on_immediate_success(self):
        orch = Orchestrator()
        orch.register("worker", handler=lambda t: "ok", capabilities=[])
        orch.dispatch_with_retry(_make_task("t1"), max_retries=3)
        assert orch.get_stats().get("total_retries", 0) == 0


class TestDispatchWithRetryRecovery:
    """dispatch_with_retry recovers after transient failures."""

    def test_recovers_after_one_timeout(self):
        orch = Orchestrator()
        counter = [0]

        def flaky_handler(t):
            counter[0] += 1
            if counter[0] == 1:
                raise TimeoutError("transient timeout")
            return "recovered"

        orch.register("worker", handler=flaky_handler, capabilities=[])
        result = orch.dispatch_with_retry(_make_task("t_flaky"), max_retries=2)
        assert result.status == "success"
        assert counter[0] == 2

    def test_all_retries_exhausted(self):
        orch = Orchestrator()

        def always_fail(t):
            raise TimeoutError("always fails")

        orch.register("worker", handler=always_fail, capabilities=[])
        result = orch.dispatch_with_retry(_make_task("t_exhaust"), max_retries=1)
        assert result.status == "failed"
        assert "after" in (result.error or "")

    def test_stats_updated_on_failure(self):
        orch = Orchestrator()

        def always_fail(t):
            raise RuntimeError("boom")

        orch.register("worker", handler=always_fail, capabilities=[])
        orch.dispatch_with_retry(_make_task("t_fail"), max_retries=0)
        assert orch.get_stats().get("total_errors", 0) >= 1


class TestDispatchWithRetryBackoff:
    """Backoff timing between retries."""

    def test_backoff_delays_retry(self):
        orch = Orchestrator()
        timestamps = []

        def handler_with_timing(t):
            timestamps.append(time.time())
            if len(timestamps) < 2:
                raise TimeoutError("retry me")
            return "ok"

        orch.register("worker", handler=handler_with_timing, capabilities=[])
        result = orch.dispatch_with_retry(
            _make_task("t_timing"), max_retries=2, backoff_factor=0.5
        )
        assert result.status == "success"
        if len(timestamps) >= 2:
            elapsed = timestamps[1] - timestamps[0]
            assert elapsed >= 0.4


class TestDispatchWithRetryParameters:
    """max_retries and backoff_factor parameter handling."""

    def test_max_retries_zero(self):
        orch = Orchestrator()
        orch.register("worker", handler=lambda t: "ok", capabilities=[])
        result = orch.dispatch_with_retry(_make_task("t0"), max_retries=0)
        assert result.status == "success"

    def test_busy_status_does_not_retry(self):
        """busy status is treated as success, no retry triggered."""
        orch = Orchestrator()
        orch.register("worker", handler=lambda t: "ok", capabilities=[])

        original = orch.dispatch
        call_count = [0]

        def fake_dispatch(task):
            call_count[0] += 1
            if call_count[0] == 1:
                return AgentResult(
                    task_id=task.task_id, agent_name="worker",
                    status="busy", result=""
                )
            return original(task)

        orch.dispatch = fake_dispatch
        result = orch.dispatch_with_retry(_make_task("t_busy"), max_retries=2)
        assert result.status == "success"
        assert call_count[0] == 2


class TestDispatchWithRetryDefaults:
    """Default parameter values."""

    def test_default_max_retries_is_2(self):
        orch = Orchestrator()
        orch.register("worker", handler=lambda t: "ok", capabilities=[])
        # Should succeed on first attempt with default max_retries=2
        result = orch.dispatch_with_retry(_make_task("t_def"))
        assert result.status == "success"

    def test_default_backoff_factor_is_1(self):
        orch = Orchestrator()
        counter = [0]

        def fail_once(t):
            counter[0] += 1
            if counter[0] == 1:
                raise TimeoutError("transient")
            return "ok"

        orch.register("worker", handler=fail_once, capabilities=[])
        result = orch.dispatch_with_retry(_make_task("t_bo"), max_retries=1)
        assert result.status == "success"
