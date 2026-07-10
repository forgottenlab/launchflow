# Next Codex Task

This file is reserved for the next task prepared by ChatGPT.

Do not execute this file until the user asks you to execute the prepared task.

## Task goal

Close any running `dist/LaunchFlow.exe`, then rerun the final release and export smoke checks if another release readiness pass is requested.

## Allowed scope

TBD

## Required behavior

TBD

## Standing safety rules

- Do not read, print, generate, or package real private keys.
- Do not include real `.lic` files in public release artifacts.
- Do not claim PyInstaller export is verified unless a real build completed.
- Keep `editor/`, `runtime/`, and `shared/` boundaries intact unless a task explicitly asks for a larger refactor.

## Tests / checks

- `python tools/validate_release_smoke.py`
- `python tools/validate_export_smoke.py`
- `git diff --check`
- `git status --short`

## Final handoff

Update `.ai/codex_result.md` with changed files, summary, commands run, test result, and remaining risks.
