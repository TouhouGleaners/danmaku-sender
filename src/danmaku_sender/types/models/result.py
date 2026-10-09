from dataclasses import dataclass
from enum import Enum

from danmaku_sender.types.exceptions.api_errors import BiliDmErrorCode


@dataclass(frozen=True)
class BiliSendResponse:
    """B 站发包的底层响应：远端业务状态与回执。

    Attributes:
        code (int): B 站返回码。
        is_success (bool): 远端是否接受。
        msg (str): B 站原话。
        hint (str): 错误码描述，用作 UI 提示。
        dmid (str): 弹幕身份，接受时才有。
        is_visible (bool): API 是否回执可见。
    """
    code: int
    is_success: bool
    msg: str
    hint: str
    dmid: str = ""
    is_visible: bool = True

    @property
    def is_fatal(self) -> bool:
        """错误码是否为致命错误。

        Returns:
            bool: 致命返回 True。
        """
        return BiliDmErrorCode.from_code(self.code).is_fatal

    @classmethod
    def from_api_json(cls, response_json: dict) -> "BiliSendResponse":
        """从 API JSON 响应构建。

        Args:
            response_json (dict): B 站返回的 JSON。

        Returns:
            BiliSendResponse: 底层响应。
        """
        code = response_json.get('code', BiliDmErrorCode.RESPONSE_MALFORMED.code)
        msg = str(response_json.get('message', '')).strip()

        err_enum = BiliDmErrorCode.from_code(code)

        # 如果我们定义了该错误，hint 用字典描述；否则 hint 透传B站原话
        if err_enum != BiliDmErrorCode.BILI_UNKNOWN_ERROR:
            hint = err_enum.description
        else:
            hint = msg if msg else err_enum.description

        dmid, visible = "", True
        if code == BiliDmErrorCode.SUCCESS.code:
            data = response_json.get('data', {})
            if isinstance(data, dict):
                dmid = str(data.get('dmid_str', data.get('dmid', '')))
                visible = data.get('visible', True)

        return cls(
            code=code,
            is_success=code == BiliDmErrorCode.SUCCESS.code,
            msg=msg,
            hint=hint,
            dmid=dmid,
            is_visible=visible,
        )


class SendStatus(Enum):
    """单条弹幕的处理结论。

    Attributes:
        SUCCESS (str): 远端成功且本地已存证。
        DEGRADED (str): 远端成功但本地存证失败。
        FAILED (str): 未发出。
    """
    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True)
class DanmakuSendResult:
    """单条弹幕的业务处理结果。

    Attributes:
        status (SendStatus): 处理结论。
        response (BiliSendResponse): 远端响应。
        storage_error (str | None): 本地存证失败的原因。
    """
    status: SendStatus
    response: BiliSendResponse
    storage_error: str | None = None

    @property
    def is_posted(self) -> bool:
        """是否已物理发出。

        Returns:
            bool: 发出返回 True。
        """
        return self.status in (SendStatus.SUCCESS, SendStatus.DEGRADED)

    @property
    def is_accounted(self) -> bool:
        """是否已入账可核销。

        Returns:
            bool: 已入账返回 True。
        """
        return self.status is SendStatus.SUCCESS

    @property
    def is_fatal(self) -> bool:
        """远端错误是否为致命错误。

        Returns:
            bool: 致命返回 True。
        """
        return self.response.is_fatal
