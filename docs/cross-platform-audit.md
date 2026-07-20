# LaunchFlow Cross-Platform Coupling Audit

## Executive Summary

This audit records the current `v0.1.0-beta.2` Windows baseline. It is an architecture and coupling assessment and makes no support claim for Linux or macOS. No runtime, editor, license, schema, or packaging behavior was changed as part of the audit.

The repository has **no identified P0 import/startup blocker caused solely by importing a Windows-only Python module**. Windows-only calls are generally inside functions or guarded branches, for example `shared/app_icon.py:33-36` and `licensing/hwid.py:49-57`. However, the main workflows are not cross-platform: default URL opening calls `os.startfile` (`runtime/launcher_runtime.py:195`), Application supports Windows entry types (`runtime/launcher_runtime.py:151-167`), Command is modeled and edited as `cmd`/PowerShell (`shared/models.py:102`, `editor/ui/main_window.py:2301`), and all production packaging outputs are Windows EXE (`tools/build_editor_release.py:88-144`, `tools/build_single_exe.py:549-572`).

## Current Support Boundary

- **Current support:** Windows x86_64 Beta; behavior must remain frozen while adapters are introduced.
- Linux/macOS source paths found during this audit are implementation fragments, not supported workflows.
- README already states the Windows-only boundary (`README.md:5,21,193`), so README files are intentionally unchanged.

## Target Platforms

- **Experimental target:** Linux x86_64.
- **Priority experimental target:** macOS arm64 on Apple Silicon, including M3 physical validation.
- **Future consideration:** Linux arm64, macOS x86_64, and macOS universal2.

No target above Windows is claimed as implemented or released.

## Audit Method

The audit covered `editor/`, `runtime/`, `shared/`, `licensing/`, the production build/export tools, all `check_*_smoke.py` and `validate_*_smoke.py` scripts, current architecture/testing docs, README files, and release notes. It searched both explicit branches (`os.name`, `sys.platform`) and implicit assumptions such as executable suffixes, shell names, user-data locations, desktop APIs, fonts, error codes, packaging output names, and test commands.

Severity means:

| Severity | Meaning |
|---|---|
| P0 | Prevents import or editor startup on another platform. |
| P1 | Blocks or mis-executes a core workflow: run, activation, save/open, or packaging. |
| P2 | Produces degraded UX, non-native behavior, or incomplete platform integration. |
| P3 | Maintainability, documentation, test taxonomy, or future compatibility debt. |

## Findings Summary

| Severity | Count |
|---|---:|
| P0 | 0 |
| P1 | 7 |
| P2 | 7 |
| P3 | 6 |
| **Total** | **20** |

These are conceptual findings. The static checker reports individual source occurrences, so its occurrence count is intentionally larger.

