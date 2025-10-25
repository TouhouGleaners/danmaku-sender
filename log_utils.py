import logging


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