"""Normalize user-entered URLs by adding https:// when no scheme is present."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any


_SCHEME_WITH_AUTHORITY = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_EXPLICIT_NON_AUTHORITY_SCHEMES = re.compile(
    r"^(mailto|data|about|javascript|tel|sms|file):",
    re.IGNORECASE,
)


def normalize_missing_url_scheme(url: str) -> str:
    """Return *url* with https:// prefixed when the user omitted a scheme.

    Explicit schemes are preserved, including http, https, ftp, file, mailto
    and any other value written as ``scheme://...``. A host:port value such as
    ``localhost:8080`` or a bare domain such as ``www.baidu.com`` is treated as
    missing a scheme and receives an ``https://`` prefix. Empty or whitespace
    input is only stripped.
    """

    text = str(url).strip()
    if not text:
        return text
    if _SCHEME_WITH_AUTHORITY.match(text) or _EXPLICIT_NON_AUTHORITY_SCHEMES.match(text):
        return text
    return "https://" + text


def _is_url_step(step: Any) -> bool:
    if isinstance(step, dict):
        return str(step.get("type", "")).lower() == "url"
    step_type = str(getattr(step, "type", "") or "").lower()
    if step_type:
        return step_type == "url"
    return type(step).__name__ == "UrlStep"


def normalize_plan_url_schemes(steps: Iterable[Any]) -> bool:
    """Normalize URL fields on plan steps in place. Returns True if any changed."""

    changed = False
    for step in steps:
        if not _is_url_step(step):
            continue
        if isinstance(step, dict):
            raw = step.get("url", "")
            if not isinstance(raw, str):
                continue
            normalized = normalize_missing_url_scheme(raw)
            if normalized != raw:
                step["url"] = normalized
                changed = True
            continue
        raw = getattr(step, "url", None)
        if not isinstance(raw, str):
            continue
        normalized = normalize_missing_url_scheme(raw)
        if normalized != raw:
            step.url = normalized
            changed = True
    return changed