| ID | Area | Severity | File / Symbol | Windows Assumption | Linux Impact | macOS Impact | Recommendation |
|---|---|---|---|---|---|---|---|
| CP-01 | Process/shell | P1 | `shared/models.py:102`; `runtime.command_runner.build_command_args` at `runtime/command_runner.py:47-64` | cmd/PowerShell shell IDs | Saved shell is silently run with `/bin/sh` | zsh is not modeled; saved shell is silently run with `/bin/sh` | `CommandBackend`; reject unsupported shell values |
| CP-02 | URL launch | P1 | `RuntimeExecutor._run_url` at `runtime/launcher_runtime.py:176-197` | `os.startfile` opens default browser | Default URL fails | Default URL fails | `ApplicationLauncher.open_url` |
| CP-03 | Application | P1 | `RuntimeExecutor._run_app` at `runtime/launcher_runtime.py:136-174` | `.lnk`, `.ps1`, Windows picker filters | No `.sh`/`.desktop`/AppImage policy | No `.app`/`.command`/open policy | Per-platform application capability/filter |
| CP-04 | HWID | P1 | `licensing/hwid.py:37-100` | MachineGuid plus `vol C:` | Generic fallback is not stability-proven | Generic fallback is not stability-proven | Versioned `HardwareIdentityProvider` |
| CP-05 | Editor package | P1 | `tools.build_editor_release.build_release` at `tools/build_editor_release.py:85-148` | ICO and `.exe` onefile | No native artifact | No app bundle, signing, or notarization | Per-host `PackagingBackend` |
| CP-06 | Launcher export | P1 | `tools/build_single_exe.py:38,421-461,498-577` | Windows packable suffixes and EXE output | No ELF/AppImage export | No `.app`/`.dmg` export | Current-host packaging only |
| CP-07 | Export runtime | P1 | `EMBEDDED_TEMPLATE` at `tools/build_single_exe.py:54-399` | Duplicated AppData/MessageBox/startfile/shell behavior | Source fixes do not propagate | Source fixes do not propagate | Generate from/reuse backend contracts |
| CP-08 | Paths | P2 | `resolve_data_root` at `shared/app_paths.py:19-34` | `%LOCALAPPDATA%`, one generic fallback | XDG config/cache split missing | Application Support/Logs/Caches missing | `PlatformPaths`; evaluate QStandardPaths |
| CP-09 | Desktop | P2 | `shared/app_icon.py:15-39`; `shared/diagnostics.py:103-110` | AppUserModelID, ICO, startfile | No desktop/icon/open-folder integration | No icns/Info.plist/Dock/open integration | `DesktopIntegration` |
| CP-10 | Diagnostics | P2 | `build_diagnostic_text` at `shared/diagnostics.py:22-33,76-100` | `Windows:` and `%USERPROFILE%` labels | Mislabels Linux | Mislabels macOS | Platform label/path aliases; keep redaction |
| CP-11 | Shortcuts | P2 | `SHORTCUTS`/QAction setup at `editor/ui/main_window.py:115-122,2198-2223` | Literal Ctrl sequences | Native mapping unverified | Command-key/menu convention unverified | Qt StandardKey plus native validation |
| CP-12 | Qt UI | P2 | theme/control QSS at `editor/ui/main_window.py:602-800` | Windows fonts and measured control geometry | WM/font/DPI unverified | native menu/font/Retina unverified | Offscreen plus physical matrices |
| CP-13 | Dev entry | P2 | `tools/run_editor_dev.ps1:1-20` | PowerShell and LOCALAPPDATA | Cannot use helper | Cannot use helper | Separate minimal platform launchers |
| CP-14 | Errors | P2 | `friendly_command_error`/decode at `runtime/command_runner.py:34-44,81-99` | 9009 and Windows code pages | POSIX errno/signals unmapped | POSIX/launch errors unmapped | Backend error normalization; retain raw data |
| CP-15 | Migration | P3 | `_candidate_legacy_roots` at `shared/data_migration.py:50-66` | `LaunchFlow.exe` probe | Linux legacy roots undefined | macOS legacy roots undefined | Backend supplies explicit roots |
| CP-16 | Cache names | P3 | `PlanService.get_cached_exe_path` at `editor/services/plan_service.py:338-349` | Cache artifact ends `.exe` | Misnamed/inapplicable | Misnamed/inapplicable | Packaging backend owns artifact name |
| CP-17 | Duplication | P3 | `tools/build_single_exe.py:54-399` | Separate Windows-biased runtime | Drift risk | Drift risk | Shared/generated execution contract |
| CP-18 | Tests | P3 | `tools/validate_release_smoke.py:54-109`; `tools/validate_export_smoke.py:70-203` | EXE/taskkill/cmd/PowerShell | No native release gates | No native release gates | Explicit platform labels and jobs |
| CP-19 | Docs | P3 | `README.md:5,92-105,193`; `docs/architecture.md:251-260` | Current product is intentionally Windows-only | Must stay a target, not claim | Must stay a target, not claim | Update only after release gates pass |
| CP-20 | License metadata | P3 | `licensing/request_token.py:45-55`; `licensing/license_schema.py:10-24` | Signed payload has no platform/arch | Future entitlement policy unresolved | Future arch/universal policy unresolved | New versioned design only; do not alter current schemas |

## Detailed Evidence

