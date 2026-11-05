import logging

from PySide6.QtCore import QObject, Signal

from danmaku_sender.config import ApiAuthConfig, NetworkPolicy, Settings
from danmaku_sender.infra.bilibili.bili_api_client import BiliApiClient
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.service.danmaku_verifier import DanmakuVerifier
from danmaku_sender.state import AppState
from danmaku_sender.types.models.common import VerifyResult

from .concurrency import PoolTask

logger = logging.getLogger(__name__)


class HistoryController(QObject):
    """历史记录业务控制器。"""

    historyFetched = Signal(int, list)
    historyFailed = Signal(int, object)  # (序号, 异常)
    tasksFetched = Signal(int, object)   # (序号, (list[TaskRecordRow], dict[str, MonitorStats]))
    tasksFailed = Signal(int, object)    # (序号, 异常)
    verifyCompleted = Signal(dict)
    verifyFailed = Signal(object)

    def __init__(
        self,
        state: AppState,
        settings: Settings,
        history_manager: HistoryManager,
        parent=None,
    ):
        """初始化控制器。

        Args:
            state: 状态树聚合根，取活动会话的身份凭据。
            settings: 配置容器，取传输策略。
            history_manager: 本地账本。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.state = state
        self.settings = settings
        self.history_manager = history_manager
        self._query_seq = 0
        self._task_seq = 0

    def load_tasks(self) -> int:
        """发起异步任务清单查询，连同按任务的存活统计一起回传。

        Returns:
            int: 查询序号，经 tasksFetched 连同结果回传，供调用方丢弃过期结果。
        """
        self._task_seq += 1
        seq = self._task_seq
        PoolTask.submit(
            self._task_load_tasks,
            lambda payload: self.tasksFetched.emit(seq, payload),
            lambda err: self.tasksFailed.emit(seq, err),
        )
        return seq

    def query(self, keyword: str, status_filter: int, task_id: str | None = None) -> int:
        """发起异步弹幕历史查询。

        Args:
            keyword: 关键字。
            status_filter: 核销状态过滤条件。
            task_id: 归属任务，None 表示不限。

        Returns:
            int: 查询序号，经 historyFetched 连同结果回传，供调用方丢弃过期结果。
        """
        self._query_seq += 1
        seq = self._query_seq
        PoolTask.submit(
            self._task_query,
            lambda records: self.historyFetched.emit(seq, records),
            lambda err: self.historyFailed.emit(seq, err),
            keyword, status_filter, task_id,
        )
        return seq

    def verify_records(self, cid: int) -> None:
        """发起异步弹幕验证（单个分P）。

        Args:
            cid: 分 P 的 cid。
        """
        session = self.state.session
        auth = ApiAuthConfig(sessdata=session.sessdata, bili_jct=session.bili_jct)
        network = NetworkPolicy(use_system_proxy=self.settings.global_config.use_system_proxy)
        PoolTask.submit(
            self._task_verify_single,
            self.verifyCompleted.emit,
            self.verifyFailed.emit,
            cid, auth, network,
        )

    def verify_all(self) -> None:
        """发起异步批量验证（所有待验证记录）。"""
        session = self.state.session
        auth = ApiAuthConfig(sessdata=session.sessdata, bili_jct=session.bili_jct)
        network = NetworkPolicy(use_system_proxy=self.settings.global_config.use_system_proxy)
        PoolTask.submit(
            self._task_verify_all,
            self.verifyCompleted.emit,
            self.verifyFailed.emit,
            auth, network,
        )

    # ---- 后台任务：装配与执行逻辑 ----

    def _task_load_tasks(self) -> tuple[list, dict]:
        """读取任务清单与按任务的存活统计（后台线程执行）。

        Returns:
            任务记录行，以及任务标识到存活统计的映射。
        """
        return self.history_manager.list_tasks(), self.history_manager.get_task_stats()

    def _task_query(self, keyword: str, status_filter: int, task_id: str | None) -> list:
        """查询弹幕历史（后台线程执行）。

        Args:
            keyword: 关键字。
            status_filter: 核销状态过滤条件。
            task_id: 归属任务，None 表示不限。

        Returns:
            弹幕历史记录。
        """
        return self.history_manager.query_history(keyword, status_filter, task_id=task_id)

    def _task_verify_single(
        self,
        cid: int,
        auth: ApiAuthConfig,
        network: NetworkPolicy,
    ) -> VerifyResult:
        """单个分P验证（后台线程执行）。

        Args:
            cid: 分 P 的 cid。
            auth: 身份凭据。
            network: 传输策略。

        Returns:
            核销结果。
        """
        with BiliApiClient(auth, network) as client:
            verifier = DanmakuVerifier(api_client=client, history_manager=self.history_manager)
            return verifier.verify_cid(cid)

    def _task_verify_all(
        self,
        auth: ApiAuthConfig,
        network: NetworkPolicy,
    ) -> VerifyResult:
        """批量验证所有待验证记录（后台线程执行）。

        Args:
            auth: 身份凭据。
            network: 传输策略。

        Returns:
            核销结果。
        """
        pending_cids = self.history_manager.get_pending_cids()

        if not pending_cids:
            logger.info("没有待验证的弹幕记录。")
            return {'verified': 0, 'lost': 0, 'total_checked': 0}

        cids = [entry['cid'] for entry in pending_cids]

        with BiliApiClient(auth, network) as client:
            verifier = DanmakuVerifier(api_client=client, history_manager=self.history_manager)
            return verifier.verify_batch(cids)
