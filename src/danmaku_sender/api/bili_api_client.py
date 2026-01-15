import time
import logging
from typing import Generator, Protocol
from contextlib import contextmanager

import requests
from requests.exceptions import ConnectionError, HTTPError, RequestException, Timeout

from .wbi_signer import WbiSigner

from ..core.exceptions import BiliApiException
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
    def __init__(self, sessdata: str, bili_jct: str, use_system_proxy: bool):
        if not all([sessdata, bili_jct]):
            raise ValueError("SESSDATA 和 BILI_JCT 不能为空")
        
        self.sessdata = sessdata
        self.bili_jct = bili_jct
        self.use_system_proxy = use_system_proxy
        self.logger = logging.getLogger("BiliApiClient")
        self.session = self._create_session()

        try:
            self.wbi_keys = WbiSigner.get_wbi_keys()
        except RuntimeError as e:
            self.logger.critical(f"WBI密钥获取失败: {e}")
            raise BiliApiException(code=-1, message=f"获取WBI签名密钥失败: {e}") from e

    @classmethod
    def from_config(cls, config: BiliConfigProto):
        """
        工厂方法：直接从配置对象创建实例。
        鸭子类型：只要 config 对象里有 sessdata, bili_jct, use_system_proxy 属性即可。
        """
        return cls(
            sessdata=config.sessdata,
            bili_jct=config.bili_jct,
            use_system_proxy=config.use_system_proxy
        )

    def _create_session(self) -> requests.Session:
        """创建一个配置好 Headers 和 Cookies 的 requests.Session 对象"""
        session = requests.Session()
        session.headers.update(self.BASE_HEADER)
        session.cookies.update({
            'SESSDATA': self.sessdata,
            'bili_jct': self.bili_jct
        })

        if not self.use_system_proxy:
            self.logger.info("用户已关闭系统代理选项，将强制直连。")
            session.trust_env = False
            session.proxies = {"http": None, "https": None}
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
        负责将 requests 的各种异常精准映射为 BiliApiException。
        """
        try:
            yield
        except Timeout as e:
            self.logger.error(f"请求超时: {url}, Error: {e}")
            raise BiliApiException(
                code=BiliDmErrorCode.TIMEOUT_ERROR.code,
                message=f"请求超时: {e}",
                is_network_error=True
            ) from e

        except ConnectionError as e:
            self.logger.error(f"连接失败: {url}, Error: {e}")
            raise BiliApiException(
                code=BiliDmErrorCode.CONNECTION_ERROR.code,
                message=f"网络连接断开: {e}",
                is_network_error=True
            ) from e

        except HTTPError as e:
            status_code = e.response.status_code if e.response is not None else "Unknown"
            self.logger.error(f"HTTP错误: {url}, Status: {status_code}")
            raise BiliApiException(
                code=BiliDmErrorCode.HTTP_ERROR.code,
                message=f"HTTP协议错误: {e}",
                is_network_error=True
            ) from e

        except RequestException as e:
            self.logger.error(f"请求异常: {url}, Error: {e}")
            raise BiliApiException(
                code=BiliDmErrorCode.NETWORK_ERROR.code,
                message=f"请求发生异常: {e}",
                is_network_error=True
            ) from e
        
    def _request(self, method: str, url: str, **kwargs) -> dict:
        """
        通用的JSON API请求方法，包含错误处理逻辑。
        成功时返回API响应中的 'data' 字段内容，失败时抛出 BiliApiException。
        """
        kwargs.setdefault('timeout', 10)

        with self._network_guards(url):
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()

            try:
                data = response.json()
            except ValueError as e:
                self.logger.error(f"JSON解码失败: {url}, Response: {response.text[:100]}")
                raise BiliApiException(
                    code=BiliDmErrorCode.PARSE_ERROR.code,
                    message=f"无法解析服务器响应: {e}",
                    is_network_error=False
                ) from e

            code = data.get('code', BiliDmErrorCode.GENERIC_FAILURE.code)
            if code == BiliDmErrorCode.SUCCESS.code:
                return data.get('data', {})
            else:
                message = data.get('message', '未知错误')
                self.logger.warning(f"API请求失败: {url}, Code: {code}, Message: {message}")
                raise BiliApiException(code=code, message=message)

    def get_video_info(self, bvid: str) -> dict:
        """根据BVID获取视频详细信息"""
        url = "https://api.bilibili.com/x/web-interface/view"
        params = {'bvid': bvid}
        self.logger.info(f"正在获取视频信息: {bvid}")
        return self._request('GET', url, params=params)

    def get_danmaku_list_xml(self, cid: int) -> str:
        """获取指定CID的线上实时弹幕XML内容"""
        url = f"https://api.bilibili.com/x/v1/dm/list.so?oid={cid}"

        with self._network_guards(url):
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.content.decode('utf-8')

    def post_danmaku(self, cid: int, bvid: str, danmaku: dict) -> dict:
        """发送单条弹幕"""
        url = "https://api.bilibili.com/x/v2/dm/post"
        img_key, sub_key = self.wbi_keys
        base_params = {
            'type': '1', 'oid': cid, 'msg': danmaku['msg'], 'bvid': bvid,
            'progress': danmaku['progress'], 'mode': danmaku['mode'],
            'fontsize': danmaku['fontsize'], 'color': danmaku['color'],
            'pool': '0', 'rnd': int(time.time()), 'csrf': self.bili_jct
        }

        signed_params = WbiSigner.enc_wbi(params=base_params, img_key=img_key, sub_key=sub_key)

        return self._request('POST', url, data=signed_params)