import time

from PySide6.QtCore import QObject, Signal

from ..config import ApiAuthConfig, SenderConfig, MonitorConfig, ValidationConfig
from ..types.models.account import AccountCredential
from ..types.models.video_state import VideoState


class AppState(QObject):
    """
    应用程序全局状态管理。
    继承自 QObject 以支持信号槽机制，实现 UI 与 逻辑 的解耦。
    """
    credentialsChanged = Signal()
    senderLogReceived = Signal(str)
    monitorLogReceived = Signal(str)
    senderActiveChanged = Signal()
    monitorActiveChanged = Signal()
    editorDirtyChanged = Signal()

    def __init__(self):
        super().__init__()
        self.app_launch_time = time.time()

        # 核心凭证
        self._sessdata: str = ""
        self._bili_jct: str = ""

        # 各模块配置
        self.sender_config = SenderConfig()
        self.monitor_config = MonitorConfig()
        self.validation_config = ValidationConfig()

        # 运行时状态
        self.video_state = VideoState()

        # 多账号
        self.saved_accounts: list[AccountCredential] = []

        self._sender_is_active: bool = False
        self._monitor_is_active: bool = False
        self._editor_is_dirty: bool = False

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

    @property
    def editor_is_dirty(self) -> bool:
        return self._editor_is_dirty

    @editor_is_dirty.setter
    def editor_is_dirty(self, value: bool):
        if self._editor_is_dirty != value:
            self._editor_is_dirty = value
            self.editorDirtyChanged.emit()

    def get_api_auth(self) -> ApiAuthConfig:
        """
        工厂方法：从当前状态生成一个用于初始化的 API 凭证对象。
        """
        return ApiAuthConfig(
            sessdata=self.sessdata,
            bili_jct=self.bili_jct,
            use_system_proxy=self.sender_config.use_system_proxy
        )
