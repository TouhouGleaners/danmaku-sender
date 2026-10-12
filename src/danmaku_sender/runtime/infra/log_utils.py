import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from danmaku_sender.config.app_meta import AppInfo


class LogNamespace:
    """日志命名空间契约（基于模块路径）"""
    SENDER_PREFIXES = ("danmaku_sender.service.sender", "danmaku_sender.ui.views.sender", "danmaku_sender.controller.sender")
    MONITOR_PREFIXES = ("danmaku_sender.controller.monitor", "danmaku_sender.ui.views.monitor")


class GuiLoggingHandler(QObject, logging.Handler):
    """基于命名空间前缀路由日志到 UI 窗口。

    信号是 Qt Signal，跨线程 emit 时自动排队到主线程，避免后台线程直接操作 UI。
    """

    senderLogReceived = Signal(str)
    monitorLogReceived = Signal(str)

    def __init__(self) -> None:
        """初始化处理器，同时启用 QObject 信号与 logging.Handler。"""
        QObject.__init__(self)
        logging.Handler.__init__(self)

    def emit(self, record):
        """
        发出一条日志记录。

        该方法会处理日志记录，并根据模块路径前缀路由至对应的信号:
        danmaku_sender.service.sender / danmaku_sender.ui.views.sender → senderLogReceived
        danmaku_sender.controller.monitor / danmaku_sender.ui.views.monitor → monitorLogReceived
        其他模块的日志将被忽略

        Args:
            record (logging.LogRecord)：待输出的日志记录对象。
        """
        try:
            text = self.format(record)
            if record.name.startswith(LogNamespace.SENDER_PREFIXES):
                self.senderLogReceived.emit(text)
            elif record.name.startswith(LogNamespace.MONITOR_PREFIXES):
                self.monitorLogReceived.emit(text)
            # 其他模块的日志直接忽略
        except Exception:
            self.handleError(record)


class DailyLogFileHandler(logging.handlers.TimedRotatingFileHandler):
    """自定义日志轮转：YYYY-MM-DD.log"""
    def rotation_filename(self, filename: str) -> str:
        """重写父类的 rotation_filename 方法，以自定义归档文件的命名格式。"""
        # 计算归档日期，保持文件名如：2026-03-27.log
        previous_rollover_time = self.rolloverAt - self.interval
        if self.utc:
            archive_datetime = datetime.fromtimestamp(previous_rollover_time, tz=UTC)
        else:
            archive_datetime = datetime.fromtimestamp(previous_rollover_time)
        base_path = Path(self.baseFilename)
        return str(base_path.parent / f"{archive_datetime.strftime('%Y-%m-%d')}.log")


def init_app_logging(log_dir: Path):
    """全局日志系统"""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = log_dir / AppInfo.LOG_FILE_NAME

    # --- 定义格式 ---
    # 文件和控制台: 详细格式 [时间] [线程/级别] [模块名]: 消息
    detailed_formatter = logging.Formatter(
        '[%(asctime)s] [%(threadName)s/%(levelname)s] [%(name)s]: %(message)s',
        datefmt='%H:%M:%S'
    )
    # GUI: 精简格式 [时间] [级别] 消息
    gui_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%H:%M:%S')

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
    logging.getLogger("keyring").setLevel(logging.WARNING)
    logging.getLogger("win32ctypes").setLevel(logging.WARNING)

    logging.info(f"日志系统初始化完成。日志路径: {log_file_path}")