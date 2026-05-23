# Bug Report

## 1. Summary

HITL validation on branch `feature/operator_cli_rcp` is blocked because the active repository `.venv` does not import the editable `src` package. The active venv contains a correct editable-install `.pth` file, but macOS file flags mark the `.pth` files as `hidden`, so Python's `site` startup intentionally skips them. This prevents `/Users/mjseno/Documents/Development/2026_fortfolio_projects/release-confidence-platform/src` from being added to `sys.path` and causes `.venv/bin/rcp --help` and `.venv/bin/python scripts/rcp.py --help` to fail with `ModuleNotFoundError: No module named 'release_confidence_platform'`.

## 2. Investigation Context

- Source of report: HITL validation retest / QA blocking evidence.
- Branch context: `feature/operator_cli_rcp`; investigation performed in the active branch, no new branch created.
- Related workflow: Operator CLI installed command and script shim in the active repository `.venv` after src-layout packaging remediation.
- Failing commands reported by QA:
  - `.venv/bin/rcp --help`
  - `.venv/bin/python scripts/rcp.py --help`
- Passing controls reported by QA:
  - static src-layout / `pyproject.toml` inspection
  - clean editable install
  - clean non-editable install
  - clean editable script shim
  - unit/contract tests and ruff

## 3. Observed Symptoms

QA-provided active `.venv` failures:

```text
.venv/bin/rcp --help
ModuleNotFoundError: No module named 'release_confidence_platform'
```

```text
.venv/bin/python scripts/rcp.py --help
ModuleNotFoundError: No module named 'release_confidence_platform'
```

Expected behavior: after successful `pip install -e .`, the active venv should process the editable `.pth`, place the repository `src` directory on `sys.path`, and allow both installed `rcp` and the script shim to import `release_confidence_platform` without `PYTHONPATH`.

Observed interpreter state from the active `.venv`:

```text
exe /Users/mjseno/Documents/Development/2026_fortfolio_projects/release-confidence-platform/.venv/bin/python
prefix /Users/mjseno/Documents/Development/2026_fortfolio_projects/release-confidence-platform/.venv
no_site 0
ignore_environment 0
safe_path False
sitepackages ['/Users/mjseno/Documents/Development/2026_fortfolio_projects/release-confidence-platform/.venv/lib/python3.11/site-packages']
path ['', '/opt/homebrew/Cellar/python@3.11/3.11.11/Frameworks/Python.framework/Versions/3.11/lib/python311.zip', '/opt/homebrew/Cellar/python@3.11/3.11.11/Frameworks/Python.framework/Versions/3.11/lib/python3.11', '/opt/homebrew/Cellar/python@3.11/3.11.11/Frameworks/Python.framework/Versions/3.11/lib/python3.11/lib-dynload', '/Users/mjseno/Documents/Development/2026_fortfolio_projects/release-confidence-platform/.venv/lib/python3.11/site-packages', '/opt/homebrew/opt/python-tk@3.11/libexec']
ModuleNotFoundError: No module named 'release_confidence_platform'
```

The key symptom is that `src` is absent from `sys.path` even though editable metadata exists.

## 4. Evidence Collected

Files and artifacts inspected:

- `pyproject.toml`
- `src/release_confidence_platform/**`
- `.venv/pyvenv.cfg`
- `.venv/bin/rcp`
- `.venv/lib/python3.11/site-packages/__editable__.release_confidence_platform-0.0.0.pth`
- `.venv/lib/python3.11/site-packages/distutils-precedence.pth`
- `.venv/lib/python3.11/site-packages/release_confidence_platform-0.0.0.dist-info/direct_url.json`
- `.venv/lib/python3.11/site-packages/release_confidence_platform-0.0.0.dist-info/RECORD`
- `.venv/lib/python3.11/site-packages/release_confidence_platform-0.0.0.dist-info/top_level.txt`
- `.venv/lib/python3.11/site-packages/release_confidence_platform-0.0.0.dist-info/entry_points.txt`
- active Python `sys.flags`, `site` configuration, and verbose startup output
- macOS file flags for `.venv` and `.pth` files

Packaging evidence:

- `pyproject.toml:24-31` uses corrected `src` layout:

```toml
[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]
include = ["release_confidence_platform*"]
exclude = ["tests*", "docs*", "apps*"]
namespaces = false
```

- `src/release_confidence_platform/` exists and contains `operator_cli/main.py` plus the package modules.
- `.venv/bin/rcp:3` imports the expected entry point:

