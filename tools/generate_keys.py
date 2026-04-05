"""
generate_keys.py

离线授权密钥生成工具。

该脚本负责：
- 生成 RSA 私钥与公钥；
- 将公钥写入 data 目录；
- 将私钥写入 private 目录。

位置：
- tools/generate_keys.py

相关模块：
- licensing.crypto
- tools.license_generator

安全注意事项：
- 私钥只能保留在开发者本地环境中；
- 私钥绝不能进入发布包，也不应提交到公开仓库；
- 公钥可用于发布版验签与调试。
"""

from __future__ import annotations

import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    # 工具脚本通常会被直接独立执行，
    # 手动注入项目根路径可保持导入行为一致。
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    """
    生成 RSA 密钥对并写入本地目录。
    """
    project_root = Path(__file__).resolve().parent.parent

    data_dir = project_root / "data"
    private_dir = project_root / "private"
    data_dir.mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True, exist_ok=True)

    public_key_path = data_dir / "public_key.pem"
    private_key_path = private_dir / "private_key.pem"

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_key_path.write_bytes(private_bytes)
    public_key_path.write_bytes(public_bytes)

    print("=" * 60)
    print("RSA 密钥生成完成")
    print(f"公钥: {public_key_path}")
    print(f"私钥: {private_key_path}")
    print("注意：private_key.pem 不要发给任何用户，也不要放进发布包。")
    print("=" * 60)


if __name__ == "__main__":
    main()