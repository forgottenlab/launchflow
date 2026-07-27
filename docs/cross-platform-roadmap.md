# LaunchFlow Cross-Platform Roadmap

## Goal and non-goals

The goal is to make platform support an explicit backend capability while preserving the current Windows Beta behavior and plan format. This roadmap does not implement Linux/macOS support and does not commit to a release date.

Non-goals:

- no new step types;
- no language-specific Python/Java/Node steps;
- no change to existing plan JSON;
- no change to the current Windows machine-code algorithm, `LFREQ1`, `lflic-1`, or RSA signing flow;
- no attempt to cross-compile every artifact from Windows;
- no broad Qt UI redesign.

## Proposed module boundary

```text
shared/platform/
  base.py          # protocols, capability/result types, platform errors
  detection.py     # PlatformInfo and backend selection
  paths.py         # PlatformPaths and resource/user-data locations
  process.py       # CommandBackend and process error normalization
  applications.py  # ApplicationLauncher and native application targets
  urls.py          # UrlOpener and default/explicit browser specifications
  identity.py      # HardwareIdentityProvider
  desktop.py       # DesktopIntegration: current folder opening and process identity
  diagnostics.py   # diagnostics platform labels and ordered path aliases
  shortcuts.py     # frozen editor shortcut strings and policy selection
  packaging.py     # PackagingBackend and artifact capabilities
```

Suggested contracts:

| Contract | Responsibility | Must not own |
|---|---|---|
| `PlatformInfo` | normalized OS, architecture, frozen state, capability flags | plan mutation or license decisions |
| `PlatformPaths` | config/data/cache/log/temp/resource locations and conservative legacy roots | file migration policy or user-selected save/export destinations |
| `CommandBackend` | supported shell IDs, argv construction, process flags, decoding hints, friendly error classification | command text rewriting beyond documented backend rules |
| `ApplicationLauncher` | validate/launch native applications, scripts, and working directories | URL opening, packaging, or plan serialization |
| `UrlOpener` | choose default-browser versus explicit-browser mode and construct an immutable open specification | URL parsing, browser discovery, process execution, or plan serialization |
| `HardwareIdentityProvider` | versioned identity inputs and privacy-safe diagnostics | RSA signing, entitlement, or silent identity migration |
| `DesktopIntegration` | perform narrowly introduced desktop operations: open-directory and process application identity | paths/data creation, icon/resource loading, packaging, or core execution decisions |
| `ShortcutPolicy` | provide frozen shortcut strings for the existing editor action set | QAction creation, signal wiring, keyboard events, focus, persistence, or UI execution |
| `PackagingBackend` | host-native artifact name, icon/bundle resources, PyInstaller invocation, output verification | cross-compilation claims or plan schema changes |

Backends should return structured results/capabilities. Core code should reject unsupported operations before dispatch rather than silently map a saved Windows shell to an unrelated Unix shell.

## Phase 0 — Audit and guard (current)

| Field | Definition |
|---|---|
| Goal | Establish evidence and boundaries without changing production behavior. |
| In scope | Audit, matrix, roadmap, static checker, reviewed baseline, one changelog item. |
| Out of scope | Runtime/editor/license/schema/build changes and Linux/macOS implementation. |
| Files likely affected | `docs/`, new `tools/check_platform_coupling_*`, `CHANGELOG.md`, local `.ai/`. |
| Tests required | Static check, Python compile, keyword scan, doc-sensitive scan, diff/status checks. |
| Exit criteria | Zero new core coupling; official support remains Windows-only; Windows production files unchanged. |
| Rollback boundary | Remove only the new docs/checker/changelog entry; never touch Windows runtime state. |

## Phase 1 — Platform-neutral core extraction

