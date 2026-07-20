# LaunchFlow Platform Support Matrix

## Target boundary and status vocabulary

- Current support: Windows x86_64 Beta.
- Experimental target: Linux x86_64.
- Priority experimental target: macOS arm64 on Apple Silicon, with M3 included in physical validation.
- Future consideration: Linux arm64, macOS x86_64, and macOS universal2.

The only permitted matrix statuses are `Supported`, `Partially portable`, `Windows-only`, `Planned`, `Requires real-device validation`, and `Not planned yet`. A reusable code path does not imply user support.

## Capability matrix

| Capability | Windows | Linux target | macOS target | Portability | Notes |
|---|---|---|---|---|---|
| Editor startup | Supported | Planned | Planned | Partially portable | No known P0 import-only blocker (`shared/app_icon.py:33-39`, `licensing/hwid.py:49-60`), but neither target has native-host evidence. |
| Plan save/load | Supported | Partially portable | Partially portable | Partially portable | JSON conversion/save is neutral (`shared/models.py:117-187`, `editor/services/plan_service.py:295-316`); platform parameters remain. |
| Recent plans | Supported | Partially portable | Partially portable | Partially portable | Plan history service is reusable after `PlatformPaths`; physical single-click/focus behavior still needs validation. |
| Four step schema | Supported | Partially portable | Partially portable | Partially portable | `app`, `url`, `command`, `wait` remain unchanged (`shared/models.py:31,145-187`). |
| Application step | Supported | Planned | Planned | Windows-only | Generic `Popen` is reusable (`runtime/launcher_runtime.py:169-173`), but `.lnk`/`.ps1`, picker filters, `.desktop`, AppImage, shell scripts, Unix executables, `.app`, `.command`, and native open semantics need separate policies (`runtime/launcher_runtime.py:151-167`, `editor/ui/main_window.py:3387-3400`). |
| URL step | Supported | Planned | Planned | Windows-only | Explicit-browser launch is reusable (`runtime/launcher_runtime.py:183-193`); default browser calls `os.startfile` (`runtime/launcher_runtime.py:195`). |
| Command step | Supported | Planned | Planned | Windows-only | UI/model expose cmd/PowerShell while non-Windows silently maps to `/bin/sh` (`shared/models.py:102`, `runtime/command_runner.py:47-64`, `editor/ui/main_window.py:2301`). Linux needs sh/bash; macOS needs zsh/bash policy. |
| Wait step | Supported | Partially portable | Partially portable | Partially portable | Delay/stop logic is neutral (`runtime/launcher_runtime.py:227-240`); native runtime execution remains unverified. |
| Logging | Supported | Partially portable | Partially portable | Partially portable | Structured/raw process logging is reusable; launcher log root is Windows-only (`runtime/command_runner.py:20-31,102-157`, `tools/build_single_exe.py:88-102`). |
| Diagnostics | Supported | Planned | Planned | Partially portable | Redaction is reusable, labels/path aliases/open-folder are Windows-centric (`shared/diagnostics.py:22-33,88,103-110`). |
| Offline activation | Supported | Planned | Planned | Partially portable | RSA and request parsing are reusable, but stable native HWID and packaged public-key validation are not complete. |
| HWID | Supported | Planned | Planned | Windows-only | Windows registry/volume sources and weak generic fallback (`licensing/hwid.py:37-100`). |
| Platform/architecture in signed payload | Not planned yet | Not planned yet | Not planned yet | Not planned yet | Neither exists today (`licensing/request_token.py:45-55,74-91`, `licensing/license_schema.py:10-24`); existing `LFREQ1`/`lflic-1` remain frozen. |
| User data/config/cache paths | Supported | Planned | Planned | Partially portable | Phase 1a routes the unchanged Windows and override behavior through `shared/platform/paths.py`; non-Windows still uses a legacy compatibility fallback, not XDG or macOS-native locations. No Linux/macOS support claim follows from this abstraction. |
| Editor packaging | Supported | Planned | Planned | Windows-only | Windows ICO/EXE onefile only (`tools/build_editor_release.py:85-148`). Each OS must build itself. |
| Launcher export | Supported | Planned | Planned | Windows-only | Windows suffix collection and EXE output (`tools/build_single_exe.py:38,421-461,498-577`). |
| Bundled local applications | Supported | Planned | Planned | Windows-only | Current packable set is `.exe/.bat/.cmd/.com/.ps1`; complex AppImage, desktop, bundle, dylib/framework and licensing rules are undefined. |
| Icons | Supported | Planned | Planned | Windows-only | ICO/AppUserModelID only (`shared/app_icon.py:15-39`); Linux needs PNG/SVG/desktop integration, macOS needs icns/Info.plist/Dock integration. |
| Native shortcuts/menu conventions | Supported | Requires real-device validation | Requires real-device validation | Partially portable | Literal Ctrl bindings require Qt StandardKey/native menu verification, especially Command on macOS (`editor/ui/main_window.py:115-122,2198-2223`). |
| Dark/light themes | Supported | Requires real-device validation | Requires real-device validation | Partially portable | QSS/font/control metrics need real host checks (`editor/ui/main_window.py:602-800`). |
| Physical GUI validation | Supported | Requires real-device validation | Requires real-device validation | Requires real-device validation | Offscreen evidence cannot prove fonts, window manager, Dock/taskbar, focus, pointer, keyboard, or DPI (`docs/beta-testing.md:249-269`). |
| Developer launch helper | Supported | Planned | Planned | Windows-only | Current helper is PowerShell plus `%LOCALAPPDATA%` (`tools/run_editor_dev.ps1:1-20`). |
| Clean-host packaged runtime | Supported | Planned | Planned | Windows-only | Current release checks target `LaunchFlow.exe` (`tools/validate_release_smoke.py:5,54-109`, `tools/validate_release_data_isolation.py:42-74`). |

