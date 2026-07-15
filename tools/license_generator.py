"""
license_generator.py

离线授权生成器。

该脚本由开发者本地使用，负责：
- 解析用户发送的申请码；
- 提取其中的机器码；
- 结合授权编号、测试用户名、到期时间等信息生成授权数据；
- 使用私钥对授权数据进行签名；
- 输出最终可分发给用户的 .lic 文件。

位置：
- tools/license_generator.py

相关模块：
- shared.utils
- private/private_key.pem

安全注意事项：
- 本脚本只能在开发者本地环境运行；
- 私钥文件不得进入发布包或公开仓库；
- 输出的 .lic 文件应仅发送给对应申请设备的测试用户。
"""

from __future__ import annotations

import base64
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    # 该工具脚本通常直接从 tools 目录运行，
    # 手动注入项目根路径可以避免相对导入在独立运行时失效。
    sys.path.insert(0, str(PROJECT_ROOT))

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from shared.utils import write_json
from licensing.request_token import parse_request_token


def canonical_json_bytes(data: Dict[str, Any]) -> bytes:
    """
    将授权载荷转换为稳定的 JSON 字节串。

    说明：
    - 生成签名与验签必须基于相同的序列化规则；
    - 因此这里与 licensing.crypto 中保持一致的 canonical 处理方式。
    """
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def load_private_key(private_key_path: Path):
    """
    加载开发者本地私钥。

    参数：
    - private_key_path: 私钥文件路径。

    返回值：
    - cryptography 私钥对象。
    """
    with private_key_path.open("rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def sign_payload(private_key_path: Path, payload: Dict[str, Any]) -> str:
    """
    使用私钥对授权载荷进行签名。

    参数：
    - private_key_path: 私钥文件路径；
    - payload: 不包含 signature 字段的授权载荷。

    返回值：
    - base64 编码后的签名字符串。
    """
    private_key = load_private_key(private_key_path)
    message = canonical_json_bytes(payload)

    signature = private_key.sign(
        message,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def build_license_data(
    *,
    license_id: str,
    tester_name: str,
    machine_id: str,
    edition: str,
    expire_at: str,
    created_at: str,
    private_key_path: Path,
) -> Dict[str, Any]:
    """
    构建完整授权文件数据。

    参数：
    - license_id: 授权编号；
    - tester_name: 测试用户名；
    - machine_id: 目标设备机器码；
    - edition: 授权版本标识；
    - expire_at: 授权到期时间；
    - created_at: 授权创建时间；
    - private_key_path: 私钥路径。

    返回值：
    - 包含签名字段的授权字典。
    """
    payload = {
        "license_id": license_id,
        "tester_name": tester_name,
        "machine_id": machine_id.upper(),
        "edition": edition,
        "expire_at": expire_at,
        "created_at": created_at,
    }

    signature = sign_payload(private_key_path, payload)
    return {
        **payload,
        "signature": signature,
    }


def parse_request_code(request_code: str) -> Dict[str, Any]:
    """
    解析申请码并还原出原始请求载荷。

    参数：
    - request_code: 用户发来的申请码。

    返回值：
    - 申请码中包含的原始字典数据。
    """
    return parse_request_token(request_code)


def prompt_input(prompt: str, default: str = "") -> str:
    """
    带默认值的命令行输入辅助函数。

    参数：
    - prompt: 提示语；
    - default: 默认值。

    返回值：
    - 用户输入值，若为空则返回默认值。
    """
    if default:
        text = input(f"{prompt} [{default}]: ").strip()
        return text or default
    return input(f"{prompt}: ").strip()


def main() -> None:
    """
    授权生成器主入口。

    使用流程：
    1. 输入用户申请码；
    2. 解析出目标机器码；
    3. 输入测试用户名、授权编号、版本与到期时间；
    4. 使用私钥生成签名；
    5. 输出 .lic 文件到 generated_licenses 目录。
    """
    project_root = Path(__file__).resolve().parent.parent
    private_key_path = project_root / "private" / "private_key.pem"
    output_dir = project_root / "generated_licenses"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not private_key_path.exists():
        raise FileNotFoundError(
            f"未找到私钥文件：{private_key_path}\n"
            f"请先运行 tools/generate_keys.py 生成密钥对。"
        )

    print("=" * 60)
    print("Visual Launcher 离线授权生成器")
    print("=" * 60)

    request_code = prompt_input("请输入用户发来的申请码")
    request_data = parse_request_code(request_code)

    machine_id = str(request_data.get("machine_id", "")).strip().upper()
    if not machine_id:
        raise ValueError("申请码中未解析到 machine_id")

    tester_name = prompt_input("测试用户名", "测试用户")
    license_id = prompt_input("授权编号", f"TEST-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    edition = prompt_input("授权版本", "beta")
    expire_at = prompt_input("到期时间", "2026-12-31 23:59:59")
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    license_data = build_license_data(
        license_id=license_id,
        tester_name=tester_name,
        machine_id=machine_id,
        edition=edition,
        expire_at=expire_at,
        created_at=created_at,
        private_key_path=private_key_path,
    )

    output_path = output_dir / f"{license_id}.lic"
    write_json(output_path, license_data)

    print("\n" + "=" * 60)
    print("授权文件生成成功")
    print(f"机器码: {machine_id}")
    print(f"输出文件: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
