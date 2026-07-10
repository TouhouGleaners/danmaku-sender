from .resources import AppResources
from .app_state import AppState
from .config_manager import ConfigManager
from .account_manager import AccountManager


class Runtime:
    """
    应用运行时

    持有所有全局服务，管理生命周期。
    """

    def __init__(self) -> None:
        # === 基础设施 ===
        self.resources = AppResources()

        # === 状态 ===
        self.app_state = AppState()

        # === 持久化管理器 ===
        self.config_manager = ConfigManager()
        self.account_manager = AccountManager()

        self._bootstrapped = False

    def bootstrap(self) -> None:
        """编排完整的启动序列"""
        if self._bootstrapped:
            return
        self._bootstrapped = True

        self.resources.theme.init_theme()
        self.account_manager.load_credentials(self.app_state)
        self.config_manager.load(self.app_state)
