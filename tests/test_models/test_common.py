"""common 模型单元测试 — VideoTarget, DanmakuStatus"""
from danmaku_sender.types.models.common import VideoTarget


class TestVideoTarget:
    def test_display_string_with_title(self):
        vt = VideoTarget(bvid="BV1xx411c7mD", cid=1001, title="我的视频")
        assert vt.display_string == "我的视频"

    def test_display_string_without_title(self):
        vt = VideoTarget(bvid="BV1xx411c7mD", cid=1001)
        assert vt.display_string == "BV1xx411c7mD"

    def test_display_string_empty_title(self):
        vt = VideoTarget(bvid="BV1xx411c7mD", cid=1001, title="")
        assert vt.display_string == "BV1xx411c7mD"

    def test_unset_is_empty_sentinel(self):
        vt = VideoTarget.unset()
        assert vt.bvid == ""
        assert vt.cid == 0
        assert vt.title == ""
        assert not vt.is_assigned

    def test_is_assigned_needs_bvid_and_cid(self):
        assert not VideoTarget(bvid="", cid=0).is_assigned
        assert not VideoTarget(bvid="BV1xx411c7mD", cid=0).is_assigned
        assert not VideoTarget(bvid="", cid=1001).is_assigned
        assert VideoTarget(bvid="BV1xx411c7mD", cid=1001).is_assigned

    def test_display_string_unset_target(self):
        assert VideoTarget.unset().display_string == "未指定视频目标"
