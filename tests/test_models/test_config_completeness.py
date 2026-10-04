"""配置完整性判据 — TaskSpec / QueueTask 的缺失项说明与初始状态"""
from danmaku_sender.config import SenderConfig
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import QueueTask, TaskSpec, TaskStatus


def make_spec(danmaku_count: int, target: VideoTarget) -> TaskSpec:
    return TaskSpec(
        task_id="t1",
        target=target,
        danmakus=tuple(Danmaku(msg=f"m{i}", progress=i) for i in range(danmaku_count)),
        config=SenderConfig().to_task_config(),
    )


def make_draft(danmaku_count: int, target: VideoTarget) -> QueueTask:
    return QueueTask(
        target=target,
        danmakus=[Danmaku(msg=f"m{i}", progress=i) for i in range(danmaku_count)],
        config_snapshot=SenderConfig().to_task_config(),
    )


TARGET = VideoTarget(bvid="BV1xx411c7mD", cid=1001, title="我的视频")


class TestMissingConfigText:
    """缺失项说明：表格提示、任务详情与跳过原因共用这三句"""

    def test_complete_returns_empty(self):
        assert make_spec(1, TARGET).missing_config_text == ""
        assert make_draft(1, TARGET).missing_config_text == ""

    def test_missing_danmakus(self):
        assert make_spec(0, TARGET).missing_config_text == "未导入弹幕"
        assert make_draft(0, TARGET).missing_config_text == "未导入弹幕"

    def test_missing_target(self):
        assert make_spec(1, VideoTarget.unset()).missing_config_text == "未指定视频目标"
        assert make_draft(1, VideoTarget.unset()).missing_config_text == "未指定视频目标"

    def test_missing_both(self):
        expected = "未导入弹幕，且未指定视频目标"
        assert make_spec(0, VideoTarget.unset()).missing_config_text == expected
        assert make_draft(0, VideoTarget.unset()).missing_config_text == expected

    def test_partial_target_counts_as_missing(self):
        """有 BVID 但没选分P 也算未指定，与既有校验口径一致"""
        half = VideoTarget(bvid="BV1xx411c7mD", cid=0)
        assert make_spec(1, half).missing_config_text == "未指定视频目标"


class TestConfigCompleteness:
    """齐备判据与新建状态"""

    def test_is_config_complete(self):
        assert make_spec(1, TARGET).is_config_complete is True
        assert make_spec(0, TARGET).is_config_complete is False
        assert make_spec(1, VideoTarget.unset()).is_config_complete is False
        assert make_spec(0, VideoTarget.unset()).is_config_complete is False

        assert make_draft(1, TARGET).is_config_complete is True
        assert make_draft(0, VideoTarget.unset()).is_config_complete is False

    def test_initial_status(self):
        assert make_draft(1, TARGET).initial_status is TaskStatus.PENDING
        assert make_draft(0, TARGET).initial_status is TaskStatus.UNCONFIGURED
        assert make_draft(1, VideoTarget.unset()).initial_status is TaskStatus.UNCONFIGURED
        assert make_draft(0, VideoTarget.unset()).initial_status is TaskStatus.UNCONFIGURED
