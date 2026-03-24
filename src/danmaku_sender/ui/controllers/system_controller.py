import logging

from PySide6.QtCore import QObject, Signal, QThreadPool

from ..framework.task_runner import GenericTask
from ...api.update_checker import UpdateChecker, UpdateInfo
from ...config.app_config import AppInfo


logger = logging.getLogger("SystemController")


def _check_update(use_proxy: bool):
    """纯业务逻辑：连接 GitHub API 检查更新"""
    return UpdateChecker.check(AppInfo.VERSION, use_proxy)


class SystemController(QObject):
    """系统业务控制器 (更新检查等)"""
    update_found = Signal(str, str, str)  # version, notes, url
    no_update = Signal(bool)              # 是否是手动检查触发的

    def __init__(self, parent=None):
        super().__init__(parent)

    def check_for_updates(self, use_proxy: bool, is_manual: bool = False):
        """发起异步更新检查"""
        task = GenericTask(_check_update, use_proxy)

        def _handle_res(info: UpdateInfo):
            if info.has_update:
                self.update_found.emit(info.remote_version, info.release_notes, info.url)
            else:
                self.no_update.emit(is_manual)

        task.signals.result.connect(_handle_res)
        QThreadPool.globalInstance().start(task)