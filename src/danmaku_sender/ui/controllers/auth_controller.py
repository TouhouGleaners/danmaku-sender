import logging
import threading

from PySide6.QtCore import QObject, Signal, QThreadPool, Slot

from ..framework.concurrency import BaseWorker, GenericTask

from ...api.bili_api_client import BiliApiClient
from ...core.state import ApiAuthConfig
from ...core.models.user import UserProfile


logger = logging.getLogger("App.System.Auth")


def _fetch_user_nav(auth_config: ApiAuthConfig) -> UserProfile:
    with BiliApiClient.from_config(auth_config) as client:
        try:
            # 用户信息
            nav_data = client.get_user_info()

            if not nav_data.get('isLogin'):
                return UserProfile(is_login=False, username="未登录")

            username = nav_data.get('uname', "未知用户")
            face_url = nav_data.get('face', "")

            # 下载头像
            avatar_data = b""
            if face_url:
                try:
                    avatar_data = client.get_raw_resource(face_url)
                except Exception as e:
                    logger.warning(f"下载头像失败 [URL: {face_url}]", exc_info=True)

            return UserProfile(is_login=True, username=username, avatar_bytes=avatar_data)

        except Exception as e:
            # 主流程失败
            logger.error(f"同步获取用户信息任务崩溃: {e}", exc_info=True)
            raise


class AuthController(QObject):
    """用户授权与身份控制器"""
    userProfileReady = Signal(UserProfile)

    qrReady = Signal(str)
    qrStatusUpdated = Signal(str)
    qrLoginSucceeded = Signal(dict)
    qrLoginFailed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._qr_worker: QRLoginWorker | None = None
        self._qr_stop_event = threading.Event()

    def refresh_user_info(self, auth_config: ApiAuthConfig):
        """发起异步请求刷新用户信息"""
        if not auth_config.sessdata:
            self.userProfileReady.emit(UserProfile(False, "未登录"))
            return

        task = GenericTask(_fetch_user_nav, auth_config)
        task.signals.result.connect(self.userProfileReady.emit)

        task.signals.error.connect(lambda _: self.userProfileReady.emit(UserProfile(False, "未登录")))
        QThreadPool.globalInstance().start(task)

    def start_qr_login(self, use_system_proxy: bool):
        """启动扫码登录后台任务"""
        if self._qr_worker and self._qr_worker.isRunning():
            return

        self._qr_stop_event.clear()

        self._qr_worker = QRLoginWorker(
            use_system_proxy=use_system_proxy,
            stop_event=self._qr_stop_event
        )

        # 桥接信号
        self._qr_worker.qrReady.connect(self.qrReady.emit)
        self._qr_worker.statusUpdated.connect(self.qrStatusUpdated.emit)
        self._qr_worker.loginSucceeded.connect(self.qrLoginSucceeded.emit)
        self._qr_worker.loginFailed.connect(self.qrLoginFailed.emit)

        # 生命周期兜底
        self._qr_worker.finished.connect(self._on_qr_worker_cleanup)
        self._qr_worker.finished.connect(self._qr_worker.deleteLater)
        self._qr_worker.start()

    def stop_qr_login(self):
        """停止扫码登录"""
        if self._qr_worker and self._qr_worker.isRunning():
            self._qr_stop_event.set()


    # region Slots

    @Slot()
    def _on_qr_worker_cleanup(self):
        """垃圾回收机制"""
        if self._qr_worker is not None:
            logger.debug("QRLoginWorker 生命周期结束，清理控制器引用。")
            self._qr_worker = None

    # endregion


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
        self.logger = logging.getLogger("App.Auth.QRWorker")

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