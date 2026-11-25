"""任务资料快照单元测试 — TaskInfo"""
from danmaku_sender.types.models.queue import DanmakuPack, TaskInfo


class TestTaskInfo:
    def test_defaults_are_unknown(self):
        info = TaskInfo()
        assert info.video_title == ""
        assert info.part_page is None
        assert info.part_title == ""
        assert info.duration_ms is None
        assert DanmakuPack().source_path is None

    def test_holds_task_description(self):
        info = TaskInfo(
            video_title="我的视频",
            part_page=2,
            part_title="P2",
            duration_ms=1000,
        )
        assert info.video_title == "我的视频"
        assert info.part_page == 2
        assert info.part_title == "P2"
        assert info.duration_ms == 1000
