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


    @property
    def is_fatal(self) -> bool:
        """
        判断当前错误是否为致命错误。
        通过将错误码转换为 BiliDmErrorCode 枚举类型，检查其 is_fatal 属性
        来确定该错误是否为致命错误。
        致命错误通常表示无法恢复的严重问题，应该立即停止相关操作。

        Returns:
            bool: 如果是致命错误返回 True，否则返回 False。
        """
        return BiliDmErrorCode.from_code(self.code).is_fatal

    @classmethod
    def from_api_response(cls, response_json: dict) -> 'DanmakuSendResult':
        """从 API JSON 响应构建结果对象"""
        # 提取原始 code 和 message
        code = response_json.get('code', BiliDmErrorCode.BILI_UNKNOWN_ERROR.code)
        raw_msg = str(response_json.get('message', ''))

        # 转换枚举
        err_enum = BiliDmErrorCode.from_code(code)

        # 如果是定义过的已知错误，优先使用 description
        # 如果是 BILI_UNKNOWN_ERROR，优先用B站返回的 raw_msg，没有时用用枚举默认描述
        if err_enum != BiliDmErrorCode.BILI_UNKNOWN_ERROR:
            display_msg = err_enum.description
        else:
            display_msg = raw_msg if raw_msg else err_enum.description

        dmid, visible = "", True
        if code == BiliDmErrorCode.SUCCESS.code:
            data_obj = response_json.get('data', {})
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