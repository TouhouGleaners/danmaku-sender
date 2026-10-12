"""平台能力：电源管理与系统通知。"""
from .notify import send_windows_notification
from .power import KeepSystemAwake, PowerManagement

__all__ = ["KeepSystemAwake", "PowerManagement", "send_windows_notification"]
