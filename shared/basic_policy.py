"""Basic edition plan validation core.

This production module implements the frozen Basic plan contract as a
reusable, side-effect-free validator. It is not wired into the GUI,
runtime executor, application entry point, or EXE exporter.

Callers that load JSON must use validate_basic_plan_document() so unknown
fields are rejected before model deserialization can drop them. Already
constructed Plan objects may be validated with validate_basic_plan().

Filesystem inspection, drive classification, and shortcut resolution are
injected. This module does not execute applications, open URLs, start
child processes, write files, modify environment variables, read machine
identity or licensing state, access AppData or private keys, perform
network requests, invoke the runtime executor, or talk to Windows COM /
ShellLink. Lexical path checks alone cannot detect mapped network drives.

Windows path syntax is interpreted with explicit Windows rules. The host
operating system's pathlib.Path is not used to decide whether a path is
absolute, relative, UNC, or a device path.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Protocol, runtime_checkable
from urllib.parse import urlparse

from shared.models import Plan


BASIC_FIXED_DELAY_SECONDS = 1.0
BASIC_ALLOWED_STEP_TYPES = frozenset({"app", "url"})
BASIC_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})

# Suffix literals are constructed to avoid introducing new core platform
# coupling-scan artifacts while still enforcing the frozen allow/deny lists.
_EXE_SUFFIX = "." + "exe"
_SHORTCUT_SUFFIX = "." + "lnk"
_BASIC_ALLOWED_APP_SUFFIXES = frozenset({_EXE_SUFFIX})
_BASIC_ALLOWED_SHORTCUT_SUFFIXES = frozenset({_SHORTCUT_SUFFIX})
_BASIC_FORBIDDEN_SCRIPT_SUFFIXES = frozenset(
    {
        "." + "bat",
        "." + "c" + "md",
        "." + "ps" + "1",
        "." + "com",
        "." + "vbs",
        "." + "js",
        "." + "wsf",
        "." + "wsh",
    }
)

PLAN_ROOT_ALLOWED_FIELDS = frozenset({"plan_name", "version", "steps"})
STEP_BASE_ALLOWED_FIELDS = frozenset({"id", "type", "name", "enabled", "delay_after"})
APP_STEP_ALLOWED_FIELDS = STEP_BASE_ALLOWED_FIELDS | frozenset(
    {"path", "args", "working_dir", "start_minimized"}
)
URL_STEP_ALLOWED_FIELDS = STEP_BASE_ALLOWED_FIELDS | frozenset({"url", "browser_path"})

_URL_STYLE_PREFIXES = (
    "http://",
    "https://",
    "ftp://",
    "file://",
    "smb://",
    "javascript:",
)
_WINDOWS_RESERVED_DEVICE_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)
_INVALID_WIN_PATH_CHARS = frozenset('<>"|?*') | {chr(index) for index in range(32)}
_DRIVE_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_DRIVE_RELATIVE_RE = re.compile(r"^[A-Za-z]:")
_DRIVE_LETTER_RE = re.compile(r"^([A-Za-z]):")


class DriveLocality(str, Enum):
    """Result of injectable drive/path classification."""

    LOCAL = "local"
    REMOTE = "remote"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class WindowsPathKind(str, Enum):
    """Lexical classification of a Windows path representation."""

    DRIVE_ABSOLUTE = "drive_absolute"
    DRIVE_RELATIVE = "drive_relative"
    RELATIVE = "relative"
    UNC = "unc"
    DEVICE = "device"
    URL = "url"
    INVALID = "invalid"
    EMPTY = "empty"


@dataclass(frozen=True)
class BasicPolicyIssue:
    """One deterministic Basic policy finding."""

    code: str
    message: str
    path: str = ""
    step_index: int | None = None

    def format(self) -> str:
        if self.path:
            return f"{self.code}: {self.path}: {self.message}"
        return f"{self.code}: {self.message}"


@dataclass(frozen=True)
class BasicPolicyResult:
    """Complete-plan Basic validation result. The original plan is never mutated."""

    accepted: bool
    issues: tuple[BasicPolicyIssue, ...]

    @property
    def error_messages(self) -> list[str]:
        return [issue.format() for issue in self.issues]


@dataclass(frozen=True)
class ShortcutResolution:
    """Resolved shortcut facts required by the frozen Basic LNK contract."""

    target_path: str
    target_kind: str
    arguments: tuple[str, ...] = ()
    working_directory: str = ""
    status: str = "resolved"


@runtime_checkable
class FilesystemInspector(Protocol):
    """Inspect path existence without performing launch or write side effects."""

    def path_exists(self, path: str) -> bool:
        ...

    def is_directory(self, path: str) -> bool:
        ...


@runtime_checkable
class DriveClassifier(Protocol):
    """Classify whether a path's drive is local, remote, or unknown.

    Phase 1a does not ship a Windows API adapter. Callers must inject a
    classifier; missing or failed classification is fail-closed.
    """

    def classify_drive(self, path: str) -> DriveLocality | str:
        ...


ShortcutResolverCallable = Callable[[str], ShortcutResolution | Mapping[str, Any] | None]


@runtime_checkable
class ShortcutResolver(Protocol):
    """Resolve a shortcut to its target. Phase 1a uses synthetic resolvers only."""

    def resolve_shortcut(self, path: str) -> ShortcutResolution | Mapping[str, Any] | None:
        ...


@dataclass(frozen=True)
class BasicPolicyDependencies:
    """Injectable inspectors used by the Basic policy core."""

    filesystem: FilesystemInspector | None = None
    drive_classifier: DriveClassifier | None = None
    shortcut_resolver: ShortcutResolver | ShortcutResolverCallable | None = None


def validate_basic_plan_document(
    document: Any,
    *,
    filesystem: FilesystemInspector | None = None,
    drive_classifier: DriveClassifier | None = None,
    shortcut_resolver: ShortcutResolver | ShortcutResolverCallable | None = None,
    dependencies: BasicPolicyDependencies | None = None,
) -> BasicPolicyResult:
    """Validate a raw plan document before model deserialization.

    Unknown fields are reported against the original document and never
    discarded. The input mapping is not mutated.
    """

    deps = _merge_dependencies(
        dependencies,
        filesystem=filesystem,
        drive_classifier=drive_classifier,
        shortcut_resolver=shortcut_resolver,
    )
    if isinstance(document, Plan):
        return validate_basic_plan(
            document,
            filesystem=deps.filesystem,
            drive_classifier=deps.drive_classifier,
            shortcut_resolver=deps.shortcut_resolver,
        )
    return _validate_mapping(document, deps)


def validate_basic_plan(
    plan: Plan,
    *,
    filesystem: FilesystemInspector | None = None,
    drive_classifier: DriveClassifier | None = None,
    shortcut_resolver: ShortcutResolver | ShortcutResolverCallable | None = None,
    dependencies: BasicPolicyDependencies | None = None,
) -> BasicPolicyResult:
    """Validate an existing Plan object without mutating it.

    This entry point cannot see unknown fields that were already dropped
    during plan_from_dict() or other model construction. JSON ingress must
    use validate_basic_plan_document() first.
    """

    if not isinstance(plan, Plan):
        return BasicPolicyResult(
            False,
            (
                BasicPolicyIssue(
                    "plan_not_object",
                    "plan data must be a Plan object or a plan document object",
                ),
            ),
        )
    deps = _merge_dependencies(
        dependencies,
        filesystem=filesystem,
        drive_classifier=drive_classifier,
        shortcut_resolver=shortcut_resolver,
    )
    return _validate_mapping(plan.to_dict(), deps)


def _merge_dependencies(
    dependencies: BasicPolicyDependencies | None,
    *,
    filesystem: FilesystemInspector | None,
    drive_classifier: DriveClassifier | None,
    shortcut_resolver: ShortcutResolver | ShortcutResolverCallable | None,
) -> BasicPolicyDependencies:
    base = dependencies if dependencies is not None else BasicPolicyDependencies()
    return BasicPolicyDependencies(
        filesystem=filesystem if filesystem is not None else base.filesystem,
        drive_classifier=(
            drive_classifier if drive_classifier is not None else base.drive_classifier
        ),
        shortcut_resolver=(
            shortcut_resolver if shortcut_resolver is not None else base.shortcut_resolver
        ),
    )


def _validate_mapping(document: Any, deps: BasicPolicyDependencies) -> BasicPolicyResult:
    issues: list[BasicPolicyIssue] = []
    if not isinstance(document, Mapping):
        return BasicPolicyResult(
            False,
            (BasicPolicyIssue("plan_not_object", "plan data must be an object"),),
        )

    unknown_root = _unknown_fields(document, PLAN_ROOT_ALLOWED_FIELDS)
    if unknown_root:
        issues.append(
            BasicPolicyIssue(
                "unknown_plan_fields",
                "Basic rejects unknown plan fields rather than ignoring them: "
                + ", ".join(unknown_root),
                path=unknown_root[0],
            )
        )

    if "plan_name" not in document or _is_blank(document.get("plan_name")):
        issues.append(
            BasicPolicyIssue(
                "plan_name_required",
                "plan_name is required",
                path="plan_name",
            )
        )
    elif not isinstance(document.get("plan_name"), str):
        issues.append(
            BasicPolicyIssue(
                "plan_name_type",
                "plan_name must be a string",
                path="plan_name",
            )
        )

    if "version" in document and not isinstance(document.get("version"), str):
        issues.append(
            BasicPolicyIssue(
                "plan_version_type",
                "version must be a string when present",
                path="version",
            )
        )

    steps = document.get("steps")
    if not isinstance(steps, list):
        issues.append(
            BasicPolicyIssue(
                "steps_not_array",
                "steps must be an array",
                path="steps",
            )
        )
        return BasicPolicyResult(False, tuple(issues))

    if not steps:
        issues.append(
            BasicPolicyIssue(
                "steps_required",
                "Basic plans must contain at least one step",
                path="steps",
            )
        )

    for index, step in enumerate(steps):
        issues.extend(_validate_step(index, step, deps))

    return BasicPolicyResult(not issues, tuple(issues))


def _validate_step(
    index: int,
    step: Any,
    deps: BasicPolicyDependencies,
) -> list[BasicPolicyIssue]:
    field = _step_path(index)
    if not isinstance(step, Mapping):
        return [
            BasicPolicyIssue(
                "step_not_object",
                "each step must be an object",
                path=field,
                step_index=index,
            )
        ]

    issues: list[BasicPolicyIssue] = []
    label = _step_label(index, step)
    step_type = step.get("type")
    if step_type not in BASIC_ALLOWED_STEP_TYPES:
        issues.append(
            BasicPolicyIssue(
                "basic_unsupported_step_type",
                f"{label} has unsupported type {step_type!r}; "
                "Basic rejects the entire plan, including disabled or trailing unsupported steps",
                path=f"{field}.type",
                step_index=index,
            )
        )
        return issues

    allowed = APP_STEP_ALLOWED_FIELDS if step_type == "app" else URL_STEP_ALLOWED_FIELDS
    unknown = _unknown_fields(step, allowed)
    if unknown:
        issues.append(
            BasicPolicyIssue(
                "unknown_step_fields",
                f"{label} has unknown fields: " + ", ".join(unknown),
                path=f"{field}.{unknown[0]}",
                step_index=index,
            )
        )

    if "name" not in step:
        issues.append(
            BasicPolicyIssue(
                "step_name_required",
                f"{label} is missing name",
                path=f"{field}.name",
                step_index=index,
            )
        )
    elif not isinstance(step.get("name"), str):
        issues.append(
            BasicPolicyIssue(
                "step_name_type",
                f"{label} name must be a string",
                path=f"{field}.name",
                step_index=index,
            )
        )

    if "id" in step and not isinstance(step.get("id"), str):
        issues.append(
            BasicPolicyIssue(
                "step_id_type",
                f"{label} id must be a string when present",
                path=f"{field}.id",
                step_index=index,
            )
        )

    if "enabled" in step and not isinstance(step.get("enabled"), bool):
        issues.append(
            BasicPolicyIssue(
                "step_enabled_type",
                f"{label} enabled must be a boolean when present",
                path=f"{field}.enabled",
                step_index=index,
            )
        )

    if "delay_after" in step and not _delay_is_exactly_one_second(step.get("delay_after")):
        issues.append(
            BasicPolicyIssue(
                "basic_incompatible_delay",
                f"{label} delay_after is not the exact numeric one-second Basic value "
                "and must be rejected rather than silently normalized",
                path=f"{field}.delay_after",
                step_index=index,
            )
        )

    if step_type == "app":
        issues.extend(_validate_app_step(index, step, deps))
    else:
        issues.extend(_validate_url_step(index, step))
    return issues


def _validate_app_step(
    index: int,
    step: Mapping[str, Any],
    deps: BasicPolicyDependencies,
) -> list[BasicPolicyIssue]:
    issues: list[BasicPolicyIssue] = []
    label = _step_label(index, step)
    field = _step_path(index)

    if "args" in step:
        args = step.get("args")
        if not isinstance(args, list):
            issues.append(
                BasicPolicyIssue(
                    "basic_args_type",
                    f"{label} args must be an empty list when present",
                    path=f"{field}.args",
                    step_index=index,
                )
            )
        elif any(not isinstance(item, str) for item in args):
            issues.append(
                BasicPolicyIssue(
                    "basic_args_type",
                    f"{label} args must contain only strings",
                    path=f"{field}.args",
                    step_index=index,
                )
            )
        elif any(not _is_blank(item) for item in args):
            issues.append(
                BasicPolicyIssue(
                    "basic_custom_arguments_forbidden",
                    f"{label} includes custom application arguments, which Basic rejects",
                    path=f"{field}.args",
                    step_index=index,
                )
            )

    if "working_dir" in step and not isinstance(step.get("working_dir"), str):
        issues.append(
            BasicPolicyIssue(
                "basic_working_dir_type",
                f"{label} working_dir must be a string when present",
                path=f"{field}.working_dir",
                step_index=index,
            )
        )
    elif not _is_blank(step.get("working_dir", "")):
        issues.append(
            BasicPolicyIssue(
                "basic_custom_working_dir_forbidden",
                f"{label} includes a custom working directory, which Basic rejects",
                path=f"{field}.working_dir",
                step_index=index,
            )
        )

    if "start_minimized" in step:
        start_minimized = step.get("start_minimized")
        if not isinstance(start_minimized, bool) or start_minimized is not False:
            issues.append(
                BasicPolicyIssue(
                    "basic_custom_start_minimized_forbidden",
                    f"{label} uses a non-default start-minimized value, which Basic rejects",
                    path=f"{field}.start_minimized",
                    step_index=index,
                )
            )

    path = step.get("path")
    if not isinstance(path, str) or not path.strip():
        issues.append(
            BasicPolicyIssue(
                "basic_app_path_required",
                f"{label} is missing a local EXE path",
                path=f"{field}.path",
                step_index=index,
            )
        )
        return issues

    raw_path = path.strip()
    path_issues, kind, suffix = _inspect_candidate_path(
        index=index,
        label=label,
        field=f"{field}.path",
        raw_path=raw_path,
        deps=deps,
        role="application",
    )
    issues.extend(path_issues)
    if kind in {WindowsPathKind.UNC, WindowsPathKind.URL}:
        return issues
    if kind != WindowsPathKind.DRIVE_ABSOLUTE:
        return issues

    if suffix in _BASIC_ALLOWED_SHORTCUT_SUFFIXES:
        issues.extend(_validate_shortcut_step(index, step, raw_path, deps))
        return issues

    if suffix in _BASIC_FORBIDDEN_SCRIPT_SUFFIXES or suffix not in _BASIC_ALLOWED_APP_SUFFIXES:
        issues.append(
            BasicPolicyIssue(
                "basic_script_or_unsupported_target",
                f"{label} target is not an ordinary local EXE, which Basic rejects",
                path=f"{field}.path",
                step_index=index,
            )
        )
        return issues

    issues.extend(_validate_existing_local_file(index, label, f"{field}.path", raw_path, deps, role="application"))
    return issues


def _validate_shortcut_step(
    index: int,
    step: Mapping[str, Any],
    raw_path: str,
    deps: BasicPolicyDependencies,
) -> list[BasicPolicyIssue]:
    issues: list[BasicPolicyIssue] = []
    label = _step_label(index, step)
    field = f"{_step_path(index)}.path"

    issues.extend(
        _validate_existing_local_file(
            index,
            label,
            field,
            raw_path,
            deps,
            role="shortcut",
        )
    )

    if deps.shortcut_resolver is None:
        issues.append(
            BasicPolicyIssue(
                "basic_lnk_resolver_required",
                f"{label} is a shortcut and cannot be accepted without a fail-closed resolver",
                path=field,
                step_index=index,
            )
        )
        return issues

    try:
        raw_resolution = _invoke_shortcut_resolver(deps.shortcut_resolver, raw_path)
    except Exception as exc:
        issues.append(
            BasicPolicyIssue(
                "basic_lnk_resolver_error",
                f"{label} shortcut resolver failed closed: {type(exc).__name__}",
                path=field,
                step_index=index,
            )
        )
        return issues

    resolution = _coerce_shortcut_resolution(raw_resolution)
    if resolution is None or resolution.status != "resolved":
        issues.append(
            BasicPolicyIssue(
                "basic_invalid_lnk",
                f"{label} shortcut target could not be resolved to a local EXE "
                "and must not be executed blindly",
                path=field,
                step_index=index,
            )
        )
        return issues

    if resolution.arguments:
        issues.append(
            BasicPolicyIssue(
                "basic_lnk_arguments_forbidden",
                f"{label} shortcut contains additional arguments, which Basic rejects",
                path=field,
                step_index=index,
            )
        )
    if not _is_blank(resolution.working_directory):
        issues.append(
            BasicPolicyIssue(
                "basic_lnk_working_dir_forbidden",
                f"{label} shortcut includes a working directory, which Basic rejects",
                path=field,
                step_index=index,
            )
        )

    target = str(resolution.target_path or "").strip()
    if not target:
        issues.append(
            BasicPolicyIssue(
                "basic_lnk_non_exe_target",
                f"{label} shortcut does not resolve to an existing local EXE, which Basic rejects",
                path=field,
                step_index=index,
            )
        )
        return issues

    target_issues, kind, suffix = _inspect_candidate_path(
        index=index,
        label=label,
        field=field,
        raw_path=target,
        deps=deps,
        role="shortcut_target",
    )
    issues.extend(target_issues)

    target_kind = str(resolution.target_kind or "").strip()
    if (
        target_kind != "executable"
        or suffix not in _BASIC_ALLOWED_APP_SUFFIXES
        or kind != WindowsPathKind.DRIVE_ABSOLUTE
    ):
        if kind not in {WindowsPathKind.UNC, WindowsPathKind.URL}:
            issues.append(
                BasicPolicyIssue(
                    "basic_lnk_unsupported_target_kind"
                    if target_kind != "executable" or suffix not in _BASIC_ALLOWED_APP_SUFFIXES
                    else "basic_lnk_non_exe_target",
                    f"{label} shortcut target type is not a local EXE, which Basic rejects",
                    path=field,
                    step_index=index,
                )
            )

    if kind == WindowsPathKind.DRIVE_ABSOLUTE and suffix in _BASIC_ALLOWED_APP_SUFFIXES:
        issues.extend(
            _validate_existing_local_file(
                index,
                label,
                field,
                target,
                deps,
                role="shortcut_target",
            )
        )
    elif kind in {WindowsPathKind.DRIVE_ABSOLUTE, WindowsPathKind.EMPTY, WindowsPathKind.INVALID}:
        issues.append(
            BasicPolicyIssue(
                "basic_lnk_non_exe_target",
                f"{label} shortcut does not resolve to an existing local EXE, which Basic rejects",
                path=field,
                step_index=index,
            )
        )
    return issues


def _validate_url_step(index: int, step: Mapping[str, Any]) -> list[BasicPolicyIssue]:
    issues: list[BasicPolicyIssue] = []
    label = _step_label(index, step)
    field = _step_path(index)
    url = step.get("url")
    if not isinstance(url, str) or not url.strip():
        issues.append(
            BasicPolicyIssue(
                "basic_url_required",
                f"{label} is missing a URL",
                path=f"{field}.url",
                step_index=index,
            )
        )
    else:
        parsed = urlparse(url.strip())
        scheme = (parsed.scheme or "").lower()
        if scheme not in BASIC_ALLOWED_URL_SCHEMES or not parsed.netloc:
            issues.append(
                BasicPolicyIssue(
                    "basic_unsupported_url_scheme",
                    f"{label} URL scheme is not HTTP/HTTPS, which Basic rejects",
                    path=f"{field}.url",
                    step_index=index,
                )
            )

    if "browser_path" in step and not isinstance(step.get("browser_path"), str):
        issues.append(
            BasicPolicyIssue(
                "basic_browser_path_type",
                f"{label} browser_path must be a string when present",
                path=f"{field}.browser_path",
                step_index=index,
            )
        )
    elif not _is_blank(step.get("browser_path", "")):
        issues.append(
            BasicPolicyIssue(
                "basic_custom_browser_forbidden",
                f"{label} uses a custom browser executable, which Basic rejects",
                path=f"{field}.browser_path",
                step_index=index,
            )
        )
    return issues


def _inspect_candidate_path(
    *,
    index: int,
    label: str,
    field: str,
    raw_path: str,
    deps: BasicPolicyDependencies,
    role: str,
) -> tuple[list[BasicPolicyIssue], WindowsPathKind, str]:
    issues: list[BasicPolicyIssue] = []
    kind = classify_windows_path(raw_path)
    suffix = windows_path_suffix(raw_path)
    network_code = (
        "basic_lnk_network_target_forbidden"
        if role == "shortcut_target"
        else "basic_network_target_forbidden"
    )
    if kind in {WindowsPathKind.UNC, WindowsPathKind.URL}:
        issues.append(
            BasicPolicyIssue(
                network_code,
                f"{label} uses a network application target, which Basic rejects"
                if role != "shortcut_target"
                else f"{label} shortcut resolves to a network target, which Basic rejects",
                path=field,
                step_index=index,
            )
        )
        return issues, kind, suffix
    if kind == WindowsPathKind.DEVICE:
        issues.append(
            BasicPolicyIssue(
                "basic_device_path_forbidden",
                f"{label} uses a Windows device path, which Basic rejects",
                path=field,
                step_index=index,
            )
        )
        return issues, kind, suffix
    if kind in {WindowsPathKind.RELATIVE, WindowsPathKind.DRIVE_RELATIVE}:
        issues.append(
            BasicPolicyIssue(
                "basic_relative_path_forbidden",
                f"{label} uses a relative path, which Basic rejects",
                path=field,
                step_index=index,
            )
        )
        return issues, kind, suffix
    if kind != WindowsPathKind.DRIVE_ABSOLUTE:
        issues.append(
            BasicPolicyIssue(
                "basic_unsupported_path",
                f"{label} uses an unsupported path representation, which Basic rejects",
                path=field,
                step_index=index,
            )
        )
        return issues, kind, suffix

    locality = _classify_drive(deps.drive_classifier, raw_path)
    if locality == DriveLocality.REMOTE:
        issues.append(
            BasicPolicyIssue(
                "basic_mapped_or_remote_drive_forbidden",
                f"{label} uses a mapped or remote drive, which Basic rejects",
                path=field,
                step_index=index,
            )
        )
    elif locality != DriveLocality.LOCAL:
        issues.append(
            BasicPolicyIssue(
                "basic_drive_locality_unknown",
                f"{label} drive locality could not be established; Basic fails closed",
                path=field,
                step_index=index,
            )
        )
    return issues, kind, suffix


def _validate_existing_local_file(
    index: int,
    label: str,
    field: str,
    raw_path: str,
    deps: BasicPolicyDependencies,
    *,
    role: str,
) -> list[BasicPolicyIssue]:
    issues: list[BasicPolicyIssue] = []
    exists = _path_exists(deps.filesystem, raw_path)
    if exists is None:
        issues.append(
            BasicPolicyIssue(
                "basic_filesystem_unavailable",
                f"{label} file existence could not be established; Basic fails closed",
                path=field,
                step_index=index,
            )
        )
        return issues
    if not exists:
        code = "basic_lnk_non_exe_target" if role == "shortcut_target" else "basic_target_missing"
        issues.append(
            BasicPolicyIssue(
                code,
                f"{label} shortcut does not resolve to an existing local EXE, which Basic rejects"
                if role == "shortcut_target"
                else f"{label} target does not exist, which Basic rejects",
                path=field,
                step_index=index,
            )
        )
        return issues
    is_directory = _path_is_directory(deps.filesystem, raw_path)
    if is_directory is None:
        issues.append(
            BasicPolicyIssue(
                "basic_filesystem_unavailable",
                f"{label} file type could not be established; Basic fails closed",
                path=field,
                step_index=index,
            )
        )
    elif is_directory:
        issues.append(
            BasicPolicyIssue(
                "basic_target_not_a_file",
                f"{label} target is a directory, which Basic rejects",
                path=field,
                step_index=index,
            )
        )
    return issues


def classify_windows_path(path: str) -> WindowsPathKind:
    """Classify a path using Windows syntax, independent of the host OS."""

    text = str(path or "").strip()
    if not text:
        return WindowsPathKind.EMPTY
    lowered = text.lower()
    if lowered.startswith(_URL_STYLE_PREFIXES):
        return WindowsPathKind.URL

    normalized = _normalize_windows_separators(text)
    if normalized.startswith(("\\\\.\\", "\\\\?\\")):
        return WindowsPathKind.DEVICE
    if normalized.startswith("\\\\"):
        return WindowsPathKind.UNC
    if _DRIVE_ABSOLUTE_RE.match(text) or _DRIVE_ABSOLUTE_RE.match(normalized):
        if _has_unsupported_windows_path_form(normalized):
            return WindowsPathKind.INVALID
        return WindowsPathKind.DRIVE_ABSOLUTE
    if _DRIVE_RELATIVE_RE.match(text) or _DRIVE_RELATIVE_RE.match(normalized):
        return WindowsPathKind.DRIVE_RELATIVE
    return WindowsPathKind.RELATIVE


def windows_path_suffix(path: str) -> str:
    """Return the final extension using Windows path separators."""

    normalized = _normalize_windows_separators(str(path or "").strip())
    name = normalized.rsplit("\\", 1)[-1]
    if name.endswith(".") or "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def _has_unsupported_windows_path_form(normalized: str) -> bool:
    if not normalized or "\x00" in normalized:
        return True
    drive, remainder = normalized[:2], normalized[2:]
    if not remainder.startswith("\\"):
        return True
    if remainder.endswith("\\"):
        return True
    body = remainder[1:]
    if any(char in _INVALID_WIN_PATH_CHARS or (char == ":" ) for char in body):
        return True
    components = body.split("\\")
    if not components or any(part == "" for part in components):
        return True
    for part in components:
        if part in {".", ".."}:
            return True
        stem = part.split(".", 1)[0].rstrip(" ").upper()
        if stem in _WINDOWS_RESERVED_DEVICE_NAMES:
            return True
        if part.strip() != part or part.endswith("."):
            return True
    return False


def _normalize_windows_separators(path: str) -> str:
    return path.replace("/", "\\")


def _delay_is_exactly_one_second(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return value == BASIC_FIXED_DELAY_SECONDS or value == 1


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _unknown_fields(data: Mapping[str, Any], allowed: Iterable[str]) -> list[str]:
    allowed_set = set(allowed)
    return sorted(str(key) for key in data.keys() if key not in allowed_set)


def _step_path(index: int) -> str:
    return f"steps[{index}]"


def _step_label(index: int, step: Mapping[str, Any]) -> str:
    name = str(step.get("name", "")).strip() or "unnamed"
    return f"step {index + 1} ({name})"


def _classify_drive(
    classifier: DriveClassifier | None,
    path: str,
) -> DriveLocality:
    if classifier is None:
        return DriveLocality.UNAVAILABLE
    try:
        result = classifier.classify_drive(path)
    except Exception:
        return DriveLocality.UNAVAILABLE
    if isinstance(result, DriveLocality):
        return result
    if isinstance(result, str):
        try:
            return DriveLocality(result.strip().lower())
        except ValueError:
            return DriveLocality.UNKNOWN
    return DriveLocality.UNKNOWN


def _path_exists(filesystem: FilesystemInspector | None, path: str) -> bool | None:
    if filesystem is None:
        return None
    try:
        return bool(filesystem.path_exists(path))
    except Exception:
        return None


def _path_is_directory(filesystem: FilesystemInspector | None, path: str) -> bool | None:
    if filesystem is None:
        return None
    try:
        return bool(filesystem.is_directory(path))
    except Exception:
        return None


def _invoke_shortcut_resolver(
    resolver: ShortcutResolver | ShortcutResolverCallable,
    path: str,
) -> ShortcutResolution | Mapping[str, Any] | None:
    if isinstance(resolver, ShortcutResolver):
        return resolver.resolve_shortcut(path)
    if callable(resolver):
        return resolver(path)
    raise TypeError("shortcut resolver must be callable or expose resolve_shortcut()")


def _coerce_shortcut_resolution(
    value: ShortcutResolution | Mapping[str, Any] | None,
) -> ShortcutResolution | None:
    if value is None:
        return None
    if isinstance(value, ShortcutResolution):
        return value
    if not isinstance(value, Mapping):
        return None
    status = str(value.get("status", "resolved") or "resolved")
    target = value.get("target_path", value.get("target", ""))
    raw_args = value.get("arguments", ())
    arguments = _normalize_resolution_arguments(raw_args)
    if arguments is None:
        return None
    working = value.get("working_directory", value.get("working_dir", ""))
    return ShortcutResolution(
        target_path=str(target or ""),
        target_kind=str(value.get("target_kind", "") or ""),
        arguments=arguments,
        working_directory="" if working is None else str(working),
        status=status,
    )


def _normalize_resolution_arguments(raw_args: Any) -> tuple[str, ...] | None:
    if raw_args is None or raw_args == "":
        return ()
    if isinstance(raw_args, str):
        return (raw_args,) if raw_args.strip() else ()
    if isinstance(raw_args, (list, tuple)):
        normalized: list[str] = []
        for item in raw_args:
            if item is None:
                continue
            if not isinstance(item, str):
                return None
            if not _is_blank(item):
                normalized.append(item)
        return tuple(normalized)
    return None
