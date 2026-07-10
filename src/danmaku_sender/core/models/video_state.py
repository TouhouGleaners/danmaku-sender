from dataclasses import dataclass, field

from .danmaku import Danmaku


@dataclass
class VideoState:
    """视频相关的运行时状态"""
    bvid: str = ""
    video_title: str = "（未获取到视频标题）"
    selected_cid: int | None = None
    selected_part_name: str = ""
    selected_part_duration_ms: int = 0
    loaded_danmakus: list[Danmaku] = field(default_factory=list)

    # CID 到 分P名 的映射
    cid_parts_map: dict = field(default_factory=dict)

    @property
    def is_ready_to_send(self) -> bool:
        return bool(self.bvid) and (self.selected_cid is not None) and bool(self.loaded_danmakus)

    @property
    def danmaku_count(self) -> int:
        return len(self.loaded_danmakus)
