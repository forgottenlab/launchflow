"""
utils.py

通用文件与 JSON 工具模块。

该模块负责：
- 创建目录；
- 读取 JSON 文件；
- 写入 JSON 文件；
- 列出目录中的 JSON 文件；
- 在文件缺失时返回默认 JSON 数据。

位置：
- shared/utils.py

相关模块：
- editor.services.plan_service
- licensing.license_manager
- tools.license_generator
- runtime.launcher

说明：
- 这里尽量保持工具函数简单稳定；
- 文件读写异常交由调用层决定如何处理与提示。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def ensure_dir(path: Path) -> None:
    """
    确保目录存在。

    参数：
    - path: 目标目录路径。
    """
    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> Any:
    """
    读取 JSON 文件内容。

    参数：
    - path: JSON 文件路径。

    返回值：
    - 反序列化后的 Python 对象。
    """
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    """
    将对象写入为 JSON 文件。

    参数：
    - path: 目标文件路径；
    - data: 待序列化对象。

    说明：
    - 写入前会确保父目录存在；
    - 使用 UTF-8 和缩进格式，便于人工查看与调试。
    """
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_json_files(directory: Path) -> list[Path]:
    """
    列出目录下所有 JSON 文件。

    参数：
    - directory: 目标目录。

    返回值：
    - 排序后的 JSON 文件路径列表。
    """
    if not directory.exists():
        return []
    return sorted(directory.glob("*.json"))


def load_or_default_json(path: Path, default: Any) -> Any:
    """
    读取 JSON 文件，若文件不存在则返回默认值。

    参数：
    - path: JSON 文件路径；
    - default: 默认返回对象。

    返回值：
    - 文件内容或默认值。
    """
    if not path.exists():
        return default
    return read_json(path)