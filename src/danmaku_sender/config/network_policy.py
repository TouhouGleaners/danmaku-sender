"""传输策略。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkPolicy:
    """网络传输策略，控制请求的传输层行为。

    Attributes:
        use_system_proxy: 是否跟随系统代理；为 False 时强制直连。
    """

    use_system_proxy: bool = True
