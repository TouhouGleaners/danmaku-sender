"""持久化配置容器。"""
from dataclasses import dataclass, field

from .global_config import GlobalConfig
from .monitor_config import MonitorConfig
from .send_policy import SendPolicy
from .sender_config import SenderConfig
from .theme_config import ThemeConfig
from .validation_config import ValidationConfig


@dataclass
class Settings:
    """全部持久化配置的容器。

    实例终身不换，只就地更新字段。

    Attributes:
        global_config: 跨模块共享的系统设置。
        sender_config: 发送参数。
        send_policy: 发送策略。
        monitor_config: 监视参数。
        theme_config: 主题外观。
        validation_config: 校验关键字。
    """

    global_config: GlobalConfig = field(default_factory=GlobalConfig)
    sender_config: SenderConfig = field(default_factory=SenderConfig)
    send_policy: SendPolicy = field(default_factory=SendPolicy)
    monitor_config: MonitorConfig = field(default_factory=MonitorConfig)
    theme_config: ThemeConfig = field(default_factory=ThemeConfig)
    validation_config: ValidationConfig = field(default_factory=ValidationConfig)
