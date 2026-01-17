from dataclasses import dataclass

from .errors import BiliDmErrorCode


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
        code = response_json.get('code', BiliDmErrorCode.GENERIC_FAILURE.code)
        raw_msg = str(response_json.get('message', '无原始错误信息'))

        data_obj = response_json.get('data', {})
        dmid: str = ""
        visible: bool = True

        if isinstance(data_obj, dict):
            dmid = data_obj.get('dmid_str', str(data_obj.get('dmid', '')))
            visible = data_obj.get('visible', True)

        enum_err = BiliDmErrorCode.from_code(code)
        display_msg = enum_err.description_str if enum_err else raw_msg

        return cls(
            code=code,
            is_success=(code == BiliDmErrorCode.SUCCESS.code),
            raw_message=raw_msg,
            display_message=display_msg,
            dmid=dmid,
            is_visible=visible
        )