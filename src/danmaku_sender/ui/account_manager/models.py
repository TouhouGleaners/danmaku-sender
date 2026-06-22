"""账号管理 UI 层数据模型"""
import hashlib
from dataclasses import dataclass, field


# 预设调色板：柔和的粉彩色系
_PALETTE = [
    "#F28B82", "#FBBC04", "#FFF475", "#CCFF90",
    "#A7FFEB", "#CBF0F8", "#AECBFA", "#D7AEFB",
    "#FDCFE8", "#E6C9A8", "#E8EAED",
]


def _color_from_sessdata(sessdata: str) -> str:
    """根据 sessdata 哈希分配一个稳定的颜色"""
    h = hashlib.md5(sessdata.encode()).hexdigest()
    return _PALETTE[int(h[:8], 16) % len(_PALETTE)]


@dataclass
class AccountData:
    """单个账号的 UI 层数据"""
    nickname: str = "未知用户"
    sessdata: str = ""
    bili_jct: str = ""
    color: str = field(default_factory=lambda: "#E8EAED")
    is_valid: bool | None = None  # None=未检测, True=有效, False=失效

    def __post_init__(self):
        if self.color == "#E8EAED" and self.sessdata:
            self.color = _color_from_sessdata(self.sessdata)

    @property
    def initial(self) -> str:
        """取昵称首字作为头像字母"""
        return self.nickname[0].upper() if self.nickname else "?"

    @property
    def masked_sessdata(self) -> str:
        return _mask(self.sessdata)

    @property
    def masked_bili_jct(self) -> str:
        return _mask(self.bili_jct)


def _mask(value: str) -> str:
    """遮蔽凭据：保留前4后4，中间用 * 替代"""
    if len(value) <= 8:
        return value
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"
