"""LaunchFlow Dual Edition Phase 0 contract specification.

This module freezes Basic and Professional acceptance criteria for later
implementation. It is documentation-as-code for Phase 0 contract tests.

It is NOT wired into editor startup, the GUI, the runtime executor, the
production exporter, or licensing. Importing this module must have no
filesystem, network, license, or hardware-identity side effects.

Confirmed existing production behavior lives in editor/, runtime/, shared/,
licensing/, and tools/build_single_exe.py. Rules below that are marked as
frozen requirements must not be mistaken for current implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlparse


PHASE = "0"
BASIC_FIXED_DELAY_SECONDS = 1.0
BASIC_DATA_DIR_NAME = "LaunchFlow-Basic"
PROFESSIONAL_DATA_DIR_NAME = "LaunchFlow"

BASIC_ALLOWED_STEP_TYPES = frozenset({"app", "url"})
BASIC_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})
BASIC_ALLOWED_APP_SUFFIXES = frozenset({".exe"})
BASIC_ALLOWED_SHORTCUT_SUFFIXES = frozenset({".lnk"})
BASIC_FORBIDDEN_SCRIPT_SUFFIXES = frozenset({
    ".bat",
    ".cmd",
    ".ps1",
    ".com",
    ".vbs",
    ".js",
    ".wsf",
    ".wsh",
})

PLAN_ROOT_ALLOWED_FIELDS = frozenset({"plan_name", "version", "steps"})
STEP_BASE_ALLOWED_FIELDS = frozenset({"id", "type", "name", "enabled", "delay_after"})
APP_STEP_ALLOWED_FIELDS = STEP_BASE_ALLOWED_FIELDS | frozenset({
    "path",
    "args",
    "working_dir",
    "start_minimized",
})
URL_STEP_ALLOWED_FIELDS = STEP_BASE_ALLOWED_FIELDS | frozenset({"url", "browser_path"})
COMMAND_STEP_FIELDS = STEP_BASE_ALLOWED_FIELDS | frozenset({
    "command",
    "shell",
    "working_dir",
    "new_window",
})
WAIT_STEP_FIELDS = STEP_BASE_ALLOWED_FIELDS | frozenset({"seconds"})

ENTRY_POINTS = (
    "direct_json_load",
    "imported_plan",
    "template",
    "plan_history",
    "disabled_steps",
    "direct_model",
    "direct_executor",
    "export",
)

BASIC_RUNNER_FORBIDDEN_SUBSTRINGS = (
    "run_command_step",
    "run_wait_step",
    "licensing",
    "license_manager",
    "LicenseManager",
    "get_machine_id",
    "get_machine_fingerprint_parts",
    "HardwareIdentityProvider",
    "validate_current_license",
    "powershell_script",
)

PROFESSIONAL_RUNNER_REQUIRED_SUBSTRINGS = (
    "run_app_step",
    "run_url_step",
    "run_command_step",
    "run_wait_step",
)


ShortcutResolver = Callable[[str], Mapping[str, Any] | None]
PathPredicate = Callable[[str], bool]


class EditionContractViolation(ValueError):
    """Raised when a plan or export request violates a frozen edition contract."""


@dataclass(frozen=True)
class ContractIssue:
    """One accept/reject decision for a plan, step, or export request."""

    code: str
    message: str
    step_index: int | None = None

    def format(self) -> str:
        if self.step_index is None:
            return f"{self.code}: {self.message}"
        return f"{self.code}: step {self.step_index + 1}: {self.message}"


@dataclass(frozen=True)
class ContractValidationResult:
    accepted: bool
    issues: tuple[ContractIssue, ...]
    edition: str
    entry_point: str

    @property
    def error_messages(self) -> list[str]:
        return [issue.format() for issue in self.issues]


def load_shortcut_resolutions(path: Path) -> dict[str, Mapping[str, Any]]:
    """Load the Phase 0 synthetic LNK oracle. This is not a production API."""

    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("paths", payload)
    return {str(key): value for key, value in raw.items()}


def default_is_network_path(path: str) -> bool:
    text = str(path or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith(("http://", "https://", "ftp://", "file://", "smb://")):
        return True
    normalized = text.replace("/", "\\")
    return normalized.startswith("\\\\")


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _unknown_fields(data: Mapping[str, Any], allowed: Iterable[str]) -> list[str]:
    allowed_set = set(allowed)
    return sorted(key for key in data.keys() if key not in allowed_set)


def _step_label(index: int, step: Mapping[str, Any]) -> str:
    name = str(step.get("name", "")).strip() or "unnamed"
    return f"step {index + 1} ({name})"


def _delay_is_fixed_one_second(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return float(value) == BASIC_FIXED_DELAY_SECONDS


def _suffix(path: str) -> str:
    return Path(str(path)).suffix.lower()


def _basic_app_target_issues(
    index: int,
    step: Mapping[str, Any],
    *,
    shortcut_resolver: ShortcutResolver | None,
    is_network_path: PathPredicate,
) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    label = _step_label(index, step)
    path = step.get("path")
    if not isinstance(path, str) or not path.strip():
        issues.append(ContractIssue("basic_app_path_required", f"{label} is missing a local EXE path", index))
        return issues

    raw_path = path.strip()
    if is_network_path(raw_path):
        issues.append(ContractIssue(
            "basic_network_target_forbidden",
            f"{label} uses a network application target, which Basic rejects",
            index,
        ))
        return issues

    suffix = _suffix(raw_path)
    args = step.get("args", [])
    if "args" in step and not isinstance(args, list):
        issues.append(ContractIssue("basic_args_type", f"{label} args must be an empty list when present", index))
    elif isinstance(args, list) and any(not _is_blank(item) for item in args):
        issues.append(ContractIssue(
            "basic_custom_arguments_forbidden",
            f"{label} includes custom application arguments, which Basic rejects",
            index,
        ))

    if not _is_blank(step.get("working_dir", "")):
        issues.append(ContractIssue(
            "basic_custom_working_dir_forbidden",
            f"{label} includes a custom working directory, which Basic rejects",
            index,
        ))

    if "start_minimized" in step and step.get("start_minimized") is not False:
        issues.append(ContractIssue(
            "basic_custom_start_minimized_forbidden",
            f"{label} uses a non-default start-minimized value, which Basic rejects",
            index,
        ))

    if suffix in BASIC_ALLOWED_SHORTCUT_SUFFIXES:
        if shortcut_resolver is None:
            issues.append(ContractIssue(
                "basic_lnk_resolver_required",
                f"{label} is a shortcut and cannot be accepted without a failed-closed resolver",
                index,
            ))
            return issues
        resolution = shortcut_resolver(raw_path)
        if not isinstance(resolution, Mapping) or resolution.get("status") != "resolved":
            issues.append(ContractIssue(
                "basic_invalid_lnk",
                f"{label} shortcut target could not be resolved to a local EXE and must not be executed blindly",
                index,
            ))
            return issues
        if resolution.get("is_network_target") or is_network_path(str(resolution.get("target", ""))):
            issues.append(ContractIssue(
                "basic_lnk_network_target_forbidden",
                f"{label} shortcut resolves to a network target, which Basic rejects",
                index,
            ))
        if resolution.get("arguments"):
            issues.append(ContractIssue(
                "basic_lnk_arguments_forbidden",
                f"{label} shortcut contains additional arguments, which Basic rejects",
                index,
            ))
        if not resolution.get("is_local_exe") or not resolution.get("target_exists"):
            issues.append(ContractIssue(
                "basic_lnk_non_exe_target",
                f"{label} shortcut does not resolve to an existing local EXE, which Basic rejects",
                index,
            ))
        target_kind = str(resolution.get("target_kind", ""))
        target_suffix = _suffix(str(resolution.get("target", "")))
        if target_kind != "executable" or target_suffix not in BASIC_ALLOWED_APP_SUFFIXES:
            issues.append(ContractIssue(
                "basic_lnk_unsupported_target_kind",
                f"{label} shortcut target type is not a local EXE, which Basic rejects",
                index,
            ))
        return issues

    if suffix in BASIC_FORBIDDEN_SCRIPT_SUFFIXES or suffix not in BASIC_ALLOWED_APP_SUFFIXES:
        issues.append(ContractIssue(
            "basic_script_or_unsupported_target",
            f"{label} target is not an ordinary local EXE, which Basic rejects",
            index,
        ))
    return issues


def _basic_url_issues(index: int, step: Mapping[str, Any]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    label = _step_label(index, step)
    url = step.get("url")
    if not isinstance(url, str) or not url.strip():
        issues.append(ContractIssue("basic_url_required", f"{label} is missing a URL", index))
        return issues
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in BASIC_ALLOWED_URL_SCHEMES or not parsed.netloc:
        issues.append(ContractIssue(
            "basic_unsupported_url_scheme",
            f"{label} URL scheme is not HTTP/HTTPS, which Basic rejects",
            index,
        ))
    if not _is_blank(step.get("browser_path", "")):
        issues.append(ContractIssue(
            "basic_custom_browser_forbidden",
            f"{label} uses a custom browser executable, which Basic rejects",
            index,
        ))
    return issues


def validate_basic_plan_dict(
    plan_data: Any,
    *,
    entry_point: str = "direct_json_load",
    shortcut_resolver: ShortcutResolver | None = None,
    is_network_path: PathPredicate = default_is_network_path,
) -> ContractValidationResult:
    """Reject an entire Basic-incompatible plan before any execution or export side effects."""

    issues: list[ContractIssue] = []
    if entry_point not in ENTRY_POINTS:
        issues.append(ContractIssue("unknown_entry_point", f"unsupported validation entry point: {entry_point}"))

    if not isinstance(plan_data, dict):
        issues.append(ContractIssue("plan_not_object", "plan data must be an object"))
        return ContractValidationResult(False, tuple(issues), "basic", entry_point)

    unknown_root = _unknown_fields(plan_data, PLAN_ROOT_ALLOWED_FIELDS)
    if unknown_root:
        issues.append(ContractIssue(
            "unknown_plan_fields",
            "Basic rejects unknown plan fields rather than ignoring them: " + ", ".join(unknown_root),
        ))

    if "plan_name" not in plan_data or _is_blank(plan_data.get("plan_name")):
        issues.append(ContractIssue("plan_name_required", "plan_name is required"))

    steps = plan_data.get("steps")
    if not isinstance(steps, list):
        issues.append(ContractIssue("steps_not_array", "steps must be an array"))
        return ContractValidationResult(False, tuple(issues), "basic", entry_point)

    if not steps:
        issues.append(ContractIssue("steps_required", "Basic plans must contain at least one step"))

    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            issues.append(ContractIssue("step_not_object", "each step must be an object", index))
            continue

        step_type = step.get("type")
        if step_type not in BASIC_ALLOWED_STEP_TYPES:
            issues.append(ContractIssue(
                "basic_unsupported_step_type",
                f"{_step_label(index, step)} has unsupported type {step_type!r}; "
                "Basic rejects the entire plan, including disabled or trailing unsupported steps",
                index,
            ))
            continue

        allowed = APP_STEP_ALLOWED_FIELDS if step_type == "app" else URL_STEP_ALLOWED_FIELDS
        unknown = _unknown_fields(step, allowed)
        if unknown:
            issues.append(ContractIssue(
                "unknown_step_fields",
                f"{_step_label(index, step)} has unknown fields: " + ", ".join(unknown),
                index,
            ))

        if "name" not in step:
            issues.append(ContractIssue("step_name_required", f"{_step_label(index, step)} is missing name", index))

        if "delay_after" in step and not _delay_is_fixed_one_second(step.get("delay_after")):
            issues.append(ContractIssue(
                "basic_incompatible_delay",
                f"{_step_label(index, step)} delay_after is not the fixed one-second Basic value "
                "and must be rejected rather than silently normalized",
                index,
            ))

        if step_type == "app":
            issues.extend(
                _basic_app_target_issues(
                    index,
                    step,
                    shortcut_resolver=shortcut_resolver,
                    is_network_path=is_network_path,
                )
            )
        elif step_type == "url":
            issues.extend(_basic_url_issues(index, step))

    return ContractValidationResult(not issues, tuple(issues), "basic", entry_point)


def validate_basic_entry_point(
    plan_data: Any,
    entry_point: str,
    **kwargs: Any,
) -> ContractValidationResult:
    """The same Basic accept/reject rules apply at every ingress listed in ENTRY_POINTS."""

    return validate_basic_plan_dict(plan_data, entry_point=entry_point, **kwargs)


def basic_export_preflight(
    plan_data: Any,
    *,
    shortcut_resolver: ShortcutResolver | None = None,
    is_network_path: PathPredicate = default_is_network_path,
) -> ContractValidationResult:
    """Validate a Basic export before any temp, output, or packaging-tool side effects."""

    return validate_basic_plan_dict(
        plan_data,
        entry_point="export",
        shortcut_resolver=shortcut_resolver,
        is_network_path=is_network_path,
    )


def require_no_basic_activation(activation_required: bool, license_probe_attempted: bool, hwid_probe_attempted: bool) -> None:
    """Basic export and runtime must not require activation, license files, or HWID collection."""

    if activation_required or license_probe_attempted or hwid_probe_attempted:
        raise EditionContractViolation(
            "Basic must not require activation, read a license file, or collect hardware identity"
        )


def professional_export_authorization_required(professional_activation_valid: bool) -> None:
    """Professional export retains the existing successful-activation requirement."""

    if not professional_activation_valid:
        raise EditionContractViolation(
            "Professional export requires existing successful Professional activation"
        )


def basic_runner_source_violations(source: str) -> list[str]:
    """Return frozen Basic runner violations found in a candidate embedded-runner source."""

    violations = []
    for token in BASIC_RUNNER_FORBIDDEN_SUBSTRINGS:
        if token in source:
            violations.append(token)
    return violations


def professional_runner_source_missing(source: str) -> list[str]:
    """Return symbols the current Professional/unrestricted runner is expected to keep."""

    return [token for token in PROFESSIONAL_RUNNER_REQUIRED_SUBSTRINGS if token not in source]


def data_directory_names() -> dict[str, str]:
    return {
        "basic": BASIC_DATA_DIR_NAME,
        "professional": PROFESSIONAL_DATA_DIR_NAME,
        "basic_dev": f"{BASIC_DATA_DIR_NAME}-Dev",
        "professional_dev": f"{PROFESSIONAL_DATA_DIR_NAME}-Dev",
    }
