from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path
from typing import TypedDict

from .danmaku import Danmaku


class RelativePosition(Enum):
    """相对参考项的位置：在参考项之上还是之下。

    Attributes:
        ABOVE (str): 参考项之上，列表更靠前、时间更早。
        BELOW (str): 参考项之下，列表更靠后、时间更晚。
    """
    ABOVE = "上方"
    BELOW = "下方"


class DanmakuStatus(IntEnum):
    PENDING = 0   # 待验证
    VERIFIED = 1  # 已存活
    LOST = 2      # 已丢失


@dataclass(frozen=True, kw_only=True)
class VideoTarget:
    """发送/核销的目标：以 BVID+CID 定位的某个分P。未指定的项为 None。

    Attributes:
        bvid (str | None): 视频 BVID，未指定为 None。
        cid (int | None): 分P的 CID，未指定为 None。
    """
    bvid: str | None = None
    cid: int | None = None

    @property
    def is_assigned(self) -> bool:
        """是否已指定有效目标：BVID 与分P 都在才算。"""
        return self.bvid is not None and self.cid is not None


@dataclass(frozen=True)
class TaskMeta:
    """任务的描述性资料：展示、校验与溯源。

    Attributes:
        video_title (str): 视频标题。
        part_page (int | None): 第几 P（1-based），未指定为 None。
        part_title (str): 分P标题。
        part_duration_ms (int | None): 分P时长（毫秒），未知为 None。
        xml_path (Path | None): 弹幕文件来自哪。
    """
    video_title: str = ""
    part_page: int | None = None
    part_title: str = ""
    part_duration_ms: int | None = None
    xml_path: Path | None = None


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
