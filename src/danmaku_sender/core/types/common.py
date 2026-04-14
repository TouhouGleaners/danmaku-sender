from dataclasses import dataclass
from enum import IntEnum
from typing import TypedDict


class DanmakuStatus(IntEnum):
    PENDING = 0   # 待验证
    VERIFIED = 1  # 已存活
    LOST = 2      # 已丢失


@dataclass
class VideoTarget:
    """封装发送目标BVID和CID的视频信息"""
    bvid: str
    cid: int
    title: str = ""

    @property
    def display_string(self) -> str:
        """日志显示：如果有标题显示标题，没标题显示 BVID。"""
        return self.title if self.title else self.bvid


class MonitorStats(TypedDict):
    """监控统计数据结构"""
    total: int
    verified: int
    pending: int
    lost: int


class AuthCookies(TypedDict):
    """身份凭证 Cookie 结构"""
    SESSDATA: str
    bili_jct: str