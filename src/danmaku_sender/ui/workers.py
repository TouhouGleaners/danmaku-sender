import logging
import threading

from PySide6.QtCore import Signal

from .framework.concurrency import BaseWorker

from ..core.engines.sender import DanmakuScheduler, DanmakuExecutor, SendingContext, SendJob
from ..core.engines.bili_monitor import BiliDanmakuMonitor
from ..core.database.history_manager import HistoryManager
from ..core.state import ApiAuthConfig, SenderConfig, MonitorConfig
from ..core.models.danmaku import Danmaku
from ..core.models.result import DanmakuSendResult
from ..core.models.structs import VideoTarget
from ..core.models.video import VideoInfo
from ..core.services.video_fetcher import VideoFetcher
from ..core.models.exceptions import BiliApiError, BiliNetworkError
from ..api.bili_api_client import BiliApiClient
from ..utils.system_utils import KeepSystemAwake
from ..utils.notification_utils import send_windows_notification


class FetchInfoWorker(BaseWorker):
    """用于后台获取视频信息的线程"""
    finished_success = Signal(VideoInfo)  # 成功信号，携带视频信息 VideoInfo
    finished_error = Signal(str)          # 失败信号，携带错误信息

    def __init__(self, bvid, auth_config: ApiAuthConfig, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger("App.System.Worker.Fetch")
        self.bvid = bvid
        self.auth_config = auth_config

    def run(self):
        try:
            with BiliApiClient.from_config(self.auth_config) as client:
                service = VideoFetcher(client)
                video_info = service.fetch_info(self.bvid)
                self.finished_success.emit(video_info)

        except (BiliApiError, BiliNetworkError) as e:
            self.report_error("获取视频信息失败", e)
            self.finished_error.emit(str(e))

        except Exception as e:
            self.logger.critical("非预期的系统崩溃", exc_info=True)
            self.finished_error.emit("程序内部发生未知错误，请检查日志。")


class SendTaskWorker(BaseWorker):
    """用于后台发送弹幕的线程"""
    progress_updated = Signal(int, int)  # 已尝试, 总数
    task_finished = Signal(object)       # 携带 sender 实例以便后续处理(如保存失败弹幕)

    def __init__(
        self,
        bvid,
        cid,
        danmakus,
        auth_config: ApiAuthConfig,
        strategy_config: SenderConfig,
        stop_event: threading.Event,
        video_title: str = "",
        parent=None
    ):
        super().__init__(parent)
        self.logger = logging.getLogger("App.Sender.Worker")
        self.target = VideoTarget(bvid=bvid, cid=cid, title=video_title)
        self.danmakus = danmakus
        self.auth_config = auth_config
        self.strategy_config = strategy_config
        self.stop_event = stop_event
        self.sender_instance = None
        self.history_manager = HistoryManager()

    def run(self):
        ctx: SendingContext | None = None
        try:
            with KeepSystemAwake(self.strategy_config.prevent_sleep):
                with BiliApiClient.from_config(self.auth_config) as client:
                    executor = DanmakuExecutor(client)
                    self.scheduler = DanmakuScheduler(executor, self.history_manager)

                    def _progress_cb(attempted, total):
                        self.progress_updated.emit(attempted, total)

                    def _save_to_db_cb(dm: Danmaku, result: DanmakuSendResult):
                        if result.is_success and result.dmid:
                            if not dm.dmid:
                                dm.dmid = result.dmid
                            self.history_manager.record_danmaku(self.target, dm, result.is_visible)

                    job = SendJob(
                        target=self.target,
                        danmakus=self.danmakus,
                        config=self.strategy_config,
                        stop_event=self.stop_event,
                        progress_callback=_progress_cb,
                        result_callback=_save_to_db_cb
                    )
                    ctx = self.scheduler.run_pipeline(job)

        except Exception as e:
            self.report_error("任务发生严重错误", e)
        finally:
            if ctx:
                self._log_and_notify_summary(ctx)
            self.task_finished.emit(self.scheduler)

    def _log_and_notify_summary(self, ctx: SendingContext):
        """记录日志并弹送系统通知（纯 UI 侧交互）"""
        self.logger.info("--- 发送任务结束 ---")
        if ctx.auto_stop_reason:
            self.logger.info(f"原因：{ctx.auto_stop_reason}")
        elif self.stop_event.is_set():
            self.logger.info("原因：任务被用户手动停止。")
        elif ctx.fatal_error_occurred:
            self.logger.critical("原因：任务因致命错误中断。请检查配置或网络！")
        else:
            self.logger.info("原因：所有弹幕已处理完毕。")

        self.logger.info(f"总计: {ctx.total} | 成功: {ctx.success_count} | 跳过: {ctx.skipped_count} | 失败: {ctx.attempted_count - ctx.success_count}")

        # 发送桌面通知
        notification_title = "弹幕发送任务已结束"
        summary_message = f"成功: {ctx.success_count} / 尝试: {ctx.attempted_count} / 总计: {ctx.total}"

        if ctx.auto_stop_reason:
            msg = f"自动停止：{ctx.auto_stop_reason}\n{summary_message}"
        elif self.stop_event.is_set():
            msg = f"任务已被手动停止。\n{summary_message}"
        elif ctx.fatal_error_occurred:
            msg = f"任务因致命错误中断！\n{summary_message}"
        elif ctx.total == 0:
            msg = "没有需要发送的弹幕。"
        elif ctx.success_count == ctx.attempted_count:
            msg = f"任务已完成！所有 {ctx.success_count} 条均发送成功。"
        else:
            msg = f"任务已完成。\n{summary_message}"

        send_windows_notification(notification_title, msg)


class MonitorTaskWorker(BaseWorker):
    """监视任务后台线程"""
    stats_updated = Signal(dict)
    status_updated = Signal(str)
    task_finished = Signal()

    def __init__(
        self,
        target: VideoTarget,
        auth_config: ApiAuthConfig,
        monitor_config: MonitorConfig,
        stop_event: threading.Event,
        parent=None
    ):
        super().__init__(parent)
        self.logger = logging.getLogger("App.Monitor.Worker")
        self.target = target
        self.auth_config = auth_config
        self.monitor_config = monitor_config
        self.stop_event = stop_event

    def run(self):
        try:
            with KeepSystemAwake(self.monitor_config.prevent_sleep):
                with BiliApiClient.from_config(self.auth_config) as client:
                    monitor = BiliDanmakuMonitor(api_client=client, target=self.target)

                    self.logger.info(f"🛡️ 监视启动: {self.target.display_string} | CID: {self.target.cid}")

                    while not self.stop_event.is_set():
                        snap_baseline = self.monitor_config.stats_baseline
                        snap_interval = self.monitor_config.refresh_interval

                        # 单次检查
                        stats = monitor.monitor(stats_baseline=snap_baseline)

                        # 结果信号
                        self.stats_updated.emit(stats)
                        self.status_updated.emit(f"监视中 (存活: {stats['verified']})")

                        msg = (
                            f"监视中... 总计:{stats['total']} | "
                            f"✅存活:{stats['verified']} | "
                            f"⏳待验:{stats['pending']}"
                        )
                        if stats.get('lost', 0) > 0:
                            msg += f" | ❌丢失:{stats['lost']}"

                        self.log_message.emit(msg)

                        if self.stop_event.wait(snap_interval):
                            self.logger.info("收到停止信号，监视任务终止。")
                            break

        except Exception as e:
            self.report_error("监视任务异常", e)
        finally:
            self.task_finished.emit()


class QueryHistoryWorker(BaseWorker):
    """异步查询历史记录"""
    finished_success = Signal(list)  # 返回查询到的 records 列表

    def __init__(self, keyword: str, status_filter: int, parent=None):
        super().__init__(parent)
        self.keyword = keyword
        self.status_filter = status_filter
        self.history_manager = HistoryManager()

    def run(self):
        try:
            records = self.history_manager.query_history(self.keyword, self.status_filter)
            self.finished_success.emit(records)
        except Exception as e:
            self.report_error("查询历史失败", e)
            self.finished_success.emit([])


class QRLoginWorker(BaseWorker):
    """扫码登录后台轮询线程"""
    qr_ready = Signal(str)           # 携带生成的二维码文本 (URL)
    status_updated = Signal(str)     # 携带当前扫码状态文案
    login_success = Signal(dict)     # 携带成功后的 cookies 字典
    login_failed = Signal(str)       # 携带失败原因

    def __init__(self, use_system_proxy: bool, parent=None):
        super().__init__(parent)
        self.use_system_proxy = use_system_proxy
        self.stop_event = threading.Event()

    def run(self):
        try:
            config = ApiAuthConfig(sessdata="", bili_jct="", use_system_proxy=self.use_system_proxy)

            with BiliApiClient.from_config(config) as client:
                # 申请二维码
                data = client.generate_qr_code()
                url = data.get('url')
                qrcode_key = data.get('qrcode_key')

                if not url or not qrcode_key:
                    self.login_failed.emit("获取二维码失败：B站接口返回异常")
                    return

                # 通知 UI 渲染二维码
                self.qr_ready.emit(url)
                self.status_updated.emit("请使用哔哩哔哩客户端扫码")

                # 开始轮询
                while not self.stop_event.is_set():
                    # 每次轮询等待 2 秒
                    if self.stop_event.wait(2.0):
                        self.logger.info("用户取消了扫码登录。")
                        break

                    # 发起轮询请求
                    status, cookies = client.poll_qr_code(qrcode_key)

                    if status == 0:
                        # 扫码且确认成功
                        self.login_success.emit(cookies)
                        break
                    elif status == 86090:
                        self.status_updated.emit("已扫码，请在手机端确认登录")
                    elif status == 86101:
                        pass  # 未扫码，继续等
                    elif status == 86038:
                        self.login_failed.emit("二维码已失效，请关闭重试")
                        break
                    else:
                        self.login_failed.emit(f"未知的状态码: {status}")
                        break

        except Exception as e:
            self.report_error("扫码登录环境异常", e)
            self.login_failed.emit(f"网络异常: {e}")
        finally:
            self.logger.info("扫码轮询线程已退出。")