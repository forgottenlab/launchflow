"""Behavior smoke for Windows Application path keyword lookup."""

from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.platform.application_lookup import (
    BASIC_LOOKUP_SUFFIXES,
    PROFESSIONAL_LOOKUP_SUFFIXES,
    SOURCE_APP_PATHS,
    SOURCE_PROGRAM_FILES,
    SOURCE_START_MENU,
    SOURCE_UNINSTALL,
    SOURCE_WELL_KNOWN,
    STATUS_AMBIGUOUS,
    STATUS_FOUND,
    STATUS_INVALID,
    STATUS_NOT_FOUND,
    STATUS_UNSUPPORTED,
    ApplicationCatalogEntry,
    ApplicationLookupDependencies,
    lookup_windows_application,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _deps(**kwargs: object) -> ApplicationLookupDependencies:
    defaults = dict(
        system="Windows",
        list_app_paths=lambda: (),
        list_uninstall=lambda: (),
        list_shortcuts=lambda _tokens: (),
        program_roots=(),
        direct_file_roots=(),
        well_known={},
        path_is_file=lambda _path: False,
        path_is_dir=lambda _path: False,
        listdir=lambda _path: (),
        expandvars=lambda path: path,
        resolve_shortcut_target=lambda _path: "",
    )
    defaults.update(kwargs)
    return ApplicationLookupDependencies(**defaults)


def _existing(*paths: str) -> dict[str, bool]:
    return {os.path.normpath(path): True for path in paths}


def _is_file_from(existing: dict[str, bool]):
    def path_is_file(path: str) -> bool:
        return existing.get(os.path.normpath(path), False)

    return path_is_file


def check_invalid_and_unsupported() -> None:
    empty = lookup_windows_application("  ", dependencies=_deps())
    require(empty.status == STATUS_INVALID, "blank keyword should be invalid")
    require("steam" in empty.message, "blank-keyword message should show the steam example")

    short = lookup_windows_application("s", dependencies=_deps())
    require(short.status == STATUS_INVALID, "single-character keyword should be invalid")

    posix = lookup_windows_application("steam", dependencies=_deps(system="Linux"))
    require(posix.status == STATUS_UNSUPPORTED, "non-Windows hosts should fail closed")
    require("Windows" in posix.message, "unsupported message should name Windows")


def check_typed_absolute_path() -> None:
    path = r"C:\Tools\demo.exe"
    existing = _existing(path)
    found = lookup_windows_application(
        path,
        dependencies=_deps(path_is_file=_is_file_from(existing)),
    )
    require(found.status == STATUS_FOUND, "existing absolute path should be accepted")
    require(found.matches[0].path == os.path.normpath(path), "typed path was not preserved")

    missing = lookup_windows_application(
        r"C:\Tools\missing.exe",
        dependencies=_deps(path_is_file=_is_file_from(existing)),
    )
    require(missing.status == STATUS_NOT_FOUND, "missing absolute path should not invent a result")
    require("未找到该路径" in missing.message, "missing path message drifted")

    unc = lookup_windows_application(r"\\server\share\steam.exe", dependencies=_deps())
    require(unc.status == STATUS_NOT_FOUND, "UNC paths must be rejected")
    require("网络路径" in unc.message, "UNC rejection message drifted")


def check_unique_keyword_and_steam_layout() -> None:
    steam = r"C:\Program Files (x86)\Steam\steam.exe"
    helper = r"C:\Program Files (x86)\Steam\steamwebhelper.exe"
    existing = _existing(steam, helper)
    directories = {
        os.path.normpath(r"C:\Program Files (x86)"): True,
        os.path.normpath(r"C:\Program Files (x86)\Steam"): True,
    }
    listing = {
        os.path.normpath(r"C:\Program Files (x86)"): ["Steam", "Unrelated"],
        os.path.normpath(r"C:\Program Files (x86)\Steam"): ["steam.exe", "steamwebhelper.exe"],
    }

    def listdir(path: str) -> list[str]:
        return listing.get(os.path.normpath(path), [])

    result = lookup_windows_application(
        "steam",
        dependencies=_deps(
            well_known={
                "steam": (r"C:\Program Files (x86)\Steam\steam.exe",),
            },
            program_roots=(r"C:\Program Files (x86)",),
            path_is_file=_is_file_from(existing),
            path_is_dir=lambda path: directories.get(os.path.normpath(path), False),
            listdir=listdir,
        ),
    )
    require(result.status == STATUS_FOUND, "steam should resolve to a unique executable")
    require(len(result.matches) == 1, "helper executables were not filtered out")
    require(result.matches[0].path == os.path.normpath(steam), "steam path drifted")
    require(result.matches[0].source in {SOURCE_WELL_KNOWN, SOURCE_PROGRAM_FILES}, "unexpected steam source")


def check_not_found() -> None:
    result = lookup_windows_application("definitely-missing-app-xyz", dependencies=_deps())
    require(result.status == STATUS_NOT_FOUND, "unknown keyword should be not_found")
    require(result.matches == (), "not_found must not invent matches")
    require("未扫描整个磁盘" in result.message, "not_found message should say the drive was not scanned")


def check_ambiguous_matches() -> None:
    first = r"C:\Program Files\Alpha\demo.exe"
    second = r"C:\Program Files\Beta\demo.exe"
    existing = _existing(first, second)
    result = lookup_windows_application(
        "demo",
        dependencies=_deps(
            list_app_paths=lambda: (
                ApplicationCatalogEntry(path=first, display_name="Demo Alpha", source=SOURCE_APP_PATHS),
                ApplicationCatalogEntry(path=second, display_name="Demo Beta", source=SOURCE_UNINSTALL),
            ),
            path_is_file=_is_file_from(existing),
        ),
    )
    require(result.status == STATUS_AMBIGUOUS, "two existing executables must be disambiguated")
    require(len(result.matches) == 2, "ambiguous lookup lost a match")
    require({match.path for match in result.matches} == {os.path.normpath(first), os.path.normpath(second)}, "ambiguous paths drifted")
    require("请选择" in result.message, "ambiguous message should ask the user to choose")


def check_dedupe_shortcut_and_app_paths() -> None:
    exe = r"C:\Program Files\Steam\steam.exe"
    link = r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Steam.lnk"
    existing = _existing(exe, link)
    result = lookup_windows_application(
        "steam",
        dependencies=_deps(
            list_app_paths=lambda: (
                ApplicationCatalogEntry(path=exe, display_name="Steam", source=SOURCE_APP_PATHS),
            ),
            list_shortcuts=lambda _tokens: (
                ApplicationCatalogEntry(
                    path=link,
                    display_name="Steam",
                    source=SOURCE_START_MENU,
                    shortcut_target=exe,
                ),
            ),
            path_is_file=_is_file_from(existing),
        ),
    )
    require(result.status == STATUS_FOUND, "shortcut and App Paths should collapse to one path")
    require(len(result.matches) == 1, "resolved shortcut was not deduplicated")
    require(result.matches[0].path == os.path.normpath(exe), "deduped path should be the executable")


def check_basic_suffix_filter() -> None:
    script = r"C:\Tools\steam.ps1"
    exe = r"C:\Tools\steam.exe"
    existing = _existing(script, exe)
    professional = lookup_windows_application(
        "steam",
        allowed_suffixes=PROFESSIONAL_LOOKUP_SUFFIXES,
        dependencies=_deps(
            list_app_paths=lambda: (
                ApplicationCatalogEntry(path=script, display_name="Steam Script", source=SOURCE_APP_PATHS),
            ),
            path_is_file=_is_file_from(existing),
        ),
    )
    require(professional.status == STATUS_FOUND, "Professional should accept a matching script")
    require(professional.matches[0].path == os.path.normpath(script), "Professional script path drifted")

    basic = lookup_windows_application(
        "steam",
        allowed_suffixes=BASIC_LOOKUP_SUFFIXES,
        dependencies=_deps(
            list_app_paths=lambda: (
                ApplicationCatalogEntry(path=script, display_name="Steam Script", source=SOURCE_APP_PATHS),
            ),
            path_is_file=_is_file_from(existing),
        ),
    )
    require(basic.status == STATUS_NOT_FOUND, "Basic must not return a .ps1 path")

    basic_exe = lookup_windows_application(
        "steam",
        allowed_suffixes=BASIC_LOOKUP_SUFFIXES,
        dependencies=_deps(
            list_app_paths=lambda: (
                ApplicationCatalogEntry(path=exe, display_name="Steam", source=SOURCE_APP_PATHS),
            ),
            path_is_file=_is_file_from(existing),
        ),
    )
    require(basic_exe.status == STATUS_FOUND, "Basic should accept a matching EXE")


def check_does_not_walk_entire_drive() -> None:
    walked: list[str] = []

    def listdir(path: str) -> list[str]:
        walked.append(os.path.normpath(path))
        if os.path.normpath(path) == os.path.normpath(r"C:\Program Files"):
            return ["Steam"]
        if os.path.normpath(path) == os.path.normpath(r"C:\Program Files\Steam"):
            return ["steam.exe"]
        raise AssertionError(f"unexpected directory listing: {path}")

    directories = {
        os.path.normpath(r"C:\Program Files"): True,
        os.path.normpath(r"C:\Program Files\Steam"): True,
    }
    existing = _existing(r"C:\Program Files\Steam\steam.exe")
    result = lookup_windows_application(
        "steam",
        dependencies=_deps(
            program_roots=(r"C:\Program Files",),
            path_is_file=_is_file_from(existing),
            path_is_dir=lambda path: directories.get(os.path.normpath(path), False),
            listdir=listdir,
        ),
    )
    require(result.status == STATUS_FOUND, "shallow Program Files lookup failed")
    require(os.path.normpath("C:\\") not in walked, "lookup listed the drive root")
    require(all(not item.endswith(":\\") or item.endswith("Program Files") for item in walked), "lookup walked an unexpected root")


def main() -> int:
    check_invalid_and_unsupported()
    check_typed_absolute_path()
    check_unique_keyword_and_steam_layout()
    check_not_found()
    check_ambiguous_matches()
    check_dedupe_shortcut_and_app_paths()
    check_basic_suffix_filter()
    check_does_not_walk_entire_drive()
    print("application lookup smoke ok")
    print("cases=invalid,unsupported,typed-path,unique-steam,not-found,ambiguous,dedupe,basic-suffix,no-drive-walk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
