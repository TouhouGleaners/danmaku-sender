from danmaku_sender.types.models.evented_model import EventedModel
from danmaku_sender.types.models.danmaku import Danmaku


class VideoState(EventedModel):
    """视频相关的共享运行时状态。继承 EventedModel，属性变更时自动触发订阅回调。"""

    bvid: str = ""
    video_title: str = "（未获取到视频标题）"
    selected_cid: int | None = None
    selected_part_name: str = ""
    selected_part_duration_ms: int = 0
    loaded_danmakus: list[Danmaku] = []
    cid_parts_map: dict[int, str] = {}

    @property
    def is_ready_to_send(self) -> bool:
        return bool(self.bvid) and (self.selected_cid is not None) and bool(self.loaded_danmakus)

    @property
    def danmaku_count(self) -> int:
        return len(self.loaded_danmakus) if self.loaded_danmakus else 0
