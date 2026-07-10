# Project Context

## Project

- Name: LaunchFlow
- Path: `E:\code\python\Daily-Tools\visual-launcher-release`
- Repository: `https://github.com/forgottenlab/launchflow`
- Status: `0.1.0-beta`

## Purpose

LaunchFlow is a Windows desktop visual launch workflow builder. It lets users compose launch plans with application, URL, command, and wait steps, run those plans locally, save them as JSON, and export a plan as a standalone startup EXE.

## Stack

- Python
- PySide6
- PyInstaller
- `cryptography`

## Important Directories

- `editor/`: PySide6 editor UI and workbench logic.
- `editor/services/`: plan and settings persistence.
- `runtime/`: runtime execution logic reused by trial runs.
- `shared/`: models, schema validation, utilities, app metadata.
- `tools/`: packaging, license generation, key generation helpers.
- `licensing/`: offline activation and license validation.
- `docs/`: user and architecture documentation.
- `data/`: local templates, settings, and user plan storage.

## Current Behavior

- Editor startup checks local offline license before entering the workbench.
- Plans are stored as JSON through `PlanService`.
- Trial run executes the current plan directly through `RuntimeExecutor`.
- Export uses `tools/build_single_exe.py` to generate an embedded launcher script and package it with PyInstaller.
- Portable path strategy: released app data, logs, and license files are relative to the executable directory.

## Safety Boundaries

- Do not read or expose private keys, real license files, tokens, credentials, or sensitive user configuration.
- Never commit or package `private/private_key.pem`.
- Never generate, print, or leak production private keys.
- Never include real `.lic` authorization files from `generated_licenses/` or user devices in public release packages.
- Do not modify remote repositories or deploy without explicit authorization.
- Treat trial run as an active local execution action because it can open applications, URLs, and command windows.
- Treat packaging scripts as sensitive enough to require focused validation after edits.

## Local Commands

- Run editor from source: `python editor/main.py`
- Build editor release: `python tools/build_editor_release.py`
- Export logic entrypoint: `tools/build_single_exe.py`
- Narrow syntax check: `python -m compileall editor runtime shared tools`
- Static spinbox contract: `python tools/check_ui_spinbox_contract.py`
- Editor GUI smoke: `python tools/check_editor_gui_smoke.py`
- Export smoke: `python tools/validate_export_smoke.py`
- Release smoke: `python tools/validate_release_smoke.py`

## Testing Expectations

- For model, schema, runtime, or packaging changes, run at least Python compilation checks.
- For export behavior changes, prefer a small direct invocation of `build_single_file_exe` only when PyInstaller is available and the user accepts the build cost.
- Do not claim packaged EXE behavior is verified unless an actual PyInstaller build completed.
- If PyInstaller export cannot be run or fails, record the exact blocker in `.ai/codex_result.md` and the final handoff.
- After UI edits, run AST checks and at least one relevant smoke/structural check.
- Before rebuilding `dist/LaunchFlow.exe`, ensure no previous `dist/LaunchFlow.exe` process is still running.

## Documentation To Keep Aligned

- `README.md`
- `docs/architecture.md`
- `docs/beta-testing.md`
- `CHANGELOG.md`
- `.ai/codex_result.md`

Behavior changes in export, authorization, runtime execution, packaging, or user-visible UI should update these documents in the same task.

## ChatGPT / Codex Collaboration

ChatGPT can prepare scoped tasks in `.ai/next_codex_task.md`. Codex should execute local inspection, file edits, commands, and tests, then update `.ai/codex_result.md` with changed files, commands, results, and remaining risks.
