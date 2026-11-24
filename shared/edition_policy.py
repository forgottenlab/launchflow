"""Gated Basic edition policy ingress for LaunchFlow.

Basic validation is enforced only when an explicit Basic edition context
is active. If no edition context exists, or the context is Professional,
callers keep the current single-product / Professional behavior.

This module does not introduce edition launch entries, change the data
directory identity, or alter licensing or export authorization.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from shared.basic_policy import (
    BasicPolicyDependencies,
    BasicPolicyResult,
    DriveClassifier,
    DriveLocality,
    FilesystemInspector,
    ShortcutResolution,
    ShortcutResolver,
    validate_basic_plan,
    validate_basic_plan_document,
)
from shared.models import Plan
from shared.platform.detection import current_platform_info


BASIC_EDITION = "basic"
PROFESSIONAL_EDITION = "professional"


@dataclass(frozen=True)
class EditionContext:
    """Process or task edition context used to gate Basic validation."""

    edition: str | None = None
    dependencies: BasicPolicyDependencies | None = None


@dataclass(frozen=True)
class OsFilesystemInspector:
    """Existence checks delegated to the operating system path APIs."""

    def path_exists(self, path: str) -> bool:
        return os.path.exists(path)

    def is_directory(self, path: str) -> bool:
        return os.path.isdir(path)


@dataclass(frozen=True)
class UnavailableDriveClassifier:
    """Fail-closed classifier used when Windows volume APIs are not available."""

    def classify_drive(self, path: str) -> DriveLocality:
        return DriveLocality.UNAVAILABLE


@dataclass(frozen=True)
class UnavailableShortcutResolver:
    """Fail-closed resolver used when Windows shortcut APIs are not available."""

    def resolve_shortcut(self, path: str) -> ShortcutResolution:
        raise RuntimeError("Windows shortcut resolution is unavailable on this host")


class BasicPolicyViolation(ValueError):
    """Raised when an active Basic edition context rejects a plan."""

    def __init__(self, result: BasicPolicyResult) -> None:
        self.result = result
        if result.issues:
            message = result.issues[0].format()
            if len(result.issues) > 1:
                message = f"{message} ({len(result.issues)} issues)"
        else:
            message = "Basic edition rejected the plan"
        super().__init__(message)


_process_context = EditionContext()
_override_context: ContextVar[EditionContext | None] = ContextVar(
    "launchflow_edition_context",
    default=None,
)


def get_edition_context() -> EditionContext:
    """Return the current override context, or the process-wide default."""

    override = _override_context.get()
    if override is not None:
        return override
    return _process_context


def set_process_edition_context(context: EditionContext) -> EditionContext:
    """Replace the process-wide edition context.

    Future edition launch entries may call this at startup. Phase 1b does
    not change application entry points and never sets Basic by default.
    """

    global _process_context
    previous = _process_context
    _process_context = context
    return previous


def set_edition_context_override(context: EditionContext | None) -> Token:
    """Set a task-local edition override. Prefer edition_scope() in tests."""

    return _override_context.set(context)


def reset_edition_context_override(token: Token) -> None:
    _override_context.reset(token)


@contextmanager
def edition_scope(
    edition: str | None,
    *,
    dependencies: BasicPolicyDependencies | None = None,
) -> Iterator[EditionContext]:
    """Temporarily override the edition context in the current task."""

    context = EditionContext(edition=edition, dependencies=dependencies)
    token = set_edition_context_override(context)
    try:
        yield context
    finally:
        reset_edition_context_override(token)


def is_basic_edition_active() -> bool:
    """True only when an explicit Basic edition context is active."""

    edition = get_edition_context().edition
    if edition is None:
        return False
    return str(edition).strip().casefold() == BASIC_EDITION


def build_production_basic_policy_dependencies() -> BasicPolicyDependencies:
    """Construct default production inspectors for an active Basic context."""

    filesystem: FilesystemInspector = OsFilesystemInspector()
    try:
        windows = current_platform_info().system == "windows"
    except Exception:
        windows = False

    if not windows:
        return BasicPolicyDependencies(
            filesystem=filesystem,
            drive_classifier=UnavailableDriveClassifier(),
            shortcut_resolver=UnavailableShortcutResolver(),
        )

    from shared.platform.windows_drives import WindowsDriveClassifier
    from shared.platform.windows_shell_links import WindowsShortcutResolver

    drive_classifier: DriveClassifier = WindowsDriveClassifier()
    shortcut_resolver: ShortcutResolver = WindowsShortcutResolver()
    return BasicPolicyDependencies(
        filesystem=filesystem,
        drive_classifier=drive_classifier,
        shortcut_resolver=shortcut_resolver,
    )


def resolve_basic_policy_dependencies(
    dependencies: BasicPolicyDependencies | None = None,
) -> BasicPolicyDependencies:
    if dependencies is not None:
        return dependencies
    context_dependencies = get_edition_context().dependencies
    if context_dependencies is not None:
        return context_dependencies
    return build_production_basic_policy_dependencies()


def validate_basic_ingress(
    plan_or_document: Plan | Mapping[str, Any] | Any,
    *,
    dependencies: BasicPolicyDependencies | None = None,
) -> BasicPolicyResult | None:
    """Validate a plan only when Basic edition is active.

    Returns None when the current product / Professional path should be
    left unchanged. When Basic is active, returns the structured result
    without mutating the input.
    """

    if not is_basic_edition_active():
        return None
    deps = resolve_basic_policy_dependencies(dependencies)
    if isinstance(plan_or_document, Plan):
        return validate_basic_plan(plan_or_document, dependencies=deps)
    return validate_basic_plan_document(plan_or_document, dependencies=deps)


def enforce_basic_policy_on_ingress(
    plan_or_document: Plan | Mapping[str, Any] | Any,
    *,
    dependencies: BasicPolicyDependencies | None = None,
) -> BasicPolicyResult | None:
    """Reject an incompatible plan when Basic edition is active.

    This is a no-op on the current Professional path. When Basic is
    active and the plan is incompatible, BasicPolicyViolation is raised
    before the caller performs execution or packaging side effects.
    """

    result = validate_basic_ingress(plan_or_document, dependencies=dependencies)
    if result is None:
        return None
    if not result.accepted:
        raise BasicPolicyViolation(result)
    return result
