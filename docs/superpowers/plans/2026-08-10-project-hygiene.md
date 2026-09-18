# Project Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove reproducible local artifacts and retire stale root-level report snapshots while preserving `docs/reports/` as the single authoritative report location.

**Architecture:** Treat documentation canonicalization as a tested repository contract and local artifact deletion as a separate, explicitly bounded hygiene operation. All destructive filesystem work resolves literal targets beneath the repository root, rejects reparse points, and leaves dependencies, memory, and tool state untouched.

**Tech Stack:** Git, PowerShell, Python `unittest`, Markdown

## Global Constraints

- Preserve `venv/`, `frontend/node_modules/`, `.auto-memory/`, `.agents/`, `.compound-engineering/`, `.superpowers/`, `.worktrees/`, capability stores, and all unlisted untracked paths.
- Delete only the ignored artifacts and two tracked root reports enumerated in the approved design.
- Keep `docs/reports/PROJECT_ANALYSIS.md`, `docs/reports/GITHUB_LEARNING_REPORT.md`, and `docs/reports/README.md` unchanged unless validation proves a broken link.
- Do not change application code, API contracts, dependencies, architecture, or runtime behavior.
- Do not push commits to a remote.

---

### Task 1: Enforce the Canonical Report Location

**Files:**
- Modify: `tests/test_readme.py`
- Delete: `PROJECT_ANALYSIS.md`
- Delete: `GITHUB_LEARNING_REPORT.md`
- Verify: `docs/reports/README.md`
- Verify: `docs/reports/PROJECT_ANALYSIS.md`
- Verify: `docs/reports/GITHUB_LEARNING_REPORT.md`

**Interfaces:**
- Consumes: the existing `ROOT = Path(__file__).parent.parent` repository locator in `tests/test_readme.py`
- Produces: `TestReadme.test_reports_have_one_canonical_home`, a guardrail that requires both maintained reports under `docs/reports/` and rejects duplicate root snapshots

- [ ] **Step 1: Verify the tracked worktree and active references**

Run:

```powershell
git status --short --branch
rg -n "PROJECT_ANALYSIS\.md|GITHUB_LEARNING_REPORT\.md" README.md AGENTS.md CLAUDE.md docs/SETUP.md docs/DEVELOPMENT_GUIDE.md docs/protocols skills tests
```

Expected:

- `git status` reports no tracked changes.
- Every active documentation reference points to `docs/reports/PROJECT_ANALYSIS.md`, `docs/reports/GITHUB_LEARNING_REPORT.md`, or `docs/reports/README.md`.
- No startup, development, protocol, skill, or test file treats either root-level snapshot as authoritative.

- [ ] **Step 2: Add a failing canonical-location guardrail**

Add this method to `TestReadme` in `tests/test_readme.py`:

```python
    def test_reports_have_one_canonical_home(self):
        reports = ROOT / "docs" / "reports"

        self.assertTrue((reports / "PROJECT_ANALYSIS.md").is_file())
        self.assertTrue((reports / "GITHUB_LEARNING_REPORT.md").is_file())
        self.assertFalse((ROOT / "PROJECT_ANALYSIS.md").exists())
        self.assertFalse((ROOT / "GITHUB_LEARNING_REPORT.md").exists())
```

- [ ] **Step 3: Run the guardrail and verify that it fails for the intended reason**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_readme.TestReadme.test_reports_have_one_canonical_home -v
```

Expected: `FAIL`; the first false assertion reports that `PROJECT_ANALYSIS.md` exists at the repository root.

- [ ] **Step 4: Remove only the two tracked stale snapshots**

Use `apply_patch` with these exact deletion directives:

```text
*** Begin Patch
*** Delete File: C:\GitHub\贾维斯\PROJECT_ANALYSIS.md
*** Delete File: C:\GitHub\贾维斯\GITHUB_LEARNING_REPORT.md
*** End Patch
```

Expected: Git records two tracked deletions; the maintained files under `docs/reports/` remain present.

- [ ] **Step 5: Run the canonical report and documentation tests**

Run:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_readme tests.test_docs_setup tests.test_iteration_ledger -v
```

Expected: all tests pass, including `test_reports_have_one_canonical_home`.

- [ ] **Step 6: Verify every local Markdown target in the report index**

Run:

```powershell
$indexPath = (Resolve-Path -LiteralPath 'docs\reports\README.md').Path
$indexRoot = Split-Path -Parent $indexPath
$text = Get-Content -Raw -Encoding UTF8 -LiteralPath $indexPath
$links = [regex]::Matches($text, '\[[^\]]+\]\(([^)]+\.md)\)')
foreach ($link in $links) {
    $target = [IO.Path]::GetFullPath((Join-Path $indexRoot $link.Groups[1].Value))
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
        throw "Broken report link: $($link.Groups[1].Value)"
    }
}
Write-Output "REPORT_LINKS_OK=$($links.Count)"
```

Expected: `REPORT_LINKS_OK=15` and no exception.

- [ ] **Step 7: Validate and commit the canonicalization**

Run:

```powershell
git diff --check
git status --short
git diff --stat
git add -- tests/test_readme.py PROJECT_ANALYSIS.md GITHUB_LEARNING_REPORT.md
git commit -m "chore: canonicalize project reports"
```

Expected before the commit:

```text
 D GITHUB_LEARNING_REPORT.md
 D PROJECT_ANALYSIS.md
 M tests/test_readme.py
```

Expected commit: one test modification and two report deletions; no canonical `docs/reports/` file is modified.

---

### Task 2: Remove Reproducible Local Artifacts

