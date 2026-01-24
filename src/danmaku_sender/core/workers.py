import logging
from PySide6.QtCore import QThread, Signal

from .bili_sender import BiliDanmakuSender
from .bili_monitor import BiliDanmakuMonitor
from .history_manager import HistoryManager
from .state import ApiAuthConfig, SenderConfig, MonitorConfig
from .models.danmaku import Danmaku
from .models.result import DanmakuSendResult 
from .models.structs import VideoTarget

from ..api.bili_api_client import BiliApiClient
from ..api.update_checker import UpdateChecker
from ..config.app_config import AppInfo
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


class UpdateCheckWorker(BaseWorker):
    """用于后台检查更新的线程"""
    update_found = Signal(str, str, str)  # 版本，信息，URL
    no_update = Signal()                  # 无更新 (手动检查时反馈)

    def __init__(self, use_proxy: bool, is_manual: bool = False, parent=None):
        super().__init__(parent)
        self.use_proxy = use_proxy
        self.is_manual = is_manual

    def run(self):
        try:
            info = UpdateChecker.check(AppInfo.VERSION, self.use_proxy)
            if info.has_update:
                self.update_found.emit(info.remote_version, info.release_notes, info.url)
            elif self.is_manual:
                self.no_update.emit()
        except Exception as e:
            if self.is_manual:
                self.report_error("检查更新失败", e)
            else:
                self.logger.warning(f"自动更新检查失败: {e}")


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
                 stop_event, video_title: str = "",
                 parent=None):
        super().__init__(parent)
        self.target = VideoTarget(bvid=bvid, cid=cid, title=video_title)
        self.danmakus = danmakus
        self.auth_config = auth_config
        self.strategy_config = strategy_config
        self.stop_event = stop_event
        self.sender_instance = None
        self.history_manager = HistoryManager()

    def run(self):
        try:
            with KeepSystemAwake(self.strategy_config.prevent_sleep):
                with BiliApiClient.from_config(self.auth_config) as client:
                    self.sender_instance = BiliDanmakuSender(client)

                    def _progress_cb(attempted, total):
                        self.progress_updated.emit(attempted, total)

                    def _save_to_db_cb(dm: Danmaku, result: DanmakuSendResult):
                        if result.is_success and result.dmid:
                            if not dm.dmid:
                                dm.dmid = result.dmid
                            self.history_manager.record_danmaku(self.target, dm, result.is_visible)

                    self.sender_instance.send_danmaku_from_list(
                        target=self.target,
                        danmakus=self.danmakus,
                        config=self.strategy_config,
                        stop_event=self.stop_event,
                        progress_callback=_progress_cb,
                        result_callback=_save_to_db_cb,
                        history_manager=self.history_manager
                    )
        except Exception as e:
            self.report_error("任务发生严重错误", e)
        finally:
            self.task_finished.emit(self.sender_instance)


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
        stop_event,
        parent=None
    ):
        super().__init__(parent)
        self.target = target
        self.auth_config = auth_config
        self.monitor_config = monitor_config
        self.stop_event = stop_event

    def run(self):
        try:
            with KeepSystemAwake(self.monitor_config.prevent_sleep):
                with BiliApiClient.from_config(self.auth_config) as client:
                    monitor = BiliDanmakuMonitor(
                        api_client=client,
                        target=self.target,
                        interval=self.monitor_config.refresh_interval
                    )

                    def _callback(stats: dict):
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

                    monitor.run(self.stop_event, _callback)
        
        except Exception as e:
            self.report_error("监视任务异常", e)
        finally:
            self.task_finished.emit()