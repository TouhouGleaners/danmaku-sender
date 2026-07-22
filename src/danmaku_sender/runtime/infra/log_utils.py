import sys
import logging
import logging.handlers
from pathlib import Path
from datetime import datetime, timezone

from PySide6.QtCore import SignalInstance

from danmaku_sender.config.app_meta import AppInfo


class LogNamespace:
    """日志命名空间契约"""
    SENDER = "App.Sender"
    MONITOR = "App.Monitor"
    SYSTEM = "App.System"


class GuiLoggingHandler(logging.Handler):
    """基于命名空间前缀路由日志到 UI 窗口。

    回调约束: sender / monitor 信号必须是 Qt SignalInstance，
    以确保跨线程 emit 时自动排队到主线程，避免后台线程直接操作 UI。
    """
    def __init__(self):
        super().__init__()
        self._sender_signal: SignalInstance | None = None
        self._monitor_signal: SignalInstance | None = None

    @property
    def sender_signal(self) -> SignalInstance | None:
        return self._sender_signal

    @sender_signal.setter
    def sender_signal(self, signal: SignalInstance | None):
        if signal is not None and not isinstance(signal, SignalInstance):
            raise TypeError(
                f"sender_signal 必须是 SignalInstance，收到 {type(signal).__name__}。"
                "直接 UI 操作在后台线程调用会导致崩溃。"
            )
        self._sender_signal = signal

    @property
    def monitor_signal(self) -> SignalInstance | None:
        return self._monitor_signal

    @monitor_signal.setter
    def monitor_signal(self, signal: SignalInstance | None):
        if signal is not None and not isinstance(signal, SignalInstance):
            raise TypeError(
                f"monitor_signal 必须是 SignalInstance，收到 {type(signal).__name__}。"
                "直接 UI 操作在后台线程调用会导致崩溃。"
            )
        self._monitor_signal = signal

    def emit(self, record):
        """
        发出一条日志记录。

        该方法会处理日志记录，并根据日志器名称前缀，将其路由至对应的信号。
        它针对不同组件的日志做分流处理:
        来自 "App.Sender" 的日志，发送至 sender_signal
        来自 "App.Monitor" 的日志，发送至 monitor_signal
        来自 "App.System" 及其他来源的日志，将被忽略

        Args:
            record (logging.LogRecord)：待输出的日志记录对象。
        """
        try:
            text = self.format(record)
            if record.name.startswith(LogNamespace.SENDER) and self._sender_signal:
                self._sender_signal.emit(text)
            elif record.name.startswith(LogNamespace.MONITOR) and self._monitor_signal:
                self._monitor_signal.emit(text)
            # App.System 或其他开头的日志直接忽略
        except Exception:
            self.handleError(record)


class DailyLogFileHandler(logging.handlers.TimedRotatingFileHandler):
    """自定义日志轮转：YYYY-MM-DD.log"""
    def rotation_filename(self, filename: str) -> str:
        """重写父类的 rotation_filename 方法，以自定义归档文件的命名格式。"""
        # 计算归档日期，保持文件名如：2026-03-27.log
        previous_rollover_time = self.rolloverAt - self.interval
        if self.utc:
            archive_datetime = datetime.fromtimestamp(previous_rollover_time, tz=timezone.utc)
        else:
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
    logging.getLogger("peewee").setLevel(logging.WARNING)

    logging.info(f"日志系统初始化完成。日志路径: {log_file_path}")