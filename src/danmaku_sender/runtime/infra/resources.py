import logging

from ..managers.theme_manager import ThemeManager


class AppResources:
    """
    全局资源持有

    统一管理基础设施资源。
    """

    def __init__(self) -> None:
        self.logger: logging.Logger = logging.getLogger(__name__)
        self.theme: ThemeManager = ThemeManager.instance()
