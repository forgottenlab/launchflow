# macOS arm64 GitHub Actions Bootstrap

## Status

Phase 2a1 status is **macOS arm64 CI bootstrap prepared**. The target remains
**Planned / Experimental preparation**. Windows x86_64 is still the only
supported Beta target, and no result from this workflow changes the public
support matrix by itself.

The workflow is intentionally manual/branch-validation infrastructure. It is
not a release workflow and does not publish a GitHub Release.

## Why a Windows host cannot produce the evidence

Windows cannot build a native macOS application bundle with the same meaning as
a target-host build. PyInstaller packages for the OS on which it runs; Mach-O
architecture, `.app` layout, Info.plist generation, Qt Cocoa plugins, and native
process startup must be observed on macOS. Cross-compiling those claims from a
Windows machine would be misleading.

The repository therefore uses GitHub-hosted `macos-15` only as an ephemeral
Apple Silicon build and automated-test host. The runner must prove Darwin and
arm64 before installing or running the project checks.

## Workflow contract

`.github/workflows/macos-arm64-ci.yml` is triggered by an explicit dispatch and
by relevant pull-request or `main` changes. Its only repository permission is
`contents: read`. It has no secret reference, signing identity, certificate,
Apple service credential, deployment permission, or release-upload step.

The workflow records only allowlisted system facts:

- `uname -s`, `uname -m`, and `sw_vers`;
- safe `system_profiler` chip/core fields, excluding serial and hardware IDs;
- a path-sanitized Python executable, Python version, `platform.machine()`,
  sysconfig platform, and Git commit;
- exact allowlisted dependency versions.

It never dumps the environment, HOME, runner user, hostname, network fields, or
credential configuration.

## Isolated paths

All mutable paths are below `$RUNNER_TEMP`:

- `$RUNNER_TEMP/launchflow-data` for source runtime data;
- `$RUNNER_TEMP/launchflow-build` for PyInstaller work files;
- `$RUNNER_TEMP/launchflow-dist` for the app bundle;
- `$RUNNER_TEMP/launchflow-spec` for generated spec data;
- `$RUNNER_TEMP/launchflow-evidence` for reports, safe logs, and the screenshot;
- `$RUNNER_TEMP/launchflow-artifacts` for the final ZIP.

`QT_QPA_PLATFORM=offscreen`, `LAUNCHFLOW_DATA_DIR`, and bytecode-cache
isolation are set before imports. The workflow checks that production folders
and the repository remain unchanged.

## Safe import and source smoke

The full host smoke imports the requested modules one by one and treats every
exception as a failure. Import-time guards reject process launch, URL opening,
network calls, host/user identity helpers, sensitive file suffixes, and key
loader calls. It also proves that importing does not create a QApplication,
change cwd or environment, or write to the repository.

The offscreen gate directly constructs `MainWindow`; it does not call
`editor.main.main()`. It shows, processes events, captures a fixed synthetic
window screenshot, closes the window, and checks for remaining Qt threads. The
screenshot is only **Qt offscreen render evidence** and is **not real macOS manual GUI validation**.

Plan persistence uses a synthetic four-step plan in a temporary Unicode path
containing spaces. Command executes one fixed-output `/bin/sh` process through
the current compatibility backend. Wait uses a short duration. Application and
URL exercise only factories with injected existence fixtures and immutable
LaunchSpecs; no application or browser is started. Diagnostics uses a synthetic
path presentation and must redact the fixture home/request values. Shortcut
coverage is limited to injected macOS selection of the legacy policy; the full
Windows `check_shortcut_policy_smoke.py` remains skipped because its native-text
and QAction assertions intentionally freeze Windows behavior.

These checks do not claim that the legacy POSIX Application, URL, Command,
shortcut, path, or diagnostics fallbacks are native macOS implementations.

## Experimental builder and bundle evidence

`tools/build_macos_experimental.py` refuses every host except Darwin arm64 and
requires explicit absolute output paths below `$RUNNER_TEMP`. It invokes the
current interpreter with PyInstaller, `--clean`, `--noconfirm`, `--windowed`,
`--onedir`, arm64 targeting, and bundle identifier
`io.github.forgottenlab.launchflow`.

The output is unsigned by any Developer ID, not notarized, and non-production.
PyInstaller may apply an ad-hoc Mach-O signature as a platform build detail; the
bundle probe captures `codesign -dv` without printing it and rejects every
Authority/Team identity. No reviewed ICNS is configured, no DMG is created, and
no Windows artifact is overwritten. The required public build field remains
`signed=false` (no distribution identity), alongside `notarized=false` and
`production=false`; the bundle report separately records any ad-hoc status.

