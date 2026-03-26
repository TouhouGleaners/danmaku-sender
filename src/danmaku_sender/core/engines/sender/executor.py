import logging

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

    def execute(self, target: VideoTarget, danmaku: Danmaku) -> DanmakuSendResult:
        """
        执行单次发送，并内聚处理所有底层的 HTTP / 业务异常

        Args:
            target(VideoTarget): 包含 cid 和 bvid 的视频目标
            danmaku(Danmaku): 待发送的实体数据

        Returns:
            DanmakuSendResult: 标准化的结果实体。
        """
        try:
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

        except BiliNetworkError as e:
            self.logger.error(f"❌ 网络传输异常! 内容: '{danmaku.msg}', 错误: {e.message}")
            return DanmakuSendResult(
                code=BiliDmErrorCode.NETWORK_ERROR.code,
                is_success=False,
                msg=str(e),
                hint=BiliDmErrorCode.NETWORK_ERROR.description
            )

        except BiliApiError as e:
            self.logger.error(f"❌ 请求构造被拒: {e.message}")
            return DanmakuSendResult(
                code=e.code,
                is_success=False,
                msg=e.message,
                hint=BiliDmErrorCode.from_code(e.code).description
            )