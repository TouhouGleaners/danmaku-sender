from .observable_state import ObservableState, observed
from danmaku_sender.types.models.danmaku import Danmaku


class VideoState(ObservableState):
    """视频相关的共享运行时状态。属性变更时自动发射 changed 信号。"""

    bvid = observed()
    video_title = observed()
    selected_cid = observed()
    selected_part_name = observed()
    selected_part_duration_ms = observed()
    loaded_danmakus = observed()
    cid_parts_map = observed()

    def __init__(self) -> None:
        super().__init__()
        self.bvid: str = ""
        self.video_title: str = "（未获取到视频标题）"
        self.selected_cid: int | None = None
        self.selected_part_name: str = ""
        self.selected_part_duration_ms: int = 0
        self.loaded_danmakus: list[Danmaku] = []
        self.cid_parts_map: dict[int, str] = {}

    @property
    def is_ready_to_send(self) -> bool:
        return bool(self.bvid) and (self.selected_cid is not None) and bool(self.loaded_danmakus)

    @property
    def danmaku_count(self) -> int:
        return len(self.loaded_danmakus) if self.loaded_danmakus else 0
