import sys
import ctypes

from PySide6.QtWidgets import QApplication

from danmaku_sender.config.app_meta import AppInfo
from danmaku_sender.runtime.log_utils import init_app_logging
from danmaku_sender.ui.framework.style_loader import get_app_icon


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
    log_dir = AppInfo.Paths.LOGS
    init_app_logging(log_dir)

    from .runtime import Runtime
    from .ui.main_window import MainWindow

    app = QApplication(argv)
    app.setStyle("Fusion")
    app.setWindowIcon(get_app_icon())
    app.setApplicationName(AppInfo.NAME)
    app.setApplicationVersion(AppInfo.VERSION)

    rt = Runtime()
    rt.bootstrap()

    window = MainWindow(rt)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()