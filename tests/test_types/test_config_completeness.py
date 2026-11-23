"""配置完整性判据 — Task / TaskDraft 的缺失项说明与初始状态"""
from danmaku_sender.config import SenderConfig
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import (
    DanmakuPack,
    SendOptions,
    TargetSlot,
    Task,
    TaskDraft,
    TaskState,
    TaskStatus,
)

TARGET = VideoTarget(bvid="BV1xx411c7mD", cid=1001)


def make_task(danmaku_count: int, target: VideoTarget | None) -> Task:
    """构造领域任务，弹幕按条数生成；``target`` 为 None 表示未配置目标。"""
    return Task(
        task_id="t1",
        slot=None if target is None else TargetSlot(target=target),
        pack=DanmakuPack(items=tuple(Danmaku(msg=f"m{i}", progress=i) for i in range(danmaku_count))),
        options=SendOptions(pacing=SenderConfig.PacingConfig().to_task_config()),
        state=TaskState(),
    )


def make_draft(danmaku_count: int, target: VideoTarget | None) -> TaskDraft:
    """构造编辑沙盒，弹幕按条数生成；``target`` 为 None 表示未配置目标。"""
    return TaskDraft(
        target=target,
        danmakus=[Danmaku(msg=f"m{i}", progress=i) for i in range(danmaku_count)],
        config=SenderConfig.PacingConfig().to_task_config(),
    )


class TestMissingConfigText:
    """缺失项说明：表格提示、任务详情与跳过原因共用这三句"""

    def test_complete_task_has_no_message(self):
        assert make_task(1, TARGET).missing_config_text == ""
        assert make_draft(1, TARGET).missing_config_text == ""

    def test_no_danmakus(self):
        expected = "未导入弹幕"
        assert make_task(0, TARGET).missing_config_text == expected
        assert make_draft(0, TARGET).missing_config_text == expected

    def test_no_target(self):
        expected = "未指定视频目标"
        assert make_task(1, None).missing_config_text == expected
        assert make_draft(1, None).missing_config_text == expected

    def test_neither(self):
        expected = "未导入弹幕，且未指定视频目标"
        assert make_task(0, None).missing_config_text == expected
        assert make_draft(0, None).missing_config_text == expected


class TestConfigCompleteness:
    def test_complete(self):
        assert make_task(1, TARGET).is_config_complete is True
        assert make_draft(1, TARGET).is_config_complete is True

    def test_missing_each(self):
        assert make_task(0, TARGET).is_config_complete is False
        assert make_task(1, None).is_config_complete is False
        assert make_task(0, None).is_config_complete is False

    def test_draft_initial_status(self):
        assert make_draft(1, TARGET).initial_status is TaskStatus.PENDING
        assert make_draft(1, None).initial_status is TaskStatus.UNCONFIGURED
        assert make_draft(0, None).initial_status is TaskStatus.UNCONFIGURED
