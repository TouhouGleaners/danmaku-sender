import logging
import logging.handlers
from pathlib import Path
from datetime import datetime, timezone


# Sender 相关日志源
SENDER_LOG_WHITELIST = (
    "SenderTab", 
    "DanmakuSender", 
    "DanmakuParser", 
    "BiliUtils", 
    "BiliApiClient", 
    "WbiSigner",
    "CredentialManager",
    "NotificationUtils",
    "UpdateChecker"
)

# Monitor 相关日志源
MONITOR_LOG_WHITELIST = (
    "MonitorTab",
    "DanmakuMonitor"
)


class GuiLoggingHandler(logging.Handler):
    """
    一个自定义的日志处理程序，将日志消息根据其来源路由到不同的GUI文本框。
    它通过检查日志记录的名称(record.name)来决定目标。
    """
    def __init__(self):
        super().__init__()
        # 存储不同日志目标的更新函数
        self.output_targets = {
            "sender_tab": None,
            "monitor_tab": None,
        }

    def emit(self, record):
        """根据 record.name 将日志消息发送到正确的GUI组件。"""
        msg = self.format(record)
        target_func = None

        if record.name in SENDER_LOG_WHITELIST:
            target_func = self.output_targets.get("sender_tab")
        elif record.name in MONITOR_LOG_WHITELIST:
            target_func = self.output_targets.get("monitor_tab")

        # 请注意：
        # 如果 record.name 不在上述任何白名单中（例如 ValidatorTab），
        # target_func 将保持为 None。这意味着该日志会被静默丢弃（不显示在 GUI），
        # 但依然会被 FileHandler 写入日志文件。这是有意为之的设计。

        if target_func:
            target_func(msg)


class DailyLogFileHandler(logging.handlers.TimedRotatingFileHandler):
    """
    自定义的 TimedRotatingFileHandler:
    - 当前活动日志文件名为 'latest.log'。
    - 轮转后的历史日志文件名为 'YYYY-MM-DD.log'。
    通过重写 `rotation_filename` 方法来实现定制化的文件名。
    父类的 `_doRollover` 会自动调用 `rotation_filename`。
    """
    def __init__(self, filename, when='midnight', interval=1, backupCount=0, encoding=None, delay=False, utc=False):
        super().__init__(filename, when, interval, backupCount, encoding, delay, utc)

    def rotation_filename(self, filename: str) -> str:
        """
        重写父类的 rotation_filename 方法，以自定义归档文件的命名格式。
        这个方法会由父类的 `_doRollover` 调用。
        """
        previous_rollover_time = self.rolloverAt - self.interval  # 当前文件完成写入，即将被归档的时间点
        # 根据 UTC 设置获取日期
        if self.utc:
            archive_datetime = datetime.fromtimestamp(previous_rollover_time, tz=timezone.utc)
        else:
            archive_datetime = datetime.fromtimestamp(previous_rollover_time)
        
        # 构造形如'YYYY-MM-DD.log'的文件名
        base_path = Path(self.baseFilename)
        archive_name = f"{archive_datetime.strftime('%Y-%m-%d')}.log"
        desired_archive_file_path = base_path.parent / archive_name
        
        return str(desired_archive_file_path)