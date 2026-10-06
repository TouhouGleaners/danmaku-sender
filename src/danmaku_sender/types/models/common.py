from dataclasses import dataclass
from enum import Enum, IntEnum, auto
from typing import TypedDict

from .danmaku import Danmaku


class RelativePosition(Enum):
    """相对参考项的位置（有序集合中的前后）。

    队列插入、编辑器插入与上下移动共用这一根轴：ABOVE 是参考项之前，
    BELOW 是参考项之后。
    """
    ABOVE = auto()
    BELOW = auto()


class DanmakuStatus(IntEnum):
    PENDING = 0   # 待验证
    VERIFIED = 1  # 已存活
    LOST = 2      # 已丢失


@dataclass(frozen=True)
class VideoTarget:
    """封装发送目标BVID和CID的视频信息（不可变）。

    缺席的目标用空值表示（见 :meth:`unset`），不必引入 Optional。
    """
    bvid: str
    cid: int
    title: str = ""

    @classmethod
    def unset(cls) -> "VideoTarget":
        """尚未指定视频目标的空哨兵（拖入 XML 建任务的初始态）。"""
        return cls(bvid="", cid=0, title="")

    @property
    def is_assigned(self) -> bool:
        """是否已指定有效目标：BVID 与分P 都在才算。"""
        return bool(self.bvid) and self.cid > 0

    @property
    def display_string(self) -> str:
        """日志显示：有标题显示标题，没标题显示 BVID，都没有则标注未指定。"""
        return self.title or self.bvid or "未指定视频目标"


class MonitorStats(TypedDict):
    """监控统计数据结构"""
    total: int
    verified: int
    pending: int
    lost: int


class VerifyResult(TypedDict):
    """弹幕验证结果"""
    verified: int
    lost: int
    total_checked: int


class AuthCookies(TypedDict):
    """身份凭证 Cookie 结构"""
    SESSDATA: str
    bili_jct: str


class UnsentDanmakusRecord(TypedDict):
    """未发送弹幕记录"""
    dm: Danmaku
    reason: str


class PendingCidRecord(TypedDict):
    """待验证 CID 记录"""
    bvid: str
    cid: int


class PendingDanmakuRecord(TypedDict):
    """待验证弹幕记录"""
    dmid: str
    msg: str
    progress: int
    ctime: float
