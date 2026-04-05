"""
license_manager.py

本地授权管理模块。

该模块负责：
- 管理授权文件 license.lic 的保存、读取与删除；
- 校验授权文件的字段完整性、签名合法性、机器码匹配情况与过期状态；
- 返回统一的授权校验结果对象，供程序入口与激活窗口使用。

位置：
- licensing/license_manager.py

相关模块：
- licensing.crypto
- licensing.hwid
- licensing.activation_service
- editor.main
- editor.ui.activation_window

注意事项：
- 本模块是离线授权体系中的核心组件之一；
- 授权是否属于当前设备，以当前机器码与授权文件中的 machine_id 比对为准；
- 签名校验依赖公钥验签逻辑，私钥绝不能进入发布包。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from shared.utils import read_json, write_json, ensure_dir
from licensing.crypto import verify_signature
from licensing.hwid import get_machine_id


@dataclass
class LicenseCheckResult:
    """
    授权校验结果对象。

    字段说明：
    - is_valid: 当前授权是否有效；
    - code: 机器可读的错误码或状态码；
    - message: 用户可读的结果说明；
    - license_data: 授权有效或部分失败场景下的授权原始数据。
    """

    is_valid: bool
    code: str
    message: str
    license_data: Optional[Dict[str, Any]] = None


class LicenseManager:
    """
    本地授权管理器。

    负责 license 文件的保存、读取与校验。
    校验内容包括签名合法性、机器码匹配以及授权是否过期。

    该类通常由程序启动入口与激活窗口共同调用，
    是离线授权流程中的核心协调组件。
    """

    def __init__(self, project_root: Path) -> None:
        """
        初始化授权管理器。

        参数：
        - project_root: 当前项目根目录或发布版 exe 所在目录。
        """
        self.project_root = project_root
        self.data_dir = self.project_root / "data"
        self.licenses_dir = self.project_root / "licenses"
        self.license_path = self.licenses_dir / "license.lic"
        self.public_key_path = self.data_dir / "public_key.pem"

        ensure_dir(self.data_dir)
        ensure_dir(self.licenses_dir)

    def get_license_path(self) -> Path:
        """
        获取本地授权文件路径。
        """
        return self.license_path

    def has_license(self) -> bool:
        """
        判断本地是否已存在授权文件。
        """
        return self.license_path.exists()

    def save_license(self, license_data: Dict[str, Any]) -> None:
        """
        保存授权文件到本地固定位置。

        参数：
        - license_data: 授权文件对应的字典数据。
        """
        write_json(self.license_path, license_data)

    def load_license(self) -> Dict[str, Any]:
        """
        读取本地授权文件。

        返回值：
        - 授权文件对应的字典数据。

        异常：
        - FileNotFoundError: 当授权文件不存在时抛出。
        """
        if not self.license_path.exists():
            raise FileNotFoundError("未找到 license.lic")
        return read_json(self.license_path)

    def remove_license(self) -> None:
        """
        删除本地授权文件。

        使用场景：
        - 手动重置测试环境；
        - 重新导入新的授权文件；
        - 清理失效授权。
        """
        if self.license_path.exists():
            self.license_path.unlink()

    def validate_current_license(self) -> LicenseCheckResult:
        """
        校验当前本地授权是否有效。

        返回结果中会包含：
        - 是否有效；
        - 失败原因代码；
        - 用户可读的错误信息；
        - 授权数据（若可读取）。

        校验顺序：
        1. 授权文件是否存在；
        2. 授权文件是否可正常读取；
        3. 进入授权内容级别校验。
        """
        if not self.license_path.exists():
            return LicenseCheckResult(
                is_valid=False,
                code="missing_license",
                message="当前尚未激活",
            )

        try:
            license_data = self.load_license()
        except Exception as e:
            return LicenseCheckResult(
                is_valid=False,
                code="license_read_failed",
                message=f"授权文件读取失败: {e}",
            )

        return self.validate_license_data(license_data)

    def validate_license_data(self, license_data: Dict[str, Any]) -> LicenseCheckResult:
        """
        校验指定授权数据是否有效。

        参数：
        - license_data: 已加载的授权文件内容。

        返回值：
        - LicenseCheckResult: 包含授权状态与详细结果说明。

        校验内容：
        1. 关键字段是否齐全；
        2. 签名是否正确；
        3. 当前机器码是否与授权绑定一致；
        4. 授权是否已过期。
        """
        required_fields = [
            "license_id",
            "tester_name",
            "machine_id",
            "edition",
            "expire_at",
            "created_at",
            "signature",
        ]
        for field in required_fields:
            if field not in license_data:
                return LicenseCheckResult(
                    is_valid=False,
                    code="license_field_missing",
                    message=f"授权文件缺少字段: {field}",
                )

        signature = str(license_data.get("signature", "")).strip()
        payload = {k: v for k, v in license_data.items() if k != "signature"}

        ok = verify_signature(self.public_key_path, payload, signature)
        if not ok:
            return LicenseCheckResult(
                is_valid=False,
                code="invalid_signature",
                message="授权签名校验失败",
            )

        current_machine_id = get_machine_id()
        target_machine_id = str(license_data.get("machine_id", "")).strip().upper()

        if current_machine_id.upper() != target_machine_id:
            return LicenseCheckResult(
                is_valid=False,
                code="machine_not_match",
                message="当前授权不属于这台电脑",
                license_data=license_data,
            )

        expire_text = str(license_data.get("expire_at", "")).strip()
        try:
            expire_at = datetime.strptime(expire_text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return LicenseCheckResult(
                is_valid=False,
                code="invalid_expire_format",
                message="授权到期时间格式错误，应为 YYYY-MM-DD HH:MM:SS",
                license_data=license_data,
            )

        if datetime.now() > expire_at:
            return LicenseCheckResult(
                is_valid=False,
                code="license_expired",
                message="授权已过期",
                license_data=license_data,
            )

        return LicenseCheckResult(
            is_valid=True,
            code="ok",
            message="授权有效",
            license_data=license_data,
        )