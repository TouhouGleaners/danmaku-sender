import ctypes
import faulthandler
import sys

from PySide6.QtWidgets import QApplication

from danmaku_sender.config.app_meta import AppInfo
from danmaku_sender.infra.crash_dump import CrashDumpLog
from danmaku_sender.ui.framework.cursor_policy import AutoHandCursorFilter
from danmaku_sender.ui.framework.focus_policy import ClickAwayFocusFilter
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

    app = QApplication(argv)

    # GuiLoggingHandler 是 QObject，须在 QApplication 之后建以防线程归属问题；
    # 下述导入里的启动告警也须落在日志通道建立之后
    log_dir = AppInfo.Paths.LOGS
    init_app_logging(log_dir)

    from .app.runtime import Runtime
    from .ui.main_window import MainWindow

    # 硬崩时留下 C 级调用栈；转储不可用时跳过诊断，不阻断启动
    crash_dump = CrashDumpLog().prepare(log_dir)
    if crash_dump is not None:
        faulthandler.enable(file=crash_dump, all_threads=True)

    # 必须早于任何控件创建：光标在控件 polish 时设置
    app.installEventFilter(AutoHandCursorFilter(app))
    app.installEventFilter(ClickAwayFocusFilter(app))
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

    code = app.exec()
    sys.exit(code)


if __name__ == "__main__":
    main()