| ID | Severity | Boundary | Evidence and impact |
|---|---|---|---|
| CP-01 | P1 | Command backend | `CommandStep.shell` defaults to `cmd` (`shared/models.py:102`), templates repeat that default (`editor/services/plan_service.py:65,263`), the UI only accepts `cmd`/`powershell` (`editor/ui/main_window.py:532,2301`), while every non-Windows host is silently mapped to `/bin/sh` (`runtime/command_runner.py:47-64`). A saved `cmd` plan would therefore change semantics rather than report incompatibility. |
| CP-02 | P1 | Default browser | Default URL launch uses unguarded `os.startfile` (`runtime/launcher_runtime.py:176-197`); the exported launcher duplicates it (`tools/build_single_exe.py:216-232`). URL data is portable, but default-browser execution is not. |
| CP-03 | P1 | Application launch | Runtime has special `.lnk` and `.ps1` paths (`runtime/launcher_runtime.py:151-167`); the picker advertises only Windows suffixes (`editor/ui/main_window.py:3387-3400`). Generic executable launch is reusable, but Linux desktop files, macOS app bundles, and native open semantics are absent. |
| CP-04 | P1 | Hardware identity | Windows uses registry `MachineGuid` and `vol C:` (`licensing/hwid.py:37-60,84-100`). Other systems fall back to OS version, hostname, and username (`licensing/hwid.py:63-81`), so identity can change on OS upgrade, hostname change, or account change. Activation may run, but durable binding is not established. |
| CP-05 | P1 | Editor packaging | Release packaging requires `launchflow.ico`, passes `--onefile`, and expects `<name>.exe` (`tools/build_editor_release.py:85-144`). PyInstaller cannot cross-compile these missing platform artifacts from one Windows job. |
| CP-06 | P1 | Plan launcher export | Packable assets are Windows suffixes (`tools/build_single_exe.py:38,421-461`), the builder expects an EXE (`tools/build_single_exe.py:498-577`), and the UI presents an EXE-only destination (`editor/ui/main_window.py:3812-3827`). Linux/macOS launcher artifacts do not exist. |
| CP-07 | P1 | Embedded launcher runtime | The generated launcher independently embeds Windows AppData, MessageBox, `os.startfile`, cmd/PowerShell, and `/bin/sh` fallback behavior (`tools/build_single_exe.py:88-102,134-160,186-269`). Source runtime fixes would not automatically fix exported launchers. |
| CP-08 | P2 | User-data paths | Windows uses `%LOCALAPPDATA%`, but all non-Windows systems share `~/.local/share/LaunchFlow` (`shared/app_paths.py:19-34`). This does not separate config/cache/data by XDG and is not the standard macOS Application Support location. |
| CP-09 | P2 | Desktop integration | App identity/icon integration is Windows AppUserModelID plus ICO (`shared/app_icon.py:15-39`); opening logs is Windows-only and otherwise a silent no-op (`shared/diagnostics.py:103-110`). |
| CP-10 | P2 | Diagnostics | Diagnostics label every OS as `Windows` and mask home as `%USERPROFILE%` (`shared/diagnostics.py:22-33,88`). Redaction still protects the resolved home path, but output is misleading on Linux/macOS. |
| CP-11 | P2 | Keyboard conventions | Actions use literal `Ctrl+...` strings (`editor/ui/main_window.py:115-122,2198-2223`) instead of Qt standard keys. macOS Command-key conventions and menu presentation have not been validated. |
| CP-12 | P2 | Qt presentation | Global font favors Windows families (`editor/ui/main_window.py:796-800`); custom controls and frameless windows depend on pixel metrics and native subcontrol geometry (`editor/ui/main_window.py:602-784`, `editor/ui/activation_window.py:203-217`). Offscreen tests cannot establish Linux window-manager or macOS native behavior. |
| CP-13 | P2 | Developer entry point | Developer mode is a PowerShell script using `%LOCALAPPDATA%` (`tools/run_editor_dev.ps1:1-20`); no shell-neutral or per-platform entry point exists. |
| CP-14 | P2 | Error interpretation | Friendly Command errors include Windows return code `9009` and Windows code-page decoding (`runtime/command_runner.py:34-44,81-99`). POSIX signal termination, shell-not-found, permission, and macOS launch errors need backend-specific mapping while retaining raw details. |
| CP-15 | P3 | Legacy migration | A recognized legacy cwd is partly identified by `LaunchFlow.exe` (`shared/data_migration.py:60-65`). The copy/no-overwrite engine is reusable, but platform discovery belongs behind path/migration policy. |
| CP-16 | P3 | Cached artifact naming | Plan service and UI cache paths are always `.exe` (`editor/services/plan_service.py:338-349`, `editor/ui/main_window.py:3023-3044`). These names leak Windows packaging into editor services. |
| CP-17 | P3 | Runtime duplication | Export embeds a second runtime in `EMBEDDED_TEMPLATE` (`tools/build_single_exe.py:54-399`) instead of consuming a shared platform contract. This creates drift risk for process, error, logging, and desktop behavior. |
| CP-18 | P3 | Test taxonomy | Release/export smokes invoke Windows artifacts and commands (`tools/validate_release_smoke.py:54-109`, `tools/validate_export_smoke.py:70-203`), while several GUI smokes run Qt offscreen (`tools/check_editor_gui_smoke.py:25,393`). The suite does not currently declare per-platform capability or skip reasons. |
| CP-19 | P3 | Public terminology | README correctly states Windows-only (`README.md:5,21,92-105,193`), while architecture calls multi-platform compatibility future work (`docs/architecture.md:251-260`). Terminology must remain accurate until release gates pass; it is not presently misleading. |
| CP-20 | P3 | License platform metadata | `LFREQ1` requires schema/product/version/machine/request/time only (`licensing/request_token.py:45-55,74-91`); `lflic-1` requires machine/product/version/entitlement fields but no platform or architecture (`licensing/license_schema.py:10-24,46-69`). Adding signed fields in place would change compatibility, so any future metadata must be versioned and migration-designed rather than inserted into the existing formats. |

