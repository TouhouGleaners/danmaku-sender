import logging
from threading import Event

from .executor import DanmakuExecutor
from .context import SendingContext, DanmakuFingerprint, SendJob
from .delay_manager import DelayManager

from ...database.history_manager import HistoryManager
from ...models.danmaku import Danmaku
from ...models.errors import BiliDmErrorCode


class DanmakuScheduler:
    """
    弹幕发送调度器 (Scheduler)

    不亲自发包（委托 Executor），也不亲自存库（通过 Callback 委派）。
    职责：遍历队列、断点续传（去重）、容错处理、时间控制与任务阻断。
    """
    def __init__(self, executor: DanmakuExecutor, history_manager: HistoryManager | None = None):
        self.logger = logging.getLogger("DanmakuScheduler")
        self.executor = executor
        self.history_manager = history_manager
        self.unsent_danmakus = []

    @staticmethod
    def _get_fingerprint(dm: Danmaku) -> DanmakuFingerprint:
        """生成物理指纹，用于识别内容、位置、样式完全一样的重复弹幕"""
        return (dm.msg, dm.progress, dm.mode, dm.fontsize, dm.color)

    def _should_skip(self, dm: Danmaku, ctx: SendingContext) -> bool:
        """
        断点续传：智能去重逻辑

        对每个指纹计数，若当前发送序列中该指纹的出现次数 <= 数据库中已成功发送的次数，则跳过。
        """
        if not ctx.config.skip_sent or not self.history_manager:
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

    def _check_auto_stop(self, ctx: SendingContext, stop_event: Event) -> bool:
        """检查是否满足用户配置的自动终止条件（发满 N 条或运行满 M 分钟）"""
        if ctx.config.stop_after_count > 0 and ctx.success_count >= ctx.config.stop_after_count:
            ctx.auto_stop_reason = f"达到数量限制 ({ctx.config.stop_after_count}条)"
            stop_event.set()
            return True

        if ctx.config.stop_after_time > 0 and ctx.elapsed_minutes >= ctx.config.stop_after_time:
            ctx.auto_stop_reason = f"达到时间限制 ({ctx.config.stop_after_time}分钟)"
            stop_event.set()
            return True

        return False

    def run_pipeline(self, job: SendJob) -> SendingContext:
        """
        流水线主入口
        
        执行逻辑：
        检查取消信号 -> 回调进度 -> 查重拦截 -> 委派发送 -> 错误/风控判定 -> 回调数据 -> 延时控制
        """
        self.logger.info(f"🚀 启动调度流水线... 目标: {job.target.display_string} (CID: {job.target.cid})")
        
        # 初始化统计容器
        ctx = SendingContext(total=len(job.danmakus), config=job.config, target=job.target)
        self.unsent_danmakus = []

        if not job.danmakus:
            return ctx

        # 初始化时钟管理器
        delay_manager = DelayManager(
            normal_min=job.config.min_delay, normal_max=job.config.max_delay,
            burst_size=job.config.burst_size, rest_min=job.config.rest_min, rest_max=job.config.rest_max
        )

        if job.progress_callback:
            job.progress_callback(0, ctx.total)

        for i, dm in enumerate(job.danmakus):
            # --- 检查中止指令 ---
            if job.stop_event.is_set():
                ctx.add_unsent(job.danmakus[i:], "任务手动停止")
                break

            if job.progress_callback:
                job.progress_callback(i + 1, ctx.total)

            # --- 查重断点续传 ---
            if self._should_skip(dm, ctx):
                ctx.skipped_count += 1
                continue

            ctx.attempted_count += 1
            self.logger.info(f"[{i+1}/{ctx.total}] 准备执行: {dm.msg}")

            # --- 委派 Executor 发送 ---
            result = self.executor.execute(job.target, dm)

            # --- 回调注入层 ---
            if job.result_callback:
                job.result_callback(dm, result)

            # --- 结果 ---
            if not result.is_success:
                ctx.add_unsent(dm, result.hint)

                # A: 遭遇致命封禁，直接摧毁流水线
                if result.is_fatal:
                    ctx.fatal_error_occurred = True
                    ctx.add_unsent(job.danmakus[i+1:], f"致命错误: {result.hint}")
                    break

                # B: 遭遇风控限流，下发惩罚性延时
                if result.code == BiliDmErrorCode.FREQ_LIMIT.code:
                    self.logger.warning("⚠️ 触发频率限制！强制附加 10 秒惩罚延时...")
                    if job.stop_event.wait(10.0):
                        ctx.add_unsent(job.danmakus[i+1:], "任务在惩罚延时中被手动停止")
                        break
            else:
                ctx.success_count += 1

            # --- 检查用户设置的自动终止阀值 ---
            if self._check_auto_stop(ctx, job.stop_event):
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

        self.unsent_danmakus = ctx.unsent_records
        return ctx