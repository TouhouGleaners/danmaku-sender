"""装配总线：构造各层、接线应用级行为、管理生命周期。"""
import logging

from PySide6.QtCore import QObject, QTimer

from danmaku_sender.config import Settings
from danmaku_sender.config.app_meta import AppInfo
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.infra.persistence.queue_store import QueueStore
from danmaku_sender.infra.storage import AccountStorage, ConfigStorage
from danmaku_sender.state import AppState
from danmaku_sender.types.exceptions.exceptions import QueueStorageError
from danmaku_sender.types.models.queue import TaskStatus

logger = logging.getLogger(__name__)


class Runtime(QObject):
    """装配总线：持有全局服务，接线应用级行为，管理生命周期。

    依赖图的顶点——可依赖各层，自身不被任何层依赖。
    ``settings`` 为持久化配置，``app_state`` 为易失状态树；
    二者生命周期不同，故平级持有。

    Attributes:
        settings: 持久化配置容器。
        app_state: 易失状态树。
    """

    CONFIG_SAVE_DEBOUNCE_MS = 800

    def __init__(self) -> None:
        """初始化运行时，构建状态与存储。"""
        super().__init__()
        # === 配置 ===
        self.settings = Settings()

        # === 状态 ===
        self.app_state = AppState()

        # === 持久化存储 ===
        self.config_storage = ConfigStorage()
        self.account_storage = AccountStorage()

        self._config_save_timer = QTimer(self)
        self._config_save_timer.setSingleShot(True)
        self._config_save_timer.setInterval(self.CONFIG_SAVE_DEBOUNCE_MS)
        self._config_save_timer.timeout.connect(self._save_config)

        self._bootstrapped = False

    def bootstrap(self) -> None:
        """编排完整的启动序列。"""
        if self._bootstrapped:
            return
        self._bootstrapped = True

        # === 数据库 ===
        self.history_manager = HistoryManager(AppInfo.Paths.HISTORY_DB)
        self.queue_store = self._open_queue_store()

        try:
            self._activate_saved_accounts()
        except Exception as e:
            logger.error(f"凭据加载失败，将以未登录状态继续: {e}")

        self.config_storage.load(self.settings)

        # 配置写回 → 防抖落盘
        self.app_state.configChanged.connect(self._config_save_timer.start)

    def shutdown(self) -> None:
        """退出前强制落盘配置与凭据，关闭队列库。"""
        self._config_save_timer.stop()
        self._save_config()
        self._save_credentials()
        self.queue_store.close()

    def _open_queue_store(self) -> QueueStore:
        """打开队列数据库并将任务恢复至状态树。

        若存在上次异常退出残留的 RUNNING 任务，则修正为 PAUSED 并保留其游标，以便用户继续发送。

        Returns:
            QueueStore: 已完成初始化与恢复的队列存储实例。
        """
        store = QueueStore.open_with_recovery(AppInfo.Paths.QUEUE_DB)
        recovered = store.load_all()
        paused = 0
        for task in recovered:
            if task.execution.status is not TaskStatus.RUNNING:
                continue
            task.execution.status = TaskStatus.PAUSED
            paused += 1
            try:
                store.update_task_state(
                    task.definition.task_id,
                    status=TaskStatus.PAUSED,
                    cursor=task.execution.attempted,
                    burst_count=0,
                    error=task.execution.error_msg or None,
                )
            except QueueStorageError:
                logger.exception(f"启动纠偏落库失败 [task_id={task.definition.task_id}]")
        if paused:
            logger.info(f"启动纠偏: {paused} 个残留发送中的任务转为已暂停")
        if recovered:
            self.app_state.workspace.queue_state.restore_tasks(recovered)
        return store

    def _activate_saved_accounts(self) -> None:
        """加载已保存账号并激活第一个。"""
        accounts = self.account_storage.load_accounts()
        self.app_state.session.saved_accounts = accounts
        if accounts:
            first = accounts[0]
            self.app_state.session.sessdata = first.sessdata
            self.app_state.session.bili_jct = first.bili_jct
            logger.info(f"已激活账号: {first.name or '(未命名)'}")

    def _save_config(self) -> None:
        """落盘持久化配置。"""
        self.config_storage.save(self.settings)

    def _save_credentials(self) -> None:
        """登记当前凭据并落盘账号列表。"""
        session = self.app_state.session
        session.upsert_account(session.sessdata, session.bili_jct)
        self.account_storage.save_accounts(session.saved_accounts)
