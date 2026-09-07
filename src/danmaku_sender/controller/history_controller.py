import logging

from PySide6.QtCore import QObject, Signal

from .concurrency import PoolTask

from danmaku_sender.repo.bili_api_client import BiliApiClient
from danmaku_sender.repo.history_manager import HistoryManager
from danmaku_sender.service.danmaku_verifier import DanmakuVerifier
from danmaku_sender.types.models.common import VerifyResult
from danmaku_sender.config import ApiAuthConfig


logger = logging.getLogger(__name__)


class HistoryController(QObject):
    """历史记录业务控制器"""
    historyFetched = Signal(list)
    verifyCompleted = Signal(dict)
    errorOccurred = Signal(object)

    def __init__(self, history_manager: HistoryManager, parent=None):
        super().__init__(parent)
        self.history_manager = history_manager

    def query(self, keyword: str, status_filter: int):
        """发起异步数据库查询"""
        PoolTask.submit(
            self.history_manager.query_history,
            self.historyFetched.emit,
            self.errorOccurred.emit,
            keyword, status_filter,
        )

    def verify_records(self, cid: int, auth_config: ApiAuthConfig):
        """发起异步弹幕验证（单个分P）"""
        PoolTask.submit(
            self._task_verify_single,
            self.verifyCompleted.emit,
            self.errorOccurred.emit,
            cid, auth_config,
        )

    def verify_all(self, auth_config: ApiAuthConfig):
        """发起异步批量验证（所有待验证记录）"""
        PoolTask.submit(
            self._task_verify_all,
            self.verifyCompleted.emit,
            self.errorOccurred.emit,
            auth_config,
        )

    # ---- 后台任务：装配与执行逻辑 ----

    def _task_verify_single(self, cid: int, auth_config: ApiAuthConfig) -> VerifyResult:
        """单个分P验证（后台线程执行）"""
        with BiliApiClient.from_config(auth_config) as client:
            verifier = DanmakuVerifier(api_client=client, history_manager=self.history_manager)
            return verifier.verify_cid(cid)

    def _task_verify_all(self, auth_config: ApiAuthConfig) -> VerifyResult:
        """批量验证所有待验证记录（后台线程执行）"""
        pending_cids = self.history_manager.get_pending_cids()

        if not pending_cids:
            logger.info("没有待验证的弹幕记录。")
            return {'verified': 0, 'lost': 0, 'total_checked': 0}

        cids = [entry['cid'] for entry in pending_cids]

        with BiliApiClient.from_config(auth_config) as client:
            verifier = DanmakuVerifier(api_client=client, history_manager=self.history_manager)
            return verifier.verify_batch(cids)