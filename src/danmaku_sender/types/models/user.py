from dataclasses import dataclass


@dataclass
class UserProfile:
    """用户信息领域模型"""
    is_login: bool
    username: str
    uid: int = 0
    avatar_bytes: bytes = b""