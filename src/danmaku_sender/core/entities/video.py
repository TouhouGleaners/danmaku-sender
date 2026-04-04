from dataclasses import dataclass


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