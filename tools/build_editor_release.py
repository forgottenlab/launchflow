"""
build_editor_release.py

编辑器发布版打包脚本。

该脚本负责：
- 检查当前环境是否已安装 PyInstaller；
- 清理旧构建目录与旧产物；
- 准备发布运行所需的基础数据目录与默认文件；
- 调用 PyInstaller 将编辑器入口打包为单文件 exe。

位置：
- tools/build_editor_release.py

适用场景：
- 本地开发完成后生成新的发布版编辑器；
- 迭代修复 UI、授权或流程逻辑后重新打包测试。

注意事项：
- 该脚本用于打包编辑器本体，不用于生成用户启动方案 exe；
- 打包前会清理旧 build / dist 目录，请避免在其中放置手工维护文件。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def run_command(command: list[str], cwd: Path | None = None) -> None:
    """
    执行外部命令，并在命令失败时抛出异常。

    参数：
    - command: 需要执行的命令列表；
    - cwd: 可选工作目录。
    """
    print(f"\n[执行命令] {' '.join(command)}")
    result = subprocess.run(command, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"命令执行失败，退出码: {result.returncode}")


def ensure_pyinstaller() -> None:
    """
    确保当前 Python 环境中已安装 PyInstaller。

    说明：
    - 打包脚本面向开发环境；
    - 若用户环境中缺少 PyInstaller，会自动尝试安装。
    """
    try:
        __import__("PyInstaller")
        print("[检查] 已检测到 PyInstaller")
    except ImportError:
        print("[检查] 未检测到 PyInstaller，开始自动安装...")
        run_command([sys.executable, "-m", "pip", "install", "pyinstaller"])


def clean_old_build(base_dir: Path, exe_name: str) -> None:
    """
    清理旧的构建目录与 spec 文件。

    参数：
    - base_dir: 项目根目录；
    - exe_name: 可执行文件名称。
    """
    for path in [
        base_dir / "build",
        base_dir / "dist",
        base_dir / f"{exe_name}.spec",
    ]:
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
                print(f"[清理] 已删除目录: {path}")
            else:
                path.unlink()
                print(f"[清理] 已删除文件: {path}")


def build_editor_command(project_root: Path, exe_name: str = "LaunchFlow") -> list[str]:
    """Build the authoritative PyInstaller command for the editor release."""
    entry_script = project_root / "editor" / "main.py"
    icon_path = project_root / "assets" / "launchflow.ico"
    public_key_path = project_root / "data" / "public_key.pem"
    if not entry_script.exists():
        raise FileNotFoundError(f"未找到入口文件: {entry_script}")
    if not icon_path.exists():
        raise FileNotFoundError(f"未找到 Windows 图标: {icon_path}")

    dist_dir = project_root / "dist"
    build_dir = project_root / "build"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        exe_name,
        "--icon",
        str(icon_path),
        "--add-data",
        f"{icon_path}{os.pathsep}assets",
    ]
    if public_key_path.is_file():
        command.extend(["--add-data", f"{public_key_path}{os.pathsep}data"])
    command.extend([
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir),
        "--specpath",
        str(build_dir),
        "--paths",
        str(project_root),
        str(entry_script),
    ])
    return command


def build_editor_release(project_root: Path, exe_name: str = "LaunchFlow") -> Path:
    """
    打包编辑器发布版。

    参数：
    - project_root: 项目根目录；
    - exe_name: 生成的 exe 名称。

    返回值：
    - 生成后的 exe 文件路径。
    """
    dist_dir = project_root / "dist"
    command = build_editor_command(project_root, exe_name)

    run_command(command, cwd=project_root)

    exe_path = dist_dir / f"{exe_name}.exe"
    if not exe_path.exists():
        raise FileNotFoundError(f"打包完成但未找到 exe: {exe_path}")

    return exe_path


def ensure_runtime_data(project_root: Path) -> None:
    """Validate read-only release inputs without creating user data in source."""
    required = [
        project_root / "editor" / "main.py",
        project_root / "assets" / "launchflow.ico",
    ]
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("发布资源缺失: " + ", ".join(str(path) for path in missing))


def main() -> None:
    """
    打包脚本主入口。
    """
    project_root = Path(__file__).resolve().parent.parent
    exe_name = "LaunchFlow"

    print("=" * 60)
    print("开始打包 LaunchFlow.exe")
    print("=" * 60)
    print(f"[项目目录] {project_root}")

    try:
        ensure_pyinstaller()
        clean_old_build(project_root, exe_name)
        ensure_runtime_data(project_root)
        exe_path = build_editor_release(project_root, exe_name)

        print("\n" + "=" * 60)
        print("[成功] 打包完成")
        print(f"[输出] {exe_path}")
        print("=" * 60)

    except Exception as e:
        print("\n" + "=" * 60)
        print(f"[失败] {e}")
        print("=" * 60)

    input("\n按回车键退出...")


if __name__ == "__main__":
    main()