## Process and Shell Execution

`execute_command` already provides the reusable contract of argv execution with `shell=False`, `stdin=DEVNULL`, two pipes, `communicate()`, and raw return data (`runtime/command_runner.py:102-157`). Windows-specific argv, hidden/background flags, quoting, code pages, and error normalization must move behind `CommandBackend`. Linux needs explicit sh/bash capabilities; macOS needs explicit zsh/bash capabilities. Installing another shell must not silently reinterpret an existing plan.

## Application Launching

Fire-and-forget ordinary executable launch is reusable (`runtime/launcher_runtime.py:169-173`). Windows `.exe/.bat/.cmd/.com/.ps1/.lnk`, Linux executable/`.sh`/`.desktop`/AppImage, and macOS Unix executable/`.command`/`.app` each need platform capability rules. Application paths are inherently local; an import-time portability diagnostic is safer than immediate schema change.

## Data and Configuration Paths

`LAUNCHFLOW_DATA_DIR` absolute override remains useful for tests (`shared/app_paths.py:19-26`). Future defaults should separately consider `%LOCALAPPDATA%`, XDG data/config/cache roots, and macOS Application Support/Logs/Caches. QStandardPaths is a candidate, not a decision, because migration compatibility and headless tests must be proven first.

## UI and OS Integration

Qt is reusable, but AppUserModelID/ICO, Linux desktop files and PNG/SVG, macOS icns/Info.plist/Dock, native menu shortcuts, file filters, font fallback, frameless windows, and control geometry are separate platform evidence. Offscreen success is only a construction/rendering signal.

## Packaging and Export

PyInstaller must build on the target OS: Windows builds Windows, Linux builds Linux, macOS builds macOS. Linux artifact choice (ELF/AppImage) is undecided. macOS needs `.app`/`.dmg`, Code Signing, Hardened Runtime, Notarization, Gatekeeper, and arm64-first architecture validation; x86_64/universal2 remain future considerations.

## Licensing and Hardware Identity

The present RSA signature flow, `LFREQ1`, `lflic-1`, machine comparison, and public-key packaging must remain unchanged for Windows Beta. The blocker is not RSA; it is the definition and lifecycle of `machine_id`.

A future cross-platform design needs a `HardwareIdentityProvider` with an explicit identity algorithm/version and privacy review. Existing Windows licenses must continue to resolve with the current Windows algorithm. Linux/macOS issuance should remain unsupported until stable platform sources, collision analysis, reset/recovery behavior, VM/container/clone behavior, and upgrade tests are specified. Platform/architecture metadata is not currently in either signed contract; future signed metadata requires a new compatible version, not mutation of `lflic-1`.

## Diagnostics and Privacy

Existing redaction masks resolved home/local paths and machine/request/signature material (`shared/diagnostics.py:16-74`), so it is not limited to one literal Windows user-profile prefix. Linux home and macOS user-home paths still need platform-appropriate aliases and fixtures. Future diagnostics should state system/architecture/provider version while preserving the current rule: do not read license content, private keys, or upload automatically.

## Plan Portability

- URL values and Wait durations are portable data; default-browser execution still needs a backend.
- Application paths, local assets, arguments, working directories, and path separators are normally host-specific.
- Command text is only partially portable; shell identity and external program availability determine meaning.
- Windows paths on Linux/macOS should be diagnosed before run, not rewritten automatically.
- Do not add a platform field to the current Beta schema. Future options are plan-level hints, step-level overrides, portability diagnostics, and import-time warnings without adding step types.

## Reusable Components

