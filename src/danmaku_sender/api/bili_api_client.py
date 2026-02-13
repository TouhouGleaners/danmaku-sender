import logging
from typing import Any, Generator, Protocol
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
    def __init__(self, sessdata: str, bili_jct: str, use_system_proxy: bool, logger: logging.Logger | None = None):
        if not all([sessdata, bili_jct]):
            raise ValueError("SESSDATA 和 BILI_JCT 不能为空")
        
        self.sessdata = sessdata
        self.bili_jct = bili_jct
        self.use_system_proxy = use_system_proxy
        self.logger = logger if logger else logging.getLogger("BiliApiClient")
        self.session = self._create_session()

        try:
            self.wbi_keys = WbiSigner.get_wbi_keys()
        except RuntimeError as e:
            self.logger.critical(f"WBI密钥获取失败: {e}")
            raise BiliApiException(code=-1, message=f"获取WBI签名密钥失败: {e}") from e

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

        except (ValueError, UnicodeDecodeError) as e:
            self.logger.error(f"响应解码失败: {url}")
            raise BiliApiException(
                code=BiliDmErrorCode.PARSE_ERROR.code,
                message=f"响应数据格式错误: {e}",
                is_network_error=False
            ) from e

        except RequestException as e:
            self.logger.error(f"请求异常: {url}, Error: {e}")
            raise BiliApiException(
                code=BiliDmErrorCode.NETWORK_ERROR.code,
                message=f"请求发生异常: {e}",
                is_network_error=True
            ) from e
        
    def _request(self, method: str, url: str, return_raw: bool = False, **kwargs) -> Any:
        """
        通用的JSON API请求方法。
        return_raw=True 时返回完整 JSON，不抛出业务异常（用于发送接口）。
        """
        kwargs.setdefault('timeout', 10)

        with self._network_guards(url):
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            data = response.json()

            if return_raw:
                return data

            # 标准模式：自动拆包，有错误码直接抛异常
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

    def post_danmaku(self, cid: int, bvid: str, danmaku_params: dict) -> dict:
        """发送单条弹幕"""
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