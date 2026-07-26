"""Verify Phase 1d UrlOpener behavior and Windows equivalence."""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import FrozenInstanceError
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.launcher_runtime import RuntimeExecutor
from shared.models import UrlStep
from shared.platform.base import PlatformInfo
from shared.platform.detection import detect_platform
from shared.platform.urls import (
    LegacyPosixUrlOpener,
    UrlOpener,
    UrlOpenSpec,
    WindowsUrlOpener,
    get_url_opener,
)
from tools.build_single_exe import (
    EMBEDDED_TEMPLATE,
    URL_OPEN_SCHEMA,
    _prepare_embedded_plan_and_assets,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _platform(system: str, sys_platform: str, os_name: str = "posix") -> PlatformInfo:
    return detect_platform(
        system=system,
        machine="x86_64",
        os_name=os_name,
        sys_platform=sys_platform,
    )


def _windows_opener(path_exists=lambda _path: True) -> WindowsUrlOpener:  # type: ignore[no-untyped-def]
    opener = get_url_opener(
        platform_info=_platform("Windows", "win32", "nt"),
        path_exists=path_exists,
    )
    require(isinstance(opener, WindowsUrlOpener), "Windows URL opener was not selected")
    require(isinstance(opener, UrlOpener), "Windows URL opener does not satisfy Protocol")
    return opener


def _assert_backend_selection() -> None:
    windows = _windows_opener()
    require(windows.supported_open_modes == ("shell_open", "process"), "Windows modes changed")

    for system, sys_platform in (("Linux", "linux"), ("Darwin", "darwin"), ("Other", "other")):
        opener = get_url_opener(
            platform_info=_platform(system, sys_platform),
            path_exists=lambda _path: True,
        )
        require(isinstance(opener, LegacyPosixUrlOpener), f"legacy URL opener missing: {system}")
        require(opener.supported_open_modes == ("process",), f"legacy opener claimed default mode: {system}")
        spec = opener.build_open_spec("custom://value", "/tmp/browser")
        require(spec.command_args == ("/tmp/browser", "custom://value"), "legacy explicit-browser fallback changed")
        try:
            opener.build_open_spec("custom://value", "")
        except NotImplementedError as exc:
            require("尚未支持" in str(exc), "unsupported default-browser error is unclear")
        else:
            raise AssertionError(f"non-Windows default browser was treated as supported: {system}")


def _assert_default_specs() -> None:
    existence_checks: list[str] = []
    opener = _windows_opener(lambda path: existence_checks.append(path) or True)
    url = "  custom+测试://host/空 格?q=one&percent=100%25#片段?x=y\\tail  "
    for browser in ("", None):
        spec = opener.build_open_spec(url, browser)
        require(spec.open_mode == "shell_open", "empty/missing browser no longer selects shell-open")
        require(spec.url == url, "default URL was trimmed, parsed, or rewritten")
        require(spec.executable is None and spec.command_args == (), "shell-open gained process argv")
        require(spec.cwd is None, "shell-open gained cwd")
        require(spec.creationflags == 0 and not spec.use_startupinfo, "shell-open gained Windows process flags")
        require(
            not spec.use_stdin_devnull and not spec.use_stdout_devnull and not spec.use_stderr_devnull,
            "shell-open gained stream ownership",
        )
    require(existence_checks == [], "default spec construction probed an executable")

    empty = opener.build_open_spec("", "")
    require(empty.url == "" and empty.open_mode == "shell_open", "platform layer changed empty-URL validation ownership")


def _assert_explicit_specs() -> None:
    browser_paths = (
        r"C:\Test\browser.exe",
        r"C:\Program Files\Test Browser\browser.exe",
        r"C:\Temp\中文 浏览器\browser.exe",
    )
    urls = (
        "https://example.invalid/path with space",
        "https://例子.invalid/中文",
        "https://example.invalid/?a=1&b=100%25#fragment?x=y\\tail",
        "custom-scheme://value?equals=a=b&percent=%VALUE%",
        "",
    )
    seen: list[str] = []
    opener = _windows_opener(lambda path: seen.append(path) or True)
    for browser_path in browser_paths:
        for url in urls:
            spec = opener.build_open_spec(url, browser_path)
            require(spec.open_mode == "process", "explicit browser did not select process mode")
            require(spec.url == url, "explicit URL was trimmed, parsed, or rewritten")
            require(spec.executable == browser_path, "explicit browser executable changed")
            require(spec.command_args == (browser_path, url), "explicit-browser argv/order changed")
            require(spec.cwd is None, "explicit browser gained cwd")
            require(spec.creationflags == 0, "explicit browser gained creationflags")
            require(not spec.use_startupinfo, "explicit browser gained startupinfo")
            require(spec.startupinfo_dw_flags == 0 and spec.startupinfo_show_window == 0, "startupinfo flags changed")
            require(
                not spec.use_stdin_devnull and not spec.use_stdout_devnull and not spec.use_stderr_devnull,
                "explicit browser gained DEVNULL streams",
            )
    require(len(seen) == len(browser_paths) * len(urls), "explicit browser existence check count changed")

    missing = r"C:\Test\missing browser.exe"
    opener = _windows_opener(lambda path: path != missing)
    try:
        opener.build_open_spec("https://example.invalid/", missing)
    except FileNotFoundError as exc:
        require(str(exc) == f"浏览器路径不存在: {missing}", "missing-browser exception text changed")
    else:
        raise AssertionError("missing explicit browser did not raise FileNotFoundError")


class _UnreadableProcess:
    def wait(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("URL runtime called wait()")

    def communicate(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("URL runtime called communicate()")

    @property
    def returncode(self) -> int:
        raise AssertionError("URL runtime read returncode")


def _assert_runtime_contract(temp_root: Path) -> None:
    import runtime.launcher_runtime as launcher_runtime

    original_popen = launcher_runtime.subprocess.Popen
    original_startfile = launcher_runtime.os.startfile
    original_get_url_opener = launcher_runtime.get_url_opener
    original_environment = os.environ.copy()
    original_cwd = Path.cwd()
    calls: list[tuple[list[str], dict[str, object]]] = []
    opened: list[str] = []
    runtime_opener = get_url_opener(
        platform_info=_platform("Windows", "win32", "nt"),
        path_exists=os.path.exists,
    )

    def fake_popen(args: list[str], **kwargs: object) -> _UnreadableProcess:
        calls.append((args, kwargs))
        return _UnreadableProcess()

    launcher_runtime.subprocess.Popen = fake_popen  # type: ignore[assignment]
    launcher_runtime.os.startfile = opened.append  # type: ignore[attr-defined]
    launcher_runtime.get_url_opener = lambda: runtime_opener  # type: ignore[assignment]
    try:
        default_url = "custom+测试://host/空 格?q=one&b=100%25#片段"
        default_logs: list[str] = []
        RuntimeExecutor(log_callback=default_logs.append).run_url_step(
            UrlStep(name="default", url=default_url, browser_path="")
        )
        require(opened == [default_url], "default URL did not call os.startfile exactly once")
        require(calls == [], "default URL unexpectedly called Popen")
        require(default_logs == [f"[成功] 已打开网址: {default_url}"], "default success log changed")

        browser_path = temp_root / "Browser 中文.exe"
        browser_path.write_bytes(b"fixture")
        explicit_url = "https://example.invalid/a b?one=1&two=100%25#片段\\tail"
        explicit_logs: list[str] = []
        result = RuntimeExecutor(log_callback=explicit_logs.append).run_url_step(
            UrlStep(name="explicit", url=explicit_url, browser_path=str(browser_path))
        )
        require(result is None and len(calls) == 1, "explicit browser was not one-shot fire-and-forget")
        args, kwargs = calls[0]
        require(args == [str(browser_path), explicit_url], "runtime explicit-browser argv changed")
        require(kwargs == {}, f"runtime explicit-browser Popen options changed: {kwargs}")
        require(kwargs.get("shell", False) is False, "explicit browser no longer uses shell=False semantics")
        require(all(name not in kwargs for name in ("stdin", "stdout", "stderr")), "explicit browser gained stream redirection")
        require(all(name not in kwargs for name in ("cwd", "env", "creationflags", "startupinfo")), "explicit browser process options changed")
        require(explicit_logs == [f"[成功] 已打开网址: {explicit_url}"], "explicit success log changed")
        require(os.environ == original_environment and Path.cwd() == original_cwd, "URL runtime changed environment or cwd")

        before = (len(opened), len(calls))
        try:
            RuntimeExecutor().run_url_step(UrlStep(url=" \t ", browser_path=""))
        except ValueError as exc:
            require(str(exc) == "URL 为空", "empty-URL exception text changed")
        else:
            raise AssertionError("empty URL did not raise ValueError")
        require((len(opened), len(calls)) == before, "empty URL caused an external action")

        missing = str(temp_root / "missing.exe")
        try:
            RuntimeExecutor().run_url_step(UrlStep(url="custom://value", browser_path=missing))
        except FileNotFoundError as exc:
            require(str(exc) == f"浏览器路径不存在: {missing}", "runtime missing-browser error changed")
        else:
            raise AssertionError("runtime swallowed missing-browser error")

        shell_error = OSError("raw shell-open failure")
        launcher_runtime.os.startfile = lambda *_args: (_ for _ in ()).throw(shell_error)  # type: ignore[attr-defined]
        try:
            RuntimeExecutor().run_url_step(UrlStep(url="custom://shell-error"))
        except OSError as caught:
            require(caught is shell_error, "runtime replaced shell-open exception")
        else:
            raise AssertionError("runtime swallowed shell-open exception")

        launcher_runtime.os.startfile = opened.append  # type: ignore[attr-defined]
        for error in (
            FileNotFoundError("raw process missing"),
            PermissionError("raw process denied"),
            IsADirectoryError("raw process directory"),
            OSError("raw process system error"),
        ):
            launcher_runtime.subprocess.Popen = (  # type: ignore[assignment]
                lambda *_args, _error=error, **_kwargs: (_ for _ in ()).throw(_error)
            )
            try:
                RuntimeExecutor().run_url_step(
                    UrlStep(url="custom://process-error", browser_path=str(browser_path))
                )
            except BaseException as caught:
                require(caught is error, f"runtime replaced explicit-browser exception: {error}")
            else:
                raise AssertionError(f"runtime swallowed explicit-browser exception: {error}")

        legacy = LegacyPosixUrlOpener(
            _platform("Linux", "linux"),
            path_exists=lambda _path: True,
        )
        launcher_runtime.get_url_opener = lambda: legacy  # type: ignore[assignment]
        launcher_runtime.os.startfile = lambda *_args: (_ for _ in ()).throw(AssertionError("startfile called"))  # type: ignore[attr-defined]
        try:
            RuntimeExecutor().run_url_step(UrlStep(url="custom://non-windows"))
        except NotImplementedError:
            pass
        else:
            raise AssertionError("non-Windows default URL unexpectedly executed")
    finally:
        launcher_runtime.subprocess.Popen = original_popen  # type: ignore[assignment]
        launcher_runtime.os.startfile = original_startfile  # type: ignore[attr-defined]
        launcher_runtime.get_url_opener = original_get_url_opener  # type: ignore[assignment]


def _assert_errors() -> None:
    opener = _windows_opener()
    expectations = (
        (FileNotFoundError("missing"), "路径"),
        (PermissionError("denied"), "权限"),
        (IsADirectoryError("directory"), "目录"),
        (OSError("system"), "系统错误"),
        (AttributeError("startfile"), "不支持"),
    )
    for error, expected in expectations:
        explanation = opener.explain_open_error(error)
        require(expected in explanation, f"friendly URL explanation missing: {error}")
        require(str(error) not in explanation, "friendly explanation copied raw private detail")


def _assert_export_contract(temp_root: Path) -> None:
    original = {
        "plan_name": "URL export contract",
        "steps": [
            {
                "type": "url",
                "name": "default",
                "url": "  custom://default/中文?q=1&x=100%25#片段  ",
                "browser_path": "",
                "delay_after": 0.5,
            },
            {
                "type": "url",
                "name": "explicit",
                "url": "  https://example.invalid/a b?q=1&x=100%25#片段  ",
                "browser_path": r"  C:\Temp\Test Browser\浏览器.exe  ",
                "delay_after": 0.0,
            },
            {"type": "command", "command": "echo command", "shell": "cmd", "working_dir": ""},
            {"type": "app", "path": r"C:\Temp\tool.xyz", "args": [], "working_dir": ""},
            {"type": "wait", "seconds": 0.25, "delay_after": 0.0},
        ],
    }
    original_snapshot = json.dumps(original, ensure_ascii=False, sort_keys=True)
    prepared, assets = _prepare_embedded_plan_and_assets(original)
    require(json.dumps(original, ensure_ascii=False, sort_keys=True) == original_snapshot, "export mutated source plan")
    require(assets == [], "URL browser path was treated as a bundled asset")

    default_launch = prepared["steps"][0]["_url_open"]
    explicit_launch = prepared["steps"][1]["_url_open"]
    require(default_launch["schema"] == URL_OPEN_SCHEMA, "default URL schema missing")
    require(default_launch["open_mode"] == "shell_open", "default URL spec mode changed")
    require(default_launch["url"] == "custom://default/中文?q=1&x=100%25#片段", "export URL trim boundary changed")
    require(default_launch["command_args"] == [] and default_launch["executable"] is None, "default URL gained argv")
    expected_browser = r"C:\Temp\Test Browser\浏览器.exe"
    expected_url = "https://example.invalid/a b?q=1&x=100%25#片段"
    require(explicit_launch["schema"] == URL_OPEN_SCHEMA, "explicit URL schema missing")
    require(explicit_launch["open_mode"] == "process", "explicit URL spec mode changed")
    require(explicit_launch["executable"] == expected_browser, "export browser trim boundary changed")
    require(explicit_launch["command_args"] == [expected_browser, expected_url], "export URL argv changed")
    require(explicit_launch["cwd"] is None and explicit_launch["creationflags"] == 0, "export URL process options changed")
    require(not explicit_launch["use_startupinfo"], "export URL gained startupinfo")
    require(
        not any(explicit_launch[name] for name in ("use_stdin_devnull", "use_stdout_devnull", "use_stderr_devnull")),
        "export URL gained DEVNULL streams",
    )
    json.dumps(default_launch, ensure_ascii=False)
    json.dumps(explicit_launch, ensure_ascii=False)
    require("_command_launch" in prepared["steps"][2], "Command metadata regression")
    require("_application_launch" in prepared["steps"][3], "Application metadata regression")
    require(prepared["steps"][4] == original["steps"][4], "Wait step changed during export preparation")

    old_data_root = os.environ.get("LAUNCHFLOW_DATA_DIR")
    try:
        os.environ["LAUNCHFLOW_DATA_DIR"] = str(temp_root / "embedded AppData")
        script = EMBEDDED_TEMPLATE.replace("__PLAN_DATA__", repr(prepared))
        namespace = {"__name__": "launchflow_url_embedded_smoke", "__file__": str(temp_root / "launcher.py")}
        exec(compile(script, "<url_embedded_smoke>", "exec"), namespace)
        opened: list[str] = []
        process_calls: list[tuple[list[str], dict[str, object]]] = []

        class FakePath:
            @staticmethod
            def exists(_path: str) -> bool:
                return True

        class FakeOs:
            path = FakePath()

            @staticmethod
            def startfile(url: str) -> None:
                opened.append(url)

        class FakeSubprocess:
            DEVNULL = subprocess.DEVNULL

            @staticmethod
            def Popen(args: list[str], **kwargs: object) -> _UnreadableProcess:
                process_calls.append((args, kwargs))
                return _UnreadableProcess()

        namespace["os"] = FakeOs
        namespace["subprocess"] = FakeSubprocess

        changed_public_default = dict(prepared["steps"][0])
        changed_public_default["url"] = "custom://must-not-be-reinferred"
        namespace["run_url_step"](changed_public_default)
        require(opened == [default_launch["url"]], "embedded default URL re-inferred public fields")

        changed_public_explicit = dict(prepared["steps"][1])
        changed_public_explicit["url"] = "custom://must-not-be-reinferred"
        changed_public_explicit["browser_path"] = r"C:\wrong.exe"
        namespace["run_url_step"](changed_public_explicit)
        require(len(process_calls) == 1, "embedded explicit browser did not call Popen once")
        args, kwargs = process_calls[0]
        require(args == explicit_launch["command_args"], "embedded explicit browser re-inferred argv")
        require(kwargs == {}, f"embedded explicit browser process options changed: {kwargs}")

        shell_error = OSError("embedded raw shell error")
        FakeOs.startfile = staticmethod(lambda *_args: (_ for _ in ()).throw(shell_error))
        try:
            namespace["run_url_step"](prepared["steps"][0])
        except OSError as caught:
            require(caught is shell_error, "embedded runtime replaced shell-open exception")
        else:
            raise AssertionError("embedded runtime swallowed shell-open exception")
    finally:
        if old_data_root is None:
            os.environ.pop("LAUNCHFLOW_DATA_DIR", None)
        else:
            os.environ["LAUNCHFLOW_DATA_DIR"] = old_data_root


def _assert_public_and_dependency_contract() -> None:
    require(
        tuple(UrlOpenSpec.__dataclass_fields__)
        == (
            "open_mode",
            "url",
            "executable",
            "command_args",
            "cwd",
            "creationflags",
            "use_startupinfo",
            "startupinfo_dw_flags",
            "startupinfo_show_window",
            "use_stdin_devnull",
            "use_stdout_devnull",
            "use_stderr_devnull",
        ),
        "UrlOpenSpec fields changed",
    )
    frozen = _windows_opener().build_open_spec("custom://frozen")
    try:
        frozen.url = "changed"  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("UrlOpenSpec is not frozen")

    path = PROJECT_ROOT / "shared" / "platform" / "urls.py"
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    require(imports <= (set(sys.stdlib_module_names) | {"shared"}), f"non-stdlib import found: {imports}")
    require("PySide" not in text and "shared.models" not in text, "URL platform layer imported UI/model code")
    require("webbrowser" not in text and "QDesktopServices" not in text, "URL platform layer added another opener")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = ast.unparse(node.func)
        require(name not in {"subprocess.Popen", "os.startfile"}, f"platform layer executes URL: {name}")


def _assert_import_side_effects(temp_root: Path) -> None:
    alternate_cwd = temp_root / "alternate cwd"
    alternate_cwd.mkdir()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    probe = (
        "import os,subprocess; before=dict(os.environ); cwd=os.getcwd(); "
        "subprocess.Popen=lambda *a,**k: (_ for _ in ()).throw(AssertionError('Popen called')); "
        "os.startfile=lambda *a,**k: (_ for _ in ()).throw(AssertionError('startfile called')); "
        "import shared.platform.urls; "
        "assert os.getcwd()==cwd and dict(os.environ)==before"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=alternate_cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    require(completed.returncode == 0, f"side-effect import failed: {completed.stderr}")
    require(list(alternate_cwd.iterdir()) == [], "URL platform import wrote into cwd")


def main() -> None:
    temp_root = Path(tempfile.gettempdir()) / f"launchflow-url-backend-{os.getpid()}-{uuid.uuid4().hex}"
    temp_root.mkdir(parents=True)
    try:
        _assert_backend_selection()
        _assert_default_specs()
        _assert_explicit_specs()
        _assert_runtime_contract(temp_root)
        _assert_errors()
        _assert_export_contract(temp_root)
        _assert_public_and_dependency_contract()
        _assert_import_side_effects(temp_root)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    require(not temp_root.exists(), "URL backend smoke left temporary data")
    print("url backend smoke ok")
    print("backend=windows,legacy-posix,unknown-not-windows")
    print("default=shell-open-once,no-process,no-returncode,url-exact")
    print("explicit=popen-once,argv-exact,shell-false,no-wait,no-communicate,no-returncode")
    print("process_options=cwd-none,streams-inherited,creationflags-zero,startupinfo-none")
    print("url_values=spaces,unicode,query,ampersand,percent,fragment,question,equals,backslash,custom-scheme")
    print("errors=empty,missing,permission,directory,oserror,shell-open,raw-preserved")
    print("export_contract=json-safe,versioned,source-plan-unchanged,no-browser-asset,no-reinference")
    print("regression_metadata=command,application,wait")
    print("side_effects=import:none,process:none,url-open:none,cwd:none,environment:none,network:none")
    print("dependencies=stdlib-only,no-qt,no-model")


if __name__ == "__main__":
    main()
