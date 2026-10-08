"""common 模型单元测试 — VideoTarget, TaskMeta, DanmakuStatus"""
from danmaku_sender.types.models.common import TaskMeta, VideoTarget


class TestVideoTarget:
    def test_is_assigned_needs_bvid_and_cid(self):
        assert not VideoTarget().is_assigned
        assert not VideoTarget(bvid="BV1xx411c7mD").is_assigned
        assert not VideoTarget(cid=1001).is_assigned
        assert VideoTarget(bvid="BV1xx411c7mD", cid=1001).is_assigned

    def test_unset_is_all_none(self):
        tv = VideoTarget()
        assert tv.bvid is None
        assert tv.cid is None
        assert not tv.is_assigned


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
