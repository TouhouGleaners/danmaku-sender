import logging
import time
from threading import Event

from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.types.exceptions.exceptions import HistoryStorageError
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.result import (
    BiliSendResponse,
    DanmakuSendResult,
    SendStatus,
)

from .context import SendingContext, SendJob
from .executor import DanmakuExecutor
from .planner import PlanAction, SendPlan


class DanmakuScheduler:
    """发送控制循环。

    照发送计划逐条推进：发包、入账、按计划等待，并把每条的发送与入账结果记入 SendingContext。
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

    def _send_with_retry(self, target: VideoTarget, dm: Danmaku, stop_event: Event) -> BiliSendResponse | None:
        """按发包结论驱动重试循环；等待与中止处理都在本方法内。

        Args:
            target (VideoTarget): 发送目标。
            dm (Danmaku): 待发弹幕。
            stop_event (Event): 中止信号。

        Returns:
            BiliSendResponse | None: 最终响应；等待被用户中止时为 None，本条尚未发出。
        """
        attempt_no = 0
        while True:
            attempt = self.executor.send(target, dm, attempt_no)
            if attempt.response is not None:
                return attempt.response
            self.logger.info(f"重试前等待 {attempt.retry_delay:.1f} 秒...")
            if stop_event.wait(timeout=attempt.retry_delay):
                self.logger.info("重试等待期间接收到停止指令，本条不再发。")
                return None
            attempt_no += 1

    def _send_single(
        self,
        target: VideoTarget,
        dm: Danmaku,
        task_id: str,
        stop_event: Event,
    ) -> DanmakuSendResult | None:
        """单条弹幕的原子操作：网络发包 → 尝试入账 → 产出业务结论。

        Args:
            target (VideoTarget): 发送目标。
            dm (Danmaku): 待发弹幕。
            task_id (str): 归属任务。
            stop_event (Event): 中止信号。

        Returns:
            DanmakuSendResult | None: 确凿的业务结论；发包被用户中止时为 None，本条未发出。
        """
        response = self._send_with_retry(target, dm, stop_event)
        if response is None:
            return None

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

    def run_pipeline(self, job: SendJob, ctx: SendingContext) -> None:
        """执行发送控制循环，结果填入 ctx。

        Args:
            job (SendJob): 发送任务工单。
            ctx (SendingContext): 由调用方持有并传入，异常时结果仍在其中。
        """
        self.logger.info(f"🚀 启动调度流水线... 目标: {job.target.bvid or "未指定"} (CID: {job.target.cid})")

        if not job.danmakus:
            return

        # 待处理的弹幕下标，其后的尚未发出
        pending_from = min(max(0, job.start_index), ctx.total)

        try:
            allow_duplicates = job.queue_config.allow_duplicates
            # 查重关闭、或清单已处理完时，计划不做跳过判定，也就无需查询账本
            db_counts = (
                {}
                if allow_duplicates or pending_from >= ctx.total
                else self.history_manager.count_records_grouped(job.target)
            )
            plan = SendPlan(job.danmakus, pending_from, job.config, allow_duplicates, db_counts)
            if pending_from:
                self.logger.info(f"📌 断点续传：从第 {pending_from + 1} 条继续（前 {pending_from} 条已处理）")

            if job.progress_callback:
                job.progress_callback(pending_from, ctx.total, plan.remaining_eta(pending_from))

            for step in plan.steps:
                # --- 检查中止指令 ---
                if job.stop_event.is_set():
                    ctx.add_unsent(job.danmakus[step.index:], "任务手动停止")
                    break

                if step.action is PlanAction.SKIP_DUPLICATE:
                    ctx.skipped_count += 1
                    self.logger.info(f"⏭️ [跳过] 已发送: {step.danmaku.msg}")
                    pending_from = step.index + 1
                    if job.progress_callback:
                        job.progress_callback(pending_from, ctx.total, plan.remaining_eta(step.index))
                    continue

                ctx.attempted_count += 1
                self.logger.info(f"[{step.index + 1}/{ctx.total}] 准备执行: {step.danmaku.msg}")

                # --- 发送 + 入账：单条的原子操作 ---
                result = self._send_single(job.target, step.danmaku, job.task_id, job.stop_event)
                if result is None:
                    # 发包被用户中止：本条尚未发出，与循环顶撞见停止同样收尾
                    ctx.add_unsent(job.danmakus[step.index:], "任务手动停止")
                    break

                # 先记账再回调
                match result.status:
                    case SendStatus.SUCCESS:
                        ctx.success_count += 1

                    case SendStatus.DEGRADED:
                        ctx.success_count += 1
                        ctx.evidence_failures.append((step.danmaku, result.storage_error or "未知存证错误"))

                    case SendStatus.FAILED:
                        ctx.add_unsent(step.danmaku, result.response.hint)

                pending_from = step.index + 1
                # 进度在单条发送完毕后推进：游标只盖已处理条目，中断的一条续传会重试；
                # 致命失败即将中止，剩余时间不再有意义
                if job.progress_callback:
                    eta = 0.0 if result.is_fatal else plan.remaining_eta(step.index)
                    job.progress_callback(pending_from, ctx.total, eta)

                if job.result_callback:
                    job.result_callback(step.danmaku, result)

                if result.status is SendStatus.FAILED and result.is_fatal:
                    ctx.fatal_error_occurred = True
                    ctx.fatal_error_msg = result.response.hint
                    ctx.add_unsent(job.danmakus[step.index + 1:], f"致命错误: {result.response.hint}")
                    break

                # --- 按计划等待控制节奏 ---
                if step.delay > 0:
                    if step.is_burst_rest:
                        self.logger.info(f"⚡ 爆发后休息 {step.delay:.2f} 秒...")
                    else:
                        self.logger.info(f"等待 {step.delay:.2f} 秒...")
                    if job.stop_event.wait(timeout=step.delay):
                        ctx.add_unsent(job.danmakus[step.index + 1:], "任务手动停止")
                        break

        except Exception as e:
            ctx.fatal_error_occurred = True
            ctx.fatal_error_msg = str(e)
            ctx.add_unsent(job.danmakus[pending_from:], f"异常中断: {e}")
            self.logger.exception("发送循环异常中止")

        # 中止收尾：队列已停，剩余时间归零，不让界面挂着过时的预计
        if job.stop_event.is_set() and job.progress_callback:
            job.progress_callback(pending_from, ctx.total, 0.0)
