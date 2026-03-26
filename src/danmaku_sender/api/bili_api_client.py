import logging
from typing import Any, Generator, Protocol
from contextlib import contextmanager

import requests
from requests.exceptions import ConnectionError, HTTPError, RequestException, Timeout

from .wbi_signer import WbiSigner

from ..core.models.exceptions import BiliNetworkError, BiliApiError
from ..core.models.errors import BiliDmErrorCode


class BiliConfigProto(Protocol):
    sessdata: str
    bili_jct: str
    use_system_proxy: bool


class BiliApiClient:
    """
    一个专门用于与Bilibili API交互的客户端。
    封装了会话管理、WBI签名、请求发送和底层错误处理。
    """
    BASE_HEADER = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.bilibili.com/'
    }
    def __init__(self, sessdata: str, bili_jct: str, use_system_proxy: bool, logger: logging.Logger | None = None):
        self.sessdata = sessdata
        self.bili_jct = bili_jct
        self.use_system_proxy = use_system_proxy
        self.logger = logger if logger else logging.getLogger("App.System.API")
        self.session = self._create_session()

        try:
            self.wbi_keys = WbiSigner.get_wbi_keys()
        except RuntimeError as e:
            raise BiliApiError(
                code=BiliDmErrorCode.BILI_SERVER_ERROR.code,
                message=f"获取WBI签名密钥失败: {e}"
            ) from e

    @classmethod
    def from_config(cls, config: BiliConfigProto, logger: logging.Logger | None = None):
        """
        工厂方法：直接从配置对象创建实例。
        鸭子类型：只要 config 对象里有 sessdata, bili_jct, use_system_proxy 属性即可。
        """
        return cls(
            sessdata=config.sessdata,
            bili_jct=config.bili_jct,
            use_system_proxy=config.use_system_proxy,
            logger=logger
        )

    def _create_session(self) -> requests.Session:
        """创建一个配置好 Headers 和 Cookies 的 requests.Session 对象"""
        session = requests.Session()
        session.headers.update(self.BASE_HEADER)

        if self.sessdata and self.bili_jct:
            session.cookies.update({
                'SESSDATA': self.sessdata,
                'bili_jct': self.bili_jct
            })

        if not self.use_system_proxy:
            self.logger.info("用户已关闭系统代理选项，将强制直连。")
            session.trust_env = False
            session.proxies = {}
        return session

    def close(self):
        """关闭会话"""
        if self.session:
            self.logger.debug("Closing BiliApiClient session.")
            self.session.close()

    def __enter__(self):
        self.logger.debug("BiliApiClient session entered.")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.logger.debug("Exiting BiliApiClient session context.")
        self.close()

    @contextmanager
    def _network_guards(self, url: str) -> Generator[None, None, None]:
        """
        统一的网络异常捕获上下文。
        负责将 requests 的各种异常精准映射为 BiliApiError | BiliNetworkError。
        """
        try:
            yield

        except Timeout as e:
            self.logger.error(f"请求超时: {url}, Error: {e}")
            raise BiliNetworkError(f"请求超时: {e}") from e

        except ConnectionError as e:
            self.logger.error(f"连接失败: {url}, Error: {e}")
            raise BiliNetworkError(f"网络连接断开: {e}") from e

        except HTTPError as e:
            if e.response is None:
                # 未收到任何 HTTP 响应，可能是连接在 HTTP 层之前就被中断
                self.logger.error(f"HTTP异常: {url}, 未收到服务器响应数据")
                raise BiliNetworkError("服务器未响应，请检查代理或网络环境") from e

            status_code = e.response.status_code
            # 捕获 Body 前 200 字符用于排查
            try:
                body_sample = e.response.text[:200].replace("\n", "\\n")
            except Exception:
                body_sample = "无法读取Body"

            diag_info = f"Status: {status_code}, Body: {body_sample}"
            self.logger.error(f"HTTP协议错误: {url}, {diag_info}")

            if 500 <= status_code < 600:
                raise BiliNetworkError(f"B站服务器暂时不可用 ({diag_info})") from e
            elif status_code == 403:
                # 403 明确是权限/爬虫封禁
                raise BiliNetworkError(f"请求被拒绝 (HTTP 403)，{diag_info}") from e
            else:
                # 其他 4xx 映射到协议冲突
                raise BiliNetworkError(f"通讯协议错误 ({diag_info})") from e

        except RequestException as e:
            self.logger.error(f"请求发生非预期异常: {url}, Error: {e}")
            raise BiliNetworkError(f"请求异常: {e}") from e

        except (ValueError, UnicodeDecodeError) as e:
            self.logger.error(f"响应内容解析失败: {url}, Error: {e}")
            raise BiliApiError(code=BiliDmErrorCode.RESPONSE_MALFORMED.code,message=f"服务器响应格式无法解析: {e}") from e

    def _request(self, method: str, url: str, return_raw: bool = False, **kwargs) -> Any:
        """
        通用的JSON API请求方法。
        return_raw=True 时返回完整 JSON，不抛出业务异常（用于发送接口）。
        """
        kwargs.setdefault('timeout', 10)

        with self._network_guards(url):
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            data: dict = response.json()

            if return_raw:
                return data

            # 标准模式：自动拆包，有错误码直接抛异常
            code = data.get('code', BiliDmErrorCode.RESPONSE_MALFORMED.code)
            if code == BiliDmErrorCode.SUCCESS.code:
                return data.get('data', {})
            else:
                message = data.get('message', '未知错误')
                self.logger.warning(f"API请求失败: {url}, Code: {code}, Message: {message}")
                raise BiliApiError(code=code, message=message)

    def get_raw_resource(self, url: str) -> bytes:
        """通用的二进制资源获取方法"""
        with self._network_guards(url):
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.content

    def get_video_info(self, bvid: str) -> dict:
        """根据BVID获取视频详细信息"""
        url = "https://api.bilibili.com/x/web-interface/view"
        params = {'bvid': bvid}
        self.logger.info(f"正在获取视频信息: {bvid}")
        return self._request('GET', url, params=params)

    def get_user_info(self) -> dict:
        """
        获取当前登录用户的信息 (昵称、头像、登录状态等)
        对应接口：/x/web-interface/nav
        """
        url = "https://api.bilibili.com/x/web-interface/nav"
        return self._request('GET', url)

    def get_danmaku_list_xml(self, cid: int) -> str:
        """获取指定CID的线上实时弹幕XML内容"""
        url = f"https://api.bilibili.com/x/v1/dm/list.so?oid={cid}"

        with self._network_guards(url):
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.content.decode('utf-8')

    def post_danmaku(self, cid: int, bvid: str, danmaku_params: dict) -> dict:
        """发送单条弹幕"""
        if not (self.sessdata and self.bili_jct):
            raise BiliApiError(code=-101, message="发送弹幕需要登录凭证")

        url = "https://api.bilibili.com/x/v2/dm/post"
        img_key, sub_key = self.wbi_keys
        final_params = danmaku_params.copy()

        final_params.update({
            'oid': cid,
            'bvid': bvid,
            'csrf': self.bili_jct
        })

        signed_params = WbiSigner.enc_wbi(params=final_params, img_key=img_key, sub_key=sub_key)

        return self._request('POST', url, data=signed_params, return_raw=True)

    def generate_qr_code(self) -> dict:
        """
        获取 Web 端扫码登录的二维码 URL 和秘钥

        Returns:
            dict: 包含 'url' (二维码内容) 和 'qrcode_key' (轮询凭证)
        """
        url = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
        self.logger.info("正在请求B站扫码登录凭证...")
        return self._request('GET', url)

    def poll_qr_code(self, qrcode_key: str) -> tuple[int, dict]:
        """
        轮询二维码状态
        Args:
            qrcode_key: generate_qr_code 返回的秘钥
        Returns:
            tuple[int, dict]: (状态码, cookies字典)
            状态码: 0-成功, 86038-失效, 86090-已扫码未确认, 86101-未扫码
        """
        url = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
        params = {'qrcode_key': qrcode_key}

        data: dict = self._request('GET', url, params=params)

        poll_status = data.get('code', -1)
        cookies = {}

        if poll_status == 0:
            cookies = self.session.cookies.get_dict()
            self.logger.info("✅ 扫码登录成功！已获取 Cookie。")

        return poll_status, cookies