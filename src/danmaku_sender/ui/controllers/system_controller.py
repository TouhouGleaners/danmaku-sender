import logging

from PySide6.QtCore import QObject, Signal, QThreadPool

from ..framework.task_runner import GenericTask
from ...api.update_checker import UpdateChecker, UpdateInfo
from ...config.app_config import AppInfo


logger = logging.getLogger("App.System.System")


def _check_update(use_proxy: bool):
    """纯业务逻辑：连接 GitHub API 检查更新"""
    return UpdateChecker.check(AppInfo.VERSION, use_proxy)


class SystemController(QObject):
    """系统业务控制器 (更新检查等)"""
    update_found = Signal(str, str, str)  # version, notes, url
    no_update = Signal(bool)              # 是否需要展示“已是最新”弹窗
    check_failed = Signal(str, bool)      # 错误信息, 是否需要展示“检查失败”弹窗

    def __init__(self, parent=None):
        super().__init__(parent)
        self._update_check_in_flight = False  # 确保全局只有一个更新检查任务
        self._in_flight_is_manual = False     # 当前任务是否被视为“手动操作”

    def check_for_updates(self, use_proxy: bool, is_manual: bool = False):
        """发起异步更新检查"""
        if self._update_check_in_flight:
            if is_manual:
                # 提升当前任务等级，完成后会弹窗提醒用户
                self._in_flight_is_manual = True
                logger.debug("更新检查已在进行中，已将其提升为手动模式。")
            return

        self._update_check_in_flight = True
        self._in_flight_is_manual = is_manual

        task = GenericTask(_check_update, use_proxy)

        task.signals.result.connect(self._on_check_finished)
        task.signals.error.connect(self._on_check_failed)

        QThreadPool.globalInstance().start(task)

    def _on_check_finished(self, info: UpdateInfo):
        """内部回调：更新检查成功完成"""
        is_manual = self._in_flight_is_manual

        # 释放状态锁
        self._update_check_in_flight = False
        self._in_flight_is_manual = False

        if info.has_update:
            self.update_found.emit(info.remote_version, info.release_notes, info.url)
        else:
            self.no_update.emit(is_manual)

    def _on_check_failed(self, err: str):
        """内部回调：更新检查失败"""
        is_manual = self._in_flight_is_manual

        # 释放状态锁
        self._update_check_in_flight = False
        self._in_flight_is_manual = False

        # 如果是手动点的，通知 UI 报错
        self.check_failed.emit(err, is_manual)