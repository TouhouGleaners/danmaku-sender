from dataclasses import dataclass
"""
待发送弹幕目标视频的封装，成员包括视频基本信息和视频对应的待发送的弹幕
"""

@dataclass
class VideoPart:
    """分P信息"""
    cid: int
    page: int
    title: str  # API: part
    duration: int


@dataclass
class VideoInfo:
    """视频完整信息"""
    bvid: str
    title: str
    duration: int
    parts: list[VideoPart]

    def get_part_by_cid(self, cid: int) -> VideoPart | None:
        for p in self.parts:
            if p.cid == cid:
                return p
        return None

@dataclass
class DestVideo:
    """待发送弹幕目标视频封装"""
    info: VideoInfo
    danmaku: list[str]