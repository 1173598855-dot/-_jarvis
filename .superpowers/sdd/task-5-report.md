# Task 5 Report: SDK Coordinator And First-Party Plugin Migration

## Changes

- Replaced Core-process Plugin imports with `SubprocessPluginRuntime` lifecycle coordination through `PluginBroker`.
- Added parent-owned Worker generation allocation, direct-child/non-symlink root validation, bounded runtime failures, Worker PID metadata, and best-effort shutdown/reap.
- Kept legacy runtime values enumerable but non-executable; `python_worker` is the supported runtime.
- Converted both first-party Plugin manifests to `python_worker`; their activation functions only emit `plugin.activated`.
- Added Worker lifecycle, identity, isolation, shutdown, installation, and aggregate-suite guards.

## RED Evidence

The worktree-local command could not start because `.\\venv\\Scripts\\python.exe` is absent from the worktree. Running the same modules with the project virtual environment before implementation produced the expected RED result: 135 tests ran with 3 failures and 7 errors. The failures covered absent `RuntimeType.PYTHON_WORKER`, unsupported `PluginManager(event_bus=...)`, executable `native` content, and the old Core-process API behavior.

## GREEN Evidence

```powershell
& 'C:\\GitHub\\贾维斯\\venv\\Scripts\\python.exe' -m unittest tests.test_plugin_sdk tests.test_plugin_sdk_extended tests.test_plugin_sdk_extended_v2 tests.test_plugin_installation tests.test_plugin_broker -v
git diff --check
```

Result: 152 tests passed; `git diff --check` completed without whitespace errors.

## Commit

`feat(plugins): run first-party plugins in workers` (the single Task 5 commit containing this report).

## Residual Concerns

- `tests.test_run_all_coverage` registers the new aggregate guards, but its smoke test currently fails only because the Iteration 140 changelog/report still records 513 aggregate tests while the current aggregate suite is 552. Task 5 does not modify user documentation or historical audit metrics.
- The project virtual environment is only available from `C:\\GitHub\\贾维斯\\venv`, not the task worktree, so focused tests used that interpreter against the worktree sources.