## Current smoke classification

“Reusable” means the same behavioral contract can run on each platform with stdlib/Qt dependencies. “Parameterize” means split neutral assertions from backend-specific fixtures and add explicit skip reasons. “Native-specific” means keep a dedicated platform job and physical/release evidence.

| Check | Current platform requirement | Windows assumption | Parameterizable | Suggested labels | Recommendation |
|---|---|---|---|---|---|
| `tools/check_license_request_smoke.py` | Any source host with crypto dependency | Activation-service case obtains current HWID (`:68-72`) | Yes | `platform-neutral`, `signing-authorization` | Keep token/corruption neutral; inject identity for provider cases. |
| `tools/check_license_admin_cli_smoke.py` | Any source host with crypto dependency | None; machine ID is supplied/mocked (`:71-81,181`) | Already mocked | `platform-neutral`, `signing-authorization` | Run on every host; continue using only temporary test keys. |
| `tools/check_readme_docs_smoke.py` | Any source host | Current public docs intentionally describe Windows | Yes | `platform-neutral` | Keep link/screenshot/sensitive-content checks; add support-wording contract. |
| `tools/check_app_paths_smoke.py` | Any host, currently Windows fixture | `LaunchFlow.exe` fixture (`:60-62`) | Yes | `platform-neutral` | Supply backend path fixtures; retain override/cwd isolation. |
| `tools/check_data_migration_smoke.py` | Any source host | Legacy locations currently originate from Windows product history | Yes | `platform-neutral` | Reuse copy/no-overwrite/secret exclusions with backend legacy roots. |
| `tools/check_command_capture_smoke.py` | Windows for full check | tasklist/cmd/CREATE_NO_WINDOW (`:37-64,196`) | Split neutral/backend cases | `windows-only`, `packaged-runtime` | Keep pipe/decode/returncode neutral; add Linux/mac native process tests. |
| `tools/check_diagnostics_smoke.py` | Any host, current Windows expectations | `Windows:` and `%USERPROFILE%` (`:50,67`) | Yes | `platform-neutral` | Inject platform label/path aliases; retain redaction/privacy assertions. |
| `tools/check_dev_mode_smoke.py` | Windows | PowerShell, `.cmd`, `%LOCALAPPDATA%` (`:173-198,248-254`) | No; add peers | `windows-only` | Keep unchanged; create separate Linux/mac source-entry checks. |
| `tools/check_app_icon_smoke.py` | Windows/offscreen | ICO/AppUserModelID/PyInstaller (`:50-98`) | No; add peers | `windows-only`, `packaged-runtime` | Keep Windows evidence; add independent Linux/mac resource tests. |
| `tools/validate_release_smoke.py` | Real Windows build host | EXE/ICO/taskkill (`:54-109`) | No; add peers | `windows-only`, `packaged-runtime` | Retain; add native packaging checks on target hosts. |
| `tools/validate_release_data_isolation.py` | Real Windows packaged build | `LaunchFlow.exe` (`:42-74`) | No; add peers | `windows-only`, `packaged-runtime` | Add native clean-profile isolation gates per artifact. |
| `tools/validate_export_smoke.py` | Real Windows build host | `.cmd`, `.ps1`, PowerShell, EXE, `_MEI` (`:70-203`) | No; add peers | `windows-only`, `packaged-runtime` | Preserve Windows launcher evidence; create separate native exporters. |
| `tools/check_editor_gui_smoke.py` | Qt offscreen; real desktop still required | cmd defaults (`:218-222`) and Windows visual baseline | Yes | `platform-neutral`, `physical-gui` | Parameterize shells; run offscreen plus real Linux/mac GUI. |
| `tools/check_ui_spinbox_contract.py` | Qt widget host; real desktop still required | Current theme metrics were validated on Windows | Yes | `platform-neutral`, `physical-gui` | Run each Qt platform plugin plus native pointer/DPI check. |
| `tools/check_control_border_theme_smoke.py` | Qt offscreen; real desktop still required | Windows font/control visual baseline | Yes | `platform-neutral`, `physical-gui` | Reuse scale matrix (`:18-21`); add native render evidence. |
| `tools/check_topbar_alignment_smoke.py` | Qt offscreen; real desktop still required | Windows titlebar/font baseline | Yes | `platform-neutral`, `physical-gui` | Reuse scale assertions (`:18-21`); validate native menu/chrome. |
| `tools/check_tooltip_shortcut_smoke.py` | Qt offscreen | Literal Ctrl shortcut labels | Yes | `platform-neutral`, `physical-gui` | Make expected labels key-standard aware and validate native menus. |
| `tools/check_step_editor_sync_smoke.py` | Qt offscreen | Command fixtures use current shell model | Yes | `platform-neutral` | Use backend capability fixtures; preserve dirty/snapshot contract. |
| `tools/check_step_reorder_smoke.py` | Qt offscreen; real drag still required | Output `.exe` fixture (`:194`) | Yes | `platform-neutral`, `physical-gui` | Parameterize artifact name; retain native drag/keyboard checklist. |
| `tools/check_drag_lifecycle_smoke.py` | Qt offscreen; real drag still required | None material | Yes | `platform-neutral`, `physical-gui` | Run item-lifetime contract everywhere (`:17`) plus native drag. |
| `tools/check_plan_history_single_click_smoke.py` | Qt offscreen; real pointer still required | None material | Yes | `platform-neutral`, `physical-gui` | Run history/dirty logic everywhere plus native focus/pointer. |
| `tools/check_log_toolbar_responsive_smoke.py` | Qt offscreen; real visual still required | Windows font/DPI baseline | Yes | `platform-neutral`, `physical-gui` | Run offscreen (`:17`) plus native font/DPI. |
| `tools/check_log_presentation_smoke.py` | Qt offscreen; real visual still required | Windows font/render baseline | Yes | `platform-neutral`, `physical-gui` | Reuse categorization; add native visual inspection. |

## Physical validation still required per claimed platform

- real mouse drag/drop, keyboard/menu shortcuts, focus, clipboard, dialogs, and accessibility;
- system light/dark theme, native fonts, 100%/125%/150% or equivalent scaling, multi-monitor behavior;
- taskbar/dock icon, app identity, window grouping, default browser, application opening, and reveal-folder behavior;
- shell invisibility/terminal behavior, locale/encoding, permission errors, signals, child-process cleanup;
- release artifact on a clean user profile, data-directory isolation, public-key resource lookup, quarantine/signing/notarization where applicable;
- exported launcher execution and packaged Application assets on the same native OS/architecture.