The bundle probe reads only bundle metadata and filenames. It verifies the
expected layout and Info.plist fields, checks the main executable and Mach-O
dependencies for arm64, requires the Qt Cocoa plugin, and rejects Windows EXE,
private-key, request, and license filenames. It does not execute bundle code,
load a key, parse a request/license, or print binary contents.

## Bundle launch boundary

The current application has **no identity-free ready marker**. On a missing
license, `editor.main.main()` constructs `ActivationWindow`; its constructor
immediately loads the display identity and generates a request code. Starting
the experimental bundle in an empty data directory would therefore violate the
Phase 2a1 prohibition on real identity and request generation.

`tools/macos_ci_launch_probe.py` consequently fails closed and reports
`BLOCKED`, `executed=false`, `identity_read=false`, and
`request_generated=false`. It writes fixed safe log placeholders but starts no
process. This is an expected evidence gap, not a successful launch smoke. A
future launch run requires a separately approved, production-safe startup seam
or ready marker that does not weaken licensing.

## Artifacts

The workflow uses `ditto` to create
`LaunchFlow-macos-arm64-experimental-unsigned.zip`. Upload is `if: always()`
with seven-day retention and an explicit allowlist containing only:

- the unsigned experimental app ZIP;
- build, bundle, source-smoke, launch-boundary, and coupling JSON reports;
- fixed safe launch log placeholders;
- allowlisted dependency versions;
- the offscreen screenshot.

It does not upload `$RUNNER_TEMP` as a whole, HOME, caches, Keychain data,
certificates, request/license artifacts, credentials, or environment dumps.
Before upload, `tools/macos_ci_report.py` stores only the coupling summary (not
raw finding evidence), verifies the exact evidence-file allowlist, scans every
text report/log for credential, token, PEM, private-key-path, and expanded user
path patterns, validates the PNG header, and scans ZIP entry names for sensitive
key/request/license suffixes. Only successfully scanned files are copied into
`$RUNNER_TEMP/launchflow-upload`; the always-run artifact step reads exclusively
from that curated directory. A finding fails the scan and leaves sensitive
evidence outside the upload source.

## Test classification

| Class | Phase 2a1 handling |
|---|---|
| `run-on-macos` | Phase 2a1 full smoke, platform coupling JSON, README/docs smoke |
| `run-with-injected-fixture` | Darwin/arm64 PlatformInfo, Application/URL LaunchSpecs, diagnostics masking, plan/model round trip |
| `windows-only-skip` | Windows command capture, current-host Windows path assertion, AppUserModelID/ICO, Dev PowerShell helper |
| `sensitive-skip` | real HWID, request generation, license signing/verification, private-key tests |
| `build-skip` | Windows editor release build, EXE export, Windows Release smoke |

Existing Windows assertions are not changed or weakened. A test is skipped
because its evidence belongs to another host or crosses an explicit sensitive
boundary, not to make the macOS job green.

## What CI can prove

After a real run, CI can prove the exact hosted runner architecture, pinned
dependency installation, safe source imports under the guards, isolated plan
I/O, an offscreen MainWindow render, a target-host PyInstaller bundle, selected
Info.plist values, and arm64 Mach-O presence. Failures provide concrete evidence
for the next scoped change.

Before the first real workflow run, this repository only proves that the CI
bootstrap and its Windows-side static checks are prepared. It must not say the
macOS arm64 CI passed.

## What CI cannot prove

An ephemeral runner cannot prove:

- stable hardware identity or an HWID design suitable for customer devices;
- durable behavior across reinstall, disk replacement, user migration, clones,
  virtualization, or OS upgrades;
- native window appearance, focus, keyboard/menu conventions, Retina behavior,
  Dock integration, accessibility, or real pointer interaction;
- normal application/URL launching or a licensed startup path;
- Developer ID signing, Hardened Runtime, notarization, stapling, Gatekeeper, or
  quarantine behavior;
- a clean-user production installation, supportability, or release readiness.

The ephemeral runner must never be used as stable hardware identity evidence.

## Manual Mac acceptance and later security work

Manual Mac acceptance remains mandatory on a physical Apple Silicon device,
including a clean user profile, source startup, signed-artifact startup when
that phase is authorized, menus/focus/keyboard, fonts/theme/Retina, Dock/icon,
file dialogs, Application/URL/Command behavior, data isolation, process cleanup,
and Gatekeeper/quarantine behavior.

Developer ID signing and notarization require a separate threat model,
credential-handling plan, least-privilege secrets, audit/rotation procedure, and
explicit release authorization. Phase 2a1 performs none of them.

## Next step

The next task is to review these uncommitted files, commit the workflow through
the normal repository process, observe the first real GitHub Actions run, and
triage only the evidence it produces. A later task may address a proven blocker;
it must not silently turn experimental CI into a support or release claim.
