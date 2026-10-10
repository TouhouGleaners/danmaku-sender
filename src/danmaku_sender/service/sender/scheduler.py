import logging
import time
from threading import Event

from danmaku_sender.config import SendPolicy
from danmaku_sender.repo.history_manager import HistoryManager
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

    遍历弹幕、查重跳过、控制节奏与自动停止，并把每条的发送与入账结果记入 SendingContext。
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

    def _should_skip(self, dm: Danmaku, ctx: SendingContext, policy: SendPolicy) -> bool:
        """
        断点续传：智能去重逻辑

        对每个指纹计数，若当前发送序列中该指纹的出现次数 <= 数据库中已成功发送的次数，则跳过。
        """
        if policy.allow_duplicates or not self.history_manager:
            return False

        dm_fingerprint = self._get_fingerprint(dm)

        # 记录本次任务中，该指纹是第几次出现
        ctx.local_counter[dm_fingerprint] = ctx.local_counter.get(dm_fingerprint, 0) + 1
        current_occurrence = ctx.local_counter[dm_fingerprint]

        # 查询该指纹在历史记录中的成功次数
        if dm_fingerprint in ctx.db_count_cache:
            db_count = ctx.db_count_cache[dm_fingerprint]
        else:
            db_count = self.history_manager.count_records(ctx.target, dm)
            ctx.db_count_cache[dm_fingerprint] = db_count

        if current_occurrence <= db_count:
            self.logger.info(f"⏭️ [跳过] 已发送 ({current_occurrence}/{db_count}): {dm.msg}")
            return True
        return False

    def _check_auto_stop(self, ctx: SendingContext, stop_event: Event, policy: SendPolicy) -> bool:
        """检查是否满足用户配置的自动终止条件（发满 N 条或运行满 M 分钟）"""
        if policy.stop_after_count > 0 and ctx.success_count >= policy.stop_after_count:
            ctx.auto_stop_reason = f"达到数量限制 ({policy.stop_after_count}条)"
            stop_event.set()
            return True

        if policy.stop_after_time > 0 and ctx.elapsed_minutes >= policy.stop_after_time:
            ctx.auto_stop_reason = f"达到时间限制 ({policy.stop_after_time}分钟)"
            stop_event.set()
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

        # 初始化时钟管理器
        delay_manager = DelayManager(
            normal_min=job.config.min_delay, normal_max=job.config.max_delay,
            burst_enabled=job.config.burst_enabled, burst_size=job.config.burst_size,
            rest_min=job.config.rest_min, rest_max=job.config.rest_max,
        )

        if job.progress_callback:
            job.progress_callback(0, ctx.total)

        # 待处理的弹幕下标，其后的尚未发包
        pending_from = 0

        try:
            for i, dm in enumerate(job.danmakus):
                # --- 检查中止指令 ---
                if job.stop_event.is_set():
                    ctx.add_unsent(job.danmakus[i:], "任务手动停止")
                    break

                if job.progress_callback:
                    job.progress_callback(i + 1, ctx.total)

                # --- 查重断点续传 ---
                if self._should_skip(dm, ctx, job.policy):
                    ctx.skipped_count += 1
                    pending_from = i + 1
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

                if job.result_callback:
                    job.result_callback(dm, result)

                if result.status is SendStatus.FAILED and result.is_fatal:
                    ctx.fatal_error_occurred = True
                    ctx.fatal_error_msg = result.response.hint
                    ctx.add_unsent(job.danmakus[i + 1:], f"致命错误: {result.response.hint}")
                    break

                # --- 检查用户设置的自动终止阀值 ---
                if self._check_auto_stop(ctx, job.stop_event, job.policy):
                    reason = ctx.auto_stop_reason if ctx.auto_stop_reason else "达到自动停止条件"
                    if i + 1 < ctx.total:
                        ctx.add_unsent(job.danmakus[i+1:], f"自动停止: {reason}")
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
            self.logger.error(f"发送循环异常中止: {e}", exc_info=True)
