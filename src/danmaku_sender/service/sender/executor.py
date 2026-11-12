"""弹幕发包执行器：单次发包并给出结论，等待与重试循环由调度器驱动。"""

import logging
from dataclasses import dataclass

from danmaku_sender.infra.bilibili.bili_api_client import BiliApiClient
from danmaku_sender.types.exceptions.api_errors import BiliDmErrorCode
from danmaku_sender.types.exceptions.exceptions import BiliApiError, BiliNetworkError
from danmaku_sender.types.models.common import VideoTarget
from danmaku_sender.types.models.danmaku import Danmaku
from danmaku_sender.types.models.result import BiliSendResponse


@dataclass(frozen=True)
class SendAttempt:
    """一次发包尝试的结论。

    Attributes:
        response (BiliSendResponse | None): 最终响应；按策略还可再试时为 None。
        retry_delay (float): 再试之前建议等待的秒数；没有最终响应时才使用。
    """

    response: BiliSendResponse | None = None
    retry_delay: float = 0.0

    def __post_init__(self) -> None:
        """校验结论完整：没有最终响应时，重试建议必须是正数。

        Raises:
            ValueError: 既无响应又无等待时长；调用方拿到会零等待空转。
        """
        if self.response is None and self.retry_delay <= 0:
            raise ValueError("没有最终响应时，retry_delay 必须为正数")


class DanmakuExecutor:
    """弹幕发包执行器：执行一次发包并给出重试建议，不做等待、不做重试。

    重试策略（最大重试次数、限流罚时、网络退避）在本类给出；等待与重试循环由调用方驱动。

    Attributes:
        MAX_RETRIES (int): 单条弹幕发包失败后的最大重试次数。
    """

    MAX_RETRIES = 3

    def __init__(self, api_client: BiliApiClient) -> None:
        """初始化执行器。

        Args:
            api_client (BiliApiClient): B 站接口客户端。
        """
        self.api_client = api_client
        self.logger = logging.getLogger(__name__)

    def send(self, target: VideoTarget, danmaku: Danmaku, attempt_no: int) -> SendAttempt:
        """执行一次发包并给出结论；不等待、不重试。

        Args:
            target (VideoTarget): 包含 cid 与 bvid 的视频目标。
            danmaku (Danmaku): 待发送的弹幕。
            attempt_no (int): 本条弹幕此前已失败的尝试次数；首次发包为 0。

        Returns:
            SendAttempt: 本次尝试的结论；还可再试时给出建议等待秒数。
        """
        try:
            return SendAttempt(response=self._post(target, danmaku))
        except BiliApiError as e:
            return self._api_error_attempt(e, attempt_no)
        except BiliNetworkError as e:
            return self._network_error_attempt(e, attempt_no)

    def _post(self, target: VideoTarget, danmaku: Danmaku) -> BiliSendResponse:
        """向接口发一次包；本方法不捕获异常。

        Args:
            target (VideoTarget): 包含 cid 与 bvid 的视频目标。
            danmaku (Danmaku): 待发送的弹幕。

        Returns:
            BiliSendResponse: 标准化的远端响应。
        """
        bvid, cid = target.bvid, target.cid
        if bvid is None or cid is None:
            raise ValueError("发包需要已指定的目标（bvid 与 cid 都在）")

        params = danmaku.to_api_params()
        resp_json = self.api_client.post_danmaku(cid, bvid, params)
        result = BiliSendResponse.from_api_json(resp_json)

        if result.is_success:
            self.logger.info(f"✅ 发送成功 [ID:{result.dmid}]: {danmaku.msg}")
        else:
            self.logger.warning(f"❌ 发送失败: {result.hint}")

        return result

    def _api_error_attempt(self, e: BiliApiError, attempt_no: int) -> SendAttempt:
        """按业务异常给出结论：非限流立即失败；限流在重试额度内建议罚时后再试。

        Args:
            e (BiliApiError): 业务异常。
            attempt_no (int): 本条弹幕此前已失败的尝试次数。

        Returns:
            SendAttempt: 本次尝试的结论。
        """
        if e.code != BiliDmErrorCode.FREQ_LIMIT.code:
            self.logger.error(f"❌ 请求被拒: {e.message}")
            return SendAttempt(response=BiliSendResponse(
                code=e.code, is_success=False, msg=e.message,
                hint=BiliDmErrorCode.from_code(e.code).description,
            ))

        if attempt_no >= self.MAX_RETRIES:
            self.logger.error(f"❌ 频繁触发风控，重试 {self.MAX_RETRIES} 次后放弃: {e.message}")
            return SendAttempt(response=BiliSendResponse(
                code=e.code, is_success=False, msg=e.message,
                hint=BiliDmErrorCode.from_code(e.code).description,
            ))

        self.logger.warning(f"⚠️ 触发风控限流！建议 10 秒后重试 ({attempt_no + 1}/{self.MAX_RETRIES})...")
        return SendAttempt(retry_delay=10.0)

    def _network_error_attempt(self, e: BiliNetworkError, attempt_no: int) -> SendAttempt:
        """按网络异常给出结论：重试额度内建议指数退避后再试，额度用尽则失败。

        Args:
            e (BiliNetworkError): 网络异常。
            attempt_no (int): 本条弹幕此前已失败的尝试次数。

        Returns:
            SendAttempt: 本次尝试的结论。
        """
        if attempt_no >= self.MAX_RETRIES:
            self.logger.error(f"❌ 网络异常! 重试 {self.MAX_RETRIES} 次后彻底失败: {e.message}")
            return SendAttempt(response=BiliSendResponse(
                code=BiliDmErrorCode.NETWORK_ERROR.code, is_success=False, msg=str(e),
                hint=BiliDmErrorCode.NETWORK_ERROR.description,
            ))

        delay = 2.0 * (2 ** attempt_no)  # 指数退避: 2s, 4s, 8s
        self.logger.warning(f"⚠️ 网络波动 ({e.message})。建议 {delay} 秒后重试 ({attempt_no + 1}/{self.MAX_RETRIES})...")
        return SendAttempt(retry_delay=delay)
