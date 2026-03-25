from dataclasses import dataclass

from .errors import BiliDmErrorCode
from .exceptions import BiliNetworkError


@dataclass
class DanmakuSendResult:
    """封装弹幕发送结果"""
    code: int
    is_success: bool
    raw_message: str
    display_message: str
    dmid: str = ""  # data.dmid_str
    is_visible: bool = True

    @classmethod
    def from_api_response(cls, response_json: dict) -> 'DanmakuSendResult':
        """从 API JSON 响应构建结果对象"""
        code = response_json.get('code', BiliDmErrorCode.BILI_UNKNOWN_ERROR.code)
        raw_msg = str(response_json.get('message', '无原始错误信息'))

        if code == BiliDmErrorCode.SUCCESS.code:
            data_obj = response_json.get('data', {})
            dmid = ""
            visible = True
            if isinstance(data_obj, dict):
                dmid = str(data_obj.get('dmid_str', data_obj.get('dmid', '')))
                visible = data_obj.get('visible', True)

            return cls(
                code=0,
                is_success=True,
                raw_message="成功", 
                display_message=BiliDmErrorCode.SUCCESS.description, 
                dmid=dmid,
                is_visible=visible
            )

        enum_err = BiliDmErrorCode.from_code(code)
        display_msg = enum_err.description if enum_err else raw_msg

        return cls(code=code, is_success=False, raw_message=raw_msg, display_message=display_msg)

    @classmethod
    def from_network_error(cls, exc: BiliNetworkError) -> 'DanmakuSendResult':
        """将物理网络崩溃，转换为失败 Result"""
        return cls(
            code=BiliDmErrorCode.NETWORK_ERROR.code,
            is_success=False,
            raw_message=str(exc),
            display_message=BiliDmErrorCode.NETWORK_ERROR.description
        )

    @property
    def is_fatal(self) -> bool:
        return BiliDmErrorCode.from_code(self.code).is_fatal