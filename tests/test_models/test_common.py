"""common 模型单元测试 — VideoTarget, DanmakuStatus"""
from danmaku_sender.core.models.common import VideoTarget


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
