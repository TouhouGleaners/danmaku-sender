from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ...utils.path_utils import get_assets_path


def get_app_icon() -> QIcon:
    """获取程序全局图标"""
    icon_path = get_assets_path() / "icon.ico"
    if icon_path.exists():
        return QIcon(str(icon_path))
    return QIcon()

def get_svg_icon(name: str) -> QIcon:
    """加载矢量图标"""
    icon_path = get_assets_path() / "icons" / name
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
                app = QApplication.instance()
                if isinstance(app, QApplication):
                    app.setStyleSheet(content)
        except Exception as e:
            print(f"加载样式表失败: {e}")