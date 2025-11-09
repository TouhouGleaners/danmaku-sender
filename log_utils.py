import time
import logging
import logging.handlers
from pathlib import Path
from datetime import datetime, timezone


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

        if record.name in ("SenderTab", "ValidatorTab", "DanmakuSender", "DanmakuParser", "BiliUtils"):
            target_func = self.output_targets.get("sender_tab")
        elif record.name == "MonitorTab":
            target_func = self.output_targets.get("monitor_tab")

        if not target_func:
            target_func = self.output_targets.get("sender_tab")
        if target_func:
            target_func(msg)


class DailyLogFileHandler(logging.handlers.TimedRotatingFileHandler):
    """
    自定义的 TimedRotatingFileHandler:
    - 当前活动日志文件名为 'latest.log'。
    - 轮转后的历史日志文件名为 'YYYY-MM-DD.log'。
    """
    def __init__(self, filename, when='midnight', interval=1, backupCount=0, encoding=None, delay=False, utc=False):
        super().__init__(filename, when, interval, backupCount, encoding, delay, utc)

    def _doRollover(self):
        """
        执行日志文件的轮转操作，并自定义旧文件的命名格式。
        这个方法会在每次满足轮转条件时被 TimedRotatingFileHandler 的内部机制调用。
        """
        current_time = int(time.time())
        if self.utc:
            dst_now = datetime.now(timezone.utc).timetuple()
        else:
            dst_now = datetime.now().timetuple()

        previous_rollover_time = self.rolloverAt - self.interval
        if self.utc:
            archive_datetime = datetime.fromtimestamp(previous_rollover_time, tz=timezone.utc)
        else:
            archive_datetime = datetime.fromtimestamp(previous_rollover_time)

        base_path = Path(self.baseFilename)
        archive_file_name_path = base_path.parent / f"{archive_datetime.strftime('%Y-%m-%d')}.log"
        archive_file_name_str = str(archive_file_name_path)

        if self.stream:
            self.stream.close()
            self.stream = None

        if archive_file_name_path.exists():
            try:
                archive_file_name_path.unlink()
                logging.debug(f"已删除旧的归档日志文件: {archive_file_name_str}")
            except OSError as e:
                logging.error(f"删除旧的归档日志文件失败: {archive_file_name_str}, 错误: {e}")

        if base_path.exists():
            try:
                base_path.rename(archive_file_name_path)
                logging.debug(f"已将 {self.baseFilename} 重命名为 {archive_file_name_str}")
            except OSError as e:
                logging.error(f"重命名日志文件失败: {self.baseFilename} -> {archive_file_name_str}, 错误: {e}")

        if self.backupCount > 0:
            log_dir_path = base_path.parent
            all_rotated_logs = []
            for entry_path in log_dir_path.iterdir():
                if entry_path.is_file() and entry_path.suffix == '.log':
                    file_name_stem = entry_path.stem
                    # 检查文件名是否符合 'YYYY-MM-DD' 格式 (长度为10)
                    if len(file_name_stem) == 10: 
                        try:
                            file_date = datetime.strptime(file_name_stem, '%Y-%m-%d')
                            all_rotated_logs.append((file_date, entry_path))
                        except ValueError:
                            continue

            all_rotated_logs.sort(key=lambda x: x[0])
            for i in range(len(all_rotated_logs) - self.backupCount):
                try:
                    all_rotated_logs[i][1].unlink()
                    logging.debug(f"已删除超出备份数量的旧日志文件: {all_rotated_logs[i][1]}")
                except OSError as e:
                    logging.error(f"删除旧日志文件失败: {all_rotated_logs[i][1]}, 错误: {e}")

        if not self.delay:
            self.stream = self._open()
            new_rollover_at = self.computeRollover(current_time)
        while new_rollover_at <= current_time:
            new_rollover_at += self.interval
        self.rolloverAt = new_rollover_at