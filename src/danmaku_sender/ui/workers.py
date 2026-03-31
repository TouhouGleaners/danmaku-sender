import logging
import threading

from PySide6.QtCore import Signal

from .framework.concurrency import BaseWorker

from ..core.engines.sender import DanmakuScheduler, DanmakuExecutor, SendingContext, SendJob
from ..core.engines.bili_monitor import BiliDanmakuMonitor
from ..core.database.history_manager import HistoryManager
from ..core.state import ApiAuthConfig, SenderConfig, MonitorConfig
from ..core.models.danmaku import Danmaku
from ..core.models.result import DanmakuSendResult
from ..core.models.structs import VideoTarget
from ..api.bili_api_client import BiliApiClient
from ..utils.system_utils import KeepSystemAwake


class SendTaskWorker(BaseWorker):
    """用于后台发送弹幕的线程"""
    progressUpdated = Signal(int, int)  # 已尝试, 总数
    taskFinished = Signal(object)       # SendingContext

    def __init__(
        self,
        target: VideoTarget,
        danmakus: list[Danmaku],
        auth_config: ApiAuthConfig,
        strategy_config: SenderConfig,
        stop_event: threading.Event,
        parent=None
    ):
        super().__init__(parent)
        self.logger = logging.getLogger("App.Sender.Worker")
        self.target = target
        self.danmakus = danmakus
        self.auth_config = auth_config
        self.strategy_config = strategy_config
        self.stop_event = stop_event
        self.sender_instance = None
        self.history_manager = HistoryManager()
        self.scheduler = None

    def run(self):
        ctx = None
        try:
            ctx = self._execute_pipeline()
        except Exception as e:
            self.report_error("任务发生严重错误", e)
        finally:
            if ctx:
                self._log_summary(ctx)
            self.taskFinished.emit(ctx)

    def _execute_pipeline(self):
        with (
            KeepSystemAwake(self.strategy_config.prevent_sleep),
            BiliApiClient.from_config(self.auth_config) as client
        ):
            executor = DanmakuExecutor(client)
            self.scheduler = DanmakuScheduler(executor, self.history_manager)

            job = SendJob(
                target=self.target,
                danmakus=self.danmakus,
                config=self.strategy_config,
                stop_event=self.stop_event,
                progress_callback=self._handle_job_progress,
                result_callback=self._handle_job_result
            )
            return self.scheduler.run_pipeline(job)

    def _handle_job_progress(self, attempted: int, total: int):
        self.progressUpdated.emit(attempted, total)

    def _handle_job_result(self, dm: Danmaku, result: DanmakuSendResult):
        if result.is_success and result.dmid:
            if not dm.dmid:
                dm.dmid = result.dmid
            self.history_manager.record_danmaku(self.target, dm, result.is_visible)

    def _log_summary(self, ctx: SendingContext):
        """日志输出"""
        self.logger.info("--- 发送任务结束 ---")
        if ctx.auto_stop_reason:
            self.logger.info(f"原因：{ctx.auto_stop_reason}")
        elif self.stop_event.is_set():
            self.logger.info("原因：任务被用户手动停止。")
        elif ctx.fatal_error_occurred:
            self.logger.critical("原因：任务因致命错误中断。请检查配置或网络！")
        else:
            self.logger.info("原因：所有弹幕已处理完毕。")

        self.logger.info(f"总计: {ctx.total} | 成功: {ctx.success_count} | 跳过: {ctx.skipped_count} | 失败: {ctx.attempted_count - ctx.success_count}")


