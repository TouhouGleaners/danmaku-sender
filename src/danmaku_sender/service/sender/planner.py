"""发送计划：

在任务启动前确定“需要发送的弹幕 与 每条弹幕发送完毕后的等待时间”；
发送流程与 ETA（预计剩余时间）共用同一份计划。
"""

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum

from danmaku_sender.types.models.danmaku import Danmaku, DanmakuFingerprint
from danmaku_sender.types.models.queue import TaskConfig


class PlanAction(Enum):
    """PlanStep 的执行动作。"""

    SEND = "send"
    SKIP_DUPLICATE = "skip_duplicate"


@dataclass(frozen=True)
class PlanStep:
    """计划中的单条弹幕。

    Attributes:
        index (int): 在完整弹幕列表中的绝对索引 (0-based，断点续传后不进行重排)。
        danmaku (Danmaku): 对应的弹幕对象。
        action (PlanAction): 执行动作（发送 / 跳过重复）。
        delay (float): 当前弹幕发送完毕后的等待秒数（在生成计划时确定）；跳过项与最后一个发送步的延迟为 0。
        is_burst_rest (bool): 当前 Delay 是否为爆发期的长休整。
    """

    index: int
    danmaku: Danmaku
    action: PlanAction
    delay: float = 0.0
    is_burst_rest: bool = False


class SendPlan:
    """一次发送任务的执行计划

    负责根据断点索引与查重状态，在启动前一次性生成后续的 PlanStep 序列。

    Attributes:
        steps (tuple[PlanStep, ...]): 断点之后的 PlanStep 执行序列。
    """

    def __init__(
        self,
        danmakus: Sequence[Danmaku],
        start_index: int,
        config: TaskConfig,
        allow_duplicates: bool,
        db_counts: Mapping[DanmakuFingerprint, int],
    ) -> None:
        """由输入定出断点之后的执行计划。

        Args:
            danmakus (Sequence[Danmaku]): 完整的弹幕列表；起点之前的条目只参与出现次数统计，不生成计划步。
            start_index (int): 断点续传的起点索引；若索引越界，则计划为空。
            config (TaskConfig): 本任务的发送节奏，爆发休息按它编排。
            allow_duplicates (bool): 若为 True，则跳过查重逻辑，全部发送。
            db_counts (Mapping[DanmakuFingerprint, int]): 历史发送统计中的特征计数统计。
        """
        self.steps: tuple[PlanStep, ...] = self._build_steps(danmakus, start_index, config, allow_duplicates, db_counts)

    @staticmethod
    def _build_steps(
        danmakus: Sequence[Danmaku],
        start_index: int,
        config: TaskConfig,
        allow_duplicates: bool,
        db_counts: Mapping[DanmakuFingerprint, int],
    ) -> tuple[PlanStep, ...]:
        """把断点之后的条目编排成 PlanStep 序列。

        逐条判定查重跳过，并为需要等待的发送步确定等待时长与爆发休息。

        Args:
            danmakus (Sequence[Danmaku]): 完整的弹幕列表；起点之前的条目只参与出现次数统计。
            start_index (int): 断点续传的起点索引。
            config (TaskConfig): 本任务的发送节奏，爆发休息按它编排。
            allow_duplicates (bool): 若为 True，则跳过查重逻辑，全部发送。
            db_counts (Mapping[DanmakuFingerprint, int]): 历史发送统计中的特征计数统计。

        Returns:
            tuple[PlanStep, ...]: 起点之后每个下标一个计划步，按列表顺序。
        """
        steps: list[PlanStep] = []
        occurrences: dict[DanmakuFingerprint, int] = {}

        # 爆发阶段仅统计实际发送的弹幕，跳过项不计入；阶段计数从本次执行起算
        wait_count = 0

        for i, dm in enumerate(danmakus):
            fingerprint = dm.fingerprint
            occurrences[fingerprint] = occurrences.get(fingerprint, 0) + 1
            if i < start_index:
                continue

            if not allow_duplicates and occurrences[fingerprint] <= db_counts.get(fingerprint, 0):
                steps.append(PlanStep(index=i, danmaku=dm, action=PlanAction.SKIP_DUPLICATE))
                continue

            wait_count += 1
            is_burst_rest = config.burst_enabled and config.burst_size > 0 and wait_count % config.burst_size == 0
            delay = (
                random.uniform(config.rest_min, config.rest_max)
                if is_burst_rest
                else random.uniform(config.min_delay, config.max_delay)
            )
            steps.append(
                PlanStep(index=i, danmaku=dm, action=PlanAction.SEND, delay=delay, is_burst_rest=is_burst_rest)
            )

        # 最后一个发送步之后没有发送了，它的等待无处可用；尾随的跳过项也归它管
        for pos in range(len(steps) - 1, -1, -1):
            if steps[pos].action is PlanAction.SEND:
                steps[pos] = replace(steps[pos], delay=0.0, is_burst_rest=False)
                break

        return tuple(steps)

    def remaining_eta(self, from_index: int = 0) -> float:
        """计算指定索引起的计划步骤等待时间总和；等待时长在生成计划时确定，不包含重试带来的动态偏差。

        Args:
            from_index (int): 起算下标，取完整列表中的绝对下标（与 PlanStep.index 相同），默认从头。

        Returns:
            float: 剩余秒数。
        """
        return sum(step.delay for step in self.steps if step.index >= from_index)