| Field | Definition |
|---|---|
| Goal | Introduce no-side-effect detection/contracts and a behavior-equivalent Windows backend. |
| In scope | `base.py`, `detection.py`, `paths.py` first; then narrowly staged process/application/integration contracts. |
| Out of scope | Linux/macOS behavior, HWID algorithm, license formats, packaging, plan/schema changes. |
| Files likely affected | New `shared/platform/`; then `shared/app_paths.py` and focused call sites one adapter at a time. |
| Tests required | Exact `%LOCALAPPDATA%`/`LAUNCHFLOW_DATA_DIR` equivalence, JSON fixtures, all affected Windows smokes, static guard. |
| Exit criteria | No Windows behavior change, no new direct platform API in neutral modules, all existing plan/license fixtures unchanged. |
| Rollback boundary | Call sites can return to existing Windows functions; new adapters hold no migrated state and do not alter files. |

The first implementation slice should stop after paths. Later Phase 1 slices must separately prove cmd/PowerShell argv, hidden flags, raw output, `9009`, `.lnk`/`.ps1`, browser opening, icon, and EXE naming equivalence. The existing Windows `machine_id` must never be routed through a new algorithm in this phase.

### Phase 1a status — completed

Phase 1a now provides stdlib-only normalized platform detection, a minimal path-provider contract, a behavior-equivalent Windows provider, and a clearly named legacy fallback for non-Windows hosts. `shared/app_paths.py` retains its existing public API and delegates calculation through this boundary. `%LOCALAPPDATA%\LaunchFlow`, explicit `LAUNCHFLOW_DATA_DIR`, and the process-level `%LOCALAPPDATA%\LaunchFlow-Dev` developer override remain unchanged. Path calculation is side-effect free; only `ensure_app_directories()` creates directories.

This completion records an abstraction boundary, not Linux or macOS product support. The legacy fallback deliberately preserves the previous `~/.local/share/LaunchFlow` result until XDG and macOS-native policies are implemented and validated on real target hosts. Phase 1a does not use Qt or `QStandardPaths`, does not alter resources, migration, identity, licensing, runtime execution, packaging, or plan schemas, and must not be used as evidence of non-Windows support.

### Phase 1b status — completed

Phase 1b adds a stdlib-only `CommandBackend` and frozen `CommandLaunchSpec` under `shared/platform/process.py`. The Windows backend owns exact cmd/PowerShell argv, the existing cmd double-quote environment workaround, `CREATE_NO_WINDOW` plus `STARTF_USESHOWWINDOW`/`SW_HIDE`, output decoding candidates, launch-error classification, and friendly failure explanations. `runtime/command_runner.py` remains the public execution facade and continues to own `Popen`, `shell=False`, `DEVNULL`, both PIPE streams, `communicate()`, and `CommandResult` assembly.

The standalone export builder materializes the same LaunchSpec and explanations into its copied embedded plan, avoiding a runtime dependency on the editor/source tree while removing the second platform-selection/argv implementation. Application, URL, and Wait branches remain unchanged. Non-Windows hosts retain the old `/bin/sh -c` path only through a clearly named legacy backend with no declared supported shells; Linux sh/bash and macOS zsh/bash remain future, separately validated work.

### Phase 1c status — completed

Phase 1c adds a stdlib-only `ApplicationLauncher` and frozen `ApplicationLaunchSpec` under `shared/platform/applications.py`. The Windows backend owns the existing target classification, direct-process versus `.lnk` shell-open mode, exact PowerShell script argv, working directory, argument order, `CREATE_NO_WINDOW`, optional minimized startup info, and three `DEVNULL` streams. `runtime/launcher_runtime.py` still owns `Popen`/`os.startfile`, keeps Application fire-and-forget, and does not wait, capture, or write internal launch metadata into user plan JSON.

The standalone export builder materializes the same Application spec into its deep-copied embedded plan and resolves bundled assets under `_MEIPASS/launchflow_assets`; the original plan and Application schema remain unchanged. URL, Command, and Wait execution are unchanged. `LegacyPosixApplicationLauncher` retains only the prior generic fallback and declares no supported target kinds, so this boundary is not Linux or macOS Application support.

