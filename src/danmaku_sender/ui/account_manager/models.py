"""账号管理 UI 层数据模型"""
from dataclasses import dataclass


@dataclass
class AccountData:
    """单个账号的 UI 层数据"""
    nickname: str = "未知用户"
    sessdata: str = ""
    bili_jct: str = ""
    is_valid: bool | None = None  # None=未检测, True=有效, False=失效

    @property
    def masked_sessdata(self) -> str:
        return _mask(self.sessdata)

    @property
    def masked_bili_jct(self) -> str:
        return _mask(self.bili_jct)


def _mask(value: str) -> str:
    """遮蔽凭据：保留前4后4，中间用 * 替代，总长不超过 20"""
    if len(value) <= 8:
        return value
    stars = min(len(value) - 8, 8)
    return f"{value[:4]}{'*' * stars}{value[-4:]}"
