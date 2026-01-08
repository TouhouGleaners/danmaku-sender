import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication


def get_assets_path() -> Path:
    """获取 assets 文件夹路径"""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / 'assets'
    
    return Path(__file__).resolve().parents[3] / 'assets'

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