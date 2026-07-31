"""
hwid.py

本机标识生成模块。

该模块负责：
- 读取 Windows 环境下可用于离线设备标识的基础信息；
- 组合并生成稳定的机器码；
- 提供适合界面展示的机器码格式化能力。

位置：
- licensing/hwid.py

相关模块：
- licensing.activation_service
- licensing.license_manager

注意事项：
- 当前实现优先追求离线环境下的稳定性与兼容性，
  不追求绝对硬件唯一；
- 生成的机器码用于本地授权绑定，不用于高强度安全对抗。
"""

from __future__ import annotations

import getpass
import os
import platform
import socket
import sys
from typing import Dict

from runtime.command_runner import execute_command
from shared.platform.detection import detect_platform
from shared.platform.identity import (
    HardwareIdentityParts,
    build_legacy_v1_machine_id,
    get_hardware_identity_provider,
    read_legacy_machine_fallback,
    read_windows_machine_guid,
    read_windows_volume_stdout,
)


def _read_windows_machine_guid() -> str:
    """
    读取 Windows 注册表中的 MachineGuid。

    返回值：
    - 成功时返回 MachineGuid 字符串；
    - 失败时返回空字符串。

    说明：
    - 这是当前离线授权场景下较稳定的设备标识来源之一；
    - 非 Windows 环境下直接返回空字符串。
    """
    return read_windows_machine_guid(os_name=os.name)


def _read_machine_sid_fallback() -> str:
    """
    获取设备标识的兜底信息组合。

    返回值：
    - 由系统版本、主机名、用户名等信息拼接而成的字符串。

    说明：
    - 当更稳定的硬件标识不可用时，使用该组合作为补充；
    - 当前目标是提高离线环境下的相对稳定性，而不是强对抗唯一性。
    """
    return read_legacy_machine_fallback(
        system_reader=platform.system,
        release_reader=platform.release,
        version_reader=platform.version,
        hostname_reader=socket.gethostname,
        username_reader=getpass.getuser,
    )


def _read_volume_serial() -> str:
    """
    尝试读取系统盘卷序列号。

    返回值：
    - 成功时返回命令输出文本；
    - 失败时返回空字符串。
    """
    return read_windows_volume_stdout(execute_command, os_name=os.name)


def get_machine_fingerprint_parts() -> Dict[str, str]:
    """
    获取构成机器码的原始字段集合。

    返回值：
    - 包含 machine_guid、volume_serial、fallback 等字段的字典。

    使用场景：
    - 调试机器码来源；
    - 排查授权绑定差异问题。
    """
    platform_info = detect_platform(
        system="",
        machine="",
        os_name=os.name,
        sys_platform="",
    )
    provider = get_hardware_identity_provider(
        platform_info=platform_info,
        command_executor=execute_command,
        machine_guid_reader=_read_windows_machine_guid,
        volume_reader=_read_volume_serial,
        fallback_reader=_read_machine_sid_fallback,
        python_version_reader=lambda: sys.version.split()[0],
        platform_metadata_reader=platform.platform,
    )
    return provider.collect_parts().to_legacy_dict()


def get_machine_id() -> str:
    """
    生成当前设备机器码。

    返回值：
    - 基于多个原始字段组合后计算得到的 SHA-256 十六进制字符串。

    生成逻辑：
    1. 优先使用 MachineGuid；
    2. 叠加卷序列号与兜底系统信息；
    3. 对拼接结果执行 SHA-256 摘要。

    说明：
    - 当前机器码主要用于离线授权绑定；
    - 这里的哈希目的是固定格式并降低直接暴露原始系统信息的程度。
    """
    parts = get_machine_fingerprint_parts()

    legacy_parts = HardwareIdentityParts(
        machine_guid=parts.get("machine_guid", ""),
        volume_serial=parts.get("volume_serial", ""),
        fallback=parts.get("fallback", ""),
        python="",
        platform="",
    )
    return build_legacy_v1_machine_id(legacy_parts)


def format_machine_id(machine_id: str, group: int = 4) -> str:
    """
    将机器码格式化为更适合界面展示的分组文本。

    参数：
    - machine_id: 原始机器码字符串；
    - group: 每组字符长度，默认 4。

    返回值：
    - 按固定长度分组并以连字符连接的机器码文本。
    """
    text = "".join(ch for ch in machine_id if ch.isalnum()).upper()
    return "-".join(text[i:i + group] for i in range(0, len(text), group))
