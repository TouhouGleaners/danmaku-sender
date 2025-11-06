import sys
import logging
import platform
import threading
from pathlib import Path

from app_config import AppInfo


logger = logging.getLogger("NotificationUtils")

try:
    base_path = Path(sys._MEIPASS)
except AttributeError:
    base_path = Path(__file__).resolve().parent

ICON_PATH = base_path / 'assets' / 'icon.ico'

if not ICON_PATH.is_file():
    logger.warning(f"图标文件未找到: {ICON_PATH}。通知将可能没有图标。")
    ICON_PATH = ""
else:
    ICON_PATH = str(ICON_PATH)

try:
    from win11toast import toast
except ImportError:
    toast = None
    logger.warning("未能导入 'win11toast' 库。桌面通知功能将被禁用。")


def _send_notification_wrapper(title: str, message: str):
    """
    一个内部包装函数，用于在独立的线程中安全地调用 toast 并处理异常。
    """
    try:
        toast(
            title=title,
            body=message,
            icon=ICON_PATH,
            app_id=AppInfo.NAME
        )
        logger.info(f"成功发送通知: {title}")
    except Exception as e:
        logger.error(f"发送通知 {title} 时发生未知错误: {e}。", exc_info=True)

def send_windows_notification(title: str, message: str):
    """
    在后台启动一个线程来发送 Windows 桌面通知。
    """
    if toast is None or platform.system() != "Windows":
        logger.debug(f"跳过通知 (依赖缺失或非Windows系统): {title}")
        return
    notification_thread = threading.Thread(
        target=_send_notification_wrapper,
        args=(title, message)
    )
    notification_thread.daemon = True
    notification_thread.start()