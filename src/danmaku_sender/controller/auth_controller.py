import logging
import threading

from PySide6.QtCore import QObject, Signal, Slot

from danmaku_sender.config import ApiAuthConfig, NetworkPolicy, Settings
from danmaku_sender.infra.bilibili.bili_api_client import BiliApiClient
from danmaku_sender.service.auth_service import AuthService
from danmaku_sender.state import AppState
from danmaku_sender.types.models.user import UserProfile

from .concurrency import PoolTask, WorkerThread

logger = logging.getLogger(__name__)


class AuthController(QObject):
    """用户授权与身份控制器。"""

    userProfileReady = Signal(UserProfile)

    qrReady = Signal(str)
    qrStatusUpdated = Signal(str)
    qrLoginSucceeded = Signal(dict)
    qrLoginFailed = Signal(str)

    def __init__(self, state: AppState, settings: Settings, parent=None):
        """初始化控制器。

        Args:
            state: 状态树聚合根，取活动会话的身份凭据。
            settings: 配置容器，取传输策略。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.state = state
        self.settings = settings
        self._qr_worker: QRLoginWorker | None = None
        self._qr_stop_event = threading.Event()

    def refresh_user_info(self) -> None:
        """发起异步请求刷新用户信息。"""
        session = self.state.session
        if not session.sessdata:
            self.userProfileReady.emit(UserProfile(False, "未登录"))
            return

        auth = ApiAuthConfig(sessdata=session.sessdata, bili_jct=session.bili_jct)
        network = NetworkPolicy(use_system_proxy=self.settings.global_config.use_system_proxy)
        PoolTask.submit(
            self._task_fetch_profile,
            self.userProfileReady.emit,
            lambda _: self.userProfileReady.emit(UserProfile(False, "未登录")),
            auth, network,
        )

    def start_qr_login(self) -> None:
        """启动扫码登录后台任务。"""
        if self._qr_worker and self._qr_worker.isRunning():
            return

        self._qr_stop_event.clear()
        network = NetworkPolicy(use_system_proxy=self.settings.global_config.use_system_proxy)
        self._qr_worker = QRLoginWorker(network=network, stop_event=self._qr_stop_event)

        # 桥接信号
        self._qr_worker.qrReady.connect(self.qrReady.emit)
        self._qr_worker.statusUpdated.connect(self.qrStatusUpdated.emit)
        self._qr_worker.loginSucceeded.connect(self.qrLoginSucceeded.emit)
        self._qr_worker.loginFailed.connect(self.qrLoginFailed.emit)

        # 生命周期兜底
        self._qr_worker.finished.connect(self._on_qr_worker_cleanup)
        self._qr_worker.finished.connect(self._qr_worker.deleteLater)
        self._qr_worker.start()

    def stop_qr_login(self) -> None:
        """停止扫码登录。"""
        if self._qr_worker and self._qr_worker.isRunning():
            self._qr_stop_event.set()

    # region Slots

    @Slot()
    def _on_qr_worker_cleanup(self) -> None:
        """回收扫码登录 Worker 引用。"""
        if self._qr_worker is not None:
            logger.debug("QRLoginWorker 生命周期结束，清理控制器引用。")
            self._qr_worker = None

    # endregion

    # ---- 后台任务 ----

    def _task_fetch_profile(self, auth: ApiAuthConfig, network: NetworkPolicy) -> UserProfile:
        """获取用户信息（后台线程执行）。

        Args:
            auth: 身份凭据。
            network: 传输策略。

        Returns:
            用户资料。
        """
        with BiliApiClient(auth, network) as client:
            return AuthService(client).fetch_user_profile()


class QRLoginWorker(WorkerThread):
    """扫码登录后台轮询线程。"""

    qrReady = Signal(str)           # 携带生成的二维码文本 (URL)
    statusUpdated = Signal(str)     # 携带当前扫码状态文案
    loginSucceeded = Signal(dict)   # 携带成功后的 cookies 字典
    loginFailed = Signal(str)       # 携带失败原因

    def __init__(self, network: NetworkPolicy, stop_event: threading.Event, parent=None):
        """初始化扫码登录 Worker。

        Args:
            network: 传输策略。
            stop_event: 中止标记。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.network = network
        self.stop_event = stop_event
        self.logger = logging.getLogger(__name__)

    def run(self) -> None:
        """执行扫码登录轮询。"""
        try:
            auth = ApiAuthConfig(sessdata="", bili_jct="")
            with BiliApiClient(auth, self.network) as client:
                # 生成二维码
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