```python
from release_confidence_platform.operator_cli.main import main
```

Editable install artifact evidence:

- `.venv/lib/python3.11/site-packages/__editable__.release_confidence_platform-0.0.0.pth` contains the correct absolute source path:

```text
/Users/mjseno/Documents/Development/2026_fortfolio_projects/release-confidence-platform/src
```

- `direct_url.json` confirms an editable install from the active repository:

```json
{"dir_info": {"editable": true}, "url": "file:///Users/mjseno/Documents/Development/2026_fortfolio_projects/release-confidence-platform"}
```

- `top_level.txt` confirms the installed top-level package name:

```text
release_confidence_platform
```

- `entry_points.txt` confirms the console script target:

```text
[console_scripts]
rcp = release_confidence_platform.operator_cli.main:main
```

Python/site configuration evidence:

- `sys.flags.no_site == 0`; site processing is not disabled with `-S`.
- `sys.flags.ignore_environment == 0`; environment is not ignored with `-E`.
- `sys.flags.safe_path == False`; safe path mode is not the cause.
- `site.getsitepackages()` includes the active venv site-packages path.

macOS hidden-flag evidence:

```text
.venv/lib/python3.11/site-packages/__editable__.release_confidence_platform-0.0.0.pth flags 32832 hidden True
.venv/lib/python3.11/site-packages/distutils-precedence.pth flags 32832 hidden True
```

`ls -ldO` confirms the `hidden` flag is present on the venv tree and the `.pth` files:

```text
drwxr-xr-x   6 mjseno  staff  hidden  ... .venv
drwxr-xr-x  49 mjseno  staff  hidden  ... .venv/lib/python3.11/site-packages
-rw-r--r--   1 mjseno  staff  hidden  ... .venv/lib/python3.11/site-packages/__editable__.release_confidence_platform-0.0.0.pth
-rw-r--r--   1 mjseno  staff  hidden  ... .venv/lib/python3.11/site-packages/distutils-precedence.pth
```

Python verbose startup directly identifies the skip:

```text
Processing global site-packages
Adding directory: '/Users/mjseno/Documents/Development/2026_fortfolio_projects/release-confidence-platform/.venv/lib/python3.11/site-packages'
Skipping hidden .pth file: '/Users/mjseno/Documents/Development/2026_fortfolio_projects/release-confidence-platform/.venv/lib/python3.11/site-packages/__editable__.release_confidence_platform-0.0.0.pth'
Skipping hidden .pth file: '/Users/mjseno/Documents/Development/2026_fortfolio_projects/release-confidence-platform/.venv/lib/python3.11/site-packages/distutils-precedence.pth'
```

## 5. Execution Path / Failure Trace

1. The active `.venv` has an editable install of `release-confidence-platform`.
2. Setuptools/pip writes `.venv/lib/python3.11/site-packages/__editable__.release_confidence_platform-0.0.0.pth` containing the repository `src` path.
3. On Python startup, the `site` module scans venv site-packages for `.pth` files.
4. Python detects the macOS `UF_HIDDEN` flag on `__editable__.release_confidence_platform-0.0.0.pth` and skips it.
5. Because the `.pth` is skipped, `/Users/mjseno/Documents/Development/2026_fortfolio_projects/release-confidence-platform/src` is never appended to `sys.path`.
6. `.venv/bin/rcp` attempts `from release_confidence_platform.operator_cli.main import main` before CLI code runs.
7. The import fails with `ModuleNotFoundError` because the package exists under `src/` but `src/` is absent from `sys.path`.
8. The script shim fails for the same reason when run through `.venv/bin/python`.

## 6. Failure Classification

- Primary classification: Environment / Configuration Issue.
- Severity: Blocker.

Justification: HITL active-venv gate cannot complete because both active-venv CLI entry paths fail before argparse help renders. Clean editable and non-editable venvs pass, and the active venv contains correct packaging metadata; the failure is specific to this venv's macOS file flags.

## 7. Root Cause Analysis

Confidence label: Confirmed Root Cause.

Immediate failure point: `.venv/bin/rcp:3` cannot import `release_confidence_platform.operator_cli.main`; `.venv/bin/python scripts/rcp.py --help` cannot import `release_confidence_platform` either.

Underlying root cause: the active repository `.venv` is marked with macOS `hidden` file flags, including the editable-install `.pth` file. CPython 3.11's `site.addpackage` skips `.pth` files with hidden flags on macOS. Therefore the correct editable `src` path is not processed and does not appear on `sys.path`.