- The four-step type boundary and plan JSON conversion are centralized in `shared/models.py:31,117-187`. `WaitStep`, URL values, names, ordering, and delay fields are platform-neutral; only platform-sensitive parameters need capability validation.
- Sequential dispatch, delay, stop state, and structured results in `runtime/launcher_runtime.py:90-134,199-225` are reusable once launch/process operations are injected.
- Plan save/load/history uses ordinary JSON and paths (`editor/services/plan_service.py:295-316`) and should not be forked per OS.
- Request token canonicalization/checksum (`licensing/request_token.py:61-135`), license shape/version checks (`licensing/license_schema.py:46-69`), RSA verification in `LicenseManager` (`licensing/license_manager.py:196-253`), and frozen public-key lookup (`licensing/license_manager.py:73-90`) are conceptually platform-neutral.
- Diagnostics redaction and bounded log collection are reusable (`shared/diagnostics.py:16-74`); only labels, path aliases, and folder opening need adapters.
- Qt widgets, model/editor synchronization, dirty state, and ordering logic are mostly reusable, but each platform still needs offscreen plus physical UI validation.

## Platform-Specific Components

- Windows: cmd/PowerShell process behavior, startfile/shortcuts, AppUserModelID/ICO, MachineGuid/volume input, EXE packaging/export, and PowerShell developer helper.
- Linux target: XDG paths, sh/bash, desktop/default-browser/application launch, stable identity, desktop integration, native artifact/export, and real x86_64 release tests.
- macOS arm64 priority target: Application Support paths, zsh/bash, `.app`/open, Command-key/menu/Dock/icns/Info.plist, stable identity, Apple Silicon packaging/signing/notarization, and real M3-class validation.

## Recommended Platform Abstraction

Use `shared/platform/{base,detection,paths,process,applications,identity,integration,packaging}.py`. Centralize platform selection there; business modules should consume `PlatformInfo`, `PlatformPaths`, `CommandBackend`, `ApplicationLauncher`, `HardwareIdentityProvider`, `DesktopIntegration`, and `PackagingBackend` instead of adding scattered `sys.platform` branches. Detailed responsibilities and phases are in `docs/cross-platform-roadmap.md`.

## Tests

Current tests fall into three groups:

1. **Reusable or mockable:** request/schema/admin CLI, README/docs, plan serialization/history, redaction, and migration copy rules can run on each platform with injected paths/identity.
2. **Platform-parameterized:** AppPaths, Command, Application/URL launch, shortcuts, icons, diagnostics, editor widgets, and offscreen GUI checks need backend fixtures and explicit capability expectations.
3. **Platform-specific physical/release:** Windows release/export/data-isolation, taskbar icon, actual shell invisibility, desktop URL/application opening, fonts/themes/DPI, and mouse/keyboard behavior require native runners. Current Windows examples include `tools/check_command_capture_smoke.py:37-64,196`, `tools/check_app_icon_smoke.py:50-98`, and `tools/validate_release_data_isolation.py`.

The detailed per-script mapping, current platform requirement, Windows assumptions, parameterization decision, and proposed labels are maintained in `docs/platform-support-matrix.md`.

## Migration Risks

- An adapter refactor can regress hidden-window/quoting/error behavior even if tests pass only at unit level.
- A new HWID algorithm can invalidate existing licenses or create collisions; Windows identity must remain frozen.
- Adding fields to canonical signed payloads can break request/admin/client compatibility.
- PyInstaller, Qt plugins, native icons, code signing, and notarization require real-host evidence.
- Treating partial source execution as product support would create an unsupported security and support promise.

## Non-Goals

No Linux/macOS implementation, new step type, plan schema change, license/request/signature change, plugin system, CI workflow, cross-compilation, EXE rebuild, or broad UI rewrite is part of this audit.

## Static Coupling Guard

Run:

```powershell
python tools/check_platform_coupling_smoke.py
python tools/check_platform_coupling_smoke.py --format json
```

The stdlib-only checker scans core packages, production build/export entry points, and docs/tests as references. It ignores private/generated/dependency/build/dist/cache directories and Python comments/docstrings; it does not read licenses or keys. Output distinguishes `allowed_windows_boundary`, `platform_adapter_candidate`, `unexpected_core_coupling`, and `docs_or_test_reference`, with category/path/line/evidence. The reviewed baseline records area, reason, migration target, and whether each production occurrence may remain. A new unregistered finding under `editor/`, `runtime/`, `shared/`, or `licensing/` exits nonzero; stale baseline entries are reported for review.

## Conclusion

The Windows Beta remains the only supported release. There is no confirmed non-Windows import-only P0 blocker, but P1 runtime, identity, and packaging boundaries prevent a support claim. The safe migration is adapter-first, Windows-equivalence-first, then Linux x86_64 and macOS arm64 source experiments, followed last by per-host packaging/export and release declaration.
