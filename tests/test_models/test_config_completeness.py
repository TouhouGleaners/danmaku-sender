"""配置完整性判据 — TaskDefinition / TaskDraft 的缺失项说明与初始状态"""
from danmaku_sender.config import SenderConfig
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import TaskDefinition, TaskDraft, TaskStatus

TARGET = VideoTarget(bvid="BV1xx411c7mD", cid=1001)


def make_definition(danmaku_count: int, target: VideoTarget) -> TaskDefinition:
    return TaskDefinition(
        task_id="t1",
        target=target,
        danmakus=tuple(Danmaku(msg=f"m{i}", progress=i) for i in range(danmaku_count)),
        config=SenderConfig().to_task_config(),
    )


def make_draft(danmaku_count: int, target: VideoTarget) -> TaskDraft:
    return TaskDraft(
        target=target,
        danmakus=[Danmaku(msg=f"m{i}", progress=i) for i in range(danmaku_count)],
        config=SenderConfig().to_task_config(),
    )


class TestMissingConfigText:
    """缺失项说明：表格提示、任务详情与跳过原因共用这三句"""

    def test_complete_task_has_no_message(self):
        assert make_definition(1, TARGET).missing_config_text == ""
        assert make_draft(1, TARGET).missing_config_text == ""

    def test_no_danmakus(self):
        expected = "未导入弹幕"
        assert make_definition(0, TARGET).missing_config_text == expected
        assert make_draft(0, TARGET).missing_config_text == expected

    def test_no_target(self):
        expected = "未指定视频目标"
        assert make_definition(1, VideoTarget()).missing_config_text == expected
        assert make_draft(1, VideoTarget()).missing_config_text == expected

    def test_neither(self):
        expected = "未导入弹幕，且未指定视频目标"
        assert make_definition(0, VideoTarget()).missing_config_text == expected
        assert make_draft(0, VideoTarget()).missing_config_text == expected

    def test_bvid_without_cid_is_unassigned(self):
        """有 BVID 但没选分P 也算未指定，与既有校验口径一致"""
        half = VideoTarget(bvid="BV1xx411c7mD")
        assert make_definition(1, half).missing_config_text == "未指定视频目标"


class TestConfigCompleteness:
    def test_complete(self):
        assert make_definition(1, TARGET).is_config_complete is True
        assert make_draft(1, TARGET).is_config_complete is True

    def test_missing_each(self):
        assert make_definition(0, TARGET).is_config_complete is False
        assert make_definition(1, VideoTarget()).is_config_complete is False
        assert make_definition(0, VideoTarget()).is_config_complete is False

    def test_draft_initial_status(self):
        assert make_draft(1, TARGET).initial_status is TaskStatus.PENDING
        assert make_draft(1, VideoTarget()).initial_status is TaskStatus.UNCONFIGURED
        assert make_draft(0, VideoTarget()).initial_status is TaskStatus.UNCONFIGURED
