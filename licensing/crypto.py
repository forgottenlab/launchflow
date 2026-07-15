"""
crypto.py

离线授权签名与验签模块。

该模块负责：
- 规范化授权签名时使用的 JSON 数据格式；
- 加载内置公钥或外部公钥；
- 使用公钥对授权文件中的签名进行校验。

位置：
- licensing/crypto.py

相关模块：
- licensing.license_manager
- tools.license_generator

安全注意事项：
- 本模块只允许包含公钥，绝不能包含私钥；
- 私钥仅应存在于授权生成器所在的开发者环境中；
- 内置公钥用于发布版离线验签，能够避免额外分发 public_key.pem。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


# 发布版优先使用内置公钥完成验签，
# 这样测试用户只需要拿到 exe 和对应的 license 文件即可完成激活。
EMBEDDED_PUBLIC_KEY_PEM = b"""
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAmnWi/QH7hR2k7PVODgEo
hJRe6rDh6qxyJ/W6DxPOfgj8VH/0pGB2aNl29ezWjJzZUNxwFd2k8w7WnG5JFQds
rRyaXAwsbDdQJbI5BhAYhmNPBnTNFC9Ywj9VPUP90KwFnaSkrYiLfTxF+/ss/tZI
q20dUQkfhvH49eM23+URgdRvkkzpVXJ0NIiiT6zMTbuaSA3vTMb1EKPSSR2CakrN
mtAAZ4m5nJZyiIRO4ZY+D2ytDUKyrwgpZAR+p2iakNWapjFZ7/6hN5r6f3Fdog6R
XvJAktqGNQkl3wgyI5unVXUkf+1A7uYhG9A73Ldmj2BY4ZX5XDKa6eIk1QV+W4Bo
pQIDAQAB
-----END PUBLIC KEY-----
"""


def canonical_json_bytes(data: Dict[str, Any]) -> bytes:
    """
    将字典数据转换为稳定的 JSON 字节串。

    参数：
    - data: 需要参与签名或验签的数据字典。

    返回值：
    - 规范化后的 UTF-8 字节串。

    设计原因：
    - 签名和验签必须基于完全一致的序列化结果；
    - 通过固定排序和紧凑分隔符，避免因 JSON 格式差异导致验签失败。
    """
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def load_public_key_from_bytes(public_key_bytes: bytes):
    """
    从 PEM 字节内容中加载公钥对象。
    """
    return serialization.load_pem_public_key(public_key_bytes)


def load_public_key(public_key_path: Optional[Path] = None):
    """
    加载可用于验签的公钥。

    参数：
    - public_key_path: 外部公钥文件路径，可选。

    返回值：
    - cryptography 公钥对象。

    加载优先级：
    1. 优先使用内置公钥；
    2. 如未配置内置公钥，再尝试读取外部公钥文件。

    说明：
    - 当前项目以发布版可独立验签为目标，因此优先使用内置公钥。
    """
    if EMBEDDED_PUBLIC_KEY_PEM and b"BEGIN PUBLIC KEY" in EMBEDDED_PUBLIC_KEY_PEM:
        return load_public_key_from_bytes(EMBEDDED_PUBLIC_KEY_PEM)

    if public_key_path and public_key_path.exists():
        with public_key_path.open("rb") as f:
            return serialization.load_pem_public_key(f.read())

    raise FileNotFoundError("未找到可用的公钥")


def verify_signature(public_key_path: Optional[Path], payload: Dict[str, Any], signature_b64: str) -> bool:
    """
    使用公钥校验签名是否有效。

    参数：
    - public_key_path: 外部公钥文件路径，可选；
    - payload: 参与签名的原始授权载荷，不应包含 signature 字段；
    - signature_b64: base64 编码后的签名字符串。

    返回值：
    - True: 签名合法；
    - False: 签名无效或校验过程发生异常。
    """
    public_key = load_public_key(public_key_path)
    return verify_signature_with_key(public_key, payload, signature_b64)


def verify_signature_with_key(public_key, payload: Dict[str, Any], signature_b64: str) -> bool:
    """Verify a signature with an already loaded public key object."""
    message = canonical_json_bytes(payload)

    try:
        signature = base64.b64decode(signature_b64.encode("utf-8"), validate=True)
        public_key.verify(
            signature,
            message,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except InvalidSignature:
        return False
    except Exception:
        # 验签流程对外只暴露成功或失败，
        # 避免在普通调用层面泄露过多底层异常细节。
        return False