### Phase 1d status — completed

Phase 1d adds a stdlib-only `UrlOpener` and frozen `UrlOpenSpec` under `shared/platform/urls.py`. On Windows, an empty or missing browser value still selects one `os.startfile(url)` call at the runtime boundary. An explicit browser path still selects one fire-and-forget `Popen([browser_path, url])` call with no cwd, stream redirection, hidden-window flags, startup info, wait, communicate, return-code read, or browser asset bundling. URL values are not parsed, repaired, or given an automatic scheme.

The standalone export builder materializes the same URL spec into its deep-copied internal plan, while preserving the embedded launcher's pre-existing string-trimming and failure-log boundary. A real temporary onefile smoke proves the explicit-browser branch with a local marker substitute; the default-browser call is verified through a mocked embedded runtime so automation never opens a real browser or external site. Command, Application, Wait, `UrlStep`, plan JSON, licensing, and packaging suffixes remain unchanged.

`LegacyPosixUrlOpener` retains only the prior explicit-browser process fallback and rejects default-browser opening as unsupported. Phase 1d does not implement `xdg-open`, `gio open`, macOS `open`, `webbrowser`, or Qt `QDesktopServices`; Linux and macOS URL support remain Planned and require native-host validation.

### Phase 1e status — completed

Phase 1e adds a stdlib-only `DesktopIntegration` under `shared/platform/desktop.py`, deliberately exposing only `open_directory(path)`. `shared.diagnostics.open_logs_directory()` remains the public facade and still obtains `get_logs_dir()`, creates it with `mkdir(parents=True, exist_ok=True)`, returns the same `Path`, and leaves raw errors to the existing callers.

On Windows, `WindowsDesktopIntegration` performs the existing one-shot `os.startfile(str(path))` action with a delayed, injectable shell opener. It does not use explorer.exe, `cmd /c start`, `shell=True`, Qt, a process wait, return code, thread, cwd change, environment mutation, path-existence probe, or new logging. Linux, macOS, and unknown platforms use a compatibility-only silent no-op, exactly matching the previous guarded branch; no native support is claimed.

AppUserModelID and all icon/resource behavior remain in `shared/app_icon.py` and were intentionally not merged into this slice. Phase 1e also leaves diagnostic labels/redaction, AppPaths, Command, Application, URL, Wait, editor UI, packaging, plans, HWID, and licensing unchanged.

### Phase 1f status — completed

Phase 1f adds `DesktopIntegration.configure_application_identity(app_id)` without introducing a new module or changing any caller. `shared.app_icon.configure_windows_app_id()` remains the stable public facade with the exact `forgottenlab.launchflow.editor` default, `-> bool` result, handled `AttributeError`/`OSError`, and propagation of every other exception. `editor/main.py` still calls it exactly once before constructing QApplication.

The Windows backend resolves `ctypes.windll.shell32` only when identity is configured and forwards the AppUserModelID exactly once. Linux, macOS, and unknown backends preserve the previous `False` no-op without accessing a Windows API. Source/frozen ICO resolution, QIcon loading, QApplication/MainWindow/ActivationWindow icons, PyInstaller icon arguments, directory opening, diagnostics, runtime backends, plans, HWID, licensing, and release artifacts are unchanged. This is an identity boundary, not native Linux/macOS desktop integration.

### Phase 1g status — completed

Phase 1g adds a stdlib-only `DiagnosticsPresentationProvider` under `shared/platform/diagnostics.py`. It owns only the exact platform field label and ordered path aliases consumed by `shared/diagnostics.py`; log reading, report field order, masking, clipboard, UI presentation, and logs-directory opening remain with their existing owners. The Windows provider keeps `Windows`, `%LOCALAPPDATA%`, and `%USERPROFILE%` exactly, including LOCALAPPDATA-first replacement and empty-source suppression.

