"""API 身份凭据。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ApiAuthConfig:
    """API 身份凭据，标识接口调用方的会话身份。

    Attributes:
        sessdata: B 站会话 Cookie SESSDATA。
        bili_jct: B 站会话 Cookie bili_jct。
    """

    sessdata: str
    bili_jct: str