**Files:**
- Delete locally if present: `.test-perf/`
- Delete locally if present: `.test-pip-download/`
- Delete locally if present: `.test-runtime/`
- Delete locally if present: `.test-python-discovery.txt`
- Delete locally if present: `frontend/debug.log`
- Delete locally if present: `frontend/dist/`
- Delete locally if present: `__pycache__/` directories below `src/`, `tests/`, `scripts/`, `plugins/event-logger/`, and `plugins/plugin-template/`
- Preserve: all paths named in the global constraints

**Interfaces:**
- Consumes: repository-relative literal targets and existing `.gitignore` rules
- Produces: a clean local workspace with no listed reproducible artifact remaining; no tracked file changes

- [ ] **Step 1: Capture preservation evidence and verify ignore coverage**

Run:

```powershell
$preserved = @(
    'venv',
    'frontend\node_modules',
    '.auto-memory',
    '.agents',
    '.compound-engineering',
    '.superpowers',
    '.worktrees'
)
foreach ($relative in $preserved) {
    if (-not (Test-Path -LiteralPath $relative)) {
        throw "Expected preserved path is missing before cleanup: $relative"
    }
}
Write-Output 'PRESERVED_PATHS_PRESENT=yes'

$ignoredTargets = @(
    '.test-perf',
    '.test-pip-download',
    '.test-runtime',
    '.test-python-discovery.txt',
    'frontend/debug.log',
    'frontend/dist'
)
foreach ($relative in $ignoredTargets) {
    git check-ignore -q -- $relative
    if ($LASTEXITCODE -ne 0) {
        throw "Target is not ignored: $relative"
    }
}
Write-Output 'IGNORE_COVERAGE_OK=yes'
```

Expected: `PRESERVED_PATHS_PRESENT=yes` and `IGNORE_COVERAGE_OK=yes`.

- [ ] **Step 2: Delete the explicit direct targets with root containment checks**

Run this as one PowerShell operation:

```powershell
$repoRoot = (Resolve-Path -LiteralPath '.').Path.TrimEnd('\')
$prefix = $repoRoot + '\'
$targets = @(
    '.test-perf',
    '.test-pip-download',
    '.test-runtime',
    '.test-python-discovery.txt',
    'frontend\debug.log',
    'frontend\dist'
)
foreach ($relative in $targets) {
    if (-not (Test-Path -LiteralPath $relative)) {
        continue
    }
    $item = Get-Item -Force -LiteralPath $relative
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing reparse-point target: $relative"
    }
    $resolved = (Resolve-Path -LiteralPath $relative).Path
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Target escaped repository root: $relative"
    }
    Remove-Item -Force -Recurse -LiteralPath $resolved
}
Write-Output 'DIRECT_ARTIFACTS_REMOVED=yes'
```

Expected: `DIRECT_ARTIFACTS_REMOVED=yes`; only listed targets are removed.

- [ ] **Step 3: Delete Python bytecode caches below explicit source roots**

Run this as one PowerShell operation:

```powershell
$repoRoot = (Resolve-Path -LiteralPath '.').Path.TrimEnd('\')
$prefix = $repoRoot + '\'
$cacheRoots = @(
    'src',
    'tests',
    'scripts',
    'plugins\event-logger',
    'plugins\plugin-template'
)
$caches = foreach ($relativeRoot in $cacheRoots) {
    Get-ChildItem -Force -Directory -Filter '__pycache__' -Recurse -LiteralPath $relativeRoot
}
foreach ($cache in ($caches | Sort-Object FullName -Descending)) {
    if (($cache.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing reparse-point cache: $($cache.FullName)"
    }
    $resolved = (Resolve-Path -LiteralPath $cache.FullName).Path
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Cache escaped repository root: $resolved"
    }
    git check-ignore -q -- $resolved
    if ($LASTEXITCODE -ne 0) {
        throw "Cache is not ignored: $resolved"
    }
    Remove-Item -Force -Recurse -LiteralPath $resolved
}
Write-Output "PYTHON_CACHES_REMOVED=$(@($caches).Count)"
```

Expected: a non-negative `PYTHON_CACHES_REMOVED` count and no exception.

- [ ] **Step 4: Verify cleanup boundaries and final repository state**

Run:

```powershell
$mustBeAbsent = @(
    '.test-perf',
    '.test-pip-download',
    '.test-runtime',
    '.test-python-discovery.txt',
    'frontend\debug.log',
    'frontend\dist',
    'PROJECT_ANALYSIS.md',
    'GITHUB_LEARNING_REPORT.md'
)
foreach ($relative in $mustBeAbsent) {
    if (Test-Path -LiteralPath $relative) {
        throw "Cleanup target still exists: $relative"
    }
}

$cacheRoots = @(
    'src',
    'tests',
    'scripts',
    'plugins\event-logger',
    'plugins\plugin-template'
)
$remainingCaches = @(
    Get-ChildItem -Force -Directory -Filter '__pycache__' -Recurse -LiteralPath $cacheRoots
)
if ($remainingCaches.Count -ne 0) {
    throw "Python caches remain: $($remainingCaches.Count)"
}

foreach ($relative in @(
    'venv',
    'frontend\node_modules',
    '.auto-memory',
    '.agents',
    '.compound-engineering',
    '.superpowers',
    '.worktrees'
)) {
    if (-not (Test-Path -LiteralPath $relative)) {
        throw "Preserved path was removed: $relative"
    }
}

git diff --check
git status --short --branch
git log -2 --oneline
```

Expected:

- no cleanup target or in-scope `__pycache__/` remains;
- every previously existing preserved path still exists;
- `git diff --check` succeeds;
- the tracked worktree is clean;
- the latest implementation commit is `chore: canonicalize project reports`;
- `main` remains ahead of `origin/main`; nothing is pushed.
