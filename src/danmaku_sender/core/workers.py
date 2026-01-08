import logging
from PySide6.QtCore import QThread, Signal

from ..api.bili_api_client import BiliApiClient
from ..core.bili_sender import BiliDanmakuSender
from ..core.bili_monitor import BiliDanmakuMonitor
from ..core.state import ApiAuthConfig, SenderConfig, MonitorConfig
from ..utils.system_utils import KeepSystemAwake


class BaseWorker(QThread):
    """
    所有 Worker 线程的基类。
    提供了线程管理、信号定义和日志记录等通用功能。
    """
    log_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(self.__class__.__name__)

    def report_error(self, title: str, exception: Exception):
        self.logger.error(title, exc_info=True)
        self.log_message.emit(f"{title}: {exception}")


class FetchInfoWorker(BaseWorker):
    """用于后台获取视频信息的线程"""
    finished_success = Signal(dict)  # 成功信号，携带视频信息字典
    finished_error = Signal(str)     # 失败信号，携带错误信息

    def __init__(self, bvid, auth_config: ApiAuthConfig, parent=None):
        super().__init__(parent)
        self.bvid = bvid
        self.auth_config = auth_config

    def run(self):
        try:
            with BiliApiClient.from_config(self.auth_config) as client:
                sender = BiliDanmakuSender(client)
                info = sender.get_video_info(self.bvid)
                self.finished_success.emit(info)
        except Exception as e:
            self.report_error("获取视频信息失败", e)
            self.finished_error.emit(str(e))


class SendTaskWorker(BaseWorker):
    """用于后台发送弹幕的线程"""
    progress_updated = Signal(int, int)  # 已尝试, 总数
    task_finished = Signal(object)       # 携带 sender 实例以便后续处理(如保存失败弹幕)

    def __init__(self, bvid, cid, danmakus,
                 auth_config: ApiAuthConfig,
                 strategy_config: SenderConfig,
                 stop_event, parent=None):
        super().__init__(parent)
        self.bvid = bvid
        self.cid = cid
        self.danmakus = danmakus
        self.auth_config = auth_config
        self.strategy_config = strategy_config
        self.stop_event = stop_event
        self.sender_instance = None

    def run(self):
        try:
            with KeepSystemAwake(self.strategy_config.prevent_sleep):
                with BiliApiClient.from_config(self.auth_config) as client:
                    self.sender_instance = BiliDanmakuSender(client)

                    def _callback(attempted, total):
                        self.progress_updated.emit(attempted, total)

                    self.sender_instance.send_danmaku_from_list(
                        bvid=self.bvid,
                        cid=self.cid,
                        danmakus=self.danmakus,
                        config=self.strategy_config,
                        stop_event=self.stop_event,
                        progress_callback=_callback
                    )
        except Exception as e:
            self.report_error("任务发生严重错误", e)
        finally:
            self.task_finished.emit(self.sender_instance)


class MonitorTaskWorker(BaseWorker):
    """监视任务后台线程"""
    progress_updated = Signal(int, int)  # 匹配，总数
    status_updated = Signal(str)         # 状态更新
    task_finished = Signal()

    def __init__(self, cid, danmakus,
                 auth_config: ApiAuthConfig,
                 monitor_config: MonitorConfig,
                 stop_event, parent=None):
        super().__init__(parent)
        self.cid = cid
        self.danmakus = danmakus
        self.auth_config = auth_config
        self.monitor_config = monitor_config
        self.stop_event = stop_event

    def run(self):
        try:
            with KeepSystemAwake(self.monitor_config.prevent_sleep):
                with BiliApiClient.from_config(self.auth_config) as client:
                    monitor = BiliDanmakuMonitor(
                        api_client=client,
                        cid=self.cid,
                        loaded_danmakus=self.danmakus,
                        interval=self.monitor_config.refresh_interval,
                        time_tolerance=self.monitor_config.tolerance
                    )

                    def _callback(matched, total):
                        self.progress_updated.emit(matched, total)
                        if total > 0:
                            self.status_updated.emit(f"监视中... ({matched}/{total})")

                    monitor.run(self.stop_event, _callback)
        
        except Exception as e:
            self.report_error("监视任务异常", e)
        finally:
            self.task_finished.emit()