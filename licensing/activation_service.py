"""
activation_service.py

离线激活服务模块。

该模块负责：
- 提供当前机器码展示能力；
- 生成适合发送给作者的申请码；
- 解析申请码；
- 导入外部授权文件并交给授权管理器保存；
- 对外暴露本地授权状态检查能力。

位置：
- licensing/activation_service.py

相关模块：
- licensing.hwid
- licensing.license_manager
- editor.ui.activation_window

说明：
- 申请码本质上是包含 machine_id 等信息的请求载荷编码结果，
  因此授权生成器无需额外手工输入机器码。
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from licensing.hwid import get_machine_id, format_machine_id
from licensing.license_manager import LicenseManager


class ActivationService:
    """
    激活流程服务对象。

    该类面向激活窗口与授权流程，负责组织“展示申请信息”
    与“导入授权文件”这两类高层操作。
    """

    def __init__(self, project_root: Path) -> None:
        """
        初始化激活服务。

        参数：
        - project_root: 当前项目根目录或发布版 exe 所在目录。
        """
        self.project_root = project_root
        self.license_manager = LicenseManager(project_root)

    def get_machine_id(self) -> str:
        """
        获取当前设备的原始机器码。
        """
        return get_machine_id()

    def get_display_machine_id(self) -> str:
        """
        获取适合界面展示的分组机器码。

        返回值：
        - 已按固定分组格式化后的机器码文本。
        """
        return format_machine_id(get_machine_id())

    def generate_request_payload(self) -> Dict[str, Any]:
        """
        生成申请码对应的原始载荷数据。

        返回值：
        - 包含 machine_id、生成时间、产品名与版本标识的字典。

        说明：
        - 授权生成器会解析该载荷中的 machine_id，
          因此用户只需发送申请码，无需额外手动提供机器码。
        """
        return {
            "machine_id": self.get_machine_id(),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "product": "VisualLauncher",
            "edition": "beta",
        }

    def generate_request_code(self) -> str:
        """
        生成适合发送给作者的申请码。

        返回值：
        - 经过 base64 编码后的申请码字符串。
        """
        payload = self.generate_request_payload()
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("utf-8")

    def parse_request_code(self, request_code: str) -> Dict[str, Any]:
        """
        解析申请码并还原出原始载荷。

        参数：
        - request_code: 用户端生成的申请码。

        返回值：
        - 原始申请载荷字典。
        """
        raw = base64.urlsafe_b64decode(request_code.encode("utf-8"))
        return json.loads(raw.decode("utf-8"))

    def import_license_file(self, file_path: Path) -> None:
        """
        导入授权文件并保存到本地固定路径。

        参数：
        - file_path: 用户选择或拖入的授权文件路径。
        """
        from shared.utils import read_json

        license_data = read_json(file_path)
        self.license_manager.save_license(license_data)

    def validate_local_license(self):
        """
        校验当前本地授权状态。

        返回值：
        - LicenseCheckResult 对象。
        """
        return self.license_manager.validate_current_license()