# Codex Rules

These rules are specific to this LaunchFlow repository and supplement the global user rules.

## Scope

- Keep changes small and directly tied to the requested desktop workflow, export, UI, or packaging behavior.
- Do not redesign the whole workbench unless explicitly requested.
- Prefer preserving existing PySide6 widgets, dataclass models, and service boundaries.

## Sensitive Files

- Do not read, print, or copy private keys, real `.lic` files, tokens, or machine-bound activation data.
- Do not commit, copy into release artifacts, or print `private/private_key.pem`.
- Do not generate or leak real production private keys.
- Do not package `.lic` files from `generated_licenses/` or user devices into public releases.
- Use redacted examples in docs and tests.
- Do not write real secrets into `.ai/`, docs, logs, examples, or generated reports.

## Runtime Safety

- Trial run can launch real apps, URLs, and commands. Do not trigger it automatically during validation.
- Do not execute exported launchers automatically unless the user explicitly asks.
- Do not connect to remote services or run SSH for this project without explicit authorization markers.

## Packaging

- `tools/build_editor_release.py` packages the editor itself.
- `tools/build_single_exe.py` packages a user launch plan.
- After packaging-related edits, validate syntax at minimum with `python -m compileall`.
- Only report actual EXE packaging success after a PyInstaller command completes successfully.
- If real PyInstaller packaging did not run or did not pass, say so explicitly in `.ai/codex_result.md` and the final response.
- Generated user launchers may include `.exe`, `.bat`, `.cmd`, `.com`, and `.ps1` startup files, but must not include private keys or real `.lic` authorization files.
- Do not casually refactor boundaries between `editor/`, `runtime/`, and `shared/`; keep export/runtime changes scoped to the owning layer.
- Before release rebuilds, check that no existing `dist/LaunchFlow.exe` process is locking the previous artifact.

## UI Validation

- After UI changes, run a Python AST parse check and one relevant smoke or structural check when possible.
- Prefer Qt layout/subcontrol fixes for widget hitbox issues; do not mask geometry problems only by making controls larger.
- `tools/check_editor_gui_smoke.py` may require a local environment that can create temporary project data directories and import PySide6.

## Documentation

- Update `.ai/codex_result.md` after executing a prepared or initialization task.
- Update user docs only when behavior changes in a way users need to understand.
- Do not overwrite `.ai/next_codex_task.md` task content unless the user explicitly asks.
- Update `README.md`, `docs/architecture.md`, `docs/beta-testing.md`, and `CHANGELOG.md` when export, authorization, packaging, runtime, or user-visible behavior changes.
- Keep Chinese user documentation friendly, and keep English README summaries or short English sections for GitHub readers.
