"""common 模型单元测试 — TaskMeta"""
from danmaku_sender.types.models.common import TaskMeta


class TestTaskMeta:
    def test_defaults_are_unknown(self):
        meta = TaskMeta()
        assert meta.video_title == ""
        assert meta.part_page is None
        assert meta.part_title == ""
        assert meta.part_duration_ms is None
        assert meta.xml_path is None

    def test_holds_task_description(self):
        meta = TaskMeta(
            video_title="我的视频",
            part_page=2,
            part_title="P2",
            part_duration_ms=1000,
        )
        assert meta.video_title == "我的视频"
        assert meta.part_page == 2
        assert meta.part_title == "P2"
        assert meta.part_duration_ms == 1000
