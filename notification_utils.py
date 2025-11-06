import sys
import logging
import threading
from pathlib import Path
from win11toast import toast

from app_config import AppInfo


logger = logging.getLogger("NotificationUtils")

ICON_PATH = ""

try:
    base_path = Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else Path(__file__).parent
    icon_file = base_path / 'assets' / 'icon.ico'
    if icon_file.exists():
        ICON_PATH = str(icon_file.resolve())
except Exception:
    logging.warning("无法定位图标文件，通知将使用默认图标。", exc_info=True)

def send_windows_notification(title: str, message: str):
    notification_thread = threading.Thread(
        target=toast,
        kwargs={
            "title": title,
            "body": message,
            "icon": ICON_PATH,
            "app_id": AppInfo.NAME
            } 
    )
    notification_thread.start()