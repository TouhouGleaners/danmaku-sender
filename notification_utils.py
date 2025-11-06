import sys
import logging
from pathlib import Path
import threading


logger = logging.getLogger("NotificationService")

APP_NAME = "B站弹幕补档工具"
IS_WINDOWS = sys.platform == "win32"
ICON_PATH = ""

try:
    icon_file = Path(__file__).parent / 'assets' / 'icon.ico'
    if icon_file.exists():
        ICON_PATH = str(icon_file.resolve())
except Exception:
    pass

if IS_WINDOWS:
    try:
        from win11toast import toast
    except ImportError:
        IS_WINDOWS = False
        toast = None
else:
    toast = None

def _send_in_thread(title: str, message: str):
    try:
        toast(
            title, 
            message, 
            icon=ICON_PATH, 
            app_id=APP_NAME
        )
        logger.info(f"成功发送通知 (后台线程): '{title}'")
    except Exception as e:
        logger.error(f"在后台线程发送通知时发生错误: {e}", exc_info=True)

def send_windows_notification(title: str, message: str):
    if not IS_WINDOWS or not toast:
        return

    notification_thread = threading.Thread(
        target=_send_in_thread, 
        args=(title, message)
    )
    notification_thread.start()
    logger.info(f"已创建后台线程来发送通知: '{title}'")

if IS_WINDOWS and toast:
    logger.info("成功初始化 Windows 通知服务 (win11toast, 异步模式)。")
elif IS_WINDOWS and not toast:
    logger.warning("当前为 Windows 系统，但 win11toast 库导入失败，通知功能将不可用。")