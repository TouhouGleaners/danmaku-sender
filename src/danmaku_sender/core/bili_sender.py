import time
import logging
from threading import Event
from dataclasses import dataclass, field
from typing import Callable
from enum import Enum, auto

from .delay_manager import DelayManager
from .error_handler import normalize_exception
from .exceptions import BiliApiException
from .history_manager import HistoryManager
from .models.danmaku import Danmaku
from .models.errors import BiliDmErrorCode
from .models.result import DanmakuSendResult
from .models.structs import VideoTarget
from .services.danmaku_exporter import UnsentDanmakusRecord
from .services.danmaku_parser import DanmakuParser
from .state import SenderConfig

from ..api.bili_api_client import BiliApiClient
from ..utils.notification_utils import send_windows_notification


DanmakuFingerprint = tuple[str, int, int, int, int]


class SendFlowAction(Enum):
    """发送流程控制动作"""
    CONTINUE = auto()     # 继续发送
    STOP_FATAL = auto()   # 遇到致命错误，立即停止


@dataclass
class SendingContext:
    """封装一次发送任务的运行时状态"""
    total: int
    config: SenderConfig
    target: VideoTarget

    # 计数器
    attempted_count: int = 0
    success_count: int = 0
    skipped_count: int = 0

    # 状态标记
    start_time: float = field(default_factory=time.time)
    auto_stop_reason: str = ""
    fatal_error_occurred: bool = False
    
    # 失败记录容器
    unsent_records: list[UnsentDanmakusRecord] = field(default_factory=list)

    # 去重缓存
    # Key: 指纹 -> Value: 出现次数
    local_counter: dict[DanmakuFingerprint, int] = field(default_factory=dict)
    # Key: 指纹 -> Value: 数据库中记录的次数
    db_count_cache: dict[DanmakuFingerprint, int] = field(default_factory=dict)

    @property
    def elapsed_minutes(self) -> float:
        """任务已运行分钟数"""
        return (time.time() - self.start_time) / 60

    def add_unsent(self, danmakus: Danmaku | list[Danmaku], reason: str):
        """记录发送失败/未发送的弹幕"""
        if isinstance(danmakus, Danmaku):
            self.unsent_records.append({'dm': danmakus, 'reason': reason})
        else:
            for dm in danmakus:
                self.unsent_records.append({'dm': dm, 'reason': reason})


