import sys
import ctypes
import logging
from pathlib import Path
from platformdirs import user_data_dir

from PySide6.QtWidgets import QApplication

from .config.app_config import AppInfo
from .utils.log_utils import GuiLoggingHandler, DailyLogFileHandler
from .utils.resource_utils import get_app_icon


def setup_logging():
    """
    配置全局日志系统
    包含：控制台输出、文件轮转输出、GUI路由输出
    """
    # 基础格式
    formatter = logging.Formatter(
        '%(asctime)s [%(name)s] %(levelname)s - %(message)s', 
        datefmt='%H:%M:%S'
    )
    
    # 获取根 Logger 并重置
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Handler 1: GUI 路由
    gui_handler = GuiLoggingHandler()
    gui_handler.setFormatter(formatter)
    gui_handler.setLevel(logging.INFO)
    root_logger.addHandler(gui_handler)

    # Handler 2: 文件日志 (按天轮转)
    log_dir = Path(user_data_dir(AppInfo.NAME_EN, AppInfo.AUTHOR)) / AppInfo.LOG_DIR_NAME
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file_path = log_dir / AppInfo.LOG_FILE_NAME
    
    file_handler = DailyLogFileHandler(
        filename=str(log_file_path),
        when='midnight',
        interval=1,
        backupCount=7,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG) # 文件里记录详细的 DEBUG 信息
    root_logger.addHandler(file_handler)

    # Handler 3: 控制台输出
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)

    # 设置第三方库日志级别
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    
    logging.info(f"日志系统初始化完成。日志路径: {log_file_path}")


def main(argv=None):
    """
    程序主入口

    Args:
        argv: 命令行参数列表，默认使用 sys.argv
    """
    if argv is None:
        argv = sys.argv

    setup_logging()

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