Linux, macOS, and unknown selection uses `LegacyPosixDiagnosticsPresentationProvider`, not the Windows provider. That fallback deliberately emits the historical Windows label and aliases so existing output remains compatible; it is not native diagnostics presentation or a support claim. A fixed full-report fixture verifies character-for-character Windows output, while native Linux/macOS labels and aliases remain Planned and require separately scoped host validation.

### Phase 1h status — completed

Phase 1h adds a stdlib-only `ShortcutPolicy` and frozen seven-field `ShortcutProfile` under `shared/platform/shortcuts.py`. The Windows provider owns the exact `Ctrl+S`, `Ctrl+Shift+S`, `Ctrl+R`, `Ctrl+E`, `Delete`, `Alt+Up`, and `Alt+Down` strings. `editor/ui/main_window.py` retains the existing `SHORTCUTS` dict name/type/key set and consumes profile values without moving or recreating any QAction.

The QAction attributes, Chinese text, Window/WidgetWithChildren contexts, enabled/checkable state, menu order, top-button order, tooltips, signal handlers, draft commit, deep-copied trial/export snapshots, Delete focus semantics, and ordinary text editing shortcuts remain frozen by an independent offscreen smoke. Qt StandardKey Save/SaveAs/Delete each resolved to one equivalent Windows sequence, but there is no Run/Export StandardKey and a partial conversion would split the seven-item source of truth and the maintained `Delete` tooltip label. StandardKey was therefore audited but not adopted.

Linux, macOS, and unknown use `LegacyShortcutPolicy` with the historical Ctrl/Alt strings. This is compatibility-only and does not implement Command-key conventions, native menu presentation, or physical keyboard support. Those claims still require real target-host validation.

## Phase 2 — Linux x86_64 source-run experimental target

| Field | Definition |
|---|---|
| Goal | Start and exercise the editor from source on a declared Linux x86_64 desktop without claiming a release. |
| In scope | XDG paths; explicit sh/bash capability; ordinary executables; evaluated `.sh`/`.desktop`/AppImage policies; default URL; desktop integration; portability diagnostics. |
| Out of scope | Public Linux Beta, Linux arm64, packaged editor, exported launcher, final offline activation support. |
| Files likely affected | Linux implementations under `shared/platform/`, focused UI capability/filter wiring, new Linux-native checks/docs. |
| Tests required | XDG overrides; argv/output/exit/signal/permission/missing-command/locale; URL/application; Qt offscreen; real GNOME/KDE or a documented narrower desktop scope. |
| Exit criteria | Source editor starts on a real Linux x86_64 host; neutral plan features pass; Windows-only plan values fail clearly before execution. |
| Rollback boundary | Backend remains experimental and selectable only by detection; Windows backend and public support declaration remain untouched. |

## Phase 3 — macOS arm64 source-run experimental target

This phase prioritizes Apple Silicon and must include an M3-class real device. macOS x86_64 and universal2 remain future considerations.

| Field | Definition |
|---|---|
| Goal | Start and exercise the editor from source on macOS arm64 without claiming a packaged release. |
| In scope | Application Support/Logs/Caches; zsh/bash policy; Unix executables, `.command`, `.app`, native open/default browser; Qt StandardKey/Command menu behavior; Dock/icon development resources. |
| Out of scope | x86_64/universal2 support, signed/notarized `.app`, `.dmg`, exported launcher, final offline activation support. |
| Files likely affected | macOS implementations under `shared/platform/`, focused menu/filter integration, macOS-native checks/docs. |
| Tests required | Real arm64/M3 source launch, `.app` and executable arguments/working dir, default browser, menu/focus/accessibility, fonts/theme/Retina, headless error behavior. |
| Exit criteria | Source editor starts on real macOS arm64; neutral behaviors pass; native UI checklist is recorded; no Windows regression. |
| Rollback boundary | Experimental backend/resources can be removed without changing Windows paths, identity, plan JSON, or license acceptance. |

