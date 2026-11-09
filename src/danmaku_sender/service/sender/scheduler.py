import logging
import time
from threading import Event

from danmaku_sender.config import SenderConfig
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.types.exceptions.exceptions import HistoryStorageError
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.result import (
    BiliSendResponse,
    DanmakuSendResult,
    SendStatus,
)

from .context import DanmakuFingerprint, SendingContext, SendJob
from .delay_manager import DelayManager
from .executor import DanmakuExecutor


class DanmakuScheduler:
    """发送控制循环。

    遍历弹幕、查重跳过、控制节奏，并把每条的发送与入账结果记入 SendingContext。
    发包委托 DanmakuExecutor，入账委托 HistoryManager。
    """

    def __init__(self, executor: DanmakuExecutor, history_manager: HistoryManager):
        """初始化调度器。

        Args:
            executor (DanmakuExecutor): 发包执行器。
            history_manager (HistoryManager): 本地账本，供存证与查重。
        """
        self.logger = logging.getLogger(__name__)
        self.executor = executor
        self.history_manager = history_manager

    @staticmethod
    def _get_fingerprint(dm: Danmaku) -> DanmakuFingerprint:
        """生成弹幕指纹，用于识别内容与样式完全相同的重复弹幕。

        Args:
            dm (Danmaku): 待识别的弹幕。

        Returns:
            DanmakuFingerprint: (内容, 进度, 模式, 字号, 颜色)。
        """
        return (dm.msg, dm.progress, dm.mode, dm.fontsize, dm.color)

    @classmethod
    def _seed_local_counter(cls, ctx: SendingContext, danmakus: list[Danmaku], start_index: int):
        """把起点之前的弹幕计入出现次数，让查重的「第几次出现」始终按整份列表数。

        断点续传从中途起跑时，同一条内容可能在起点前后各出现过。若不预热，
        起点之后那次会被当成第 1 次出现，从而被账本里已有的那条误判为重复而跳过。

        Args:
            ctx (SendingContext): 运行记录，持有指纹计数缓存。
            danmakus (list[Danmaku]): 整份弹幕列表。
            start_index (int): 断点续传的起点下标。
        """
        for dm in danmakus[:start_index]:
            fingerprint = cls._get_fingerprint(dm)
            ctx.local_counter[fingerprint] = ctx.local_counter.get(fingerprint, 0) + 1

    def _send_single(
        self,
        target: VideoTarget,
        dm: Danmaku,
        task_id: str,
        stop_event: Event,
    ) -> DanmakuSendResult:
        """单条弹幕的原子操作：网络发包 → 尝试入账 → 产出业务结论。

        Args:
            target (VideoTarget): 发送目标。
            dm (Danmaku): 待发弹幕。
            task_id (str): 归属任务。
            stop_event (Event): 中止信号。

        Returns:
            DanmakuSendResult: 确凿的业务结论。
        """
        response: BiliSendResponse = self.executor.execute(target, dm, stop_event)

        if not response.is_success:
            return DanmakuSendResult(status=SendStatus.FAILED, response=response)

        if not response.dmid:
            return DanmakuSendResult(
                status=SendStatus.DEGRADED,
                response=response,
                storage_error="远端成功但未返回 dmid，无法存证",
            )

        max_retries = 3
        last_error = ""
        for attempt in range(max_retries):
            try:
                self.history_manager.record_danmaku(
                    task_id, target, dm, response.dmid, response.is_visible
                )
                return DanmakuSendResult(status=SendStatus.SUCCESS, response=response)
            except HistoryStorageError as e:
                last_error = str(e)
                if attempt < max_retries - 1:
                    time.sleep(0.05 * (attempt + 1))

        return DanmakuSendResult(
            status=SendStatus.DEGRADED,
            response=response,
            storage_error=last_error,
        )

    def _should_skip(self, dm: Danmaku, ctx: SendingContext, queue_config: SenderConfig.QueueConfig) -> bool:
        """判断该弹幕是否因已发送而跳过。

        按弹幕指纹计数：本次发送中该指纹的出现序号不大于账本中已成功发送的次数时跳过。

        Args:
            dm (Danmaku): 待判断的弹幕。
            ctx (SendingContext): 运行记录，持有指纹计数缓存。
            queue_config (SenderConfig.QueueConfig): 整队规则；allow_duplicates 为真时不做查重。

        Returns:
            bool: 需要跳过返回 True。
        """
        if queue_config.allow_duplicates or not self.history_manager:
            return False

        dm_fingerprint = self._get_fingerprint(dm)

        # 记录本次任务中，该指纹是第几次出现
        ctx.local_counter[dm_fingerprint] = ctx.local_counter.get(dm_fingerprint, 0) + 1
        current_occurrence = ctx.local_counter[dm_fingerprint]

        # 查询该指纹在历史记录中的成功次数
        if (db_count := ctx.db_count_cache.get(dm_fingerprint)) is None:
            db_count = self.history_manager.count_records(ctx.target, dm)
            ctx.db_count_cache[dm_fingerprint] = db_count

        if current_occurrence <= db_count:
            self.logger.info(f"⏭️ [跳过] 已发送 ({current_occurrence}/{db_count}): {dm.msg}")
            return True
        return False

    def run_pipeline(self, job: SendJob, ctx: SendingContext) -> None:
        """执行发送控制循环，结果填入 ctx。

        Args:
            job (SendJob): 发送任务工单。
            ctx (SendingContext): 由调用方持有并传入，异常时结果仍在其中。
        """
        self.logger.info(f"🚀 启动调度流水线... 目标: {job.target.bvid or "未指定"} (CID: {job.target.cid})")

        if not job.danmakus:
            return

        # 断点续传的起点：越界收到末尾，即本轮无事可做
        start_index = min(max(0, job.start_index), ctx.total)
        if start_index:
            self.logger.info(f"📌 断点续传：从第 {start_index + 1} 条继续（前 {start_index} 条已处理）")
            self._seed_local_counter(ctx, job.danmakus, start_index)

        # 初始化时钟管理器（爆发计数接着断点走，与 calc_eta 的绝对索引对齐）
        delay_manager = DelayManager(
            normal_min=job.config.min_delay, normal_max=job.config.max_delay,
            burst_enabled=job.config.burst_enabled, burst_size=job.config.burst_size,
            rest_min=job.config.rest_min, rest_max=job.config.rest_max,
            initial_count=start_index,
        )

        if job.progress_callback:
            job.progress_callback(start_index, ctx.total)

        # 待处理的弹幕下标，其后的尚未发包
        pending_from = start_index

        try:
            for i, dm in enumerate(job.danmakus[start_index:], start=start_index):
                # --- 检查中止指令 ---
                if job.stop_event.is_set():
                    ctx.add_unsent(job.danmakus[i:], "任务手动停止")
                    break

                # --- 查重 ---
                if self._should_skip(dm, ctx, job.queue_config):
                    ctx.skipped_count += 1
                    pending_from = i + 1
                    if job.progress_callback:
                        job.progress_callback(pending_from, ctx.total)
                    continue

                ctx.attempted_count += 1
                self.logger.info(f"[{i+1}/{ctx.total}] 准备执行: {dm.msg}")

                # --- 发送 + 入账：单条的原子操作 ---
                result = self._send_single(job.target, dm, job.task_id, job.stop_event)

                # 先记账再回调
                match result.status:
                    case SendStatus.SUCCESS:
                        ctx.success_count += 1

                    case SendStatus.DEGRADED:
                        ctx.success_count += 1
                        ctx.evidence_failures.append((dm, result.storage_error or "未知存证错误"))

                    case SendStatus.FAILED:
                        ctx.add_unsent(dm, result.response.hint)

                pending_from = i + 1
                # 进度在单条结算后推进：游标只盖已结算条目，在飞的一条崩了续传会重试
                if job.progress_callback:
                    job.progress_callback(pending_from, ctx.total)

                if job.result_callback:
                    job.result_callback(dm, result)

                if result.status is SendStatus.FAILED and result.is_fatal:
                    ctx.fatal_error_occurred = True
                    ctx.fatal_error_msg = result.response.hint
                    ctx.add_unsent(job.danmakus[i + 1:], f"致命错误: {result.response.hint}")
                    break

                # --- 正常节奏控制 ---
                is_last_item = (i == ctx.total - 1)
                if not is_last_item and delay_manager.wait_and_check_stop(job.stop_event):
                    if i + 1 < ctx.total:
                        ctx.add_unsent(job.danmakus[i+1:], "任务手动停止")
                    break

        except Exception as e:
            ctx.fatal_error_occurred = True
            ctx.fatal_error_msg = str(e)
            ctx.add_unsent(job.danmakus[pending_from:], f"异常中断: {e}")
            self.logger.exception("发送循环异常中止")
