"""
发送管线编排器 (Send Pipeline)

封装单次发送任务的完整生命周期：资源组装、调度执行、结果记录、摘要日志。
Controller 层的 Worker 只需调用 pipeline.execute()，无需接触 Executor/Scheduler 细节。
"""

import logging
import time
from collections.abc import Callable
from dataclasses import replace

from danmaku_sender.config import ApiAuthConfig
from danmaku_sender.repo.bili_api_client import BiliApiClient
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.types.exceptions.exceptions import HistoryStorageError
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.queue import TaskConfig
from danmaku_sender.types.models.result import (
    BiliSendResponse,
    DanmakuSendResult,
    SendStatus,
)

from .context import SendingContext, SendJob
from .delay_manager import DelayManager
from .executor import DanmakuExecutor
from .scheduler import DanmakuScheduler

logger = logging.getLogger(__name__)


class SendPipeline:
    """
    发送管线编排器

    职责：
    - 组装 BiliApiClient / Executor / Scheduler
    - 将成功结果记录到 HistoryManager
    - 计算 ETA 并回调进度
    - 输出任务摘要日志
    """

    def __init__(
        self,
        auth_config: ApiAuthConfig,
        history_manager: HistoryManager,
    ):
        self.auth_config = auth_config
        self.history_manager = history_manager

    def execute(
        self,
        job: SendJob,
        progress_emitter: Callable[[int, int, float], None] | None = None,
    ) -> SendingContext:
        """
        执行完整的发送管线。

        Args:
            job: 发送任务工单（含目标、弹幕、配置、回调）
            progress_emitter: 进度信号发射器 (attempted, total, eta_sec)，由 Worker 桥接

        Returns:
            SendingContext: 包含统计数据的发送上下文
        """
        with BiliApiClient.from_config(self.auth_config) as client:
            executor = DanmakuExecutor(client)
            scheduler = DanmakuScheduler(executor, self.history_manager)

            # 包装回调链，不修改原始 job 对象
            outer_result_callback = job.result_callback
            outer_progress_callback = job.progress_callback
            degraded: list[tuple[Danmaku, str]] = []

            def on_result(dm: Danmaku, response: BiliSendResponse):
                result = self._account(job.task_id, job.target, dm, response)
                if result.status is SendStatus.DEGRADED:
                    degraded.append((dm, result.storage_error or ""))
                if outer_result_callback:
                    outer_result_callback(dm, result)

            def on_progress(attempted: int, total: int):
                eta_sec = self._calc_eta(attempted, total, job.config)
                if progress_emitter:
                    progress_emitter(attempted, total, eta_sec)
                if outer_progress_callback:
                    outer_progress_callback(attempted, total)

            wrapped_job = replace(
                job,
                progress_callback=on_progress,
                result_callback=on_result,
            )

            ctx = scheduler.run_pipeline(wrapped_job)

        # 补充生命周期状态
        ctx.evidence_failures = degraded
        ctx.is_manually_stopped = job.stop_event.is_set()
        self._log_summary(ctx)
        return ctx

    def _account(
        self,
        task_id: str,
        target: VideoTarget,
        dm: Danmaku,
        response: BiliSendResponse,
    ) -> DanmakuSendResult:
        """把远端响应落成业务结论，含本地存证。

        Args:
            task_id (str): 归属任务。
            target (VideoTarget): 发送目标。
            dm (Danmaku): 发送的弹幕。
            response (BiliSendResponse): 远端响应。

        Returns:
            DanmakuSendResult: 业务处理结果。
        """
        if not response.is_success:
            return DanmakuSendResult(status=SendStatus.FAILED, response=response)

        if not response.dmid:
            logger.warning(f"远端成功但无 dmid，无法存证: {dm.msg}")
            return DanmakuSendResult(
                status=SendStatus.DEGRADED,
                response=response,
                storage_error="远端未返回 dmid",
            )

        max_retries = 3
        last_error = ""
        for attempt in range(max_retries):
            try:
                self.history_manager.record_danmaku(task_id, target, dm, response.dmid, response.is_visible)
                return DanmakuSendResult(status=SendStatus.SUCCESS, response=response)
            except HistoryStorageError as e:
                last_error = str(e)
                if attempt < max_retries - 1:
                    time.sleep(0.05 * (attempt + 1))

        logger.error(f"⚠️ [存证降级] 已发出但记账失败: {dm.msg} (dmid={response.dmid}) - {last_error}")
        return DanmakuSendResult(
            status=SendStatus.DEGRADED,
            response=response,
            storage_error=last_error,
        )

    def _calc_eta(self, attempted: int, total: int, config: TaskConfig) -> float:
        """基于任务配置计算 ETA（秒）"""
        cfg = config
        avg_normal = (cfg.min_delay + cfg.max_delay) / 2
        avg_rest = (cfg.rest_min + cfg.rest_max) / 2
        return DelayManager.calc_eta(
            attempted=attempted,
            total=total,
            burst_enabled=cfg.burst_enabled,
            burst_size=cfg.burst_size,
            avg_normal=avg_normal,
            avg_rest=avg_rest,
        )

    @staticmethod
    def _log_summary(ctx: SendingContext):
        """输出任务结束摘要"""
        logger.info("--- 发送任务结束 ---")
        if ctx.auto_stop_reason:
            logger.info(f"原因：{ctx.auto_stop_reason}")
        elif ctx.is_manually_stopped:
            logger.info("原因：任务被用户手动停止。")
        elif ctx.fatal_error_occurred:
            logger.critical("原因：任务因致命错误中断。请检查配置或网络！")
        else:
            logger.info("原因：所有弹幕已处理完毕。")

        failed = ctx.attempted_count - ctx.success_count
        logger.info(
            f"总计: {ctx.total} | 成功: {ctx.success_count} | "
            f"跳过: {ctx.skipped_count} | 失败: {failed}"
        )
