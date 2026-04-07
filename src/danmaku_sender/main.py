import sys
import ctypes
from pathlib import Path
from platformdirs import user_data_dir

from PySide6.QtWidgets import QApplication

from .config.app_config import AppInfo
from .ui.framework.style_loader import get_app_icon
from .utils.log_utils import init_app_logging


def main(argv=None):
    """
    程序主入口

    Args:
        argv: 命令行参数列表，默认使用 sys.argv
    """
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(AppInfo.NAME)
        except Exception:
            pass

    if argv is None:
        argv = sys.argv

    # 初始化日志
    log_dir = Path(user_data_dir(AppInfo.NAME_EN, AppInfo.AUTHOR)) / AppInfo.LOG_DIR_NAME
    init_app_logging(log_dir)

    from .ui.main_window import MainWindow

    app = QApplication(argv)
    app.setStyle("Fusion")
    app.setWindowIcon(get_app_icon())
    app.setApplicationName(AppInfo.NAME)
    app.setApplicationVersion(AppInfo.VERSION)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()