## Cross-cutting identity and license gate

Before either experimental target can support offline activation publicly, write and approve a threat/privacy/migration design covering stable native sources, permissions, collision risk, reinstall/disk/hostname/user/VM/container/clone/dual-boot/architecture transitions, provider versioning, recovery/reissue, and administrator support. Preserve the current Windows algorithm and every accepted `LFREQ1`/`lflic-1`. If platform/architecture becomes signed metadata, introduce a compatible new version rather than changing existing canonical payloads.

## Phase 4 — Native editor packaging per platform

| Field | Definition |
|---|---|
| Goal | Produce a native editor artifact on each target OS through `PackagingBackend`. |
| In scope | Windows EXE preservation; Linux ELF/AppImage evaluation; macOS arm64 `.app`/`.dmg`, icons/bundle metadata; resource/public-key lookup; clean-host launch. |
| Out of scope | Cross-compilation, universal2 unless separately approved, user plan launcher export, release publication. |
| Files likely affected | Platform packaging backends, native assets/spec inputs, platform-specific build/validation tools and docs. |
| Tests required | Build on same OS, frozen startup, data isolation, no-secret scan, public-key resource, native icon, clean user profile; macOS signing/Gatekeeper experiments. |
| Exit criteria | Reproducible native artifact and clean-host evidence for each claimed architecture; no claim for untested artifact types. |
| Rollback boundary | Windows builder remains authoritative until another backend independently passes; artifacts are not published automatically. |

PyInstaller may remain an implementation, but Windows builds Windows, Linux builds Linux, and macOS builds macOS.

## Phase 5 — Current-platform launcher export

| Field | Definition |
|---|---|
| Goal | Export a plan launcher only for the OS/architecture currently running the editor. |
| In scope | Native artifact names, packable asset policy, shared/generated execution backend, output validation, portability warnings. |
| Out of scope | Cross-platform export from one host, automatic bundling of complex third-party apps, plan/schema changes. |
| Files likely affected | `PackagingBackend`, export UI/service, replacement/generation of `EMBEDDED_TEMPLATE`, per-platform export tests. |
| Tests required | Current-host build/run, asset origin, raw command results, URL/Application/Wait, original-plan immutability, data-dir isolation, dependency/error messages. |
| Exit criteria | Native exported launcher runs on clean matching host; unsupported local assets are rejected or explained; Windows export remains equivalent. |
| Rollback boundary | Keep export backend gated by capability; failure disables only that platform's export, not plan editing/running. |

## Phase 6 — CI, signing, notarization, and release automation

| Field | Definition |
|---|---|
| Goal | Turn independently proven native workflows into repeatable release gates and truthful support declarations. |
| In scope | Platform-labelled unit/mock/offscreen/native/physical/frozen jobs, Windows signing policy, Linux release scope, macOS Code Signing/Hardened Runtime/Notarization/Gatekeeper, checksums and release docs. |
| Out of scope | Creating CI in the audit task, automatic release without approval, unsupported architectures, weakening security gates. |
| Files likely affected | Future CI/release workflows, signing configuration references, release validation tools, support docs/matrix. |
| Tests required | Editor/activation/four steps/save/history/data isolation/public key/no-secret/export/physical UI on every claimed platform and architecture. |
| Exit criteria | Every `Supported` matrix row has current native evidence and rollback/reissue procedures; release wording matches artifacts. |
| Rollback boundary | A failed platform gate removes that platform from the release, never downgrades Windows or bypasses signing/license checks. |

## Recommended next implementation task

Prepare a separately scoped **Phase 1i HardwareIdentityProvider audit**. Freeze the current Windows MachineGuid/volume/fallback inputs, canonical machine ID output, accepted license compatibility, error boundaries, and privacy behavior before proposing an adapter. This recommendation is planning only: do not change HWID, `LFREQ1`, `lflic-1`, RSA, licensing, packaging, or support claims without a new explicit task.
