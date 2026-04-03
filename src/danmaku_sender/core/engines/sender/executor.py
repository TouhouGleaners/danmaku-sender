import logging
from threading import Event

from ....api.bili_api_client import BiliApiClient
from ...models.danmaku import Danmaku
from ...models.structs import VideoTarget
from ...models.result import DanmakuSendResult
from ...models.exceptions import BiliApiError, BiliNetworkError
from ...models.errors import BiliDmErrorCode


class DanmakuExecutor:
    """
    弹幕发送执行器 (Executor)

    网络发包层。剥离了所有与“业务流转”、“耗时计算”相关的逻辑。
    职责：接收一条弹幕 -> 请求 B 站 API -> 标准化返回结果。
    """
    def __init__(self, api_client: BiliApiClient):
        self.api_client = api_client
        self.logger = logging.getLogger("App.Sender.Executor")

    def execute(self, target: VideoTarget, danmaku: Danmaku, stop_event: Event) -> DanmakuSendResult:
        """
        执行单次发送，并内聚处理所有底层的 HTTP / 业务异常, 提供重试

        Args:
            target(VideoTarget): 包含 cid 和 bvid 的视频目标
            danmaku(Danmaku): 待发送的实体数据
            stop_event(Event): 发送过程中可监听的中断事件

        Returns:
            DanmakuSendResult: 标准化的结果实体。
        """
        attempt = 0
        max_retries = 3

        while True:
            try:
                return self._send(target, danmaku)

            except BiliApiError as e:
                # 业务异常: 若返回结果则终止；若返回 None 则代表休眠完毕，继续重试
                if result := self._handle_api_error(e, attempt, max_retries, stop_event):
                    return result

            except BiliNetworkError as e:
                # 网络异常: 若返回结果则终止；若返回 None 则代表休眠完毕，继续重试
                if result := self._handle_network_error(e, attempt, max_retries, stop_event):
                    return result

            attempt += 1

    def _send(self, target: VideoTarget, danmaku: Danmaku) -> DanmakuSendResult:
        """内部发包: 不捕获异常"""
        params = danmaku.to_api_params()
        resp_json = self.api_client.post_danmaku(target.cid, target.bvid, params)
        result = DanmakuSendResult.from_api_response(resp_json)

        if result.is_success:
            # 若 B 站 API 返回了 DMID，则回填给内存对象
            if result.dmid:
                danmaku.dmid = result.dmid
            self.logger.info(f"✅ 发送成功 [ID:{result.dmid}]: {danmaku.msg}")
        else:
            self.logger.warning(f"❌ 发送失败: {result.hint}")

        return result

    def _handle_api_error(self, e: BiliApiError, attempt: int, max_retries: int, stop_event: Event) -> DanmakuSendResult | None:
        """
        处理业务异常

        非限流错误直接阻断 | 限流错误给予固定罚时重试
        """
        if e.code != BiliDmErrorCode.FREQ_LIMIT.code:
            self.logger.error(f"❌ 请求被拒: {e.message}")
            return DanmakuSendResult(
                code=e.code,
                is_success=False,
                msg=e.message,
                hint=BiliDmErrorCode.from_code(e.code).description
            )

        if attempt >= max_retries:
            self.logger.error(f"❌ 频繁触发风控，重试 {max_retries} 次后放弃: {e.message}")
            return DanmakuSendResult(
                code=e.code,
                is_success=False,
                msg=e.message,
                hint=BiliDmErrorCode.from_code(e.code).description
            )

        delay = 10.0
        self.logger.warning(f"⚠️ 触发风控限流！进入 {delay} 秒惩罚等待 ({attempt + 1}/{max_retries})...")
        return self._sleep_with_interrupt(delay, stop_event)

    def _handle_network_error(self, e: BiliNetworkError, attempt: int, max_retries: int, stop_event: Event) -> DanmakuSendResult | None:
        """
        处理物理网络异常

        基于指数退避计算重试延迟
        """
        if attempt >= max_retries:
            self.logger.error(f"❌ 网络异常! 重试 {max_retries} 次后彻底失败: {e.message}")
            return DanmakuSendResult(
                code=BiliDmErrorCode.NETWORK_ERROR.code,
                is_success=False,
                msg=str(e),
                hint=BiliDmErrorCode.NETWORK_ERROR.description
            )

        delay = 2.0 * (2 ** attempt)  # 指数退避: 2s, 4s, 8s
        self.logger.warning(f"⚠️ 网络波动 ({e.message})。将在 {delay} 秒后重试 ({attempt + 1}/{max_retries})...")
        return self._sleep_with_interrupt(delay, stop_event)

    def _sleep_with_interrupt(self, delay: float, stop_event: Event) -> DanmakuSendResult | None:
        """
        支持中断的休眠器

        如果被人工打断，返回终止结果；否则返回 None 以继续流转
        """
        if stop_event.wait(delay):
            self.logger.info("重试等待期间接收到停止指令，放弃发送。")
            return DanmakuSendResult(
                code=BiliDmErrorCode.CLIENT_RUNTIME_ERROR.code,
                is_success=False,
                msg="用户中断",
                hint="发送任务已被手动停止"
            )
        return None