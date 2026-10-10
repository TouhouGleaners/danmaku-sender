"""发送流水线：组装客户端与调度器，跑完一条发送任务并返回运行记录。"""

import logging
from collections.abc import Callable
from dataclasses import replace

from danmaku_sender.config import ApiAuthConfig
from danmaku_sender.repo.bili_api_client import BiliApiClient
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.types.models.queue import TaskConfig

from .context import SendingContext, SendJob
from .delay_manager import DelayManager
from .executor import DanmakuExecutor
from .scheduler import DanmakuScheduler

logger = logging.getLogger(__name__)


class SendPipeline:
    """发送流水线。

    组建 BiliApiClient、DanmakuExecutor 与 DanmakuScheduler，执行发送循环，
    汇总 SendingContext 并输出摘要日志。
    """

    def __init__(
        self,
        auth_config: ApiAuthConfig,
        history_manager: HistoryManager,
    ):
        """初始化流水线。

        Args:
            auth_config (ApiAuthConfig): B 站接口的鉴权配置。
            history_manager (HistoryManager): 本地账本，供存证与查重。
        """
        self.auth_config = auth_config
        self.history_manager = history_manager

    def execute(
        self,
        job: SendJob,
        progress_emitter: Callable[[int, int, float], None] | None = None,
    ) -> SendingContext:
        """执行一次完整的发送任务。

        Args:
            job (SendJob): 发送任务工单。
            progress_emitter (Callable[[int, int, float], None] | None): 进度发射器，
                收已发数、总数与 ETA 秒数。

        Returns:
            SendingContext: 运行记录。
        """
        # 先建 ctx，确保异常路径也能返回它
        ctx = SendingContext(total=len(job.danmakus), target=job.target)

        try:
            with BiliApiClient.from_config(self.auth_config) as client:
                executor = DanmakuExecutor(client)
                scheduler = DanmakuScheduler(executor, self.history_manager)

                outer_progress_callback = job.progress_callback

                def on_progress(attempted: int, total: int):
                    eta_sec = self._calc_eta(attempted, total, job.config)
                    if progress_emitter:
                        progress_emitter(attempted, total, eta_sec)
                    if outer_progress_callback:
                        outer_progress_callback(attempted, total)

                wrapped_job = replace(job, progress_callback=on_progress)

                scheduler.run_pipeline(wrapped_job, ctx)

        except Exception as e:
            logger.error(f"发送流水线异常中止: {e}", exc_info=True)
            ctx.fatal_error_occurred = True
            ctx.fatal_error_msg = str(e)
            # 调度器尚未处理任何弹幕时，整批按未发出登记
            if not (ctx.attempted_count or ctx.skipped_count or ctx.unsent_records):
                ctx.add_unsent(job.danmakus, f"异常中断: {e}")

        # 补充生命周期状态
        ctx.is_manually_stopped = job.stop_event.is_set()
        try:
            self._log_summary(ctx)
        except Exception:
            logger.error("发送摘要输出失败", exc_info=True)
        return ctx

    def _calc_eta(self, attempted: int, total: int, config: TaskConfig) -> float:
        """按任务节奏计算剩余 ETA（秒）。

        Args:
            attempted (int): 已尝试发包的数量。
            total (int): 弹幕总数。
            config (TaskConfig): 本任务的发送节奏。

        Returns:
            float: 剩余秒数。
        """
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
        """输出任务结束摘要。

        Args:
            ctx (SendingContext): 运行记录。
        """
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
