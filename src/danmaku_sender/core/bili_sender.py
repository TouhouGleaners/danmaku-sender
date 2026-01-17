import time
import logging
from threading import Event

from .state import SenderConfig
from .bili_danmaku_utils import DanmakuParser, UnsentDanmakusRecord
from .delay_manager import DelayManager
from .error_handler import normalize_exception
from .exceptions import BiliApiException
from .models.danmaku import Danmaku
from .models.errors import BiliDmErrorCode
from .models.result import DanmakuSendResult
from .models.structs import VideoTarget

from ..api.bili_api_client import BiliApiClient
from ..utils.notification_utils import send_windows_notification


class BiliDanmakuSender:
    """B站弹幕发送器"""
    def __init__(self, api_client: BiliApiClient):
        self.logger = logging.getLogger("DanmakuSender")
        self.api_client = api_client
        self.danmaku_parser = DanmakuParser()
        self.unsent_danmakus: list[UnsentDanmakusRecord] = []

    def get_video_info(self, bvid: str) -> dict:
        """根据BVID获取视频详细信息"""
        try:
            video_data = self.api_client.get_video_info(bvid)
            
            pages_info = [
                {'cid': p['cid'], 'page': p['page'], 'part': p['part'], 'duration': p.get('duration', 0)}
                for p in video_data.get('pages', [])
            ]
            info = {
                'title': video_data.get('title', '未知标题'),
                'duration': video_data.get('duration', 0),
                'pages': pages_info
            }
            self.logger.info(f"成功获取到视频《{info['title']}》的信息，共 {len(info['pages'])} 个分P")
            return info
        except BiliApiException as e:
            # 将底层的API异常，转换为对用户更友好的运行时错误
            log_msg = f"获取视频信息失败, Code: {e.code}, 信息: {e.message}"
            self.logger.error(log_msg)
            raise RuntimeError(log_msg) from e

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
                
    def _process_send_result(self, result: DanmakuSendResult) -> tuple[bool, bool]:
        """
        处理单条弹幕的发送结果，判断是否成功以及是否遇到致命错误。
        返回 (是否成功发送, 是否遇到致命错误)
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
    
    def _record_unsent_danmakus(self, danmakus: Danmaku | list[Danmaku], reason: str) -> None:
        """记录未发送成功的弹幕及其原因"""
        if isinstance(danmakus, Danmaku):
            self.unsent_danmakus.append({'dm': danmakus, 'reason': reason})
        else:
            for dm in danmakus:
                self.unsent_danmakus.append({'dm': dm, 'reason': reason})
    
    def send_danmaku_from_list(
        self,
        target: VideoTarget,
        danmakus: list[Danmaku],
        config: 'SenderConfig',
        stop_event: Event,
        progress_callback=None,
        result_callback=None
    ):
        """
        从一个弹幕字典列表发送弹幕，并响应停止事件
        
        Args:
            result_callback: Callable[[Danmaku, DanmakuSendResult], None] 发送结果回调
        """
        self.logger.info(f"开始发送... 目标: {target.display_string} (CID: {target.cid})")
        self.unsent_danmakus = []  # 开始新任务时清空列表

        auto_stop_reason = ""
        start_time = time.time()

        if not danmakus:
            self._log_send_summary(0, 0, 0, stop_event, False)
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
        
        total = len(danmakus)
        success_count = 0
        attempted_count = 0
        fatal_error_occurred = False

        if progress_callback:
            progress_callback(0, total)

        for i, dm in enumerate(danmakus):
            if stop_event.is_set():
                self._record_unsent_danmakus(danmakus[i:], "任务手动停止")
                break

            attempted_count += 1

            self.logger.info(f"[{i+1}/{total}] 准备发送: {dm.msg}")
            result = self._send_single_danmaku(target, dm)

            if progress_callback:
                progress_callback(attempted_count, total)

            if result_callback:
                try:
                    result_callback(dm, result)
                except Exception as e:
                    self.logger.error(f"结果回调执行异常 (不影响发送任务): {e}", exc_info=True)

            sent_successfully, is_fatal = self._process_send_result(result)
            if is_fatal:
                fatal_error_occurred = True
                fatal_err = f"致命错误: {result.display_message}"
                self._record_unsent_danmakus(dm, fatal_err)
                self._record_unsent_danmakus(danmakus[i+1:], "由于前序致命错误停止任务")
                break

            if not sent_successfully:
                self._record_unsent_danmakus(dm, result.display_message)
            else:
                success_count += 1

            if config.stop_after_count > 0 and success_count >= config.stop_after_count:
                auto_stop_reason = f"达到数量限制 ({config.stop_after_count}条)"
                self.logger.info(f"🛑 {auto_stop_reason}，自动停止任务。")
                # 记录剩余未发送的 (从下一条开始)
                if i + 1 < total:
                    self._record_unsent_danmakus(danmakus[i+1:], "达到自动停止条件")
                stop_event.set()
                break

            elapsed_minutes = (time.time() - start_time) / 60
            if config.stop_after_time > 0 and elapsed_minutes >= config.stop_after_time:
                auto_stop_reason = f"达到时间限制 ({config.stop_after_time}分钟)"
                self.logger.info(f"🛑 {auto_stop_reason}，自动停止任务。")
                if i + 1 < total:
                    self._record_unsent_danmakus(danmakus[i+1:], "达到自动停止条件")
                stop_event.set()
                break
            
            if i < total - 1 and delay_manager.wait_and_check_stop(stop_event):
                # 如果在休息时被停止，记录后续弹幕
                self._record_unsent_danmakus(danmakus[i+1:], "任务手动停止")
                break

        self._log_send_summary(total, attempted_count, success_count, stop_event, fatal_error_occurred, auto_stop_reason)

    def _log_send_summary(self, total: int, attempted_count: int, success_count: int, stop_event: Event, fatal_error_occurred: bool, auto_stop_reason: str = ""):
        """记录弹幕发送任务的总结信息。"""
        self.logger.info("--- 发送任务结束 ---")
        if auto_stop_reason:
            self.logger.info(f"原因：{auto_stop_reason}")
        elif stop_event.is_set():
            self.logger.info("原因：任务被用户手动停止。")
        elif fatal_error_occurred:
            self.logger.critical("原因：任务因致命错误中断。请检查配置或网络！")
        elif total == 0:
            self.logger.info("原因：没有弹幕可发送。")
        else:
            self.logger.info("原因：所有弹幕已发送完毕。")
        self.logger.info(f"弹幕总数: {total} 条")
        self.logger.info(f"尝试发送: {attempted_count} 条")
        self.logger.info(f"发送成功: {success_count} 条")
        self.logger.info(f"发送失败: {attempted_count - success_count} 条")

        if self.unsent_danmakus:
            self.logger.info("--- 失败原因汇总 ---")
            reason_counts: dict[str, int] = {}
            for item in self.unsent_danmakus:
                r = item['reason']
                reason_counts[r] = reason_counts.get(r, 0) + 1
            
            sorted_reasons = sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)
            
            for reason, count in sorted_reasons:
                self.logger.warning(f"  > {reason}: {count} 条")
            self.logger.info("--------------------")

        # 发送Windows通知
        notification_title = "弹幕发送任务已结束"
        summary_message = (f"成功: {success_count} / 尝试: {attempted_count} / 总计: {total}")

        if auto_stop_reason:
            notification_message = f"任务自动停止：{auto_stop_reason}\n{summary_message}"
        elif stop_event.is_set():
            notification_message = f"任务已被手动停止。\n{summary_message}"
        elif fatal_error_occurred:
            notification_message = f"任务因致命错误而中断！\n{summary_message}"
        elif total == 0:
            notification_message = "没有需要发送的弹幕。"
        elif success_count == attempted_count:
            notification_message = f"任务已完成！\n所有 {success_count} 条弹幕均已成功发送。"
        else:
            notification_message = f"任务已完成。\n{summary_message}"
            
        send_windows_notification(notification_title, notification_message)