class MonitorTaskWorker(BaseWorker):
    """监视任务后台线程"""
    statsUpdated = Signal(dict)
    statusUpdated = Signal(str)
    taskFinished = Signal()

    def __init__(
        self,
        target: VideoTarget,
        auth_config: ApiAuthConfig,
        monitor_config: MonitorConfig,
        stop_event: threading.Event,
        parent=None
    ):
        super().__init__(parent)
        self.logger = logging.getLogger("App.Monitor.Worker")
        self.target = target
        self.auth_config = auth_config
        self.monitor_config = monitor_config
        self.stop_event = stop_event

    def run(self):
        try:
            self._run_monitor_loop()
        except Exception as e:
            self.report_error("监视任务异常", e)
        finally:
            self.taskFinished.emit()

    def _run_monitor_loop(self):
        with (
            KeepSystemAwake(self.monitor_config.prevent_sleep),
            BiliApiClient.from_config(self.auth_config) as client
        ):
            monitor = BiliDanmakuMonitor(api_client=client, target=self.target)
            self.logger.info(f"🛡️ 监视启动: {self.target.display_string} | CID: {self.target.cid}")

            while not self.stop_event.is_set():
                self._execute_single_check(monitor)
                if self.stop_event.wait(self.monitor_config.refresh_interval):
                    self.logger.info("收到停止信号，监视任务终止。")
                    break

    def _execute_single_check(self, monitor: BiliDanmakuMonitor):
        snap_baseline = self.monitor_config.stats_baseline
        stats = monitor.monitor(stats_baseline=snap_baseline)

        self.statsUpdated.emit(stats)
        self.statusUpdated.emit(f"监视中 (存活: {stats['verified']})")

        msg = (
            f"监视中... 总计:{stats['total']} | "
            f"✅存活:{stats['verified']} | "
            f"⏳待验:{stats['pending']}"
        )
        if stats.get('lost', 0) > 0:
            msg += f" | ❌丢失:{stats['lost']}"

        self.logger.info(msg)


class QueryHistoryWorker(BaseWorker):
    """异步查询历史记录"""
    finished_success = Signal(list)  # 返回查询到的 records 列表

    def __init__(self, keyword: str, status_filter: int, parent=None):
        super().__init__(parent)
        self.keyword = keyword
        self.status_filter = status_filter
        self.history_manager = HistoryManager()

    def run(self):
        try:
            records = self.history_manager.query_history(self.keyword, self.status_filter)
            self.finished_success.emit(records)
        except Exception as e:
            self.report_error("查询历史失败", e)
            self.finished_success.emit([])


class QRLoginWorker(BaseWorker):
    """扫码登录后台轮询线程"""
    qrReady = Signal(str)           # 携带生成的二维码文本 (URL)
    statusUpdated = Signal(str)     # 携带当前扫码状态文案
    loginSucceeded = Signal(dict)   # 携带成功后的 cookies 字典
    loginFailed = Signal(str)       # 携带失败原因

    def __init__(self, use_system_proxy: bool, stop_event: threading.Event, parent=None):
        super().__init__(parent)
        self.use_system_proxy = use_system_proxy
        self.stop_event = stop_event  # Controller 传入

    def run(self):
        try:
            config = ApiAuthConfig(sessdata="", bili_jct="", use_system_proxy=self.use_system_proxy)

            with BiliApiClient.from_config(config) as client:
                # 申请二维码
                data = client.generate_qr_code()
                url = data.get('url')
                qrcode_key = data.get('qrcode_key')

                if not url or not qrcode_key:
                    self.loginFailed.emit("获取二维码失败：B站接口返回异常")
                    return

                # 通知 UI 渲染二维码
                self.qrReady.emit(url)
                self.statusUpdated.emit("请使用哔哩哔哩客户端扫码")

                # 开始轮询
                while not self.stop_event.is_set():
                    # 每次轮询等待 2 秒
                    if self.stop_event.wait(2.0):
                        self.logger.info("用户取消了扫码登录。")
                        break

                    # 发起轮询请求
                    status, cookies = client.poll_qr_code(qrcode_key)

                    if status == 0:
                        # 扫码且确认成功
                        self.loginSucceeded.emit(cookies)
                        break
                    elif status == 86090:
                        self.statusUpdated.emit("已扫码，请在手机端确认登录")
                    elif status == 86101:
                        pass  # 未扫码，继续等
                    elif status == 86038:
                        self.loginFailed.emit("二维码已失效，请关闭重试")
                        break
                    else:
                        self.loginFailed.emit(f"未知的状态码: {status}")
                        break

        except Exception as e:
            self.report_error("扫码登录环境异常", e)
            self.loginFailed.emit(f"网络异常: {e}")
        finally:
            self.logger.info("扫码轮询线程已退出。")