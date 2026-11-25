"""配置完整性判据 — Task 的缺失项说明与入队预备状态"""
from danmaku_sender.config import SenderConfig
from danmaku_sender.state import QueueState
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import (
    DanmakuPack,
    SendOptions,
    Task,
    TaskInfo,
    TaskState,
    TaskStatus,
)

TARGET = VideoTarget(bvid="BV1xx411c7mD", cid=1001)


def make_task(danmaku_count: int, target: VideoTarget | None) -> Task:
    """构造领域任务，弹幕按条数生成；``target`` 为 None 表示未配置目标。"""
    return Task(
        task_id="t1",
        target=target,
        info=TaskInfo(),
        pack=DanmakuPack(items=tuple(Danmaku(msg=f"m{i}", progress=i) for i in range(danmaku_count))),
        options=SendOptions(pacing=SenderConfig.PacingConfig().to_task_config()),
        state=TaskState(),
    )


class TestMissingConfigText:
    """缺失项说明：表格提示、任务详情与跳过原因共用这三句"""

    def test_complete_task_has_no_message(self):
        assert make_task(1, TARGET).missing_config_text == ""

    def test_no_danmakus(self):
        assert make_task(0, TARGET).missing_config_text == "未导入弹幕"

    def test_no_target(self):
        assert make_task(1, None).missing_config_text == "未指定视频目标"

    def test_neither(self):
        assert make_task(0, None).missing_config_text == "未导入弹幕，且未指定视频目标"


class TestConfigCompleteness:
    def test_complete(self):
        assert make_task(1, TARGET).is_config_complete is True

    def test_missing_each(self):
        assert make_task(0, TARGET).is_config_complete is False
        assert make_task(1, None).is_config_complete is False
        assert make_task(0, None).is_config_complete is False

    def test_initial_status(self):
        """入队对齐的预备状态：配置齐备转待发，残缺停在未配置"""
        assert (
            QueueState.aligned_status(TaskStatus.PENDING, "", make_task(1, TARGET).is_config_complete)[0]
            is TaskStatus.PENDING
        )
        assert (
            QueueState.aligned_status(TaskStatus.PENDING, "", make_task(1, None).is_config_complete)[0]
            is TaskStatus.UNCONFIGURED
        )
        assert (
            QueueState.aligned_status(TaskStatus.PENDING, "", make_task(0, None).is_config_complete)[0]
            is TaskStatus.UNCONFIGURED
        )
