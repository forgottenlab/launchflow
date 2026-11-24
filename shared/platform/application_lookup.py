"""Windows keyword lookup for Application step paths.

This helper is read-only and explicit: it never launches a target, never
writes to LaunchFlow data directories, and never recursively scans a whole
drive. A successful lookup returns one or more existing absolute paths;
callers store a real path in the plan rather than a new path schema.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from shared.basic_policy import WindowsPathKind, classify_windows_path


STATUS_INVALID = "invalid"
STATUS_UNSUPPORTED = "unsupported"
STATUS_NOT_FOUND = "not_found"
STATUS_FOUND = "found"
STATUS_AMBIGUOUS = "ambiguous"

SOURCE_APP_PATHS = "app_paths"
SOURCE_UNINSTALL = "uninstall"
SOURCE_START_MENU = "start_menu"
SOURCE_DESKTOP = "desktop"
SOURCE_PROGRAM_FILES = "program_files"
SOURCE_WELL_KNOWN = "well_known"
SOURCE_TYPED_PATH = "typed_path"

PROFESSIONAL_LOOKUP_SUFFIXES = (".exe", ".bat", ".cmd", ".ps1", ".lnk")
BASIC_LOOKUP_SUFFIXES = (".exe", ".lnk")

DEFAULT_WELL_KNOWN: dict[str, tuple[str, ...]] = {
    "steam": (
        r"%ProgramFiles(x86)%\Steam\steam.exe",
        r"%ProgramFiles%\Steam\steam.exe",
        r"%LocalAppData%\Programs\Steam\steam.exe",
    ),
}

_ICON_INDEX_SUFFIX = re.compile(r",\s*-?\d+\s*$")
_MAX_KEYWORD_LENGTH = 128
_MAX_MATCHES = 50
_COMMON_INSTALL_SUBDIRS = ("bin", "Bin", "application", "Application", "app", "App")


@dataclass(frozen=True)
class ApplicationLookupMatch:
    """One existing absolute path that matched a keyword."""

    path: str
    display_name: str
    source: str
    detail: str = ""


@dataclass(frozen=True)
class ApplicationLookupResult:
    """Outcome of an explicit keyword lookup."""

    keyword: str
    status: str
    matches: tuple[ApplicationLookupMatch, ...]
    message: str


@dataclass(frozen=True)
class ApplicationCatalogEntry:
    """A candidate collected from one lookup source before suffix checks."""

    path: str
    display_name: str
    source: str
    detail: str = ""
    shortcut_target: str = ""


@dataclass(frozen=True)
class ApplicationLookupDependencies:
    """Injectable catalogs so tests never touch the real machine."""

    system: str = "Windows"
    list_app_paths: Callable[[], Sequence[ApplicationCatalogEntry]] | None = None
    list_uninstall: Callable[[], Sequence[ApplicationCatalogEntry]] | None = None
    list_shortcuts: Callable[[tuple[str, ...]], Sequence[ApplicationCatalogEntry]] | None = None
    program_roots: Sequence[str] | Callable[[], Sequence[str]] | None = None
    direct_file_roots: Sequence[str] | Callable[[], Sequence[str]] | None = None
    well_known: Mapping[str, Sequence[str]] | None = None
    path_is_file: Callable[[str], bool] = os.path.isfile
    path_is_dir: Callable[[str], bool] = os.path.isdir
    listdir: Callable[[str], Sequence[str]] = os.listdir
    expandvars: Callable[[str], str] = os.path.expandvars
    resolve_shortcut_target: Callable[[str], str] | None = None


def lookup_windows_application(
    keyword: str,
    *,
    allowed_suffixes: Sequence[str] | None = None,
    dependencies: ApplicationLookupDependencies | None = None,
) -> ApplicationLookupResult:
    """Search Windows catalogs for a program matching ``keyword``.

    The search is deterministic and fail-closed. It does not rewrite input
    and does not invent a path when several matches remain.
    """

    deps = dependencies or ApplicationLookupDependencies()
    raw = str(keyword or "").strip()
    suffixes = _normalize_suffixes(allowed_suffixes)

    if not raw:
        return ApplicationLookupResult(
            keyword=raw,
            status=STATUS_INVALID,
            matches=(),
            message="请先输入要查找的程序名称，例如 steam。",
        )
    if len(raw) > _MAX_KEYWORD_LENGTH:
        return ApplicationLookupResult(
            keyword=raw,
            status=STATUS_INVALID,
            matches=(),
            message="查找关键词过长，请输入程序名称或绝对路径。",
        )
    if _system_name(deps.system) != "windows":
        return ApplicationLookupResult(
            keyword=raw,
            status=STATUS_UNSUPPORTED,
            matches=(),
            message="按名称查找程序目前仅支持 Windows。",
        )

    typed = _lookup_typed_path(raw, suffixes=suffixes, deps=deps)
    if typed is not None:
        return typed
    if len(raw) < 2:
        return ApplicationLookupResult(
            keyword=raw,
            status=STATUS_INVALID,
            matches=(),
            message="请输入至少两个字符的程序名称，例如 steam。",
        )

    tokens = _keyword_tokens(raw, suffixes=suffixes)
    collected: list[ApplicationLookupMatch] = []
    for entry in _iter_catalog_entries(deps, tokens, suffixes=suffixes):
        match = _match_entry(entry, tokens, suffixes=suffixes, deps=deps)
        if match is not None:
            collected.append(match)

    unique = _dedupe_matches(collected)
    ranked = tuple(sorted(unique, key=_match_sort_key))[:_MAX_MATCHES]
    return _result_from_matches(raw, ranked)


def _result_from_matches(
    raw: str, ranked: tuple[ApplicationLookupMatch, ...]
) -> ApplicationLookupResult:
    if not ranked:
        return ApplicationLookupResult(
            keyword=raw,
            status=STATUS_NOT_FOUND,
            matches=(),
            message=(
                f"没有在注册表、开始菜单、桌面或常见安装目录中找到“{raw}”。"
                "未扫描整个磁盘。"
            ),
        )
    if len(ranked) == 1:
        match = ranked[0]
        return ApplicationLookupResult(
            keyword=raw,
            status=STATUS_FOUND,
            matches=ranked,
            message=f"已找到 {match.display_name}：{match.path}",
        )
    return ApplicationLookupResult(
        keyword=raw,
        status=STATUS_AMBIGUOUS,
        matches=ranked,
        message=f"找到 {len(ranked)} 个匹配项，请选择要使用的程序。",
    )


def _normalize_suffixes(allowed_suffixes: Sequence[str] | None) -> tuple[str, ...]:
    if not allowed_suffixes:
        return PROFESSIONAL_LOOKUP_SUFFIXES
    normalized: list[str] = []
    seen: set[str] = set()
    for item in allowed_suffixes:
        suffix = str(item or "").strip().lower()
        if suffix and not suffix.startswith("."):
            suffix = "." + suffix
        if suffix and suffix not in seen:
            seen.add(suffix)
            normalized.append(suffix)
    return tuple(normalized) or PROFESSIONAL_LOOKUP_SUFFIXES


def _system_name(system: str) -> str:
    return str(system or "").strip().lower()


def _keyword_tokens(raw: str, *, suffixes: Sequence[str]) -> tuple[str, ...]:
    text = raw.casefold().strip().strip('"')
    tokens = [text]
    for suffix in suffixes:
        if text.endswith(suffix):
            tokens.append(text[: -len(suffix)])
            break
    # Preserve unique order.
    unique: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        cleaned = token.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            unique.append(cleaned)
    return tuple(unique)


def _lookup_typed_path(
    raw: str,
    *,
    suffixes: Sequence[str],
    deps: ApplicationLookupDependencies,
) -> ApplicationLookupResult | None:
    kind = classify_windows_path(raw)
    path_like = kind in {
        WindowsPathKind.DRIVE_ABSOLUTE,
        WindowsPathKind.DRIVE_RELATIVE,
        WindowsPathKind.UNC,
        WindowsPathKind.DEVICE,
        WindowsPathKind.URL,
    } or ("\\" in raw) or ("/" in raw)
    if not path_like:
        return None
    if kind in {WindowsPathKind.UNC, WindowsPathKind.URL, WindowsPathKind.DEVICE}:
        return ApplicationLookupResult(
            keyword=raw,
            status=STATUS_NOT_FOUND,
            matches=(),
            message="查找结果必须是本机绝对路径，不能使用网络路径或设备路径。",
        )
    expanded = deps.expandvars(raw.strip().strip('"'))
    if kind != WindowsPathKind.DRIVE_ABSOLUTE:
        return ApplicationLookupResult(
            keyword=raw,
            status=STATUS_NOT_FOUND,
            matches=(),
            message=f"未找到该路径：{raw}",
        )
    if _is_unc_path(expanded):
        return ApplicationLookupResult(
            keyword=raw,
            status=STATUS_NOT_FOUND,
            matches=(),
            message="查找结果必须是本机绝对路径，不能使用网络路径或设备路径。",
        )
    if not deps.path_is_file(expanded):
        return ApplicationLookupResult(
            keyword=raw,
            status=STATUS_NOT_FOUND,
            matches=(),
            message=f"未找到该路径：{expanded}",
        )
    suffix = _windows_suffix(expanded)
    if suffix not in suffixes:
        return ApplicationLookupResult(
            keyword=raw,
            status=STATUS_NOT_FOUND,
            matches=(),
            message=f"该路径的类型不受当前版本支持：{expanded}",
        )
    match = ApplicationLookupMatch(
        path=_normalize_existing_path(expanded),
        display_name=_display_name_from_path(expanded),
        source=SOURCE_TYPED_PATH,
        detail="用户输入的绝对路径",
    )
    return ApplicationLookupResult(
        keyword=raw,
        status=STATUS_FOUND,
        matches=(match,),
        message=f"已找到 {match.display_name}：{match.path}",
    )


def _iter_catalog_entries(
    deps: ApplicationLookupDependencies,
    tokens: tuple[str, ...],
    *,
    suffixes: Sequence[str],
) -> Iterable[ApplicationCatalogEntry]:
    if deps.list_app_paths is not None:
        yield from deps.list_app_paths()
    else:
        yield from _read_app_paths_entries()

    if deps.list_uninstall is not None:
        yield from deps.list_uninstall()
    else:
        yield from _read_uninstall_entries(tokens, suffixes=suffixes)

    if deps.list_shortcuts is not None:
        yield from deps.list_shortcuts(tokens)
    else:
        yield from _read_shortcut_entries(tokens, deps=deps)

    yield from _iter_well_known_entries(deps, tokens)
    yield from _iter_program_root_entries(deps, tokens, suffixes=suffixes)


def _iter_well_known_entries(
    deps: ApplicationLookupDependencies, tokens: tuple[str, ...]
) -> Iterable[ApplicationCatalogEntry]:
    well_known = deps.well_known if deps.well_known is not None else DEFAULT_WELL_KNOWN
    for name, paths in well_known.items():
        if not _name_matches(str(name), tokens):
            continue
        for raw_path in paths:
            expanded = deps.expandvars(str(raw_path))
            yield ApplicationCatalogEntry(
                path=expanded,
                display_name=str(name),
                source=SOURCE_WELL_KNOWN,
                detail="常见安装布局",
            )


def _iter_program_root_entries(
    deps: ApplicationLookupDependencies,
    tokens: tuple[str, ...],
    *,
    suffixes: Sequence[str],
) -> Iterable[ApplicationCatalogEntry]:
    for root in _coerce_roots(deps.direct_file_roots, _default_direct_file_roots()):
        expanded = deps.expandvars(root)
        if not expanded:
            continue
        for token in tokens:
            for suffix in suffixes:
                candidate = os.path.join(expanded, token + suffix)
                yield ApplicationCatalogEntry(
                    path=candidate,
                    display_name=token,
                    source=SOURCE_PROGRAM_FILES,
                    detail="系统目录精确文件名",
                )

    for root in _coerce_roots(deps.program_roots, _default_program_roots()):
        expanded = deps.expandvars(root)
        if not expanded or not deps.path_is_dir(expanded):
            continue
        try:
            names = list(deps.listdir(expanded))
        except OSError:
            continue
        for name in names:
            full = os.path.join(expanded, name)
            if deps.path_is_file(full):
                if _name_matches(name, tokens):
                    yield ApplicationCatalogEntry(
                        path=full,
                        display_name=_display_name_from_path(full),
                        source=SOURCE_PROGRAM_FILES,
                        detail="常见安装目录",
                    )
                continue
            if not deps.path_is_dir(full) or not _name_matches(name, tokens):
                continue
            yield from _iter_shallow_install_dir(
                full,
                folder_name=name,
                tokens=tokens,
                suffixes=suffixes,
                deps=deps,
            )


def _iter_shallow_install_dir(
    folder: str,
    *,
    folder_name: str,
    tokens: tuple[str, ...],
    suffixes: Sequence[str],
    deps: ApplicationLookupDependencies,
) -> Iterable[ApplicationCatalogEntry]:
    # Only inspect the install folder itself and a short list of common
    # subdirectories. Never walk the rest of the tree.
    search_dirs = [folder]
    for subdir in _COMMON_INSTALL_SUBDIRS:
        search_dirs.append(os.path.join(folder, subdir))

    for directory in search_dirs:
        if not deps.path_is_dir(directory):
            continue
        try:
            names = list(deps.listdir(directory))
        except OSError:
            continue
        for name in names:
            full = os.path.join(directory, name)
            if not deps.path_is_file(full):
                continue
            # Inside a matching install folder, only keep files whose stem
            # equals the keyword. This avoids steamwebhelper.exe for "steam".
            if not _name_equals(name, tokens):
                continue
            yield ApplicationCatalogEntry(
                    path=full,
                    display_name=_display_name_from_path(full),
                    source=SOURCE_PROGRAM_FILES,
                    detail=f"常见安装目录：{folder_name}",
                )


def _match_entry(
    entry: ApplicationCatalogEntry,
    tokens: tuple[str, ...],
    *,
    suffixes: Sequence[str],
    deps: ApplicationLookupDependencies,
) -> ApplicationLookupMatch | None:
    if not _catalog_entry_matches(entry, tokens):
        return None

    candidates: list[tuple[str, str]] = []
    target = (entry.shortcut_target or "").strip()
    if not target and entry.path.lower().endswith(".lnk"):
        resolver = deps.resolve_shortcut_target or _default_resolve_shortcut_target
        try:
            target = (resolver(entry.path) or "").strip()
        except (OSError, RuntimeError, ValueError, TypeError):
            target = ""
    if target:
        candidates.append((target, "resolved_shortcut"))
    if entry.path:
        candidates.append((entry.path, "source_path"))

    for raw_path, origin in candidates:
        cleaned = _clean_windows_path(deps.expandvars(raw_path))
        if not cleaned or _is_unc_path(cleaned):
            continue
        if classify_windows_path(cleaned) != WindowsPathKind.DRIVE_ABSOLUTE:
            continue
        if not deps.path_is_file(cleaned):
            continue
        suffix = _windows_suffix(cleaned)
        if suffix not in suffixes:
            continue
        detail = entry.detail
        if origin == "resolved_shortcut" and detail:
            detail = f"{detail} → {cleaned}"
        elif origin == "resolved_shortcut":
            detail = f"快捷方式目标：{cleaned}"
        return ApplicationLookupMatch(
            path=_normalize_existing_path(cleaned),
            display_name=entry.display_name or _display_name_from_path(cleaned),
            source=entry.source,
            detail=detail,
        )
    return None


def _catalog_entry_matches(entry: ApplicationCatalogEntry, tokens: tuple[str, ...]) -> bool:
    haystacks = [
        entry.display_name,
        entry.path,
        _file_name(entry.path),
        _stem(entry.path),
        entry.shortcut_target,
        _file_name(entry.shortcut_target),
        _stem(entry.shortcut_target),
        entry.detail,
    ]
    return any(_name_matches(item, tokens) for item in haystacks if item)


def _name_equals(value: str, tokens: tuple[str, ...]) -> bool:
    text = _normalize_name(value)
    if not text:
        return False
    names = {text, _normalize_name(_file_name(value)), _normalize_name(_stem(value))}
    names.discard("")
    return any(_normalize_name(token) in names for token in tokens)


def _name_matches(value: str, tokens: tuple[str, ...]) -> bool:
    text = _normalize_name(value)
    if not text:
        return False
    for token in tokens:
        needle = _normalize_name(token)
        if not needle:
            continue
        if text == needle or text.startswith(needle) or needle in text:
            return True
        # Compare stems without a trailing suffix already stripped by tokens.
        if text.split(".", 1)[0] == needle:
            return True
    return False


def _normalize_name(value: str) -> str:
    return str(value or "").casefold().strip().strip('"')


def _dedupe_matches(matches: Sequence[ApplicationLookupMatch]) -> list[ApplicationLookupMatch]:
    unique: list[ApplicationLookupMatch] = []
    seen: set[str] = set()
    for match in matches:
        key = os.path.normcase(_normalize_existing_path(match.path))
        if key in seen:
            continue
        seen.add(key)
        unique.append(match)
    return unique


def _match_sort_key(match: ApplicationLookupMatch) -> tuple[int, str, str]:
    source_rank = {
        SOURCE_TYPED_PATH: 0,
        SOURCE_APP_PATHS: 1,
        SOURCE_WELL_KNOWN: 2,
        SOURCE_START_MENU: 3,
        SOURCE_DESKTOP: 4,
        SOURCE_UNINSTALL: 5,
        SOURCE_PROGRAM_FILES: 6,
    }.get(match.source, 9)
    return (source_rank, match.display_name.casefold(), os.path.normcase(match.path))


def _clean_windows_path(path: str) -> str:
    text = str(path or "").strip().strip('"')
    text = _ICON_INDEX_SUFFIX.sub("", text).strip().strip('"')
    return text


def _windows_suffix(path: str) -> str:
    name = _file_name(path)
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].casefold()


def _file_name(path: str) -> str:
    text = _normalize_existing_path(path).rstrip("\\/")
    if not text:
        return ""
    return text.replace("/", "\\").rsplit("\\", 1)[-1]


def _stem(path: str) -> str:
    name = _file_name(path)
    if "." not in name:
        return name
    return name.rsplit(".", 1)[0]


def _display_name_from_path(path: str) -> str:
    return _stem(path) or _file_name(path) or path


def _normalize_existing_path(path: str) -> str:
    text = _clean_windows_path(path)
    if not text:
        return ""
    return os.path.normpath(text)


def _is_unc_path(path: str) -> bool:
    return classify_windows_path(path) == WindowsPathKind.UNC


def _coerce_roots(
    value: Sequence[str] | Callable[[], Sequence[str]] | None,
    default: Sequence[str],
) -> tuple[str, ...]:
    if value is None:
        return tuple(default)
    if callable(value):
        return tuple(value())
    return tuple(value)


def _default_program_roots() -> tuple[str, ...]:
    return (
        r"%ProgramFiles%",
        r"%ProgramFiles(x86)%",
        r"%LocalAppData%\Programs",
    )


def _default_direct_file_roots() -> tuple[str, ...]:
    return (
        r"%SystemRoot%\System32",
        r"%SystemRoot%\SysWOW64",
        r"%SystemRoot%",
    )


def _read_app_paths_entries() -> list[ApplicationCatalogEntry]:
    entries: list[ApplicationCatalogEntry] = []
    for root, subkey in _app_paths_locations():
        for name, default, directory in _iter_registry_subvalues(root, subkey, ("Path",)):
            path = _clean_windows_path(default)
            if not path and directory:
                path = os.path.join(_clean_windows_path(directory), name)
            if not path:
                continue
            entries.append(
                ApplicationCatalogEntry(
                    path=path,
                    display_name=_stem(name) or name,
                    source=SOURCE_APP_PATHS,
                    detail=f"App Paths：{name}",
                )
            )
    return entries


def _read_uninstall_entries(
    tokens: tuple[str, ...], *, suffixes: Sequence[str]
) -> list[ApplicationCatalogEntry]:
    entries: list[ApplicationCatalogEntry] = []
    fields = ("DisplayName", "DisplayIcon", "InstallLocation")
    for root, subkey in _uninstall_locations():
        for name, display_name, values in _iter_registry_named_values(root, subkey, fields):
            title = _clean_windows_path(values.get("DisplayName", "") or display_name or name)
            if not _name_matches(title, tokens) and not _name_matches(name, tokens):
                continue
            icon = _clean_windows_path(values.get("DisplayIcon", ""))
            install_dir = _clean_windows_path(values.get("InstallLocation", ""))
            paths: list[str] = []
            if icon:
                paths.append(icon)
            if install_dir:
                for token in tokens:
                    for suffix in suffixes:
                        paths.append(os.path.join(install_dir, token + suffix))
            for path in paths:
                entries.append(
                    ApplicationCatalogEntry(
                        path=path,
                        display_name=title or _display_name_from_path(path),
                        source=SOURCE_UNINSTALL,
                        detail=f"卸载项：{title or name}",
                    )
                )
    return entries


def _read_shortcut_entries(
    tokens: tuple[str, ...], *, deps: ApplicationLookupDependencies
) -> list[ApplicationCatalogEntry]:
    entries: list[ApplicationCatalogEntry] = []
    resolver = deps.resolve_shortcut_target or _default_resolve_shortcut_target
    for source, root in _default_shortcut_roots():
        expanded = deps.expandvars(root)
        if not deps.path_is_dir(expanded):
            continue
        try:
            walker = os.walk(expanded, followlinks=False)
        except OSError:
            continue
        for dirpath, _dirnames, filenames in walker:
            for filename in filenames:
                if not filename.casefold().endswith(".lnk"):
                    continue
                if not (
                    _name_matches(filename, tokens)
                    or _name_matches(_stem(filename), tokens)
                    or _name_matches(os.path.basename(dirpath), tokens)
                ):
                    continue
                path = os.path.join(dirpath, filename)
                target = ""
                try:
                    target = (resolver(path) or "").strip()
                except (OSError, RuntimeError, ValueError, TypeError):
                    target = ""
                entries.append(
                    ApplicationCatalogEntry(
                        path=path,
                        display_name=_stem(filename),
                        source=source,
                        detail="开始菜单" if source == SOURCE_START_MENU else "桌面快捷方式",
                        shortcut_target=target,
                    )
                )
    return entries


def _default_shortcut_roots() -> tuple[tuple[str, str], ...]:
    return (
        (SOURCE_START_MENU, r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
        (SOURCE_START_MENU, r"%AppData%\Microsoft\Windows\Start Menu\Programs"),
        (SOURCE_DESKTOP, r"%Public%\Desktop"),
        (SOURCE_DESKTOP, r"%UserProfile%\Desktop"),
    )


def _default_resolve_shortcut_target(path: str) -> str:
    from shared.platform.windows_shell_links import WindowsShortcutResolver

    try:
        resolution = WindowsShortcutResolver().resolve_shortcut(path)
    except (OSError, RuntimeError, ValueError, TypeError):
        return ""
    if getattr(resolution, "status", "") != "resolved":
        return ""
    return str(getattr(resolution, "target_path", "") or "").strip()


def _app_paths_locations() -> tuple[tuple[object, str], ...]:
    winreg = _import_winreg()
    if winreg is None:
        return ()
    return (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
    )


def _uninstall_locations() -> tuple[tuple[object, str], ...]:
    winreg = _import_winreg()
    if winreg is None:
        return ()
    return (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )


def _import_winreg():
    try:
        import winreg
    except ImportError:
        return None
    return winreg


def _iter_registry_subvalues(
    root: object, subkey: str, extra_fields: Sequence[str]
) -> Iterable[tuple[str, str, str]]:
    winreg = _import_winreg()
    if winreg is None:
        return
    try:
        key = winreg.OpenKey(root, subkey)
    except OSError:
        return
    try:
        index = 0
        while True:
            try:
                name = winreg.EnumKey(key, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(key, name) as child:
                    default = _query_registry_value(winreg, child, None)
                    extras = {
                        field: _query_registry_value(winreg, child, field)
                        for field in extra_fields
                    }
            except OSError:
                continue
            yield name, default, extras.get("Path", "")
    finally:
        winreg.CloseKey(key)


def _iter_registry_named_values(
    root: object, subkey: str, fields: Sequence[str]
) -> Iterable[tuple[str, str, dict[str, str]]]:
    winreg = _import_winreg()
    if winreg is None:
        return
    try:
        key = winreg.OpenKey(root, subkey)
    except OSError:
        return
    try:
        index = 0
        while True:
            try:
                name = winreg.EnumKey(key, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(key, name) as child:
                    values = {
                        field: _query_registry_value(winreg, child, field)
                        for field in fields
                    }
            except OSError:
                continue
            yield name, values.get("DisplayName", ""), values
    finally:
        winreg.CloseKey(key)


def _query_registry_value(winreg: object, key: object, name: str | None) -> str:
    try:
        value, value_type = winreg.QueryValueEx(key, name)  # type: ignore[attr-defined]
    except OSError:
        return ""
    text = str(value or "")
    expand = getattr(winreg, "REG_EXPAND_SZ", None)
    if expand is not None and value_type == expand:
        return os.path.expandvars(text)
    return text
