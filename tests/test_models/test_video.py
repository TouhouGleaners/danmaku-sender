"""VideoInfo / VideoPart 模型单元测试"""
import pytest
from danmaku_sender.core.models.video import VideoInfo, VideoPart


@pytest.fixture
def video_info() -> VideoInfo:
    return VideoInfo(
        bvid="BV1xx411c7mD",
        title="测试视频",
        duration=300,
        parts=[
            VideoPart(cid=1001, page=1, title="P1", duration=120),
            VideoPart(cid=1002, page=2, title="P2", duration=180),
        ]
    )


class TestVideoPart:
    def test_fields(self):
        p = VideoPart(cid=1001, page=1, title="第一P", duration=120)
        assert p.cid == 1001
        assert p.page == 1
        assert p.title == "第一P"
        assert p.duration == 120


class TestVideoInfo:
    def test_fields(self, video_info: VideoInfo):
        assert video_info.bvid == "BV1xx411c7mD"
        assert video_info.title == "测试视频"
        assert video_info.duration == 300
        assert len(video_info.parts) == 2

    def test_get_part_by_cid_found(self, video_info: VideoInfo):
        part = video_info.get_part_by_cid(1001)
        assert part is not None
        assert part.title == "P1"

    def test_get_part_by_cid_second(self, video_info: VideoInfo):
        part = video_info.get_part_by_cid(1002)
        assert part is not None
        assert part.title == "P2"

    def test_get_part_by_cid_not_found(self, video_info: VideoInfo):
        part = video_info.get_part_by_cid(9999)
        assert part is None

    def test_empty_parts_list(self):
        vi = VideoInfo(bvid="BV1test1234", title="空", duration=0, parts=[])
        assert vi.get_part_by_cid(1) is None
