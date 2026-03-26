import sys
import logging
import logging.handlers
from pathlib import Path
from datetime import datetime
from typing import Callable

from ..config.app_config import AppInfo


class GuiLoggingHandler(logging.Handler):
    """基于命名空间前缀路由日志到 UI 窗口"""
    def __init__(self):
        super().__init__()
        self.sender_callback: Callable[[str], None] | None = None
        self.monitor_callback: Callable[[str], None] | None = None

    def emit(self, record):
        """
        发出一条日志记录。

        该方法会处理日志记录，并根据日志器名称前缀，将其路由至对应的回调函数。
        它针对不同组件的日志做分流处理:
        来自 "App.Sender" 的日志，分发至 sender_callback
        来自 "App.Monitor" 的日志，分发至 monitor_callback
        来自 "App.System" 及其他来源的日志，将被忽略

        Args:
            record (logging.LogRecord)：待输出的日志记录对象。
        Raise:
            处理过程中会捕获所有异常，并交由 handleError () 方法统一处理错误，避免日志自身的异常向上冒泡传递。
        """

        try:
            msg = self.format(record)
            if record.name.startswith("App.Sender") and self.sender_callback:
                self.sender_callback(msg)
            elif record.name.startswith("App.Monitor") and self.monitor_callback:
                self.monitor_callback(msg)
            # App.System 或其他开头的日志直接忽略
        except Exception:
            self.handleError(record)


class DailyLogFileHandler(logging.handlers.TimedRotatingFileHandler):
    """自定义日志轮转：YYYY-MM-DD.log"""
    def rotation_filename(self, filename: str) -> str:
        """重写父类的 rotation_filename 方法，以自定义归档文件的命名格式。"""
        # 计算归档日期，保持文件名如：2026-03-27.log
        previous_rollover_time = self.rolloverAt - self.interval
        archive_datetime = datetime.fromtimestamp(previous_rollover_time)
        base_path = Path(self.baseFilename)
        return str(base_path.parent / f"{archive_datetime.strftime('%Y-%m-%d')}.log")


def init_app_logging(log_dir: Path):
    """全局日志系统"""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = log_dir / AppInfo.LOG_FILE_NAME

    # --- 定义格式 ---
    # 文件和控制台: 详细格式
    detailed_formatter = logging.Formatter(
        '%(asctime)s [%(name)s] %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    # GUI: 精简格式
    gui_formatter = logging.Formatter('%(asctime)s %(message)s', datefmt='%H:%M:%S')

    # --- 获取根 Logger 并重置环境 ---
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Handler A: 文件输出 (DEBUG级别，记录所有)
    file_handler = DailyLogFileHandler(
        filename=str(log_file_path),
        when='midnight',
        interval=1,
        backupCount=7,
        encoding='utf-8'
    )
    file_handler.setFormatter(detailed_formatter)
    file_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)

    # Handler B: 控制台输出 (DEBUG级别)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(detailed_formatter)
    console_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)

    # Handler C: GUI 路由 (INFO级别)
    gui_handler = GuiLoggingHandler()
    gui_handler.setFormatter(gui_formatter)
    gui_handler.setLevel(logging.INFO)
    root_logger.addHandler(gui_handler)

    # --- 屏蔽第三方库的噪音 ---
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    logging.info(f"日志系统初始化完成。日志路径: {log_file_path}")