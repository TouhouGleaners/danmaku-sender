import time

from PySide6.QtCore import QObject, Signal

from danmaku_sender.config import (
    ApiAuthConfig,
    GlobalConfig,
    MonitorConfig,
    SenderConfig,
    ThemeConfig,
    ValidationConfig,
)
from danmaku_sender.types.models.account import AccountCredential

from .queue_state import QueueState


class AppState(QObject):
    """
    应用程序全局状态管理。
    继承自 QObject 以支持信号槽机制，实现 UI 与 逻辑 的解耦。
    """
    credentialsChanged = Signal()
    configChanged = Signal()  # 配置被表单写回（自动落盘等副作用的广播点）
    senderLogReceived = Signal(str)
    monitorLogReceived = Signal(str)
    senderActiveChanged = Signal()
    monitorActiveChanged = Signal()

    def __init__(self):
        super().__init__()
        self.app_launch_time = time.time()

        # 核心凭证
        self._sessdata: str = ""
        self._bili_jct: str = ""

        # 各模块配置（global_config 为跨模块共享的系统设置）
        self.global_config = GlobalConfig()
        self.sender_config = SenderConfig()
        self.monitor_config = MonitorConfig()
        self.theme_config = ThemeConfig()
        self.validation_config = ValidationConfig()

        # 运行时状态
        self.queue_state = QueueState(self)

        # 多账号
        self.saved_accounts: list[AccountCredential] = []

        self._sender_is_active: bool = False
        self._monitor_is_active: bool = False

        # 会话运行时（不持久化）：监视统计基线时间戳，0 表示全量历史
        self.stats_baseline: float = 0.0

    @property
    def sessdata(self) -> str:
        return self._sessdata

    @sessdata.setter
    def sessdata(self, value: str):
        if self._sessdata != value:
            self._sessdata = value
            self.credentialsChanged.emit()

    @property
    def bili_jct(self) -> str:
        return self._bili_jct

    @bili_jct.setter
    def bili_jct(self, value: str):
        if self._bili_jct != value:
            self._bili_jct = value
            self.credentialsChanged.emit()

    @property
    def sender_is_active(self) -> bool:
        return self._sender_is_active

    @sender_is_active.setter
    def sender_is_active(self, value: bool):
        if self._sender_is_active != value:
            self._sender_is_active = value
            self.senderActiveChanged.emit()

    @property
    def monitor_is_active(self) -> bool:
        return self._monitor_is_active

    @monitor_is_active.setter
    def monitor_is_active(self, value: bool):
        if self._monitor_is_active != value:
            self._monitor_is_active = value
            self.monitorActiveChanged.emit()

    def get_api_auth(self) -> ApiAuthConfig:
        """
        工厂方法：从当前状态生成一个用于初始化的 API 凭证对象。
        """
        return ApiAuthConfig(
            sessdata=self.sessdata,
            bili_jct=self.bili_jct,
            use_system_proxy=self.global_config.use_system_proxy,
        )
