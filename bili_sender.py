import time
import random
import logging
from threading import Event

from bili_api_client import BiliApiClient, BiliApiException
from bili_danmaku_utils import BiliDmErrorCode, DanmakuSendResult, DanmakuParser
from notification_utils import send_windows_notification


class BiliDanmakuSender:
    """B站弹幕发送器"""
    def __init__(self, api_client: BiliApiClient):
        self.logger = logging.getLogger("DanmakuSender")
        self.api_client = api_client
        self.danmaku_parser = DanmakuParser()
        self.unsent_danmakus = []

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

    def _send_single_danmaku(self, cid: int, bvid: str, danmaku: dict) -> DanmakuSendResult:
        """发送单条弹幕"""
        try:
            result_json = self.api_client.post_danmaku(cid, bvid, danmaku)
            
            code = result_json.get('code', BiliDmErrorCode.GENERIC_FAILURE.code)
            raw_message = result_json.get('message', '无B站原始消息')
            _, display_msg = BiliDmErrorCode.resolve_bili_error(code, raw_message)

            if code == BiliDmErrorCode.SUCCESS.code:
                self.logger.info(f"✅ 成功发送: '{danmaku['msg']}'")
                return DanmakuSendResult(code=code, success=True, message=raw_message, display_message=BiliDmErrorCode.SUCCESS.description_str)
            else:
                if code == BiliDmErrorCode.FREQ_LIMIT.code:
                    self.logger.warning(f"检测到弹幕发送过于频繁 (Code: {code}: {display_msg})，将额外等待10秒...")
                    time.sleep(10)
                self.logger.warning(f"发送失败 (API响应)! 内容: '{danmaku['msg']}', Code: {code}, 消息: {display_msg} (原始: {raw_message})")
                return DanmakuSendResult(code=code, success=False, message=raw_message, display_message=display_msg)
        except BiliApiException as e:
            error_code_enum = BiliDmErrorCode.from_api_exception(e)
            
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
        if not result.success:
            error_enum = BiliDmErrorCode.from_code(result.code)
            if error_enum is None:
                error_enum = BiliDmErrorCode.UNKNOWN_ERROR
                self.logger.warning(f"⚠️ 遇到未识别错误码 (Code: {result.code})，将其视为未知致命错误。消息: '{result.display_message}'")
            
            if error_enum.is_fatal_error:
                self.logger.critical(f"❌ 遭遇致命错误 (Code: {result.code}: {result.display_message})，任务将中断。")
                return False, True  # 失败，是致命错误
            return False, False  # 失败，但不是致命错误
        return True, False  # 成功发送
    
    def send_danmaku_from_list(self, bvid: str, cid: int, danmakus: list, min_delay: float, max_delay: float, stop_event: Event, progress_callback=None):
        """从一个弹幕字典列表发送弹幕，并响应停止事件"""
        self.logger.info(f"开始从内存列表发送弹幕到 CID: {cid}")
        self.unsent_danmakus = []  # 开始新任务时清空列表
        if not danmakus:
            self._log_send_summary(0, 0, 0, stop_event, False)
            if progress_callback:
                progress_callback(0, 0)
            return
        
        total = len(danmakus)
        success_count = 0
        attempted_count = 0
        fatal_error_occurred = False

        if progress_callback:
            progress_callback(0, total)

        for i, dm in enumerate(danmakus):
            if stop_event.is_set():
                self.logger.info("任务被用户手动停止。")
                self.unsent_danmakus.extend(danmakus[i:])  # 记录剩余未发送的弹幕
                break
            attempted_count += 1

            self.logger.info(f"[{i+1}/{total}] 准备发送: {dm.get('msg', 'N/A')}")
            result = self._send_single_danmaku(cid, bvid, dm)
            self.logger.info(str(result))

            if progress_callback:
                progress_callback(attempted_count, total)

            sent_successfully, is_fatal = self._process_send_result(result)
            if is_fatal:
                fatal_error_occurred = True
                self.unsent_danmakus.append(dm)
                self.unsent_danmakus.extend(danmakus[i+1:])
                break

            if not sent_successfully:
                self.unsent_danmakus.append(dm)
            else:
                success_count += 1
            
            if stop_event.is_set():
                self.logger.info("任务被用户手动停止。")
                self.unsent_danmakus.extend(danmakus[i+1:])
                break

            if i < total - 1 and self._handle_delay_and_stop(min_delay, max_delay, stop_event):
                self.unsent_danmakus.extend(danmakus[i+1:])
                break
        self._log_send_summary(total, attempted_count, success_count, stop_event, fatal_error_occurred)

    def _handle_delay_and_stop(self, min_delay: float, max_delay: float, stop_event: Event) -> bool:
        """
        处理发送间隔等待和停止事件。
        返回是否需要中断任务（True表示需要中断，False表示继续）。
        """
        if stop_event.is_set():
            self.logger.info("任务被用户手动停止。")
            return True  # 需要中断任务

        delay = random.uniform(min_delay, max_delay)
        self.logger.info(f"等待 {delay:.2f} 秒...")
        if stop_event.wait(timeout=delay):
            self.logger.info("在等待期间接收到停止信号，立即终止。")
            return True  # 需要中断任务
        return False  # 不需要中断，继续任务

    def _log_send_summary(self, total: int, attempted_count: int, success_count: int, stop_event: Event, fatal_error_occurred: bool):
        """记录弹幕发送任务的总结信息。"""
        self.logger.info("--- 发送任务结束 ---")
        if stop_event.is_set():
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

        notification_title = "弹幕发送任务已结束"
        summary_message = (f"成功: {success_count} / 尝试: {attempted_count} / 总计: {total}")

        if stop_event.is_set():
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