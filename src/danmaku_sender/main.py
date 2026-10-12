import ctypes
import sys

from PySide6.QtWidgets import QApplication

from danmaku_sender.config.app_meta import AppInfo
from danmaku_sender.ui.framework.cursor_policy import AutoHandCursorFilter
from danmaku_sender.ui.framework.icons import get_app_icon
from danmaku_sender.ui.support.log_utils import init_app_logging


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

    from .app.runtime import Runtime
    from .ui.main_window import MainWindow

    app = QApplication(argv)
    # 必须早于任何控件创建：光标在控件 polish 时设置
    app.installEventFilter(AutoHandCursorFilter(app))
    app.setStyle("Fusion")
    app.setWindowIcon(get_app_icon())
    app.setApplicationName(AppInfo.NAME)
    app.setApplicationVersion(AppInfo.VERSION)

    rt = Runtime()
    rt.bootstrap()

    window = MainWindow(rt.app_state, rt.settings, rt.history_manager)
    window.show()

    # 退出前强制落盘配置与凭据
    app.aboutToQuit.connect(rt.shutdown)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()