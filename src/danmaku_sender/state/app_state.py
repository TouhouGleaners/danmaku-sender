"""状态树聚合根。"""
from PySide6.QtCore import QObject, Signal

from danmaku_sender.config import Settings

from .session import SessionState
from .workspace import WorkspaceState


class AppState(QObject):
    """状态树聚合根：持有三个切片，自身不装业务字段。

    按切片访问：``state.session`` 登录身份、``state.workspace`` 会话工作区、
    ``state.settings`` 持久化配置。

    Attributes:
        settings: 持久化配置容器。
        session: 登录身份与账号列表。
        workspace: 会话工作区（队列与活动状态）。
    """

    configChanged = Signal()  # 配置被表单写回（自动落盘等副作用的广播点）

    def __init__(self) -> None:
        """初始化状态树。"""
        super().__init__()
        self.settings = Settings()
        self.session = SessionState(self.settings)
        self.workspace = WorkspaceState()
