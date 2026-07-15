"""
发送管线编排器 (Send Pipeline)

封装单次发送任务的完整生命周期：资源组装、调度执行、结果记录、摘要日志。
Controller 层的 Worker 只需调用 pipeline.execute()，无需接触 Executor/Scheduler 细节。
"""

import logging
from dataclasses import replace
from typing import Callable

from .scheduler import DanmakuScheduler
from .executor import DanmakuExecutor
from .context import SendingContext, SendJob
from .delay_manager import DelayManager

from danmaku_sender.repo.bili_api_client import BiliApiClient
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.result import DanmakuSendResult
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.config import ApiAuthConfig, SenderConfig


logger = logging.getLogger("App.Sender.Pipeline")


class SendPipeline:
    """
    发送管线编排器

    职责：
    - 组装 BiliApiClient / Executor / Scheduler
    - 将成功结果记录到 HistoryManager
    - 计算 ETA 并回调进度
    - 输出任务摘要日志
    """

    def __init__(self, auth_config: ApiAuthConfig, strategy_config: SenderConfig):
        self.auth_config = auth_config
        self.strategy_config = strategy_config
        self.history_manager = HistoryManager()

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

            def on_result(dm: Danmaku, result: DanmakuSendResult):
                self._record_result(job.target, dm, result)
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
        ctx.is_manually_stopped = job.stop_event.is_set()
        self._log_summary(ctx)
        return ctx

    def _record_result(self, target: VideoTarget, dm: Danmaku, result: DanmakuSendResult):
        """将成功发送的弹幕记录到历史数据库"""
        if result.is_success and result.dmid:
            if not dm.dmid:
                dm.dmid = result.dmid
            self.history_manager.record_danmaku(target, dm, result.is_visible)

    def _calc_eta(self, attempted: int, total: int, config: SenderConfig) -> float:
        """基于任务配置计算 ETA（秒）"""
        cfg = config
        avg_normal = (cfg.min_delay + cfg.max_delay) / 2
        avg_rest = (cfg.rest_min + cfg.rest_max) / 2
        return DelayManager.calc_eta(
            attempted=attempted,
            total=total,
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
