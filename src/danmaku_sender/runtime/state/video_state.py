from .observable_state import ObservableState

from danmaku_sender.types.models.danmaku import Danmaku


class VideoState(ObservableState):
    """
    视频相关的共享运行时状态

    继承 ObservableState，属性变更时自动发射 changed 信号。
    """
    bvid: str = ""
    video_title: str = "（未获取到视频标题）"
    selected_cid: int | None = None
    selected_part_name: str = ""
    selected_part_duration_ms: int = 0
    loaded_danmakus: list[Danmaku]
    cid_parts_map: dict[int, str]

    def __init__(self):
        super().__init__()
        with self.init_context():
            self.loaded_danmakus = []
            self.cid_parts_map = {}

    @property
    def is_ready_to_send(self) -> bool:
        return bool(self.bvid) and (self.selected_cid is not None) and bool(self.loaded_danmakus)

    @property
    def danmaku_count(self) -> int:
        return len(self.loaded_danmakus) if self.loaded_danmakus else 0
