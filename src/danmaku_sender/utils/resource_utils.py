import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication


def get_assets_path() -> Path:
    """获取 assets 文件夹路径"""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / 'assets'
    
    current_file = Path(__file__).resolve()

    try:
        candidate = current_file.parents[3] / 'assets'
        if candidate.exists() and candidate.is_dir():
            return candidate
    except IndexError:
        pass
    
    return Path(sys.argv[0]).resolve().parent / 'assets'

def get_app_icon() -> QIcon:
    """获取程序全局图标"""
    icon_path = get_assets_path() / "icon.ico"
    if icon_path.exists():
        return QIcon(str(icon_path))
    return QIcon()

def load_stylesheet():
    """加载全局样式表"""
    qss_path = get_assets_path() / "qss" / "style.qss"
    if qss_path.exists():
        try:
            with open(qss_path, "r", encoding="utf-8") as f:
                content = f.read()
                QApplication.instance().setStyleSheet(content)
        except Exception as e:
            print(f"加载样式表失败: {e}")