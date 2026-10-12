import logging

from danmaku_sender.config.app_meta import AppInfo
from danmaku_sender.infra.persistence.history_manager import HistoryManager
from danmaku_sender.infra.storage import AccountStorage, ConfigStorage

from .state.app_state import AppState

logger = logging.getLogger(__name__)


class Runtime:
    """
    应用运行时

    持有所有全局服务，管理生命周期。
    """

    def __init__(self) -> None:
        # === 状态 ===
        self.app_state = AppState()

        # === 持久化存储 ===
        self.config_storage = ConfigStorage()
        self.account_storage = AccountStorage()

        self._bootstrapped = False

    def bootstrap(self) -> None:
        """编排完整的启动序列"""
        if self._bootstrapped:
            return
        self._bootstrapped = True

        # === 数据库 ===
        self.history_manager = HistoryManager(AppInfo.Paths.HISTORY_DB)

        try:
            self._activate_saved_accounts()
        except Exception as e:
            logger.error(f"凭据加载失败，将以未登录状态继续: {e}")

        self.config_storage.load(self.app_state.settings)

    def _activate_saved_accounts(self) -> None:
        """加载已保存账号并激活第一个。"""
        accounts = self.account_storage.load_accounts()
        self.app_state.saved_accounts = accounts
        if accounts:
            first = accounts[0]
            self.app_state.sessdata = first.sessdata
            self.app_state.bili_jct = first.bili_jct
            logger.info(f"已激活账号: {first.name or '(未命名)'}")