class BiliDanmakuSender:
    """B站弹幕发送器"""
    def __init__(self, api_client: BiliApiClient):
        self.logger = logging.getLogger("DanmakuSender")
        self.api_client = api_client
        self.danmaku_parser = DanmakuParser()
        self.unsent_danmakus: list[UnsentDanmakusRecord] = []
        
    @staticmethod
    def _get_fingerprint(dm: Danmaku) -> DanmakuFingerprint:
        """统一生成弹幕指纹，用于去重"""
        return (dm.msg, dm.progress, dm.mode, dm.fontsize, dm.color)

    def _send_single_danmaku(self, target: VideoTarget, danmaku: Danmaku) -> DanmakuSendResult:
        """发送单条弹幕"""
        try:
            params = danmaku.to_api_params()

            resp_json = self.api_client.post_danmaku(target.cid, target.bvid, params)
            
            result = DanmakuSendResult.from_api_response(resp_json)

            if result.is_success:
                if result.dmid:
                    danmaku.dmid = result.dmid
                self.logger.info(f"✅ 发送成功 [ID:{result.dmid}]: {danmaku.msg}")
            else:
                if result.code == BiliDmErrorCode.FREQ_LIMIT.code:
                    time.sleep(10)
                self.logger.warning(f"❌ 发送失败: {result.display_message}")
            
            return result

        except BiliApiException as e:
            error_code_enum = normalize_exception(e)
            
            log_message = f"❌ 发送异常! 内容: '{danmaku.get('msg', 'N/A')}', 错误: {e.message}"
            self.logger.error(log_message)
            return DanmakuSendResult(
                code=error_code_enum.code,
                success=False,
                message=str(e),
                display_message=error_code_enum.description_str
            )
        
    def _should_skip(self, dm: Danmaku, ctx: SendingContext, history_manager: HistoryManager | None) -> bool:
        """判断是否需要跳过当前弹幕"""
        if not ctx.config.skip_sent or not history_manager:
            return False

        # 构建指纹
        dm_fingerprint = self._get_fingerprint(dm)

        # 本地本次任务计数
        ctx.local_counter[dm_fingerprint] = ctx.local_counter.get(dm_fingerprint, 0) + 1
        current_occurrence = ctx.local_counter[dm_fingerprint]

        # 数据库历史计数 (带缓存)
        if dm_fingerprint in ctx.db_count_cache:
            db_count = ctx.db_count_cache[dm_fingerprint]
        else:
            db_count = history_manager.count_records(ctx.target, dm)
            ctx.db_count_cache[dm_fingerprint] = db_count

        if current_occurrence <= db_count:
            self.logger.info(f"⏭️ [跳过] 已发送 ({current_occurrence}/{db_count}): {dm.msg}")
            return True

        return False
                
    def _process_send_result(self, result: DanmakuSendResult) -> tuple[bool, bool]:
        """
        解析发送结果。

        Returns: 
            (is_success, is_fatal_error)
        """
        if not result.is_success:
            error_enum = BiliDmErrorCode.from_code(result.code)
            if error_enum is None:
                error_enum = BiliDmErrorCode.UNKNOWN_ERROR
                self.logger.warning(f"⚠️ 遇到未识别错误码 (Code: {result.code})，将其视为未知致命错误。消息: '{result.display_message}'")
            
            if error_enum.is_fatal_error:
                self.logger.critical(f"❌ 遭遇致命错误 (Code: {result.code}: {result.display_message})，任务将中断。")
                return False, True  # 失败，是致命错误
            return False, False  # 失败，但不是致命错误
        return True, False  # 成功发送
    
    def _handle_send_result(
        self,
        dm: Danmaku,
        result: DanmakuSendResult,
        ctx: SendingContext,
        result_callback: Callable[[Danmaku, DanmakuSendResult], None] | None
    ) -> SendFlowAction:
        """
        处理发送结果，更新上下文状态。

        Returns:
            SendFlowAction: 指示后续流程 (CONTINUE: 继续发送, STOP_FATAL: 因致命错误中断)。
        """
        # 执行回调
        if result_callback:
            try:
                result_callback(dm, result)
            except Exception as e:
                self.logger.error(f"结果回调执行异常: {e}", exc_info=True)

        # 分析结果
        sent_successfully, is_fatal = self._process_send_result(result)

        if is_fatal:
            ctx.fatal_error_occurred = True
            ctx.add_unsent(dm, f"致命错误: {result.display_message}")
            return SendFlowAction.STOP_FATAL

        if not sent_successfully:
            ctx.add_unsent(dm, result.display_message)
        else:
            ctx.success_count += 1
            
        return SendFlowAction.CONTINUE
    
    def _check_auto_stop(self, ctx: SendingContext, stop_event: Event) -> bool:
        """
        检查是否满足自动停止条件 (数量或时间)。

        Returns: True 表示触发了自动停止。
        """
        # 数量限制
        if ctx.config.stop_after_count > 0 and ctx.success_count >= ctx.config.stop_after_count:
            ctx.auto_stop_reason = f"达到数量限制 ({ctx.config.stop_after_count}条)"
            self.logger.info(f"🛑 {ctx.auto_stop_reason}，自动停止任务。")
            stop_event.set()
            return True

        # 时间限制
        if ctx.config.stop_after_time > 0 and ctx.elapsed_minutes >= ctx.config.stop_after_time:
            ctx.auto_stop_reason = f"达到时间限制 ({ctx.config.stop_after_time}分钟)"
            self.logger.info(f"🛑 {ctx.auto_stop_reason}，自动停止任务。")
            stop_event.set()
            return True

        return False

    def send_danmaku_from_list(
        self,
        target: VideoTarget,
        danmakus: list[Danmaku],
        config: SenderConfig,
        stop_event: Event,
        progress_callback=None,
        result_callback=None,
        history_manager: HistoryManager | None = None
    ):
        """
        从一个弹幕字典列表发送弹幕，并响应停止事件
        
        Args:
            result_callback: Callable[[Danmaku, DanmakuSendResult], None] 发送结果回调
            history_manager: 用于查重的数据库管理器
        """
        self.logger.info(f"开始发送... 目标: {target.display_string} (CID: {target.cid})")
        self.unsent_danmakus = []  # 开始新任务时清空列表

        # 初始化上下文
        ctx = SendingContext(total=len(danmakus), config=config, target=target)

        if not danmakus:
            self._log_send_summary(ctx, stop_event)
            if progress_callback:
                progress_callback(0, 0)
            return
        
        delay_manager = DelayManager(
            normal_min=config.min_delay,
            normal_max=config.max_delay,
            burst_size=config.burst_size,
            rest_min=config.rest_min,
            rest_max=config.rest_max
        )
        
        if progress_callback:
            progress_callback(0, ctx.total)

        for i, dm in enumerate(danmakus):
            # 检查手动停止
            if stop_event.is_set():
                ctx.add_unsent(danmakus[i:], "任务手动停止")
                break

            if progress_callback:
                progress_callback(i + 1, ctx.total)

            # 断点续传 - 智能去重
            if self._should_skip(dm, ctx, history_manager):
                ctx.skipped_count += 1
                continue

            # 发送动作
            ctx.attempted_count += 1
            self.logger.info(f"[{i+1}/{ctx.total}] 准备发送: {dm.msg}")
            
            result = self._send_single_danmaku(target, dm)

            # 处理结果 (更新状态/判断致命错误)
            action = self._handle_send_result(dm, result, ctx, result_callback)
            if action == SendFlowAction.STOP_FATAL:
                # 遇到致命错误，记录剩余所有弹幕并退出
                if i + 1 < ctx.total:
                    ctx.add_unsent(danmakus[i+1:], "由于前序致命错误停止任务")
                break

            # 检查自动停止 (数量/时间)
            if self._check_auto_stop(ctx, stop_event):
                if i + 1 < ctx.total:
                    reason = ctx.auto_stop_reason if ctx.auto_stop_reason else "达到自动停止条件"
                    ctx.add_unsent(danmakus[i+1:], f"自动停止: {reason}")
                break

            # 延时管理
            is_last_item = (i == ctx.total - 1)
            if not is_last_item and delay_manager.wait_and_check_stop(stop_event):
                # 如果在休息期间被停止
                if i + 1 < ctx.total:
                    ctx.add_unsent(danmakus[i+1:], "任务手动停止")
                break
        
        # 同步未发送列表回实例
        self.unsent_danmakus = ctx.unsent_records

        self._log_send_summary(ctx, stop_event)

    def _log_send_summary(self, ctx: SendingContext, stop_event: Event):
        """记录弹幕发送任务的总结信息"""
        self.logger.info("--- 发送任务结束 ---")

        # 判断结束原因
        if ctx.auto_stop_reason:
            self.logger.info(f"原因：{ctx.auto_stop_reason}")
        elif stop_event.is_set():
            self.logger.info("原因：任务被用户手动停止。")
        elif ctx.fatal_error_occurred:
            self.logger.critical("原因：任务因致命错误中断。请检查配置或网络！")
        elif ctx.total == 0:
            self.logger.info("原因：没有弹幕可发送。")
        else:
            self.logger.info("原因：所有弹幕已发送完毕。")
        
        self.logger.info(f"弹幕总数: {ctx.total} 条")
        self.logger.info(f"智能跳过: {ctx.skipped_count} 条")
        self.logger.info(f"尝试发送: {ctx.attempted_count} 条")
        self.logger.info(f"发送成功: {ctx.success_count} 条")
        self.logger.info(f"发送失败: {ctx.attempted_count - ctx.success_count} 条")

        # 记录失败详情
        if ctx.unsent_records:
            self.logger.info("--- 失败原因汇总 ---")
            reason_counts: dict[str, int] = {}
            for item in ctx.unsent_records:
                r = item['reason']
                reason_counts[r] = reason_counts.get(r, 0) + 1
            
            sorted_reasons = sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)
            for reason, count in sorted_reasons:
                self.logger.warning(f"  > {reason}: {count} 条")
            self.logger.info("--------------------")

        # 发送Windows通知
        notification_title = "弹幕发送任务已结束"
        summary_message = (f"成功: {ctx.success_count} / 尝试: {ctx.attempted_count} / 总计: {ctx.total}")

        if ctx.auto_stop_reason:
            notification_message = f"任务自动停止：{ctx.auto_stop_reason}\n{summary_message}"
        elif stop_event.is_set():
            notification_message = f"任务已被手动停止。\n{summary_message}"
        elif ctx.fatal_error_occurred:
            notification_message = f"任务因致命错误而中断！\n{summary_message}"
        elif ctx.total == 0:
            notification_message = "没有需要发送的弹幕。"
        elif ctx.success_count == ctx.attempted_count:
            notification_message = f"任务已完成！\n所有 {ctx.success_count} 条弹幕均已成功发送。"
        else:
            notification_message = f"任务已完成。\n{summary_message}"
            
        send_windows_notification(notification_title, notification_message)