Supporting evidence:

- Correct editable `.pth` exists and points to the correct `src` directory.
- Correct `src/release_confidence_platform` package exists.
- Python is not running with `-S`; `no_site` is `0`.
- Verbose Python startup explicitly prints `Skipping hidden .pth file` for the editable `.pth`.
- File flag inspection confirms `hidden True` and `UF_HIDDEN` is set on the editable `.pth`.
- Clean editable and non-editable venvs pass, isolating the issue to the active `.venv` environment rather than source packaging.

Contributing factors:

- The entire `.venv` tree appears to have the macOS `hidden` flag, not just one file. Future `.pth` files created inside this tree may inherit or retain problematic flags depending on how the tree is manipulated.

## 8. Confidence Level

High.

The exact Python startup diagnostic proves why `.pth` processing is skipped, and the skipped file is the exact editable artifact responsible for adding `src` to `sys.path`. No code/package defect is required to explain the active `.venv` failure.

## 9. Recommended Fix

Likely owner: release/infrastructure or operator performing HITL validation.

No source code changes are required for this issue. Remediate the active venv environment by clearing macOS hidden flags or rebuilding the venv.

Preferred remediation for the active `.venv`:

```bash
chflags -R nohidden .venv
.venv/bin/python -m pip install -e .
hash -r
```

More conservative remediation if only `.pth` files should be touched:

```bash
chflags nohidden .venv/lib/python3.11/site-packages/*.pth
.venv/bin/python -m pip install -e .
hash -r
```

Clean rebuild alternative:

```bash
rm -rf .venv
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip setuptools
.venv/bin/python -m pip install -e .[dev]
hash -r
```

Cautions:

- Use `.venv/bin/python -m pip ...` to ensure the install targets the same interpreter used by `.venv/bin/rcp`.
- Do not add `PYTHONPATH=src` as the HITL fix; that masks the editable-install gate.
- Do not add runtime `sys.path` mutation to application code; the issue is environment-level `.pth` suppression.

## 10. Suggested Validation Steps

After remediation, validate from the repository root:

```bash
.venv/bin/python -c "import sys; print([p for p in sys.path if p.endswith('/release-confidence-platform/src')])"
.venv/bin/python -c "import release_confidence_platform; print(release_confidence_platform.__file__)"
.venv/bin/rcp --help
.venv/bin/python scripts/rcp.py --help
```

Expected results:

- first command prints the repository `src` path in `sys.path`
- second command prints a file under `src/release_confidence_platform/__init__.py`
- both help commands render usage without `ModuleNotFoundError`

Validate Python is processing `.pth` rather than skipping it:

```bash
.venv/bin/python -v -c "pass" 2>&1 | grep -E "(__editable__|Skipping hidden .pth)"
```

Expected result: no `Skipping hidden .pth file` line for `__editable__.release_confidence_platform-0.0.0.pth`.

Validate file flags:

```bash
ls -lO .venv/lib/python3.11/site-packages/__editable__.release_confidence_platform-0.0.0.pth
.venv/bin/python -c "import os, stat; p='.venv/lib/python3.11/site-packages/__editable__.release_confidence_platform-0.0.0.pth'; st=os.lstat(p); print(bool(getattr(st, 'st_flags', 0) & getattr(stat, 'UF_HIDDEN', 0)))"
```

Expected result: `ls -lO` does not show `hidden` for the editable `.pth`, and the Python flag check prints `False`.

Optional outside-repo regression check:

```bash
cd /var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode
/Users/mjseno/Documents/Development/2026_fortfolio_projects/release-confidence-platform/.venv/bin/python -c "import release_confidence_platform; print(release_confidence_platform.__file__)"
/Users/mjseno/Documents/Development/2026_fortfolio_projects/release-confidence-platform/.venv/bin/rcp --help
```

## 11. Open Questions / Missing Evidence

- What operation originally applied the `hidden` flag recursively to `.venv` is unknown. This is not required to unblock HITL, but if it recurs, inspect local Finder/automation/sync tooling that may be applying macOS hidden flags.
- After clearing flags, QA should confirm the active `.venv` no longer hides newly generated `.pth` files after `pip install -e .`.

## 12. Final Investigator Decision

Likely test/environment issue, not application fix.

The active `.venv` failure is confirmed as an environment/configuration problem caused by macOS hidden file flags suppressing editable `.pth` processing. Source code/package changes are not required for this specific HITL blocker.
